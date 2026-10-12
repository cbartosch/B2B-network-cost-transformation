"""Test fixtures.

Controls that depend on the database are exercised against a real SQLAlchemy
engine, because the first audit found that none of the tests touched the DB and
the DB is where the controls live.

The second audit found the harness itself was the danger: this file used
`os.environ.setdefault("DATABASE_URL", ...)`, which is a no-op when the variable
already exists - and the api container sets it to Postgres. `make test`
therefore dropped every table in the live database, once per test.

Three independent layers now prevent that:
  1. the Makefile passes DATABASE_URL explicitly to the test process
  2. this file assigns it unconditionally, not by default
  3. db.assert_disposable() refuses any destructive call against a non-SQLite
     engine, and pytest_configure aborts the whole session before a single test
     runs if the binding is wrong
"""
import os
import sys

# Unconditional. setdefault was the defect: it silently deferred to whatever the
# container had already set.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["WORKBENCH_ENVIRONMENT"] = "TEST"

# The same lesson as DATABASE_URL, one live resource over.
#
# The api container is given ANTHROPIC_API_KEY from the environment, and
# anyone working on this system has one set. config.py reads it at import
# time, so the adapters came up configured and the suite made real, billable
# calls to the provider: one entity-resolution test alone recorded 22,431
# input tokens and 51 seconds of latency, and
# test_entity_resolution_fails_closed_without_a_provider - "the single most
# important behaviour in the bundle: no provider means no output, not
# fabricated output" - passed or failed depending on whose laptop it ran on.
#
# Cleared unconditionally and before anything imports config, for the reason
# the database binding is: a test harness must not be able to reach a live
# resource by inheriting it. Tests that need a provider install a fake
# adapter over gateway._adapters and are unaffected.
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""

sys.path.insert(0, "/app")

import pytest  # noqa: E402


def pytest_configure(config):
    """Abort before collection if the engine is not disposable.

    This runs ahead of every test, including ones that call seed(force=True),
    which deletes reference data and would otherwise fire against a real
    database even if no fixture had dropped the schema yet.
    """
    from app import db
    try:
        db.assert_disposable()
    except db.DestructiveOperationRefused as exc:
        raise pytest.UsageError(
            f"Refusing to run the control suite: {exc}\n"
            f"Resolved DATABASE_URL={os.environ.get('DATABASE_URL')!r}. "
            f"Run via `make test`, which sets it explicitly."
        ) from exc


@pytest.fixture()
def session():
    from app import db
    db.reset_schema()          # guarded; never a bare drop_all
    s = db.SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client():
    """An HTTP client against the app, with its lifespan run.

    Lives here because six test files ask for it and only three defined it -
    identically, in three places. The other three errored at setup with
    "fixture 'client' not found" and never ran, which is not a result anyone
    reads as a missing fixture when it sits among hundreds of lines of output.

    `with TestClient(app)` rather than a bare construction: the lifespan is
    what seeds reference data, and several suites depend on it having run.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c
