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
SCHEMA_VERSION = 21

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
    """4.18.0 -> 4.19.0: audit.llm_run.quality_reasons.

    One additive column carrying the quality gate's verdict on each call.
    Historical rows keep null: a call made before the gate existed was not
    judged by it, and stamping ACCEPTED on it would assert a review that never
    happened.
    """
    added = _add_column(conn, db.llm_run, "quality_reasons")
    log.info("v21: quality_reasons column added=%s", bool(added))


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


MIGRATIONS = {2: _migrate_v2, 3: _migrate_v3, 4: _migrate_v4, 5: _migrate_v5,
              6: _migrate_v6, 7: _migrate_v7, 8: _migrate_v8, 9: _migrate_v9,
              10: _migrate_v10, 11: _migrate_v11, 12: _migrate_v12,
              13: _migrate_v13, 14: _migrate_v14, 15: _migrate_v15,
              16: _migrate_v16, 17: _migrate_v17, 18: _migrate_v18,
              19: _migrate_v19, 20: _migrate_v20,
              21: _migrate_v21}


class SchemaDrift(RuntimeError):
    """The database is missing a column the code will select."""


def verify_model_matches_database(engine) -> list:
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
    if missing:
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

    with eng.begin() as conn:
        _stamp(conn, SCHEMA_VERSION)

    report = {"schema_version": SCHEMA_VERSION, "found": found,
              "detected_by": how, "migrations_applied": applied}
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
