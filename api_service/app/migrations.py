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
SCHEMA_VERSION = 10

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
    """Add a column using the type compiled from the model definition."""
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
        conn.execute(text(
            f"CREATE UNIQUE INDEX {_q(name)} ON {_q('audit')}.{_q('llm_run')} "
            f"({_q('provider')}, {_q(column)})"))
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


MIGRATIONS = {2: _migrate_v2, 3: _migrate_v3, 4: _migrate_v4, 5: _migrate_v5,
              6: _migrate_v6, 7: _migrate_v7, 8: _migrate_v8, 9: _migrate_v9,
              10: _migrate_v10}


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
