"""Schema versioning and forward migrations.

`metadata.create_all()` creates missing *tables* only. It never adds a column,
never renames one, and never notices that an existing database is the wrong
shape. Build 4.7.1 added five columns to `audit.llm_run`, a column to
`reference.lever`, a new `reference.platform_unit_cost` table and renamed
`engagement.case` to `engagement_case` - so an existing volume would have:

  * failed every `llm_run` INSERT, meaning no LIVE run could record its proof
  * failed the lever seed
  * created an empty `engagement_case`, orphaning every existing case
  * skipped the seed (thresholds were present) and left platform costs empty,
    silently dropping roughly 40% of modelled TCO

That last one is the dangerous shape: a system that starts, runs, and is wrong.
This module makes the state explicit and either migrates it or refuses to boot.

Design notes:
  * column DDL types are compiled from the model, so a migration cannot drift
    from the table definition it is supposed to be catching up to
  * every step is idempotent - re-running is a no-op, not an error
  * migrations run *before* create_all, so a rename is not defeated by an empty
    table having just been created under the new name
  * an unrecognised state is refused, loudly, rather than guessed at
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import inspect, select, text

from . import db

log = logging.getLogger("workbench.migrations")

# Bump when the physical schema changes, and add a step below.
SCHEMA_VERSION = 45

VERSION_TABLE = "schema_version"
VERSION_SCHEMA = "audit"

# Tables whose presence means "this is an existing database, not a fresh one".
LEGACY_PROBES = [("audit", "llm_run"), ("engagement", "engagement_case"),
                 ("engagement", "case"), ("reference", "threshold")]


class SchemaStateRefused(RuntimeError):
    """The database is in a state this build will not operate against."""


class MigrationFailed(RuntimeError):
    """A migration step failed. Carries the step and a remedy, because the
    alternative - a bare driver error from a crash-looping container - tells an
    operator nothing about what to do next."""


# ---------------------------------------------------------------- helpers
def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _create_index_ddl(conn, *, schema: str, table: str, name: str,
                      columns, unique: bool = False) -> str:
    """Dialect-correct CREATE INDEX.

    Found by executing the migration tests: SQLite and Postgres put the schema
    in different places, and this emitted only the Postgres form.

        Postgres : CREATE INDEX name ON schema.table (cols)
        SQLite   : CREATE INDEX schema.name ON table (cols)   <- table unqualified

    SQLite rejects the Postgres form with `near ".": syntax error`, so migration
    v9 could never complete against SQLite - which is precisely what `make test`
    runs (DATABASE_URL=sqlite://). Production is Postgres, so the defect was
    invisible there and fatal in the only place it was ever exercised.
    """
    uniq = "UNIQUE " if unique else ""
    cols = ", ".join(_q(c) for c in columns)
    if conn.dialect.name == "sqlite":
        return f"CREATE {uniq}INDEX {_q(schema)}.{_q(name)} ON {_q(table)} ({cols})"
    return (f"CREATE {uniq}INDEX {_q(name)} ON {_q(schema)}.{_q(table)} ({cols})")


def _column_is_nullable(conn, schema: str, table: str, column: str) -> bool:
    """True when `column` accepts NULL. Unknown columns report True so the
    caller proceeds and the database gives the authoritative answer."""
    try:
        for col in inspect(conn).get_columns(table, schema=schema):
            if col["name"] == column:
                return bool(col.get("nullable", True))
    except Exception:                                    # noqa: BLE001
        return True
    return True


def _has_table(conn, schema: str, table: str) -> bool:
    try:
        return inspect(conn).has_table(table, schema=schema)
    except Exception:                                    # noqa: BLE001
        return False


def _has_column(conn, schema: str, table: str, column: str) -> bool:
    if not _has_table(conn, schema, table):
        return False
    try:
        return column in {c["name"] for c in inspect(conn).get_columns(table, schema=schema)}
    except Exception:                                    # noqa: BLE001
        return False


def _add_column(conn, table_obj, column_name: str) -> bool:
    """Add a column using the type compiled from the model definition.

    Skips a table that does not exist. Migrations run before create_all, so a
    step that alters a table introduced by a *later* build meets nothing on an
    older database - create_all then builds it with the column already present.
    Without this guard the ALTER hit a missing table and the whole upgrade
    failed, which is what 21 migration tests were reporting.
    """
    if not _has_table(conn, table_obj.schema, table_obj.name):
        log.info("skipping %s.%s.%s: table not present yet, create_all will "
                 "build it complete", table_obj.schema, table_obj.name, column_name)
        return False
    if _has_column(conn, table_obj.schema, table_obj.name, column_name):
        return False
    col = table_obj.c[column_name]
    ddl_type = col.type.compile(conn.dialect)
    conn.execute(text(f"ALTER TABLE {_q(table_obj.schema)}.{_q(table_obj.name)} "
                      f"ADD COLUMN {_q(col.name)} {ddl_type}"))
    log.info("added column %s.%s.%s", table_obj.schema, table_obj.name, column_name)
    return True


# ---------------------------------------------------------------- steps
def _migrate_v2(conn) -> None:
    """4.7.0 -> 4.7.1: liveness evidence columns and the lever stage column."""
    added = 0
    for column in ("provider_request_id", "local_request_at", "clock_skew_seconds",
                   "egress_proxy", "http_status"):
        added += _add_column(conn, db.llm_run, column)
    added += _add_column(conn, db.lever, "earliest_supported_stage")
    log.info("v2: %d column(s) added", added)


def _migrate_v3(conn) -> None:
    """4.7.1: engagement.case -> engagement.engagement_case (reserved word)."""
    src, dst = "case", "engagement_case"
    has_src = _has_table(conn, "engagement", src)
    has_dst = _has_table(conn, "engagement", dst)

    if has_src and has_dst:
        # A half-finished upgrade. Guessing which one is authoritative risks
        # discarding live cases, so this stops rather than choosing.
        raise SchemaStateRefused(
            'both engagement."case" and engagement.engagement_case exist. '
            "This is a partially applied upgrade and cannot be resolved "
            "automatically. Inspect both tables, keep the one with your cases, "
            "drop the other, then restart.")
    if has_src and not has_dst:
        conn.execute(text(f"ALTER TABLE {_q('engagement')}.{_q(src)} "
                          f"RENAME TO {_q(dst)}"))
        log.info("v3: renamed engagement.case -> engagement.engagement_case")


def _migrate_v4(conn) -> None:
    """4.7.7 -> 4.7.9: TLS pin and provenance strength on every provider call."""
    added = 0
    for column in ("tls_pin", "provenance_strength"):
        added += _add_column(conn, db.llm_run, column)
    log.info("v4: %d column(s) added", added)


SUPPORT_TABLES = ("integrity_incident", "quarantined_row")


def _ensure_support_tables(engine) -> None:
    """Create the incident and quarantine tables before any migration runs.

    They are new in this build with no legacy counterpart, so creating them
    early is safe - and a migration that discovers a data conflict needs
    somewhere to preserve the evidence before it can proceed.
    """
    db.metadata.create_all(engine, tables=[db.integrity_incident,
                                           db.quarantined_row,
                                           db.known_fact_conflict])


def _raise_incident(conn, *, kind: str, severity: str, summary: str,
                    detail: dict) -> str:
    incident_id = str(uuid.uuid4())
    conn.execute(db.integrity_incident.insert().values(
        incident_id=incident_id, kind=kind, severity=severity,
        detected_at=datetime.now(timezone.utc), detected_by="migrations.ensure",
        summary=summary, detail=detail))
    log.error("[%s] %s: %s", severity, kind, summary)
    return incident_id


def _jsonable(row) -> dict:
    out = {}
    for key, value in dict(row._mapping).items():
        out[key] = value if value is None or isinstance(
            value, (str, int, float, bool, list, dict)) else str(value)
    return out


def _release_duplicate_identifiers(conn, *, schema: str, table: str,
                                   column: str, pk: str,
                                   order_by: str | None = None,
                                   scope_column: str | None = None) -> dict | None:
    """Make `column` unique without losing a row.

    Duplicates are preserved in full in audit.quarantined_row, the identifier is
    released on every copy but the earliest, and a P2 incident records what was
    touched. Nothing is deleted: a duplicate provider identifier may be the
    trace of a replayed response, which is evidence, not noise.
    """
    tbl = f"{_q(schema)}.{_q(table)}"
    # The scope must reach the row-fetch as well as the grouping. Grouping by
    # (provider, id) and then selecting rows by id alone finds the right
    # duplicate groups and then strips the wrong rows - so a migration written
    # to stop treating a cross-provider collision as a replay does exactly that
    # while running.
    group = (f"{_q(scope_column)}, {_q(column)}" if scope_column else _q(column))
    scope_select = f"{_q(scope_column)} AS scope, " if scope_column else ""
    dupes = conn.execute(text(
        f"SELECT {scope_select}{_q(column)} AS value, COUNT(*) AS n FROM {tbl} "
        f"WHERE {_q(column)} IS NOT NULL "
        f"GROUP BY {group} HAVING COUNT(*) > 1")).all()
    if not dupes:
        return None

    # "Earliest" needs a column that exists. A legacy table may predate the one
    # normally used, so fall back to the primary key rather than assuming.
    if order_by and not _has_column(conn, schema, table, order_by):
        order_by = None
    ordering = _q(order_by) if order_by else _q(pk)

    # Releasing means setting the identifier to NULL, which a NOT NULL column
    # cannot accept. Detected up front so this refuses with a cause an operator
    # can act on, instead of surfacing a raw driver error from deep inside a
    # migration - the rows are already preserved in quarantine either way.
    # Found by executing test_a_within_provider_duplicate_is_still_released.
    if not _column_is_nullable(conn, schema, table, column):
        raise SchemaStateRefused(
            f"{schema}.{table}.{column} holds duplicate values but is NOT NULL, "
            f"so the identifier cannot be released to make the column unique. "
            f"Resolve manually: the duplicate rows are the trace of a possible "
            f"replayed response and must not be deleted blindly. Inspect them, "
            f"decide which copy is authoritative, and either drop the NOT NULL "
            f"constraint or remove the superseded rows deliberately before "
            f"restarting.")

    quarantined, affected = 0, []
    for dupe in dupes:
        where, params = f"{_q(column)} = :v", {"v": dupe.value}
        if scope_column:
            scope_value = dupe.scope
            if scope_value is None:
                # NULL = NULL is false, so an equality predicate would match
                # nothing and leave the group unresolved.
                where += f" AND {_q(scope_column)} IS NULL"
            else:
                where += f" AND {_q(scope_column)} = :scope"
                params["scope"] = scope_value
        rows = conn.execute(text(
            f"SELECT * FROM {tbl} WHERE {where} ORDER BY {ordering} ASC"),
            params).all()
        if len(rows) < 2:
            continue
        keep, release = rows[0], rows[1:]
        for row in release:
            conn.execute(db.quarantined_row.insert().values(
                id=str(uuid.uuid4()), incident_id=None,
                source_schema=schema, source_table=table,
                reason=f"DUPLICATE_{column.upper()}",
                original_row=_jsonable(row),
                quarantined_at=datetime.now(timezone.utc)))
            quarantined += 1
        placeholders = ", ".join(f":p{i}" for i in range(len(release)))
        conn.execute(
            text(f"UPDATE {tbl} SET {_q(column)} = NULL "
                 f"WHERE {_q(pk)} IN ({placeholders})"),
            {f"p{i}": getattr(r, pk) for i, r in enumerate(release)})
        entry = {"value": dupe.value, "copies": dupe.n,
                 "kept": getattr(keep, pk),
                 "released": [getattr(r, pk) for r in release]}
        if scope_column:
            entry[scope_column] = dupe.scope
        affected.append(entry)

    if not affected:
        return None

    incident_id = _raise_incident(
        conn, kind=f"DUPLICATE_{column.upper()}", severity="P2",
        summary=(f"{len(affected)} duplicated {column} value(s) in "
                 f"{schema}.{table} predate the uniqueness constraint. "
                 f"{quarantined} row copies were preserved in "
                 f"audit.quarantined_row and their {column} released so the "
                 f"index could be created. Nothing was deleted. A duplicate "
                 f"provider identifier can be the trace of a replayed response "
                 f"- investigate before dismissing."),
        detail={"column": column, "duplicate_values": len(affected),
                "rows_quarantined": quarantined, "affected": affected})
    conn.execute(text(
        f"UPDATE {_q('audit')}.{_q('quarantined_row')} SET incident_id = :i "
        f"WHERE incident_id IS NULL"), {"i": incident_id})
    return {"incident_id": incident_id, "duplicate_values": len(affected),
            "rows_quarantined": quarantined}


def _has_index(conn, schema: str, table: str, name: str) -> bool:
    if not _has_table(conn, schema, table):
        return False
    try:
        return name in {i["name"] for i in inspect(conn).get_indexes(table, schema=schema)}
    except Exception:                                    # noqa: BLE001
        return False


def _migrate_v5(conn) -> None:
    """4.7.9 -> 4.7.10: verifiability column.

    This step originally also created a single-column unique index on
    provider_request_id. v9 replaces that with a composite index scoped to the
    provider, so building it here was not merely wasted work - it forced a
    *global* uniqueness release on the way through, stripping identifiers that
    two different providers may legitimately share. The index work now happens
    once, in v9, with the correct scope.
    """
    _add_column(conn, db.llm_run, "externally_verifiable")
    log.info("v5: externally_verifiable added; index deferred to v9")


def _migrate_v6(conn) -> None:
    """4.7.10 -> 4.7.11: simulation job state, checkpointing and cancellation."""
    added = 0
    for column in ("status", "progress_completed", "progress_total", "partial",
                   "cancel_requested", "started_at", "ended_at", "error"):
        added += _add_column(conn, db.simulation_run, column)
    if added:
        # Runs that predate the job runner completed synchronously, so they are
        # finished by definition. Marking them QUEUED would offer a resume that
        # would recompute an already-stored result.
        conn.execute(text(
            f"UPDATE {_q('outside_in')}.{_q('simulation_run')} "
            f"SET status = 'SUCCEEDED', progress_completed = ensemble_size, "
            f"    progress_total = ensemble_size "
            f"WHERE status IS NULL AND output_hash IS NOT NULL"))
    log.info("v6: %d column(s) added", added)


def _migrate_v7(conn) -> None:
    """4.7.12 -> 4.7.13: certificate expiry alongside the pin.

    Existing `tls_pin` values are unprefixed certificate hashes from before pins
    became self-describing. They are relabelled rather than discarded, so an
    operator who already configured one is not silently locked out.
    """
    _add_column(conn, db.llm_run, "tls_cert_not_after")
    conn.execute(text(
        f"UPDATE {_q('audit')}.{_q('llm_run')} "
        f"SET tls_pin = 'cert-sha256/' || tls_pin "
        f"WHERE tls_pin IS NOT NULL "
        f"  AND tls_pin NOT LIKE 'sha256/%' "
        f"  AND tls_pin NOT LIKE 'cert-sha256/%'"))
    log.info("v7: certificate expiry column added, legacy pins relabelled")


def _migrate_v8(conn) -> None:
    """4.7.13 -> 4.7.15: known-fact quantity conflicts.

    The table is created by _ensure_support_tables before any migration runs,
    so this step only stamps the version - there is nothing to alter.
    """
    log.info("v8: known_fact_conflict available")


def _migrate_v9(conn) -> None:
    """4.7.15 -> 4.7.16: scope identifier uniqueness to the provider.

    Global uniqueness would call a cross-provider identifier collision a replay
    and fail a genuine run. Unlikely with `msg_...` and `chatcmpl-...` prefixes,
    but the correct key costs nothing.
    """
    for old in ("uq_llm_run_provider_request_id",):
        if _has_index(conn, "audit", "llm_run", old):
            conn.execute(text(f"DROP INDEX {_q(old)}"))
            log.info("v9: dropped %s", old)
    # The response-id constraint was created with the table. Postgres can drop
    # it; SQLite cannot without a rebuild, and there it is merely stricter than
    # needed - SQLite is only used for tests, which build fresh schemas.
    if conn.dialect.name == "postgresql":
        conn.execute(text(
            f"ALTER TABLE {_q('audit')}.{_q('llm_run')} "
            f"DROP CONSTRAINT IF EXISTS uq_llm_run_provider_response_id"))

    for name, column in (("uq_llm_run_provider_response", "provider_response_id"),
                         ("uq_llm_run_provider_request", "provider_request_id")):
        if _has_index(conn, "audit", "llm_run", name):
            continue
        released = _release_duplicate_identifiers(
            conn, schema="audit", table="llm_run", column=column,
            pk="llm_run_id", order_by="created_at", scope_column="provider")
        if released:
            log.warning("v9: %s", released)
        conn.execute(text(_create_index_ddl(
            conn, schema="audit", table="llm_run", name=name,
            columns=("provider", column), unique=True)))
        log.info("v9: created %s", name)


def _migrate_v10(conn) -> None:
    """4.7.26 -> 4.8.0: reconciliation provenance.

    The table existed and nothing ever wrote to it. These columns record who
    performed a reconciliation and through which channel, which is the part that
    makes it evidence rather than a number.
    """
    added = 0
    for column in ("source", "recorded_by", "incident_id"):
        added += _add_column(conn, db.usage_reconciliation, column)
    log.info("v10: %d reconciliation column(s) added", added)


def _migrate_v11(conn) -> None:
    """4.8.4 -> 4.9.0: domain_disposition gains agent_run_id and evidence.

    Tranche 1 gives the 24-domain contract a research path (LLM-01, LLM-08).
    Before this, every row in domain_disposition was written by a person via
    PUT .../domain-dispositions, so nothing pointed back to a call that
    produced it. A research-derived EVIDENCED_PUBLIC row without a trace to
    the agent_run and the sources it names is a claim indistinguishable from
    one asserted with nothing behind it - the same discipline C4-07 applied to
    superseded_by.
    """
    added = 0
    for column in ("agent_run_id", "evidence"):
        added += _add_column(conn, db.domain_disposition, column)
    log.info("v11: %d domain_disposition column(s) added", added)


def _migrate_v12(conn) -> None:
    """4.9.0 -> 4.10.0: recommendation is a wholly new table (Tranche 2,
    LLM-07/LLM-06). Nothing to ALTER - create_all builds it after this step
    runs, per the ordering _add_column's own docstring explains. This step
    exists so SCHEMA_VERSION advances and an operator upgrading from 4.9.0
    sees a stamped step rather than a silent jump."""
    log.info("v12: recommendation table introduced; create_all will build it")


def _migrate_v13(conn) -> None:
    """4.10.0 -> 4.11.0: stage tracking on engagement_case, plus two wholly
    new tables (questionnaire_item, stage_readiness_report) that create_all
    builds after this step.

    The three ALTERs are real: engagement_case exists on any database from
    4.7.x onward, so stage/stage_advanced_by/stage_advanced_at have to be
    added to it rather than appearing with the table. Existing rows get
    stage=NULL rather than 'V0' - a server-side DEFAULT is not backfilled by
    ALTER TABLE ADD COLUMN in either engine here. domain/stage.py treats NULL
    as V0 explicitly (see current_stage) rather than relying on the column
    default, which only applies to rows inserted after this runs.
    """
    added = 0
    for column in ("stage", "stage_advanced_by", "stage_advanced_at"):
        added += _add_column(conn, db.case, column)
    log.info("v13: %d stage column(s) added; questionnaire_item and "
             "stage_readiness_report introduced, create_all will build them", added)


def _migrate_v14(conn) -> None:
    """4.11.0 -> 4.12.0: evidence-mapping columns on questionnaire_item.

    Tranche 3 shipped questionnaire answers with nowhere to go: they were
    stored and attributed but never reached the disposition contract, because
    client-supplied data had no class in the 0.3A taxonomy. CLIENT_CONFIRMED
    closes that, and these columns record what each answer did to its domain -
    including the cases where it was deliberately refused permission to
    overwrite existing independent evidence.
    """
    added = 0
    for column in ("mapping_state", "mapping_note", "mapped_at",
                   "mapping_resolution", "mapping_resolved_by",
                   "mapping_resolved_at"):
        added += _add_column(conn, db.questionnaire_item, column)
    log.info("v14: %d questionnaire_item mapping column(s) added", added)


def _migrate_v15(conn) -> None:
    """4.12.0 -> 4.13.0: scope-descriptor column on engagement_case.

    The intake page's only way to set in-scope geography was a free-text
    country list; the estimate pricing lookup filters unit_cost_prior on
    exactly what's in that column (routers/api.py, run_estimate), so a
    region or "global" selection still has to resolve to literal ISO codes -
    domain/scope.py does that at save time. in_scope_region records which
    descriptor produced the resolved list (a region code, "GLOBAL", or NULL
    for an explicit country list) purely so the choice can be shown back and
    re-edited; nothing downstream reads it for pricing or coverage.
    """
    added = _add_column(conn, db.case, "in_scope_region")
    log.info("v15: %s in_scope_region column added", "1" if added else "0")


def _migrate_v16(conn) -> None:
    """4.13.0 -> 4.14.0: research findings can reach the estimate.

    Two ALTERs on reference.unit_cost_prior, which exists on any database from
    4.7.x onward, so the provenance columns have to be added rather than
    appearing with the table. outside_in.evidenced_footprint is wholly new and
    create_all builds it after this step.

    Without the provenance columns a promoted price would be indistinguishable
    from a seeded one the moment it was written, which is the defect this
    bundle keeps finding in other forms: a value whose origin is not recorded
    is a value nobody can audit or retract.
    """
    added = 0
    for column in ("source_agent_run_id", "source_note"):
        added += _add_column(conn, db.unit_cost_prior, column)
    log.info("v16: %d unit_cost_prior provenance column(s) added; "
             "evidenced_footprint introduced, create_all will build it", added)


def _migrate_v17(conn) -> None:
    """4.14.0 -> 4.15.0: circuit prices gain a bandwidth, BROADBAND splits.

    Adds reference.unit_cost_prior.bandwidth_mbps and clears the pre-split
    rows so the seed can rebuild them. Deleting seeded reference data is
    something this module otherwise refuses to do - it is safe only because
    every affected row is identifiable as seed-written (approved_by/source
    columns untouched, ids in the old `COUNTRY-PRODUCT` form) and because
    leaving them is worse: a row keyed BROADBAND with a null bandwidth can
    never be matched by the new lookup, so it would sit in the table pricing
    nothing while appearing to be coverage.

    A researched row promoted under 4.47.0 uses the id suffix `-researched`
    and is deliberately left alone: it is not ours to delete, it carries
    provenance, and its bandwidth is simply unknown until a steward sets one.
    """
    added = _add_column(conn, db.unit_cost_prior, "bandwidth_mbps")
    removed = 0
    if _has_table(conn, "reference", "unit_cost_prior"):
        result = conn.execute(text(
            'DELETE FROM "reference"."unit_cost_prior" '
            "WHERE bandwidth_mbps IS NULL AND id NOT LIKE '%-researched'"))
        removed = result.rowcount or 0
    # The archetypes need the same treatment, and for a reason worth stating:
    # seed() is idempotent per primary key - "ensure present", never "update
    # changed". BRANCH keeps its identity across the split, so a re-seed
    # (even --force) leaves backup_product='BROADBAND' untouched: a product
    # that no longer has a single price row. Every BRANCH backup circuit would
    # then be unpriced, and the coverage gate would refuse the estimate for a
    # reason that looks like missing evidence and is really a stale row.
    #
    # Only rows naming the retired product are removed, so a steward's tuning
    # of LARGE_OFFICE or DC survives. The seed rebuilds the three it clears.
    archetypes_cleared = 0
    if _has_table(conn, "reference", "archetype_prior"):
        result = conn.execute(text(
            'DELETE FROM "reference"."archetype_prior" '
            "WHERE primary_product = 'BROADBAND' OR backup_product = 'BROADBAND'"))
        archetypes_cleared = result.rowcount or 0
    log.info("v17: bandwidth_mbps added=%s; %d pre-split price row(s) and %d "
             "archetype row(s) naming the retired BROADBAND product cleared "
             "for reseed", bool(added), removed, archetypes_cleared)


def _migrate_v18(conn) -> None:
    """4.15.0 -> 4.16.0: benchmark.benchmark_observation.

    Wholly new and in a schema that has been declared and empty since the
    first build, so there is nothing to ALTER - create_all builds it after
    this step. The version bump exists so an operator upgrading can tell that
    the vault is now expected to be there.
    """
    log.info("v18: benchmark_observation introduced, create_all will build it")


def _migrate_v19(conn) -> None:
    """4.16.0 -> 4.17.0: reference.research_brief.

    Wholly new; create_all builds it after this step and the seed populates
    catalogue version 1.0.0 from domain/research_briefs.py. The version bump
    exists so an operator can tell that research now reads briefs from the
    database rather than from the module, and that editing the module alone
    no longer changes what an agent is sent.
    """
    log.info("v19: research_brief introduced; briefs move from code to "
             "governed reference data")


def _migrate_v20(conn) -> None:
    """4.17.0 -> 4.18.0: registered-call identity on audit.llm_run.

    Eight additive columns recording which prompt, schema and tool policy
    produced a response, plus the parsed structured output and the source IDs
    supplied to the call.

    Historical rows keep null prompt identity and must not be backfilled: a
    call made before the registry existed was not made under a registered
    prompt, and inventing one would put a false provenance on a real record.
    Nulls here mean "pre-registry", which is the truth.
    """
    added = 0
    for column in ("prompt_id", "prompt_version", "prompt_hash",
                   "output_schema_version", "tool_policy_version",
                   "parsed_output", "supplied_source_ids", "reviewer_outcome"):
        added += _add_column(conn, db.llm_run, column)
    log.info("v20: %d registered-call audit column(s) added", added)




def _migrate_v21(conn) -> None:
    """4.18.0 -> 4.19.0: entity aliases, and a new brief catalogue.

    engagement_case.entity_aliases carries the trading names a subject is
    known by. Without it the perimeter check compares sources against the
    registered legal name only, which quarantines a source using the brand -
    the normal case, not the exception.

    Seed-written research briefs from the previous catalogue are deactivated
    so the new catalogue version becomes active. Only rows written by the seed
    are touched: a brief a steward published is theirs, and superseding it
    silently would undo a deliberate act.
    """
    added = _add_column(conn, db.case, "entity_aliases")
    retired = 0
    if _has_table(conn, "reference", "research_brief"):
        result = conn.execute(text(
            'UPDATE "reference"."research_brief" SET active = false '
            "WHERE approved_by = 'seed'"))
        retired = result.rowcount or 0
    log.info("v21: entity_aliases added=%s; %d seed-written brief(s) "
             "deactivated for the new catalogue", bool(added), retired)


def _migrate_v22(conn) -> None:
    """4.19.0 -> 4.20.0: the band behind a promoted site count.

    band_low, band_high and source_count on outside_in.evidenced_footprint.
    A promoted figure used to be a bare number, so an estimate could not say
    whether three sources agreed on it or one source stated it - and those
    carry very different weight in exactly the calculation it feeds.
    """
    added = 0
    for column in ("band_low", "band_high", "source_count"):
        added += _add_column(conn, db.evidenced_footprint, column)
    log.info("v22: %d band column(s) added to evidenced_footprint", added)


def _migrate_v23(conn) -> None:
    """4.20.0 -> 4.21.0: archived / archived_by on engagement_case.

    A case that has published an estimate cannot be deleted - the snapshot is
    the provenance for a number that may have left the building. Archiving is
    the route for it: out of the picker, nothing lost.
    """
    added = 0
    for column in ("archived", "archived_by"):
        added += _add_column(conn, db.case, column)
    log.info("v23: %d archive column(s) added to engagement_case", added)


def _migrate_v24(conn) -> None:
    """4.21.0 -> 4.22.0: engagement_case.analyst_footprint.

    A typed site list survived only by being run: the editor reopened on the
    last simulation's parameters, so entering counts and not running them lost
    them. Saving is now its own act and its own column.
    """
    added = _add_column(conn, db.case, "analyst_footprint")
    log.info("v24: analyst_footprint added=%s", bool(added))


def _migrate_v25(conn) -> None:
    """4.22.0 -> 4.23.0: analyst-supplied drivers on engagement_case.

    declared_users, declared_ops_cost_per_site and declared_spend_by_country.
    They were interface defaults - 5,000 users, 900 per site, and a million per
    country in the crosscheck table - so invented figures reached the baseline
    and had to be retyped on every visit, which meant the value in use was
    whatever the defaults happened to be.
    """
    added = 0
    for column in ("declared_users", "declared_ops_cost_per_site",
                   "declared_spend_by_country"):
        added += _add_column(conn, db.case, column)
    log.info("v25: %d declared-driver column(s) added", added)


def _migrate_v26(conn) -> None:
    """4.23.0 -> 4.24.0: bandwidth by industry and site type.

    reference.archetype_bandwidth is new and create_all builds it.
    engagement_case.industry is added so a case can be resolved against it.

    archetype_prior alone said a retail bank branch and a parts depot of the
    same size need the same circuit. The archetype describes the shape of a
    site; the industry describes what happens inside it.
    """
    added = _add_column(conn, db.case, "industry")
    log.info("v26: case.industry added=%s; archetype_bandwidth introduced",
             bool(added))


def _migrate_v27(conn) -> None:
    """4.24.0 -> 4.25.0: estimate_snapshot.supersedes_snapshot_id.

    Historical snapshots keep null lineage and are not backfilled by
    created_at order: two snapshots minutes apart may be a refinement or two
    unrelated attempts, and guessing would put a false chain on a real record.
    Null means "not stated", which is the truth about them.
    """
    added = _add_column(conn, db.estimate_snapshot, "supersedes_snapshot_id")
    log.info("v27: supersedes_snapshot_id added=%s", bool(added))


def _migrate_v28(conn) -> None:
    """4.25.0 -> 4.26.0: outside_in.evidenced_archetype.

    Wholly new; create_all builds it. Lets a case's own evidence inform the
    topology and not only the counts: product pairs, dual-access probability,
    bandwidth and users per site were global seeded constants, so a researched
    or asserted finding about a client's architecture reached nothing.
    """
    log.info("v28: evidenced_archetype introduced; a case's evidence can now "
             "inform topology as well as counts")


def _migrate_v29(conn) -> None:
    """4.26.0 -> 4.27.0: outside_in.evidenced_anchor.

    Wholly new; create_all builds it. The disclosed cost line the ANCHOR method
    rests on was researched, graded and stored, and reached nothing - so the
    anchor was typed by hand and the estimate capped itself under 0.6A while
    the evidence for it sat in the same case.
    """
    log.info("v29: evidenced_anchor introduced; a researched cost line can "
             "now be the anchor rather than being retyped as an assertion")


def _migrate_v30(conn) -> None:
    """4.27.0 -> 4.28.0: reference.country_region and reference.topology_template.

    Both new; create_all builds them and the seed fills them. Until now every
    site got an access circuit and nothing else, which is not a WAN but a set
    of unconnected local loops - so the baseline understated itself and no
    backbone lever had anything to act on.
    """
    log.info("v30: country_region and topology_template introduced; the "
             "simulation gains a core")


def _migrate_v31(conn) -> None:
    """4.28.0 -> 4.29.0: a price may be scoped to a region, not only a country.

    unit_cost_prior.country widens from 2 to 16 characters and gains
    scope_kind. A hub-to-core circuit belongs to EMEA rather than to Germany,
    and the column was an ISO alpha-2 field - so the first regional backbone
    row failed to insert with "value too long for type character varying(2)".

    Widening alone would have left country = 'EMEA', which is false data that
    reads as a fact. Existing rows are stamped COUNTRY, which is what they are.
    """
    added = _add_column(conn, db.unit_cost_prior, "scope_kind")
    widened = 0
    if _has_table(conn, "reference", "unit_cost_prior"):
        conn.execute(text(
            'ALTER TABLE "reference"."unit_cost_prior" '
            "ALTER COLUMN country TYPE VARCHAR(16)"))
        widened = conn.execute(text(
            'UPDATE "reference"."unit_cost_prior" SET scope_kind = \'COUNTRY\' '
            "WHERE scope_kind IS NULL")).rowcount or 0
    log.info("v31: country widened to 16; scope_kind added=%s; %d existing "
             "row(s) stamped COUNTRY", bool(added), widened)


def _migrate_v32(conn) -> None:
    """4.29.0 -> 4.30.0: engagement_case.run_settings.

    The simulation seed and ensemble size, and the V0 estimation method and
    anchor value, were widget state only. Switching page reset them, so a
    deliberately chosen seed or an ANCHOR run reverted to 42/25/BUILD_UP
    without saying so - and a reproducibility claim resting on a seed nobody
    kept is not a claim.
    """
    added = _add_column(conn, db.case, "run_settings")
    log.info("v32: run_settings added=%s", bool(added))


def _migrate_v33(conn) -> None:
    """4.29.0 -> 4.30.0: audit.llm_run.quality_reasons.

    This was written as a second _migrate_v21 in the same module, so Python
    kept the other one and the column was never added by any step. Only the
    4.68.0 reconciler was supplying it - a control doing a migration's job, and
    logging a warning that said exactly that to nobody who read it.

    One additive column carrying the quality gate's verdict on each call.
    Historical rows keep null: a call made before the gate existed was not
    judged by it, and stamping a verdict on it would assert a review that never
    happened.
    """
    added = _add_column(conn, db.llm_run, "quality_reasons")
    log.info("v33: quality_reasons added=%s (lost to a name collision at v21)",
             bool(added))


def _migrate_v34(conn) -> None:
    """4.30.0 -> 4.31.0: outside_in.location.

    Wholly new; create_all builds it. The footprint stored a count per country
    and site type, so "371 branches in Germany" and a list of 371 addresses
    were indistinguishable - and the second is far better evidence.

    Existing cases keep their counts and are simply reported as zero
    enumerated, which is what they are.
    """
    log.info("v34: location introduced; a footprint count can now be backed "
             "by the named sites behind it")


def _migrate_v35(conn) -> None:
    """4.31.0 -> 4.32.0: coordinates on outside_in.location.

    The simulation now materialises the estate site by site and carries an
    address and a position onto each named row, and there was nowhere to store
    one - a locator page usually gives coordinates and the model discarded
    them.
    """
    added = sum(_add_column(conn, db.location, c)
                for c in ("latitude", "longitude"))
    log.info("v35: %d coordinate column(s) added to location", added)


def _migrate_v36(conn) -> None:
    """4.32.0 -> 4.33.0: reference.serviceability, and density on the estate.

    The archetype said what a site needs and nothing said what could be
    delivered there, so a 4,000-store estate was priced as though every store
    could take the same product. Domain 18 researched exactly this and its
    result reached nothing.
    """
    log.info("v36: serviceability introduced; what a site needs and what can "
             "be delivered there are now different questions")


def _migrate_v37(conn) -> None:
    """4.33.0 -> 4.34.0: reference.density_mix.

    A registered total arrived with an empty footprint table and a message
    saying nothing would be guessed. Right about silent invention, wrong about
    the remedy: the analyst had to invent the split anyway with no help.
    """
    log.info("v37: density_mix introduced; a total can now propose a split "
             "that says what it is")


def _migrate_v38(conn) -> None:
    """4.34.0 -> 4.35.0: room for a unit an agent actually writes.

    known_fact.unit was VARCHAR(32) and the public sweep supplied "employees
    (total UK entity headcount band, Boots Management Services Ltd)" - 68
    characters - so accepting the proposal failed with
    StringDataRightTruncation and none of the twelve rows was written.

    Widening is only half the answer: the agent was putting a scope
    qualification in a unit field, which belongs in the note. The other half
    is in known_facts.register, which now splits an over-long unit rather than
    storing prose in a column meant for a measure.

    Widening a VARCHAR in Postgres rewrites no rows and takes no exclusive
    lock, so this is safe on a live table.
    """
    widened = 0
    for schema, table, column, width in (
            ("outside_in", "known_fact", "unit", 128),
            ("reference", "benchmark_observation", "unit", 128),
            ("reference", "benchmark_observation", "metric", 96),
            ("reference", "platform_unit_cost", "unit", 128),
            ("outside_in", "evidenced_anchor", "label", 128)):
        if _has_table(conn, schema, table):
            conn.execute(text(
                f'ALTER TABLE "{schema}"."{table}" '
                f"ALTER COLUMN {column} TYPE VARCHAR({width})"))
            widened += 1
    added = _add_column(conn, db.known_fact, "supplied_note")
    log.info("v38: %d column(s) widened for agent-supplied text; "
             "supplied_note added=%s", widened, bool(added))


def _migrate_v39(conn) -> None:
    """4.35.0 -> 4.36.0: the analyst chooses which site total to model.

    The resolver picked one registered Location footprint fact by rule - best
    corroboration standing, then largest value - and reported only the number.
    So two complementary facts competed instead of summing, and the analyst
    could not see which had won or why.
    """
    added = sum(_add_column(conn, db.case, c) for c in
                ("footprint_total_choice", "footprint_total_chosen_by"))
    log.info("v39: %d column(s) added for the chosen site total", added)


def _migrate_v40(conn) -> None:
    """4.36.0 -> 4.37.0: unit_cost_prior.price_basis.

    All 58 seeded priors landed approved=True with nothing marking them as
    indicative, so an estimate could not distinguish a placeholder from a
    steward-approved benchmark and coverage counted both as priced. An auditor
    reported exactly this as a constraint on validation.

    Existing rows default to SEED, which is what they are: a promoted price is
    written approved=False and a benchmark-derived one is written by the vault.
    """
    added = _add_column(conn, db.unit_cost_prior, "price_basis")
    log.info("v40: price_basis added=%s; existing rows default to SEED",
             bool(added))


def _migrate_v41(conn) -> None:
    """4.37.0 -> 4.38.0: reference.lever.applies_to_products.

    Audit finding C-10. A lever's cost_layers was the whole eligibility test,
    and L0 is the entire access layer - so MPLS substitution was applied to
    broadband and mobile circuits, booking savings from replacing MPLS in an
    estate that held none. The arithmetic was correct throughout; the result
    was semantically false, which is the worst failure a cost model can have
    because nothing in the output looks wrong.

    Existing rows get null, which means unconstrained - the seed then sets the
    constraint on the levers that need one.
    """
    added = _add_column(conn, db.lever, "applies_to_products")
    log.info("v41: applies_to_products added=%s; a layer match is no longer "
             "proof that a lever applies", bool(added))


def _migrate_v42(conn) -> None:
    """4.38.0 -> 4.39.0: what a unit-cost prior is worth as evidence.

    Audit finding A-02. Every seeded prior carried a price and nothing about
    its standing - no grade, no source, no term, no SLA, no tax or equipment
    basis - and priced_spend_pct treated a seeded guess and a cleared benchmark
    identically.

    Existing rows default to grade E, which is what they are: expert
    assumptions with no source claimed.
    """
    added = sum(_add_column(conn, db.unit_cost_prior, c) for c in (
        "evidence_grade", "source", "source_date", "sample_size",
        "term_months", "sla", "taxes_included", "equipment_included",
        "managed_services_included", "expires"))
    log.info("v42: %d evidence column(s) added to unit_cost_prior", added)


def _migrate_v43(conn) -> None:
    """4.39.0 -> 4.40.0: a structured speed pair and a finer geographic scope.

    One `bandwidth_mbps` conflated a bearer with a committed rate. The
    reference estate's own invoice descriptions read `Access/Port = 100/30`,
    and pricing that on the 100 looks up a tier the client never bought - 3.3x
    too high across 307 circuits.

    `bandwidth_mbps` is retained and becomes the derived figure the tariff keys
    off, so nothing downstream changes. Existing rows keep it and gain a null
    pair, which reads as "basis not recorded" rather than as symmetric.
    """
    added = sum(_add_column(conn, db.unit_cost_prior, c) for c in (
        "access_family", "speed_basis", "speed_primary_mbps",
        "speed_secondary_mbps", "monthly_data_cap_gb", "geography_area",
        "premises_type", "distance_from", "distance_to", "distance_unit"))
    log.info("v43: %d column(s) added; the pair is authoritative and "
             "bandwidth_mbps is its projection", added)


def _migrate_v44(conn) -> None:
    """Service class and access technology on the rate card.

    `product` held one value for two orthogonal facts. A client's own invoice
    data settles it: the same service rides four access technologies, 1,357
    circuits over VDSL and 52 over PON and VDSL together.

    Additive, not a flag day. Existing rows keep `product` and gain the two
    dimensions derived from it, so a snapshot written before this migration
    stays reproducible and match_prior can key on either.
    """
    added = sum(_add_column(conn, db.unit_cost_prior, c)
                for c in ("service_class", "access_technology"))
    # Derive the two dimensions from the value already stored. Done in SQL
    # rather than by re-seeding, so a steward-approved prior keeps its
    # approval and its evidence grade.
    LEGACY = {
        "DIA": ("DIA", None), "MPLS": ("IPVPN", None),
        "ETHERNET": ("ETHERNET", "ETHERNET_FIBRE"),
        "BROADBAND_PON": ("BEST_EFFORT", "PON"),
        "BROADBAND_HFC": ("BEST_EFFORT", "HFC"),
        "MOBILE_5G": ("BEST_EFFORT", "MOBILE_5G"),
    }
    migrated = 0
    for product, (service_class, technology) in LEGACY.items():
        result = conn.execute(text(
            "UPDATE reference.unit_cost_prior "
            "SET service_class = :sc, access_technology = :at "
            "WHERE product = :p AND service_class IS NULL"),
            {"sc": service_class, "at": technology, "p": product})
        migrated += result.rowcount or 0
    log.info("v44: %d column(s) added, %d prior(s) given a service class",
             added, migrated)


def _migrate_v45(conn) -> None:
    """Service class per archetype, chosen rather than implied by a product.

    `primary_product` held a service level and a delivery technology in one
    value, so choosing BROADBAND_HFC for a store asserted both - and a store
    served by PON instead came out as a substitution rather than as the same
    decision met a different way.

    Derived from the value already stored, so a seeded or edited prior keeps
    its other fields.
    """
    added = sum(_add_column(conn, db.archetype_prior, c) for c in
                ("primary_service_class", "backup_service_class"))
    added += _add_column(conn, db.case, "service_class_by_archetype")
    LEGACY = {"DIA": "DIA", "MPLS": "IPVPN", "ETHERNET": "ETHERNET",
              "BROADBAND_PON": "BEST_EFFORT", "BROADBAND_HFC": "BEST_EFFORT",
              "MOBILE_5G": "BEST_EFFORT"}
    for column, target in (("primary_product", "primary_service_class"),
                           ("backup_product", "backup_service_class")):
        for product, service_class in LEGACY.items():
            conn.execute(text(
                f"UPDATE reference.archetype_prior SET {target} = :sc "
                f"WHERE {column} = :p AND {target} IS NULL"),
                {"sc": service_class, "p": product})
    log.info("v45: %d column(s) added; service class derived from product",
             added)


MIGRATIONS = {2: _migrate_v2, 3: _migrate_v3, 4: _migrate_v4, 5: _migrate_v5,
              6: _migrate_v6, 7: _migrate_v7, 8: _migrate_v8, 9: _migrate_v9,
              10: _migrate_v10, 11: _migrate_v11, 12: _migrate_v12,
              13: _migrate_v13, 14: _migrate_v14, 15: _migrate_v15,
              16: _migrate_v16, 17: _migrate_v17, 18: _migrate_v18,
              19: _migrate_v19, 20: _migrate_v20,
              21: _migrate_v21, 22: _migrate_v22, 23: _migrate_v23, 24: _migrate_v24, 25: _migrate_v25, 26: _migrate_v26, 27: _migrate_v27, 28: _migrate_v28, 29: _migrate_v29, 30: _migrate_v30, 31: _migrate_v31, 32: _migrate_v32, 33: _migrate_v33, 34: _migrate_v34, 35: _migrate_v35, 36: _migrate_v36, 37: _migrate_v37, 38: _migrate_v38, 39: _migrate_v39, 40: _migrate_v40, 41: _migrate_v41, 42: _migrate_v42, 43: _migrate_v43, 44: _migrate_v44, 45: _migrate_v45}


class SchemaDrift(RuntimeError):
    """The database is missing a column the code will select."""


def verify_model_matches_database(engine, raise_on_drift: bool = True) -> list:
    """Every column the model declares must exist in the database.

    migrations.ensure() applies the steps it knows about; it cannot notice a
    column that was added to db.py without a corresponding step, or a step
    that silently skipped. The gap is invisible until a query happens to name
    the missing column - and which query that is depends on whether it selects
    the whole table or one column.

    That is exactly how v16 failed in the field: preflight selects
    unit_cost_prior.c.country and passed, while estimates:run selects the whole
    table and returned a bare 500 with an SQLAlchemy error in the log. Same
    database, same request, one endpoint working and one not, with nothing
    saying "schema".

    Raises rather than warns. A service that starts and 500s on its central
    calculation is worse than one that refuses to start with a message naming
    the columns to add.
    """
    missing = []
    with engine.connect() as conn:
        inspector = inspect(conn)
        for table in db.metadata.sorted_tables:
            if not _has_table(conn, table.schema, table.name):
                continue          # create_all builds it; nothing to compare yet
            try:
                actual = {c["name"] for c in inspector.get_columns(
                    table.name, schema=table.schema)}
            except Exception:                              # noqa: BLE001
                continue
            for column in table.columns:
                if column.name not in actual:
                    missing.append(f"{table.schema}.{table.name}.{column.name}")
    if missing and raise_on_drift:
        raise SchemaDrift(
            "the database is missing columns this build will query: "
            + ", ".join(sorted(missing))
            + ". A migration step is missing or did not apply. Run "
              "`migrations.ensure(db.engine)` and check its report; if the "
              "column was added to db.py without a step, add one.")
    return missing


# ---------------------------------------------------------------- version
def _ensure_version_table(conn) -> None:
    if _has_table(conn, VERSION_SCHEMA, VERSION_TABLE):
        return
    conn.execute(text(
        f"CREATE TABLE {_q(VERSION_SCHEMA)}.{_q(VERSION_TABLE)} ("
        f"  id INTEGER PRIMARY KEY,"
        f"  version INTEGER NOT NULL,"
        f"  applied_at VARCHAR(40),"
        f"  applied_by VARCHAR(64))"))


def _read_version(conn) -> int | None:
    if not _has_table(conn, VERSION_SCHEMA, VERSION_TABLE):
        return None
    row = conn.execute(text(
        f"SELECT version FROM {_q(VERSION_SCHEMA)}.{_q(VERSION_TABLE)} "
        f"WHERE id = 1")).first()
    return int(row[0]) if row else None


def _stamp(conn, version: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(text(
        f"SELECT id FROM {_q(VERSION_SCHEMA)}.{_q(VERSION_TABLE)} WHERE id = 1")).first()
    if existing:
        conn.execute(text(
            f"UPDATE {_q(VERSION_SCHEMA)}.{_q(VERSION_TABLE)} "
            f"SET version = :v, applied_at = :t, applied_by = :b WHERE id = 1"),
            {"v": version, "t": now, "b": "migrations.ensure"})
    else:
        conn.execute(text(
            f"INSERT INTO {_q(VERSION_SCHEMA)}.{_q(VERSION_TABLE)} "
            f"(id, version, applied_at, applied_by) VALUES (1, :v, :t, :b)"),
            {"v": version, "t": now, "b": "migrations.ensure"})


def _detect(conn) -> tuple[int, str]:
    """Returns (version, how_it_was_determined)."""
    stamped = _read_version(conn)
    if stamped is not None:
        return stamped, "stamped"
    # Unstamped. Either a fresh database, or one created before versioning.
    for schema, table in LEGACY_PROBES:
        if _has_table(conn, schema, table):
            return 1, f"inferred from existing {schema}.{table}"
    return SCHEMA_VERSION, "fresh database"


# ---------------------------------------------------------------- entrypoint
def repair_missing_columns(engine=None) -> list:
    """Add any model column absent from a table that already exists.

    Additive only: it adds columns, never drops, renames or retypes one, so
    running it cannot lose data. It exists because a stamp that is not earned
    is worse than no stamp at all.

    The failure it repairs was observed in the field. A migration step calls
    _add_column, which returns False without acting when it cannot - by
    design, so a step targeting a table a later build introduces does not
    fail on an older database. ensure() then stamped the target version
    regardless. One silent skip and the database records a version it never
    reached, every later run reports "up to date, nothing to do", and the
    step is never applied again. The service then refused to start for a
    column that no migration would ever add.

    Called from ensure() before the final stamp, so the stamp means what it
    says. Anything it has to add is logged at WARNING with the column names:
    self-healing that happens quietly is indistinguishable from the defect.
    """
    eng = engine or db.engine
    added = []
    with eng.begin() as conn:
        for table in db.metadata.sorted_tables:
            if not _has_table(conn, table.schema, table.name):
                continue          # create_all will build it complete
            for column in table.columns:
                if _has_column(conn, table.schema, table.name, column.name):
                    continue
                ddl_type = column.type.compile(conn.dialect)
                conn.execute(text(
                    f"ALTER TABLE {_q(table.schema)}.{_q(table.name)} "
                    f"ADD COLUMN {_q(column.name)} {ddl_type}"))
                added.append(f"{table.schema}.{table.name}.{column.name}")
    if added:
        log.warning(
            "reconciled %d column(s) the schema stamp claimed were present: "
            "%s. A migration step did not take effect on this database; the "
            "columns have been added additively. Check the step that owns "
            "them.", len(added), ", ".join(added))
    return added


def ensure(engine=None) -> dict:
    """Bring the schema to SCHEMA_VERSION, or refuse to operate.

    Returns a report suitable for logging and for /v1/health.
    """
    eng = engine or db.engine
    _ensure_support_tables(eng)
    with eng.begin() as conn:
        _ensure_version_table(conn)
        found, how = _detect(conn)

    if found > SCHEMA_VERSION:
        raise SchemaStateRefused(
            f"database schema is version {found}; this build expects "
            f"{SCHEMA_VERSION}. Running an older build against a newer schema "
            f"risks silent data loss. Deploy the matching build, or reset the "
            f"volume with `make reset` if the data is disposable.")

    applied = []
    for version in sorted(MIGRATIONS):
        if version <= found:
            continue
        try:
            with eng.begin() as conn:       # each step is its own transaction
                MIGRATIONS[version](conn)
                _stamp(conn, version)
        except SchemaStateRefused:
            raise
        except Exception as exc:            # noqa: BLE001
            # A bare driver error from a crash-looping container tells an
            # operator nothing. Name the step, the cause and the remedy.
            raise MigrationFailed(
                f"schema migration v{version} failed: {exc}\n"
                f"The database is still at v{found} and no partial change was "
                f"committed for this step. If the data is disposable, "
                f"`make reset`. Otherwise inspect the state, resolve the "
                f"conflict, and restart - migrations are idempotent and will "
                f"resume from v{found}.") from exc
        applied.append(version)

    # Wholly new tables only after the ALTERs and renames, so a rename is never
    # defeated by create_all having just made an empty table under the new name.
    db.metadata.create_all(eng)

    # Reconcile before stamping, and verify before stamping. The stamp used to
    # be written unconditionally, which made it a claim rather than a fact: one
    # silently skipped ALTER and the database recorded a version it had not
    # reached, then skipped that step on every subsequent run because it
    # believed itself current.
    reconciled = repair_missing_columns(eng)
    drift = verify_model_matches_database(eng, raise_on_drift=False)
    if drift:
        raise MigrationFailed(
            f"after migrating to v{SCHEMA_VERSION} the database is still "
            f"missing: {', '.join(drift)}. The version has NOT been stamped, "
            f"so this will be retried rather than silently skipped. A step "
            f"owns those columns and did not take effect.")

    with eng.begin() as conn:
        _stamp(conn, SCHEMA_VERSION)

    report = {"schema_version": SCHEMA_VERSION, "found": found,
              "detected_by": how, "migrations_applied": applied,
              # Surfaced rather than logged only: a reconciliation means a
              # migration step did not take effect, and that is worth seeing
              # on /v1/health rather than in a log nobody reads until the
              # service refuses to start.
              "columns_reconciled": reconciled}
    if applied:
        log.info("schema migrated %s -> %s (steps: %s)", found, SCHEMA_VERSION, applied)
    else:
        log.info("schema at version %s (%s)", SCHEMA_VERSION, how)
    return report


def status(engine=None) -> dict:
    eng = engine or db.engine
    with eng.connect() as conn:
        found, how = _detect(conn)
    return {"expected": SCHEMA_VERSION, "found": found, "detected_by": how,
            "up_to_date": found == SCHEMA_VERSION}