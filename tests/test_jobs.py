"""Asynchronous, cancellable, resumable simulation.

C2-11: §16.1 stated all three properties and the implementation had none of
them - a blocking endpoint that held a worker for up to a minute at the
permitted bounds.

`run_job` is called directly here rather than through the executor. That is the
same code path the worker thread runs, so these tests exercise the real thing
without depending on thread scheduling.
"""
import uuid

import pytest
from sqlalchemy import insert, select, update

from app import db, jobs
from app.domain import simulation

FOOTPRINT = [{"country": "GB", "archetype": "BRANCH", "sites": 40},
             {"country": "DE", "archetype": "DC", "sites": 2}]
ARCH = {"BRANCH": {"dual_access_probability": 0.55, "primary_product": "DIA",
                   "backup_product": "BROADBAND"},
        "DC": {"dual_access_probability": 1.0, "primary_product": "ETHERNET",
               "backup_product": "ETHERNET"}}


def _queue(session, *, seed=42, size=20, case_id=None):
    rid = str(uuid.uuid4())
    session.execute(insert(db.simulation_run).values(
        simulation_run_id=rid, case_id=case_id,
        model_version="sim-1.0.0", seed=seed, ensemble_size=size,
        params={"footprint": FOOTPRINT},
        pinned_priors={"archetype_prior": ARCH},
        status=jobs.QUEUED, progress_completed=0, progress_total=size,
        cancel_requested=False))
    session.commit()
    return rid


def _row(session, rid):
    session.expire_all()
    return session.execute(select(db.simulation_run).where(
        db.simulation_run.c.simulation_run_id == rid)).one()


# --- asynchronous -----------------------------------------------------------
def test_a_queued_run_starts_with_no_output(session):
    rid = _queue(session)
    row = _row(session, rid)
    assert row.status == jobs.QUEUED and row.output is None
    assert row.progress_total == 20 and row.progress_completed == 0


def test_running_a_job_completes_it_and_records_progress(session):
    rid = _queue(session)
    result = jobs.run_job(rid)
    row = _row(session, rid)
    assert result["status"] == jobs.SUCCEEDED
    assert row.status == jobs.SUCCEEDED
    assert row.progress_completed == row.progress_total == 20
    assert row.output_hash and row.output


def test_status_reports_percentage(session):
    rid = _queue(session)
    jobs.run_job(rid)
    st = jobs.status(session, rid)
    assert st["percent"] == 100.0 and st["completed"] == 20


# --- cancellable ------------------------------------------------------------
def test_cancellation_stops_between_passes_and_keeps_completed_work(session):
    rid = _queue(session, size=20)
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id == rid)
                    .values(cancel_requested=True))
    session.commit()
    result = jobs.run_job(rid)
    row = _row(session, rid)
    assert result["status"] == jobs.CANCELLED
    assert row.status == jobs.CANCELLED and row.output is None


def test_cancelling_a_finished_run_is_a_no_op(session):
    rid = _queue(session)
    jobs.run_job(rid)
    assert jobs.cancel(session, rid)["status"] == jobs.SUCCEEDED
    assert _row(session, rid).output is not None


def test_a_terminal_run_is_not_re_executed(session):
    rid = _queue(session)
    jobs.run_job(rid)
    first = _row(session, rid).output_hash
    assert jobs.run_job(rid)["note"] == "already terminal"
    assert _row(session, rid).output_hash == first


# --- resumable, and identical -----------------------------------------------
def _partial(session, rid, upto):
    """Put a run into the state a cancellation at `upto` passes would leave."""
    row = _row(session, rid)
    summaries = [simulation.summarise_pass(
        simulation.one_pass(row.seed + i, FOOTPRINT, ARCH), i)
        for i in range(upto)]
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id == rid)
                    .values(status=jobs.CANCELLED, cancel_requested=False,
                            partial={"summaries": summaries},
                            progress_completed=upto))
    session.commit()


def test_resuming_produces_a_byte_identical_result(session):
    """The property that makes cancellation safe: a resumed ensemble is the same
    estimate, not a similar one, so §0.11 reproducibility survives it."""
    straight = _queue(session, seed=7, size=25)
    jobs.run_job(straight)
    expected = _row(session, straight).output_hash

    interrupted = _queue(session, seed=7, size=25)
    _partial(session, interrupted, upto=9)
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id == interrupted)
                    .values(status=jobs.QUEUED))
    session.commit()
    jobs.run_job(interrupted)

    assert _row(session, interrupted).output_hash == expected


def test_resume_continues_rather_than_restarting(session):
    rid = _queue(session, size=25)
    _partial(session, rid, upto=9)
    row = _row(session, rid)
    assert len(row.partial["summaries"]) == 9
    jobs.run_job(rid)
    row = _row(session, rid)
    assert row.progress_completed == 25
    assert [s["index"] for s in row.partial["summaries"]] == list(range(25))


def test_resume_of_a_completed_run_does_nothing(session):
    rid = _queue(session)
    jobs.run_job(rid)
    assert jobs.resume(session, rid)["note"] == "nothing to resume"


def test_a_failed_run_keeps_its_checkpoint_for_resume(session):
    rid = _queue(session, size=25)
    _partial(session, rid, upto=12)
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id == rid)
                    .values(status=jobs.FAILED, error="provider of priors went away"))
    session.commit()
    assert jobs.resume(session, rid)["resuming_from_pass"] == 12


# --- bounds -----------------------------------------------------------------
def test_new_work_is_refused_when_the_backlog_is_full(session, monkeypatch):
    """SIM_QUEUE_MAX bounds how much work is accepted, not how much runs."""
    monkeypatch.setattr(jobs.config, "SIM_QUEUE_MAX", 2)
    for _ in range(2):
        _queue(session)
    assert jobs.backlog(session) == 2
    with pytest.raises(jobs.QueueFull):
        jobs.admit(session)


def test_admission_counts_other_work_not_the_candidate(session, monkeypatch):
    """The candidate used to count itself, because the caller created the row
    before asking - so SIM_QUEUE_MAX=1 admitted zero concurrent runs."""
    monkeypatch.setattr(jobs.config, "SIM_QUEUE_MAX", 1)
    assert jobs.admit(session) == 0, "an empty queue must admit"
    _queue(session)                                   # one run now exists
    with pytest.raises(jobs.QueueFull):
        jobs.admit(session)


def test_the_bound_admits_exactly_what_it_says(session, monkeypatch):
    monkeypatch.setattr(jobs.config, "SIM_QUEUE_MAX", 3)
    admitted = 0
    for _ in range(5):
        try:
            jobs.admit(session)
        except jobs.QueueFull:
            break
        _queue(session)
        admitted += 1
    assert admitted == 3, f"SIM_QUEUE_MAX=3 should admit 3, admitted {admitted}"


def test_submit_never_refuses_on_backlog(session, monkeypatch):
    """Scheduling and admission are separate. submit() schedules work that was
    admitted already, so it cannot refuse - which is what let reclaim, resume
    and drain be blocked by a bound they were never meant to be measured
    against."""
    monkeypatch.setattr(jobs.config, "SIM_QUEUE_MAX", 1)
    monkeypatch.setattr(jobs.config, "SIM_WORKERS", 4)
    monkeypatch.setattr(jobs.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda s: None})())
    for _ in range(5):
        _queue(session)                               # backlog far past the bound
    try:
        out = jobs.submit(_queue(session))            # must not raise
    finally:
        jobs._inflight.clear()
    assert out["status"] in (jobs.QUEUED, jobs.RUNNING)


def test_only_the_worker_bound_claims_to_be_exact():
    """Honesty check on the two guarantees. The backlog bound is advisory
    because the count and the insert are not atomic; the worker bound is not,
    because it is the one guarding a resource that can be exhausted.

    This asserts on prose, which is the weakest kind of test - it breaks when
    someone rewords a comment and proves nothing about behaviour. It failed on
    first execution for exactly that reason: it looked for "not atomic" while
    the docstring says "are not one atomic operation". Made robust below rather
    than deleted, because the distinction it guards is real, but the *load
    bearing* version of this claim is the one published on GET /v1/health
    (`simulation.workers.enforcement` = "exact, per process" versus
    `simulation.backlog.enforcement` = "advisory, not atomic across replicas").
    That payload is what a consumer actually reads; assert against it in
    preference to this if the two ever disagree.
    """
    worker_doc = " ".join(jobs.in_flight.__doc__.lower().split())
    backlog_doc = " ".join(jobs.backlog.__doc__.lower().split())
    assert "exact" in worker_doc
    assert "advisory" in backlog_doc
    assert "not exact" in backlog_doc
    assert "atomic" in backlog_doc


def test_backlog_ignores_finished_runs(session):
    rid = _queue(session)
    assert jobs.backlog(session) == 1
    jobs.run_job(rid)
    assert jobs.backlog(session) == 0


def test_the_two_bounds_measure_different_things():
    """SIM_WORKERS bounds threads in this process; SIM_QUEUE_MAX bounds work
    that exists anywhere. Conflating them is what broke reclaim."""
    assert jobs.in_flight() == 0
    assert jobs.backlog.__doc__ and "exists" in jobs.backlog.__doc__
    assert jobs.in_flight.__doc__ and "per-process" in jobs.in_flight.__doc__


def test_checkpoints_are_written_during_a_long_run(session, monkeypatch):
    monkeypatch.setattr(jobs.config, "SIM_CHECKPOINT_EVERY", 2)
    rid = _queue(session, size=6)
    jobs.run_job(rid)
    assert len(_row(session, rid).partial["summaries"]) == 6


def test_an_estimate_cannot_be_built_from_a_partial_ensemble(session):
    """The endpoint guard: async simulation means a run may exist without an
    output, and the estimate path has to say so rather than crash on None."""
    rid = _queue(session, size=25)
    _partial(session, rid, upto=9)
    row = _row(session, rid)
    assert row.status == jobs.CANCELLED and row.output is None


# --- C3-05: resume must not leave a phantom queued run ----------------------
def test_resume_restores_the_status_when_the_pool_refuses(session, monkeypatch):
    """It committed QUEUED and then let QueueFull propagate, leaving a row that
    claimed to be queued with nothing scheduled."""
    rid = _queue(session, size=25)
    _partial(session, rid, upto=9)
    assert _row(session, rid).status == jobs.CANCELLED

    def full(_run_id):
        raise jobs.QueueFull("pool is full")

    monkeypatch.setattr(jobs, "submit", full)
    with pytest.raises(jobs.QueueFull):
        jobs.resume(session, rid)
    assert _row(session, rid).status == jobs.CANCELLED, \
        "a refused resume must not leave the run claiming to be queued"


# --- C3-06: an empty ensemble ----------------------------------------------
def test_aggregating_an_empty_ensemble_says_what_is_wrong():
    """It raised a bare IndexError carrying no context."""
    with pytest.raises(ValueError, match="empty ensemble"):
        simulation.aggregate([], seed=1, ensemble_size=0, footprint=[],
                             archetypes={}, model_version="v")


# --- C3-12: no contradictory terminal record --------------------------------
def test_a_late_cancellation_does_not_leave_a_contradictory_record(session):
    """A cancel arriving during aggregation is too late to act on. Completing is
    right; recording SUCCEEDED with cancel_requested still set is not."""
    rid = _queue(session, size=6)
    _partial(session, rid, upto=6)
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id == rid)
                    .values(status=jobs.QUEUED, cancel_requested=True))
    session.commit()
    jobs.run_job(rid)
    row = _row(session, rid)
    assert row.status == jobs.SUCCEEDED
    assert not row.cancel_requested


# --- C4-05: a resume must not lose the diagnosis or the row ----------------
def test_resume_keeps_the_error_until_the_run_actually_starts(session):
    """It cleared `error` on submission, so a resume that then sat queued left
    the operator told the run had failed and no longer why."""
    rid = _queue(session, size=25)
    _partial(session, rid, upto=9)
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id == rid)
                    .values(status=jobs.FAILED, error="provider of priors went away"))
    session.commit()

    jobs._inflight.update({"busy-1", "busy-2"})          # no free worker
    try:
        jobs.resume(session, rid)
    finally:
        jobs._inflight.clear()

    row = _row(session, rid)
    assert row.status == jobs.QUEUED
    assert row.error == "provider of priors went away", \
        "the diagnosis must survive until the run actually restarts"


def test_the_error_is_cleared_when_the_run_restarts(session):
    rid = _queue(session, size=4)
    _partial(session, rid, upto=2)
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id == rid)
                    .values(status=jobs.QUEUED, error="previous attempt failed"))
    session.commit()
    jobs.run_job(rid)
    assert _row(session, rid).error is None


def test_a_resume_is_not_refused_when_the_backlog_is_full(session, monkeypatch):
    """A resume finishes work already accepted, so admission control must not
    apply - the same reasoning that exempts reclaim."""
    monkeypatch.setattr(jobs.config, "SIM_QUEUE_MAX", 1)
    monkeypatch.setattr(jobs.config, "SIM_WORKERS", 4)
    monkeypatch.setattr(jobs.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda s: None})())
    rid = _queue(session, size=6)
    _partial(session, rid, upto=2)
    for _ in range(3):
        _queue(session)                                   # backlog well past the bound
    try:
        out = jobs.resume(session, rid)                   # must not raise
    finally:
        jobs._inflight.clear()
    assert out["status"] in (jobs.QUEUED, jobs.RUNNING)


def test_a_failed_submit_does_not_leave_a_phantom_queued_run(session, monkeypatch):
    """The ordering guard: the row must not claim to be queued with nothing
    scheduled, whatever the reason submission failed."""
    rid = _queue(session, size=6)
    _partial(session, rid, upto=2)
    assert _row(session, rid).status == jobs.CANCELLED

    def boom(*_a, **_k):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(jobs, "submit", boom)
    with pytest.raises(RuntimeError):
        jobs.resume(session, rid)
    assert _row(session, rid).status == jobs.CANCELLED


# --- C4-01: a backlog larger than the bound must still drain ---------------
def test_reclaim_handles_a_backlog_larger_than_the_bound(session, monkeypatch):
    """The finding. Reclaim set every orphan QUEUED and was then refused by its
    own admission bound, so 40 orphans against SIM_QUEUE_MAX=32 reclaimed none.

    Every earlier job test used a single run, which is why the interaction was
    invisible: a bound is only interesting when something exceeds it.
    """
    monkeypatch.setattr(jobs.config, "SIM_QUEUE_MAX", 4)
    monkeypatch.setattr(jobs.config, "SIM_WORKERS", 2)
    started = []
    monkeypatch.setattr(jobs, "_drain", lambda: None)          # no threads in tests
    monkeypatch.setattr(jobs.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda s: started.append(kw)})())

    orphans = [_queue(session, size=2) for _ in range(10)]     # 10 > SIM_QUEUE_MAX
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id.in_(orphans))
                    .values(status=jobs.RUNNING))
    session.commit()

    report = jobs.reclaim_interrupted()
    jobs._inflight.clear()

    assert report["requeued"] + report["deferred"] == 10, \
        "every orphan must be accounted for, not refused"
    assert report["requeued"] == 2, "started up to SIM_WORKERS"
    assert report["deferred"] == 8, "the rest wait for a worker, not for a restart"
    session.expire_all()
    remaining = session.execute(select(db.simulation_run).where(
        db.simulation_run.c.simulation_run_id.in_(orphans),
        db.simulation_run.c.status == jobs.RUNNING)).all()
    assert not remaining, "no orphan may be left looking like a live job"


def test_reclaim_is_not_subject_to_the_admission_bound(session, monkeypatch):
    """Reclaim is not new work - it is finishing something already accepted."""
    monkeypatch.setattr(jobs.config, "SIM_QUEUE_MAX", 1)
    monkeypatch.setattr(jobs.config, "SIM_WORKERS", 4)
    monkeypatch.setattr(jobs, "_drain", lambda: None)
    monkeypatch.setattr(jobs.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda s: None})())
    orphans = [_queue(session, size=2) for _ in range(3)]
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id.in_(orphans))
                    .values(status=jobs.RUNNING))
    session.commit()
    report = jobs.reclaim_interrupted()
    jobs._inflight.clear()
    assert report["requeued"] == 3, "admission control must not block recovery"


def test_a_freed_worker_takes_the_next_queued_run(session, monkeypatch):
    """Without the drain, a run deferred for want of a worker waits for a
    restart - which is a label, not a queue."""
    monkeypatch.setattr(jobs.config, "SIM_WORKERS", 1)
    first, second = _queue(session, size=2), _queue(session, size=2)
    picked = jobs._next_waiting(session)
    assert picked == first, "oldest queued run is taken first"
    jobs._inflight.add(first)
    try:
        assert jobs._next_waiting(session) == second, \
            "a run already in flight must not be picked twice"
    finally:
        jobs._inflight.discard(first)


def test_concurrency_never_exceeds_the_worker_bound(session, monkeypatch):
    monkeypatch.setattr(jobs.config, "SIM_WORKERS", 2)
    monkeypatch.setattr(jobs.config, "SIM_QUEUE_MAX", 100)
    monkeypatch.setattr(jobs, "_drain", lambda: None)
    monkeypatch.setattr(jobs.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda s: None})())
    try:
        # `submit()` takes only run_id - `new_work=` was never a parameter, so
        # this raised TypeError before reaching a single assertion. Found by
        # executing it. Admission is `admit()`, deliberately separate from
        # scheduling, which is what the removed argument was reaching for.
        outcomes = [jobs.submit(_queue(session, size=2))["status"]
                    for _ in range(5)]
        assert outcomes.count(jobs.RUNNING) == 2
        assert outcomes.count(jobs.QUEUED) == 3
        assert jobs.in_flight() == 2
    finally:
        jobs._inflight.clear()


# --- C4-08: no database access while the thread lock is held ---------------
def test_submit_does_not_query_the_database_under_the_lock(session, monkeypatch):
    """Closed incidentally by the C4-06 split - admission moved out of submit -
    but worth pinning, because reintroducing a query here would serialise every
    submission behind database latency.

    threading.Lock is not reentrant, so a failed non-blocking acquire from the
    same thread means the lock is held.
    """
    offences = []
    real_session = jobs.db.SessionLocal

    def watched(*a, **k):
        if not jobs._lock.acquire(blocking=False):
            offences.append("SessionLocal called while _lock was held")
        else:
            jobs._lock.release()
        return real_session(*a, **k)

    monkeypatch.setattr(jobs.db, "SessionLocal", watched)
    monkeypatch.setattr(jobs.config, "SIM_WORKERS", 4)
    monkeypatch.setattr(jobs.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda s: None})())
    try:
        jobs.submit(_queue(session))
        jobs.admit(session)
    finally:
        jobs._inflight.clear()
    assert not offences, offences


def test_next_waiting_queries_before_taking_the_lock(session, monkeypatch):
    offences = []
    real_session = jobs.db.SessionLocal

    def watched(*a, **k):
        if not jobs._lock.acquire(blocking=False):
            offences.append("query under lock")
        else:
            jobs._lock.release()
        return real_session(*a, **k)

    monkeypatch.setattr(jobs.db, "SessionLocal", watched)
    _queue(session)
    jobs._next_waiting(session)
    assert not offences
