"""Schema migration tests.

These construct a 4.7.0-shaped database and upgrade it, because C2-03 was the
failure that only appears on a *second* deployment - the one nobody rehearses.
"""
import pytest
from sqlalchemy import inspect, select, text

from app import db, migrations


def _drop_everything():
    db.assert_disposable()
    db.metadata.drop_all(db.engine)
    with db.engine.begin() as conn:
        for schema, table in (("audit", "schema_version"),
                              ("engagement", "case"),
                              ("engagement", "engagement_case")):
            try:
                conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table}"'))
            except Exception:                            # noqa: BLE001
                pass


def _build_legacy():
    """The 4.7.0 physical shape: reserved-word table, no liveness columns, no
    lever stage column, no platform_unit_cost, no version stamp."""
    _drop_everything()
    with db.engine.begin() as conn:
        conn.execute(text('CREATE TABLE "engagement"."case" ('
                          'case_id VARCHAR(36) PRIMARY KEY, '
                          'subject_entity_legal_name TEXT)'))
        conn.execute(text('INSERT INTO "engagement"."case" VALUES '
                          "('c-legacy','Acme Global Holdings PLC')"))
        conn.execute(text('CREATE TABLE "audit"."llm_run" ('
                          'llm_run_id VARCHAR(36) PRIMARY KEY, '
                          'provider VARCHAR(32), '
                          'provider_response_id VARCHAR(160) NOT NULL UNIQUE, '
                          'provider_request_at TIMESTAMP, '
                          'input_tokens INTEGER, output_tokens INTEGER)'))
        conn.execute(text('INSERT INTO "audit"."llm_run" '
                          "VALUES ('l-legacy','anthropic','msg_legacy',NULL,10,5)"))
        conn.execute(text('CREATE TABLE "reference"."lever" ('
                          'lever_id VARCHAR(48) PRIMARY KEY, family VARCHAR(48))'))
        conn.execute(text('INSERT INTO "reference"."lever" '
                          "VALUES ('LEV-REPRICE-001','Same-service repricing')"))
        conn.execute(text('CREATE TABLE "reference"."threshold" ('
                          'set_name VARCHAR(64), key VARCHAR(64), value NUMERIC, '
                          'version INTEGER, approved_by VARCHAR(120), note TEXT, '
                          'PRIMARY KEY (set_name, key))'))
        conn.execute(text('INSERT INTO "reference"."threshold" VALUES '
                          "('v0_coverage_threshold_set','v0_prior_coverage_min',"
                          "0.88,4,'analyst','tuned on a live engagement')"))


def _columns(schema, table):
    with db.engine.connect() as conn:
        return {c["name"] for c in inspect(conn).get_columns(table, schema=schema)}


# --- detection --------------------------------------------------------------
def test_fresh_database_is_detected_and_needs_no_migration():
    _drop_everything()
    report = migrations.ensure(db.engine)
    assert report["detected_by"] == "fresh database"
    assert report["migrations_applied"] == []
    assert migrations.status(db.engine)["up_to_date"]


def test_unstamped_existing_database_is_detected_as_legacy():
    _build_legacy()
    with db.engine.connect() as conn:
        found, how = migrations._detect(conn)
    assert found == 1 and "inferred" in how


# --- the upgrade itself -----------------------------------------------------
def test_legacy_upgrade_adds_liveness_columns():
    """Without these, every llm_run INSERT fails and no LIVE run can record
    its proof - the control the whole design rests on."""
    _build_legacy()
    migrations.ensure(db.engine)
    cols = _columns("audit", "llm_run")
    assert {"provider_request_id", "local_request_at", "clock_skew_seconds",
            "egress_proxy", "http_status"} <= cols


def test_legacy_upgrade_adds_the_lever_stage_column():
    _build_legacy()
    migrations.ensure(db.engine)
    assert "earliest_supported_stage" in _columns("reference", "lever")


def test_legacy_upgrade_renames_the_reserved_word_table_and_keeps_cases():
    """The silent one: create_all made an empty engagement_case and every
    existing case became invisible."""
    _build_legacy()
    migrations.ensure(db.engine)
    with db.engine.connect() as conn:
        row = conn.execute(text('SELECT subject_entity_legal_name FROM '
                                '"engagement"."engagement_case" '
                                "WHERE case_id='c-legacy'")).first()
    assert row and row[0] == "Acme Global Holdings PLC"
    assert not migrations._has_table(db.engine.connect(), "engagement", "case")


def test_legacy_data_survives_the_upgrade():
    _build_legacy()
    migrations.ensure(db.engine)
    with db.engine.connect() as conn:
        run = conn.execute(text('SELECT provider_response_id, provider_request_id '
                                'FROM "audit"."llm_run"')).first()
    assert run[0] == "msg_legacy" and run[1] is None


def test_migration_is_idempotent():
    _build_legacy()
    first = migrations.ensure(db.engine)
    second = migrations.ensure(db.engine)
    assert first["migrations_applied"] and second["migrations_applied"] == []
    assert migrations.status(db.engine)["up_to_date"]


def test_legacy_upgrade_adds_request_id_uniqueness(session=None):
    """v5. A unique index, not a constraint: SQLite cannot add a constraint to
    an existing table."""
    _build_legacy()
    migrations.ensure(db.engine)
    with db.engine.connect() as conn:
        names = {i["name"] for i in inspect(conn).get_indexes("llm_run", schema="audit")}
    assert "uq_llm_run_provider_request_id" in names
    assert "externally_verifiable" in _columns("audit", "llm_run")


# --- C3-04: a constraint added to data that never had one ------------------
def test_duplicate_identifiers_do_not_crash_the_migration():
    """Adding uniqueness to data that never had it can fail on that data. The
    earlier version created the index directly, so a legacy database with two
    matching identifiers crash-looped the container at startup."""
    _build_legacy()
    with db.engine.begin() as conn:
        for i, tokens in ((2, 20), (3, 30)):
            conn.execute(text(
                'INSERT INTO "audit"."llm_run" '
                "VALUES (:id,'anthropic',:resp,NULL,:tok,5)"),
                {"id": f"l-dup-{i}", "resp": f"msg_dup_{i}", "tok": tokens})
        conn.execute(text('UPDATE "audit"."llm_run" SET provider_request_id = NULL'
                          ) if False else text("SELECT 1"))
    migrations.ensure(db.engine)
    assert "uq_llm_run_provider_request_id" in {
        i["name"] for i in inspect(db.engine.connect()).get_indexes(
            "llm_run", schema="audit")}


def test_duplicates_are_preserved_not_deleted():
    """A duplicate provider identifier can be the trace of a replayed response.
    Repairing it away would destroy the evidence of the one thing the constraint
    exists to catch."""
    _build_legacy()
    with db.engine.begin() as conn:
        conn.execute(text('ALTER TABLE "audit"."llm_run" '
                          "ADD COLUMN provider_request_id VARCHAR(160)"))
        for i in (1, 2, 3):
            conn.execute(text(
                'INSERT INTO "audit"."llm_run" (llm_run_id, provider, '
                "provider_response_id, input_tokens, output_tokens, "
                "provider_request_id) VALUES (:id,'anthropic',:resp,:tok,5,'req_same')"),
                {"id": f"l-d{i}", "resp": f"msg_d{i}", "tok": 10 * i})
        before = conn.execute(text('SELECT COUNT(*) FROM "audit"."llm_run"')).scalar()

    migrations.ensure(db.engine)

    with db.engine.connect() as conn:
        after = conn.execute(text('SELECT COUNT(*) FROM "audit"."llm_run"')).scalar()
        quarantined = conn.execute(text(
            'SELECT COUNT(*) FROM "audit"."quarantined_row"')).scalar()
        incidents = conn.execute(text(
            'SELECT severity, kind FROM "audit"."integrity_incident"')).all()
        kept = conn.execute(text(
            'SELECT COUNT(*) FROM "audit"."llm_run" '
            "WHERE provider_request_id = 'req_same'")).scalar()
    assert after == before, "no row may be deleted"
    assert quarantined >= 2, "displaced copies must be preserved in full"
    assert incidents and incidents[0][0] == "P2"
    assert kept == 1, "exactly one copy keeps the identifier"


def test_a_migration_failure_names_the_step_and_a_remedy(monkeypatch):
    """A bare driver error from a crash-looping container tells an operator
    nothing about what to do next."""
    _drop_everything()

    def boom(_conn):
        raise RuntimeError("disk on fire")

    monkeypatch.setitem(migrations.MIGRATIONS, 2, boom)
    _build_legacy()
    with pytest.raises(migrations.MigrationFailed) as exc:
        migrations.ensure(db.engine)
    message = str(exc.value)
    assert "v2" in message and "make reset" in message and "idempotent" in message


def test_support_tables_exist_before_any_migration_runs():
    """A migration that finds a data conflict needs somewhere to put the
    evidence before it can proceed."""
    _drop_everything()
    migrations.ensure(db.engine)
    with db.engine.connect() as conn:
        names = {t for t in inspect(conn).get_table_names(schema="audit")}
    assert {"integrity_incident", "quarantined_row"} <= names


# --- C4-03: the release must respect the uniqueness scope ------------------
def _llm_rows(rows):
    """rows = [(id, provider, response_id, created_at)]"""
    with db.engine.begin() as conn:
        for rid, provider, resp, created in rows:
            conn.execute(text(
                'INSERT INTO "audit"."llm_run" (llm_run_id, provider, '
                "provider_response_id, provider_request_at, input_tokens, "
                "output_tokens, created_at) "
                "VALUES (:id, :p, :r, NULL, 1, 1, :c)"),
                {"id": rid, "p": provider, "r": resp, "c": created})


def test_a_cross_provider_collision_is_not_treated_as_a_duplicate():
    """The finding: scope reached the GROUP BY and stopped there, so a migration
    written to stop treating a cross-provider collision as a replay did exactly
    that while running."""
    _build_legacy()
    _llm_rows([("a1", "anthropic", "shared", "2026-08-01T00:00:00"),
               ("o1", "openai", "shared", "2026-08-02T00:00:00")])
    migrations.ensure(db.engine)
    with db.engine.connect() as conn:
        kept = conn.execute(text(
            'SELECT llm_run_id FROM "audit"."llm_run" '
            "WHERE provider_response_id = 'shared' ORDER BY llm_run_id")).all()
        quarantined = conn.execute(text(
            'SELECT COUNT(*) FROM "audit"."quarantined_row"')).scalar()
    assert {r[0] for r in kept} == {"a1", "o1"}, \
        "one identifier per provider is legitimate and must survive"
    assert quarantined == 0, "nothing should have been quarantined"


def test_a_within_provider_duplicate_is_still_released():
    """The control itself is unchanged - only the false positive is gone."""
    _build_legacy()
    _llm_rows([("a1", "anthropic", "shared", "2026-08-01T00:00:00"),
               ("o1", "openai", "shared", "2026-08-02T00:00:00"),
               ("a2", "anthropic", "shared", "2026-08-03T00:00:00")])
    migrations.ensure(db.engine)
    with db.engine.connect() as conn:
        kept = {r[0] for r in conn.execute(text(
            'SELECT llm_run_id FROM "audit"."llm_run" '
            "WHERE provider_response_id = 'shared'")).all()}
        rows = conn.execute(text('SELECT COUNT(*) FROM "audit"."llm_run"')).scalar()
    assert kept == {"a1", "o1"}, "the second anthropic copy is released"
    assert rows == 3, "and nothing is deleted"


def test_v5_alone_neither_indexes_nor_releases_anything():
    """v5 used to build a single-column index that v9 replaces, forcing a
    *global* uniqueness release on the way through and stripping identifiers two
    providers may legitimately share - before v9 could apply the correct scope.

    Run the step in isolation rather than reading its source: a grep for
    "CREATE UNIQUE INDEX" would pass on any rewrite that spelled it differently.
    """
    _build_legacy()
    _llm_rows([("a1", "anthropic", "shared", "2026-08-01T00:00:00"),
               ("o1", "openai", "shared", "2026-08-02T00:00:00")])
    with db.engine.begin() as conn:
        migrations._ensure_support_tables(db.engine)
        migrations._migrate_v5(conn)
    with db.engine.connect() as conn:
        names = {i["name"] for i in inspect(conn).get_indexes("llm_run", schema="audit")}
        intact = conn.execute(text(
            'SELECT COUNT(*) FROM "audit"."llm_run" '
            "WHERE provider_response_id = 'shared'")).scalar()
        quarantined = conn.execute(text(
            'SELECT COUNT(*) FROM "audit"."quarantined_row"')).scalar()
    assert not any(n.startswith("uq_llm_run_provider") for n in names)
    assert intact == 2 and quarantined == 0


def test_the_composite_index_exists_after_upgrade():
    _build_legacy()
    migrations.ensure(db.engine)
    with db.engine.connect() as conn:
        names = {i["name"] for i in inspect(conn).get_indexes("llm_run", schema="audit")}
    assert "uq_llm_run_provider_response" in names
    assert "uq_llm_run_provider_request" in names
    assert "uq_llm_run_provider_request_id" not in names, "the superseded index is gone"


# --- refusal ----------------------------------------------------------------
def test_newer_schema_than_the_build_refuses_to_start():
    """Rolling back the code against a migrated database must stop, not guess."""
    _drop_everything()
    migrations.ensure(db.engine)
    with db.engine.begin() as conn:
        migrations._stamp(conn, migrations.SCHEMA_VERSION + 5)
    with pytest.raises(migrations.SchemaStateRefused):
        migrations.ensure(db.engine)


def test_half_applied_rename_refuses_rather_than_guessing():
    """Both tables present means an interrupted upgrade. Choosing one risks
    discarding live cases."""
    _build_legacy()
    with db.engine.begin() as conn:
        conn.execute(text('CREATE TABLE "engagement"."engagement_case" '
                          '(case_id VARCHAR(36) PRIMARY KEY)'))
    with pytest.raises(migrations.SchemaStateRefused):
        migrations.ensure(db.engine)


# --- the seed hole ----------------------------------------------------------
def test_seed_populates_a_table_added_by_a_later_build():
    """The nastiest part of C2-03: seed skipped everything because thresholds
    existed, so platform_unit_cost stayed empty and ~40% of TCO vanished from
    a system that otherwise ran perfectly well."""
    _build_legacy()
    migrations.ensure(db.engine)
    from app.seed import seed
    seed(force=False)
    s = db.SessionLocal()
    try:
        assert s.execute(select(db.platform_unit_cost)).first(), \
            "platform costs must be seeded even though thresholds already existed"
    finally:
        s.close()


def test_seed_does_not_overwrite_a_populated_table():
    _build_legacy()
    migrations.ensure(db.engine)
    from app.seed import seed
    seed(force=False)
    s = db.SessionLocal()
    try:
        row = s.execute(select(db.threshold).where(
            db.threshold.c.key == "v0_prior_coverage_min")).one()
        assert row.version == 4 and row.approved_by == "analyst", \
            "an analyst-tuned threshold must survive the upgrade"
    finally:
        s.close()
