"""Wiring tests: does startup actually do what it claims?

Three audits running produced a finding of the same shape - something written,
documented as a control, and (apparently) never invoked. The third instance was
a false positive: `requeue_interrupted` *was* called from the lifespan, and the
audit searched for the wrong identifier and read two empty greps as proof.

Both the real defects and the false positive have the same remedy. A unit test
on a control passes whether or not anything calls it, and a grep for a call site
depends on guessing the name. A test that exercises the real startup path and
asserts the control fired settles the question either way.

So these assert invocation, not implementation: that the lifespan runs
migrations, seeds, and reclaims interrupted work; that the auth middleware runs
on a real request; and that constraints declared in the model exist in a created
database rather than only in Python.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app import db, jobs, migrations
from app.main import app


def _spy(calls, name, result=None):
    def fn(*args, **kwargs):
        calls.append(name)
        return result
    return fn


# --- startup ----------------------------------------------------------------
def test_startup_reclaims_interrupted_simulations(monkeypatch):
    """C3-01. Had this existed, the audit would not have had to guess from greps
    - and would have found the wiring present."""
    calls = []
    monkeypatch.setattr(jobs, "reclaim_interrupted",
                        _spy(calls, "reclaim", {"cancelled": 0, "requeued": 0,
                                                "deferred": 0}))
    with TestClient(app):
        pass
    assert "reclaim" in calls, "lifespan does not reclaim interrupted simulations"


def test_startup_runs_migrations(monkeypatch):
    calls = []
    monkeypatch.setattr(migrations, "ensure",
                        _spy(calls, "migrate", {"schema_version": 0, "found": 0,
                                                "detected_by": "spy",
                                                "migrations_applied": []}))
    with TestClient(app):
        pass
    assert "migrate" in calls, "lifespan does not run migrations"


def test_startup_seeds_reference_data(monkeypatch):
    import app.seed as seed_module
    calls = []
    monkeypatch.setattr(seed_module, "seed", _spy(calls, "seed"))
    with TestClient(app):
        pass
    assert "seed" in calls, "lifespan does not seed reference data"


def test_a_failed_reclaim_does_not_prevent_the_service_starting(monkeypatch):
    """Best effort: recovery is not worth refusing to serve over."""
    def boom(*_a, **_k):
        raise RuntimeError("database asleep")

    monkeypatch.setattr(jobs, "reclaim_interrupted", boom)
    with TestClient(app) as c:
        assert c.get("/v1/health").status_code == 200


def test_a_refused_schema_does_prevent_the_service_starting(monkeypatch):
    """The opposite call: a wrong schema is worth refusing to serve over,
    because the alternative is running and being quietly wrong."""
    def refuse(*_a, **_k):
        raise migrations.SchemaStateRefused("schema is newer than this build")

    monkeypatch.setattr(migrations, "ensure", refuse)
    with pytest.raises(migrations.SchemaStateRefused):
        with TestClient(app):
            pass


# --- middleware -------------------------------------------------------------
def test_the_auth_middleware_runs_on_a_real_request(monkeypatch):
    """Registration is not execution. A middleware attached to the wrong app
    object, or after the router, would pass every unit test."""
    from app import config
    monkeypatch.setattr(config, "API_TOKEN", "wiring-check")
    with TestClient(app) as c:
        assert c.get("/v1/agents").status_code == 401


# --- schema -----------------------------------------------------------------
def test_declared_unique_indexes_exist_in_the_database(session):
    """A model declaration is not a constraint. Two of the integrity controls
    rest on the database refusing a duplicate, which is only true if the index
    was actually created."""
    with db.engine.connect() as conn:
        indexes = {i["name"] for i in inspect(conn).get_indexes("llm_run",
                                                               schema="audit")}
    # Migration v9 renames this to uq_llm_run_provider_request and explicitly
    # asserts the _id form is gone. The same stale name was fixed in
    # test_migrations.py; this duplicate was missed because the offline harness
    # could not introspect indexes and skipped the test entirely.
    assert "uq_llm_run_provider_request" in indexes


def test_declared_unique_constraints_are_enforced_by_the_database(session):
    """Behavioural counterpart: assert the database refuses, not that a name
    appears in a catalogue."""
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    shared = f"msg_{uuid.uuid4().hex}"
    run_id = jobs and None  # noqa: B018 - keep import order explicit
    for i in range(2):
        agent_run = str(uuid.uuid4())
        session.execute(insert(db.agent_run).values(
            agent_run_id=agent_run, agent_id="ENTITY-RESOLVE",
            graph_version="v1.0.0", execution_mode="LIVE", environment="TEST",
            status="QUEUED"))
        stmt = insert(db.llm_run).values(
            llm_run_id=str(uuid.uuid4()), agent_run_id=agent_run,
            provider="anthropic", model="m", request_hash="a", response_hash="b",
            provider_response_id=shared,
            provider_request_at=datetime.now(timezone.utc),
            input_tokens=1, output_tokens=1)
        if i == 0:
            session.execute(stmt)
            session.commit()
        else:
            with pytest.raises(IntegrityError):
                session.execute(stmt)
                session.commit()
            session.rollback()


# --- the reclaim itself -----------------------------------------------------
def test_reclaim_honours_a_cancellation_the_dead_process_could_not(session):
    """A run someone asked to stop must not be resurrected by a restart."""
    import uuid

    from sqlalchemy import insert, select
    rid = str(uuid.uuid4())
    session.execute(insert(db.simulation_run).values(
        simulation_run_id=rid, model_version="sim-1.0.0", seed=1, ensemble_size=5,
        params={"footprint": []}, pinned_priors={"archetype_prior": {}},
        status=jobs.CANCELLING, cancel_requested=True,
        progress_completed=2, progress_total=5))
    session.commit()

    jobs.reclaim_interrupted()
    session.expire_all()
    row = session.execute(select(db.simulation_run).where(
        db.simulation_run.c.simulation_run_id == rid)).one()
    assert row.status == jobs.CANCELLED


def test_reclaim_leaves_a_deferred_run_queued_not_running(session, monkeypatch):
    """When the pool is full the row must not stay RUNNING, or it is
    indistinguishable from a live job and no later restart will find it."""
    import uuid

    from sqlalchemy import insert, select

    def full(_run_id):
        raise jobs.QueueFull("pool is full")

    monkeypatch.setattr(jobs, "submit", full)
    rid = str(uuid.uuid4())
    session.execute(insert(db.simulation_run).values(
        simulation_run_id=rid, model_version="sim-1.0.0", seed=1, ensemble_size=5,
        params={"footprint": []}, pinned_priors={"archetype_prior": {}},
        status=jobs.RUNNING, cancel_requested=False,
        progress_completed=2, progress_total=5))
    session.commit()

    report = jobs.reclaim_interrupted()
    session.expire_all()
    row = session.execute(select(db.simulation_run).where(
        db.simulation_run.c.simulation_run_id == rid)).one()
    assert report["deferred"] == 1
    assert row.status == jobs.QUEUED


# --- C3-08: the healthcheck must not be expensive ---------------------------
def test_health_is_shallow_by_default(monkeypatch):
    """The container polls it every 10 seconds. A schema query plus two full
    policy validations per poll is a validation pass every ten seconds forever
    for no new information."""
    from app.routers import api as api_module
    calls = []
    monkeypatch.setattr(api_module.migrations, "status",
                        _spy(calls, "schema", {"up_to_date": True}))
    with TestClient(app) as c:
        body = c.get("/v1/health").json()
    assert "schema" not in body
    assert "schema" not in calls


def test_health_deep_reports_schema_and_policy():
    with TestClient(app) as c:
        body = c.get("/v1/health", params={"deep": True}).json()
    assert "schema" in body and "policy" in body


def test_health_deep_is_cached():
    """Two deep calls in quick succession must not run the checks twice."""
    from app.routers import api as api_module
    api_module._DEEP_CACHE.update(at=None, value=None)
    with TestClient(app) as c:
        first = c.get("/v1/health", params={"deep": True}).json()
        second = c.get("/v1/health", params={"deep": True}).json()
    assert first["cached"] is False and second["cached"] is True


# --- C4-04: the probe the container polls must answer the right question ----
def test_readiness_reports_a_database_outage(monkeypatch):
    """Making /v1/health shallow removed its database round-trip while the
    container still polled it, so an unreachable database reported healthy."""
    from app import db as db_module

    class _Broken:
        def connect(self):
            raise RuntimeError("could not connect to server")

    with TestClient(app) as c:
        monkeypatch.setattr(db_module, "engine", _Broken())
        r = c.get("/v1/ready")
    assert r.status_code == 503
    assert r.json()["ready"] is False
    assert "database" in r.json()["reason"]


def test_readiness_is_not_cached():
    """A cached readiness answer is not a readiness answer. Two calls must each
    reach the database."""
    from app import db as db_module
    calls = []
    real = db_module.engine.connect

    def counting():
        calls.append(1)
        return real()

    with TestClient(app) as c:
        db_module.engine.connect = counting
        try:
            c.get("/v1/ready")
            c.get("/v1/ready")
        finally:
            db_module.engine.connect = real
    assert len(calls) == 2


def test_liveness_makes_no_database_call():
    """Restarting will not fix a database outage, so liveness must not depend
    on one."""
    from app import db as db_module
    calls = []
    real = db_module.engine.connect

    def counting():
        calls.append(1)
        return real()

    with TestClient(app) as c:
        db_module.engine.connect = counting
        try:
            assert c.get("/v1/health").status_code == 200
        finally:
            db_module.engine.connect = real
    assert not calls


def test_the_container_healthcheck_targets_a_reachable_unauthenticated_path():
    """Cross-file wiring: the Dockerfile names a URL, the app has to serve it
    without a token. Nothing else checks that those two agree."""
    import re
    from pathlib import Path

    from app import config as config_module

    dockerfile = Path(__file__).resolve().parents[1] / "api_service" / "Dockerfile"
    if not dockerfile.exists():
        pytest.skip("Dockerfile not present in this image")
    text_ = dockerfile.read_text()
    match = re.search(r"http://127\.0\.0\.1:8000(/[\w/\-]+)", text_)
    assert match, "no healthcheck URL found in the Dockerfile"
    path = match.group(1)
    assert path in config_module.AUTH_EXEMPT_PATHS, (
        f"the healthcheck polls {path}, which is not auth-exempt; enabling "
        f"API_TOKEN would mark the container unhealthy forever")
    with TestClient(app) as c:
        assert c.get(path).status_code == 200


def test_a_failing_deep_check_is_not_cached(monkeypatch):
    """Caching a failure keeps reporting it after it is fixed - and a stale
    success is the shape that let a dead database look healthy."""
    from app.routers import api as api_module
    api_module._DEEP_CACHE.update(at=None, value=None)
    monkeypatch.setattr(api_module, "_policy_health",
                        lambda: {"usable": False, "detail": "policy broken"})
    with TestClient(app) as c:
        c.get("/v1/health", params={"deep": True})
    assert api_module._DEEP_CACHE["at"] is None


def test_startup_refuses_enforcement_without_spki_support(monkeypatch):
    """Wiring: the check exists, and the lifespan actually performs it."""
    from app.llm.providers import _transport
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    monkeypatch.setattr(_transport, "ALLOW_CERT_ONLY_PINNING", False)
    # startup_check() raises PinConfigurationRefused. PinningUnsupported is
    # raised by a different function for the same condition, gated on a
    # differently-named override - the open A15 finding. This asserts what the
    # startup path actually does; unifying the two is a decision about a
    # security control and is deliberately not taken here.
    with pytest.raises(_transport.PinConfigurationRefused):
        with TestClient(app):
            pass


def test_startup_refuses_a_silently_degrading_pin_configuration(monkeypatch):
    """Wiring: the check exists and the lifespan calls it. Both halves needed."""
    from app.llm.providers import _transport
    monkeypatch.setattr(_transport, "startup_check",
                        lambda: (_ for _ in ()).throw(
                            _transport.PinConfigurationRefused("cert-only enforce")))
    with pytest.raises(_transport.PinConfigurationRefused):
        with TestClient(app):
            pass


def test_startup_logs_pin_warnings_without_refusing(monkeypatch):
    from app.llm.providers import _transport
    monkeypatch.setattr(_transport, "startup_check", lambda: ["degraded but usable"])
    with TestClient(app) as c:
        assert c.get("/v1/health").status_code == 200


# --- routes must actually be callable ---------------------------------------
def test_every_domain_call_from_a_route_matches_its_signature():
    """estimates:run passed footprint_origin= and users_origin= to
    build_components, which takes neither. Every request raised TypeError
    before reaching the calculation, so V0 returned a bare 500 from the
    original build onward - while the unit tests, which call build_components
    directly with the right keywords, passed the whole time.

    Binding each call's keywords against the real signature catches the class:
    a route and a domain function that disagree about their contract."""
    import ast
    import inspect
    import pathlib

    from app.domain import (confidence, coverage, dispositions, estimate,
                            known_facts, promotion, research)

    modules = {"estimate": estimate, "coverage": coverage,
               "confidence": confidence, "dispositions": dispositions,
               "known_facts": known_facts, "research": research,
               "promotion": promotion}

    root = pathlib.Path(__file__).resolve().parents[1]
    for candidate in (root / "api_service" / "app", root / "app"):
        if (candidate / "routers" / "api.py").exists():
            api_src = (candidate / "routers" / "api.py").read_text()
            break
    else:
        pytest.skip("cannot locate the application package")

    problems = []
    for node in ast.walk(ast.parse(api_src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)):
            continue
        module = modules.get(fn.value.id)
        target = getattr(module, fn.attr, None) if module else None
        if target is None or not callable(target):
            continue
        kwargs = {k.arg for k in node.keywords if k.arg}
        accepted = set(inspect.signature(target).parameters)
        unknown = kwargs - accepted
        if unknown:
            problems.append(
                f"{fn.value.id}.{fn.attr}() called with {sorted(unknown)}, "
                f"which it does not accept (line {node.lineno})")
    assert not problems, "route/domain signature mismatch:\n" + "\n".join(problems)
