"""Readiness must tell an unseeded database from a broken one.

An external audit found that /v1/ready returned 200 while ConfidencePolicy
could not load, so an orchestrator could route traffic to an instance that
answers every request and cannot compute a confidence score. That was right,
and the fix deadlocked the stack.

The container healthcheck calls /v1/ready. An unseeded database cannot load a
policy either, and seeding runs *after* `docker compose up` - so the API never
became healthy, the UI's `depends_on: api` never released, and the only way to
seed was through a container that would not start.

Two different conditions with one symptom. This file exists so they stay
separated.
"""
import ast
from pathlib import Path

import pytest


def _ready_source():
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    tree = ast.parse(api)
    fn = next(n for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "ready")
    return ast.unparse(fn)


def test_an_empty_threshold_table_is_ready():
    """A database waiting to be seeded is not a broken one. Seeding happens
    after the stack is up, so refusing here means nothing can ever seed it."""
    source = _ready_source()
    assert "if not rows:" in source
    assert "'not seeded'" in source or '"not seeded"' in source
    assert "'ready': True" in source or '"ready": True' in source


def test_it_says_what_it_is_waiting_for():
    """"not ready" with no reason sends an operator to the logs of a container
    that has not logged anything yet."""
    assert "app.seed" in _ready_source()


def test_thresholds_present_and_a_policy_that_will_not_build_is_a_fault():
    """The condition the audit found. An instance that looks available and
    cannot produce an estimate is worse than one that is down."""
    source = _ready_source()
    assert "unusable" in source
    assert "503" in source


def test_the_fault_names_which_policy_failed():
    """A 503 saying "governed policy unusable" sends somebody looking through
    thirteen policy classes."""
    source = _ready_source()
    assert "f'{name}:" in source or 'f"{name}:' in source


def test_it_checks_the_policy_sets_that_actually_exist():
    """`coverage_policy` is not a set name - the coverage floors are seeded
    under v0_coverage_threshold_set, and checking a name that does not exist
    would report every instance as broken."""
    from app.seed import THRESHOLDS

    seeded = {row[0] for row in THRESHOLDS}
    source = _ready_source()
    for name in ("confidence_policy", "v0_coverage_threshold_set",
                 "footprint_policy"):
        assert name in source, f"{name} is not checked"
        assert name in seeded, f"{name} is checked and never seeded"


def test_every_checked_set_builds_from_the_real_seed():
    """The check must pass on a correctly seeded database, or the stack never
    starts."""
    from app.domain import policy
    from app.seed import THRESHOLDS

    rows = {}
    for set_name, key, value, *_ in THRESHOLDS:
        rows.setdefault(set_name, {})[key] = value

    # from_rows raises on an incomplete set, so building is the assertion -
    # but a test whose only statement is a call reads as if somebody forgot
    # the check, and the vacuous-test guard is right to say so.
    built = []
    for name, cls in (("confidence_policy", policy.ConfidencePolicy),
                      ("v0_coverage_threshold_set", policy.CoveragePolicy),
                      ("footprint_policy", policy.FootprintPolicy)):
        built.append(cls.from_rows(rows.get(name, {}), set_name=name))
    assert len(built) == 3 and all(p.set_name for p in built)


def test_the_healthcheck_calls_the_endpoint_this_governs():
    """If the healthcheck moved to /v1/health this file would be guarding
    nothing - and /v1/health answers before the database is reachable at all,
    which is a different question."""
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "api_service" / "Dockerfile").read_text()
    assert "/v1/ready" in dockerfile
