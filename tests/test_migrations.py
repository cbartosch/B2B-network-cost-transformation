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
        # provider_response_id is deliberately NOT declared UNIQUE here.
        # Migration v9 exists to *release* duplicate identifiers, so duplicates
        # have to be constructible in the pre-v9 state - and three tests insert
        # them on purpose. An inline UNIQUE made those tests fail on their own
        # setup. v9 drops the named constraint on Postgres and notes SQLite
        # cannot; that asymmetry is worth re-examining under a real engine.
        # Every other column here is one NO migration adds, so it must have existed
        # at 4.7.0 - see test_the_legacy_fixture_describes_a_state_that_can_
        # actually_upgrade. The earlier fixture omitted seven of them, which
        # described a database that could never have run the 4.7.0 gateway and
        # made three tests fail on their own setup.
        conn.execute(text('CREATE TABLE "audit"."llm_run" ('
                          'llm_run_id VARCHAR(36) PRIMARY KEY, '
                          'agent_run_id VARCHAR(36), '
                          'provider VARCHAR(32), '
                          'model VARCHAR(64), '
                          'request_hash VARCHAR(64), '
                          'response_hash VARCHAR(64), '
                          'provider_response_id VARCHAR(160) NOT NULL, '   # see note below
                          'provider_request_at TIMESTAMP, '
                          'input_tokens INTEGER, output_tokens INTEGER, '
                          'latency_ms INTEGER, '
                          'policy_version VARCHAR(32), '
                          'created_at TIMESTAMP)'))
        conn.execute(text('INSERT INTO "audit"."llm_run" '
                          "(llm_run_id, provider, provider_response_id, "
                          " provider_request_at, input_tokens, output_tokens) "
                          "VALUES ('l-legacy','anthropic','msg_legacy',NULL,10,5)"))
        conn.execute(text('CREATE TABLE "reference"."lever" ('
                          'lever_id VARCHAR(48) PRIMARY KEY, family VARCHAR(48), '
                          'description TEXT, cost_layers JSON, '
                          'saving_low NUMERIC(4,3), saving_base NUMERIC(4,3), '
                          'saving_high NUMERIC(4,3), scenario VARCHAR(1), '
                          'evidence_required TEXT)'))
        conn.execute(text('INSERT INTO "reference"."lever" '
                          "(lever_id, family) "
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
    # Was "uq_llm_run_provider_request_id" - the name migration v9 *drops*.
    # test_v9_scopes_uniqueness_to_the_provider asserts that same old name is
    # gone, so the two could never both pass. This one was stale: written
    # before v9 renamed the index, never re-run, so the contradiction sat
    # unnoticed in a single file.
    assert "uq_llm_run_provider_request" in names
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
                "(llm_run_id, provider, provider_response_id, "
                "provider_request_at, input_tokens, output_tokens) "
                "VALUES (:id,'anthropic',:resp,NULL,:tok,5)"),
                {"id": f"l-dup-{i}", "resp": f"msg_dup_{i}", "tok": tokens})
        conn.execute(text('UPDATE "audit"."llm_run" SET provider_request_id = NULL'
                          ) if False else text("SELECT 1"))
    migrations.ensure(db.engine)
    assert "uq_llm_run_provider_request" in {
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


def test_a_within_provider_duplicate_refuses_because_the_column_is_not_null():
    """A duplicate NOT NULL identifier cannot be released, and the migration
    now says so instead of crashing.

    This test previously asserted the opposite - that the second anthropic copy
    is released and all three rows survive. Executing it exposed a design
    contradiction rather than a simple bug:

      * `_release_duplicate_identifiers` releases by setting the column NULL
      * `audit.llm_run.provider_response_id` is `nullable=False`
      * therefore the release mechanism can never work on that column

    Two resolutions were possible. Making the column nullable would let the
    mechanism run, but weakens an audit identifier to satisfy a test, and the
    gateway already refuses a call with no response id (`verify_liveness`), so
    the constraint is defence in depth worth keeping. Refusing is the other,
    and it matches how the rest of this bundle behaves: fail closed, name the
    cause, require a person. The nullability check runs *before* any quarantine
    write, so nothing is staged and then rolled back - the live table is left
    exactly as it was, which is the state an operator wants to inspect.

    The cost is real and should be understood: a legacy database holding
    duplicate `provider_response_id` values will not start until an operator
    resolves them by hand. That is deliberate - a duplicate provider identifier
    may be the trace of a replayed response, which is exactly the thing this
    system exists to detect, and clearing it automatically at 3am is not a
    decision a migration should make.

    `provider_request_id` is nullable, so the release path still runs there,
    which is what `test_duplicates_are_preserved_not_deleted` covers.
    """
    _build_legacy()
    _llm_rows([("a1", "anthropic", "shared", "2026-08-01T00:00:00"),
               ("o1", "openai", "shared", "2026-08-02T00:00:00"),
               ("a2", "anthropic", "shared", "2026-08-03T00:00:00")])
    with pytest.raises(migrations.SchemaStateRefused) as exc:
        migrations.ensure(db.engine)
    assert "NOT NULL" in str(exc.value)
    assert "provider_response_id" in str(exc.value)

    with db.engine.connect() as conn:
        rows = conn.execute(text('SELECT COUNT(*) FROM "audit"."llm_run"')).scalar()
        quarantined = conn.execute(text(
            'SELECT COUNT(*) FROM "audit"."quarantined_row"')).scalar()
    # 4, not 3: _build_legacy() seeds one row before these three. The original
    # version of this test asserted 3, which could not have held even if the
    # release had worked - a second defect in the same never-executed test.
    assert rows == 4, "refusing must leave the live table exactly as it was"
    assert quarantined == 0, (
        "the check runs before any quarantine write, so nothing is staged and "
        "rolled back - a half-written audit trail is worse than none")


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


def test_the_legacy_fixture_describes_a_state_that_can_actually_upgrade():
    """A legacy fixture may omit ONLY columns that a migration adds.

    Anything else describes a database that could never be upgraded to the
    current schema - and therefore a test that proves nothing about the real
    upgrade path. The fixtures failed this: `audit.llm_run` omitted seven
    columns (model, request_hash, response_hash, created_at, agent_run_id,
    latency_ms, policy_version) and `reference.lever` omitted seven more, none
    of which any migration adds. Three tests failed on their own setup as a
    result, and nobody saw it because none had ever run.

    This checks the principle mechanically so the next person adding a column
    finds out here rather than in a confusing OperationalError.
    """
    import ast
    import pathlib
    import re

    # Two layouts: a checkout has api_service/app/, the image has app/ at the
    # WORKDIR root (COPY api_service/app ./app). Try both rather than assuming.
    root = pathlib.Path(__file__).resolve().parents[1]
    for candidate in (root / "api_service" / "app", root / "app"):
        if (candidate / "migrations.py").exists():
            app_dir = candidate
            break
    else:
        pytest.skip("cannot locate the application package from this layout")
    mig_src = (app_dir / "migrations.py").read_text()
    added = {}
    for m in re.finditer(r'_add_column\(conn,\s*db\.(\w+),\s*"(\w+)"\)', mig_src):
        added.setdefault(m.group(1), set()).add(m.group(2))
    for m in re.finditer(
            r'for column in \(([^)]*)\):\s*\n\s*added \+= _add_column\(conn, db\.(\w+), column\)',
            mig_src):
        for c in re.findall(r'"(\w+)"', m.group(1)):
            added.setdefault(m.group(2), set()).add(c)

    db_tree = ast.parse((app_dir / "db.py").read_text())
    current = {}
    for node in db_tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", None) == "Table"):
            current[node.targets[0].id] = {
                a.args[0].value for a in node.value.args[2:]
                if isinstance(a, ast.Call) and getattr(a.func, "id", "") == "Column"}

    fixture_src = pathlib.Path(__file__).read_text()
    for table in ("llm_run", "lever"):
        m = re.search(rf'CREATE TABLE "\w+"\."{table}" \((.*?)\)\'\)',
                      fixture_src, re.S)
        assert m, f"could not locate the legacy CREATE TABLE for {table}"
        declared = set(re.findall(r"(\w+) (?:VARCHAR|INTEGER|TIMESTAMP|TEXT|JSON|NUMERIC)",
                                  m.group(1)))
        unexplained = current[table] - declared - added.get(table, set())
        assert not unexplained, (
            f"the legacy fixture for {table} omits {sorted(unexplained)}, and no "
            f"migration adds them - so it describes a database that could never "
            f"reach the current schema")


# --- schema drift -----------------------------------------------------------
def test_a_column_in_the_model_but_not_the_database_is_refused_at_startup():
    """v16 added two columns to reference.unit_cost_prior. Where the step had
    not applied, preflight kept passing - it selects one column - while
    estimates:run returned a bare 500, because it selects the whole table.
    Same database, one endpoint working and one not, and nothing in the
    message saying "schema".

    ensure() applies steps; this checks the result."""
    _drop_everything()
    db.metadata.create_all(db.engine)
    # Fine as built.
    assert migrations.verify_model_matches_database(db.engine) == []

    # Now take a column away behind the model's back.
    with db.engine.begin() as conn:
        conn.execute(text('ALTER TABLE "reference"."unit_cost_prior" '
                          'DROP COLUMN "source_note"'))
    with pytest.raises(migrations.SchemaDrift, match="source_note"):
        migrations.verify_model_matches_database(db.engine)


def test_the_verifier_ignores_tables_create_all_has_not_built_yet():
    """A table absent entirely is not drift - create_all builds it complete
    moments later. Only a table that exists and is short a column is."""
    _drop_everything()
    assert migrations.verify_model_matches_database(db.engine) == []
