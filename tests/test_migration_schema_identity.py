"""A migration that names the wrong schema succeeds and does nothing.

v66 added a CHECK constraint forbidding a REFUSED estimate snapshot. It
guarded on `outside_in.estimate_snapshot`, and db.py has always defined that
table in `analysis`. So on every existing database:

  1. `_has_table(conn, "outside_in", "estimate_snapshot")` returned False;
  2. it logged that create_all would build the table with the constraint;
  3. it returned, and the runner stamped v66 applied.

The constraint was never added. `create_all` does not add a CHECK constraint
to a table that already exists, so the log was wrong as well as the guard --
only databases created fresh after v66 ever got it, which is the complement of
the set that holds data.

Nothing failed. The migration reported success, the version advanced, and the
integrity rule the migration exists for was absent exactly where it mattered.
That is the failure mode this test is for: not a migration that errors, but
one that silently no-ops because a string disagrees with the model.

Found by automated review on PR #4.
"""
from __future__ import annotations

import pathlib
import re

from app import db

MIGRATIONS_PY = pathlib.Path(db.__file__).with_name("migrations.py")


def _schema_of_each_table() -> dict[str, set[str]]:
    """table name -> the schema(s) the model actually puts it in."""
    out: dict[str, set[str]] = {}
    for table in db.metadata.tables.values():
        out.setdefault(table.name, set()).add(table.schema)
    return out


def _qualified_references(source: str) -> set[tuple[str, str]]:
    return set(re.findall(r"\b([a-z_]+)\.([a-z_]+)\b", source))


def test_every_schema_qualified_table_in_migrations_matches_the_model():
    """The general form of the v66 defect.

    Checks every `schema.table` string in migrations.py against db.py. A
    mismatch cannot be caught by running the migrations, because naming a
    schema that does not exist makes the table look absent rather than making
    the statement fail.
    """
    real = _schema_of_each_table()
    known_schemas = {s for schemas in real.values() for s in schemas if s}
    source = MIGRATIONS_PY.read_text(encoding="utf-8")

    mismatched = [
        f"{schema}.{table} (model says {sorted(x for x in real[table] if x)})"
        for schema, table in sorted(_qualified_references(source))
        if schema in known_schemas and table in real and schema not in real[table]
    ]

    assert not mismatched, (
        "migrations name a schema the model disagrees with; the migration will "
        "find no table, skip, and still be stamped applied:\n  "
        + "\n  ".join(mismatched))


def test_the_check_has_something_to_check():
    """Guards the test above from passing vacuously.

    If the reference pattern stops matching, or the metadata stops being
    importable, the assertion becomes trivially true and the defect walks back
    in unnoticed.
    """
    real = _schema_of_each_table()
    known_schemas = {s for schemas in real.values() for s in schemas if s}
    source = MIGRATIONS_PY.read_text(encoding="utf-8")

    checked = [
        (schema, table)
        for schema, table in _qualified_references(source)
        if schema in known_schemas and table in real
    ]

    assert len(known_schemas) >= 5, f"only {len(known_schemas)} schemas found"
    assert len(checked) >= 20, (
        f"only {len(checked)} schema-qualified references checked; the pattern "
        f"has probably stopped matching")


def test_v66_targets_the_schema_the_model_defines():
    """The specific case, stated so a reader sees which table was wrong."""
    assert db.estimate_snapshot.schema == "analysis"

    source = MIGRATIONS_PY.read_text(encoding="utf-8")
    body = source[source.index("def _migrate_v66"):]
    body = body[:body.index("\nMIGRATIONS")]

    assert "outside_in.estimate_snapshot" not in body, (
        "v66 names outside_in; the model defines the table in analysis, so the "
        "migration silently skips on every existing database")


def test_v66_derives_the_schema_rather_than_naming_it():
    """A literal is what drifted. Reading it off the model cannot."""
    source = MIGRATIONS_PY.read_text(encoding="utf-8")
    body = source[source.index("def _migrate_v66"):]
    body = body[:body.index("\nMIGRATIONS")]

    assert "db.estimate_snapshot.schema" in body
