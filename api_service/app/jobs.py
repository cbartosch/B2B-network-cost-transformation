"""Simulation job runner: asynchronous, cancellable, resumable.

C2-11: 16.1 stated all three properties and the implementation had none of
them. `run_simulation` was a plain blocking endpoint that, at the permitted
bounds, held a worker for about a minute. Bounded is not the same as
non-blocking: a request that long times out through most proxies and occupies a
worker that could be serving someone else.

The production architecture puts this on Prefect, which is out of scope for a
laptop bundle. What follows is a deliberately small in-process runner with the
three properties that actually matter:

  asynchronous  the request returns 202 immediately and the work happens on a
                worker thread with its own session; the queue is bounded so a
                burst cannot exhaust the connection pool
  cancellable   cooperatively, checked between passes, so a cancelled run stops
                at a consistent checkpoint - no thread is killed mid-write
  resumable     each pass is a pure function of its seed, so a run continues
                from its checkpoint and produces a byte-identical result to one
                that ran straight through

That last property is what makes cancellation safe to offer at all. Without it,
resuming would yield a *similar* estimate rather than the same one, and 0.11
reproducibility would not survive an interruption.
"""
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import select, update

from . import config, db
from .domain import simulation

log = logging.getLogger("workbench.jobs")

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED = (
    "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")
# A cancel accepted while a worker is mid-run. The worker stops between passes
# and settles it to CANCELLED; a process that dies first leaves the row here,
# which is what reclaim_interrupted looks for.
CANCELLING = "CANCELLING"
TERMINAL = (SUCCEEDED, FAILED, CANCELLED)


def _now():
    return datetime.now(timezone.utc)

# Run identifiers currently held by a worker. Bounds concurrency against the
# connection pool rather than against CPU: each job holds one session.
_inflight: set = set()
_lock = threading.Lock()


class RunNotFound(LookupError):
    """No such simulation run. Distinguished from a server fault so a wrong
    identifier reads as a wrong identifier."""


class QueueFull(RuntimeError):
    """Too many simulations already running."""


def _set(session, run_id: str, **values) -> None:
    session.execute(update(db.simulation_run)
                    .where(db.simulation_run.c.simulation_run_id == run_id)
                    .values(**values))
    session.commit()


def _fetch(session, run_id: str):
    """Resolve a run, or raise RunNotFound.

    This used .one(), whose NoResultFound renders as a 500 - telling a caller the
    server is broken when their identifier is wrong.
    """
    session.expire_all()
    row = session.execute(select(db.simulation_run).where(
        db.simulation_run.c.simulation_run_id == run_id)).first()
    if row is None:
        raise RunNotFound(f"simulation run {run_id!r} not found")
    return row


def _cancelled(session, run_id: str) -> bool:
    return bool(session.execute(
        select(db.simulation_run.c.cancel_requested)
        .where(db.simulation_run.c.simulation_run_id == run_id)).scalar())


def run_job(run_id: str, session=None) -> dict:
    """Execute or resume one job. Returns the terminal state.

    Called directly by the tests as well as by the worker thread, so the tested
    path is the executed path rather than a parallel implementation.
    """
    own = session is None
    s = session or db.SessionLocal()
    try:
        row = _fetch(s, run_id)
        if row.status == SUCCEEDED:
            return {"simulation_run_id": run_id, "status": SUCCEEDED,
                    "note": "already terminal"}

        params = row.params or {}
        footprint = params.get("footprint", [])
        archetypes = (row.pinned_priors or {}).get("archetype_prior", {})
        total = row.progress_total or row.ensemble_size

        # Resume from the checkpoint. Replaying an earlier index would be safe
        # too - the passes are pure - but continuing is free.
        summaries = list((row.partial or {}).get("summaries", []))
        started = len(summaries)

        _set(s, run_id, status=RUNNING,
             started_at=row.started_at or datetime.now(timezone.utc), error=None)

        for i in range(started, total):
            if _cancelled(s, run_id):
                _set(s, run_id, status=CANCELLED,
                     partial={"summaries": summaries},
                     progress_completed=len(summaries),
                     ended_at=datetime.now(timezone.utc))
                log.info("simulation %s cancelled after %d/%d passes",
                         run_id, len(summaries), total)
                return {"simulation_run_id": run_id, "status": CANCELLED,
                        "completed": len(summaries), "total": total}

            summaries.append(simulation.summarise_pass(
                simulation.one_pass(row.seed + i, footprint, archetypes), i))

            if len(summaries) % config.SIM_CHECKPOINT_EVERY == 0:
                _set(s, run_id, partial={"summaries": summaries},
                     progress_completed=len(summaries))

        output = simulation.aggregate(
            summaries, seed=row.seed, ensemble_size=total, footprint=footprint,
            archetypes=archetypes, model_version=row.model_version)
        # cancel_requested is cleared here, not left standing. A cancel that
        # arrives after the last pass is too late to act on - completing is
        # correct - but a row that reads SUCCEEDED *and* cancel_requested is a
        # record asserting two contradictory things, and a reader cannot tell
        # which one happened. The same clearing already happens on reclaim.
        # Found by executing test_a_late_cancellation_does_not_leave_a_
        # contradictory_record, which had never run.
        _set(s, run_id, status=SUCCEEDED, output=output,
             output_hash=simulation.output_hash(output),
             partial={"summaries": summaries}, progress_completed=total,
             cancel_requested=False,
             ended_at=datetime.now(timezone.utc))
        return {"simulation_run_id": run_id, "status": SUCCEEDED,
                "completed": total, "total": total}

    except Exception as exc:                                  # noqa: BLE001
        log.exception("simulation %s failed", run_id)
        try:
            # The checkpoint is deliberately left in place: a failure part way
            # through is exactly when resuming is worth having.
            _set(s, run_id, status=FAILED, error=str(exc)[:2000],
                 ended_at=datetime.now(timezone.utc))
        except Exception:                                     # noqa: BLE001
            pass
        return {"simulation_run_id": run_id, "status": FAILED, "error": str(exc)}
    finally:
        if own:
            s.close()


def _worker(run_id: str) -> None:
    try:
        run_job(run_id)
    finally:
        with _lock:
            _inflight.discard(run_id)
        # A freed worker takes the next waiting run, which is what makes QUEUED
        # a queue rather than a label. Without this a run deferred for want of a
        # worker waits for a restart.
        _drain()


def in_flight() -> int:
    """Worker threads running in *this* process.

    Exact: counted under a lock, and the only bound that guards a resource which
    can genuinely be exhausted.

    Threads are a per-process resource, so this is the right scope for the
    concurrency bound. An earlier revision replaced this count with a database
    query on the reasoning that an in-memory bound is per-replica - but
    per-replica is correct for a per-replica resource, and the substitution left
    thread creation bounded only indirectly.
    """
    with _lock:
        return len(_inflight)


def backlog(session=None) -> int:
    """Runs queued or running anywhere. How much work *exists*, which is a
    different question from how much is running here.

    Advisory, not exact. The count and the subsequent insert are not one atomic
    operation, so two replicas admitting simultaneously can each read a depth
    below the bound and both accept. A Postgres advisory lock would close that,
    and it is deliberately not used: over-admitting by a few under a concurrent
    burst costs nothing, because the resource that can actually be exhausted -
    worker threads - is bounded exactly and per-process by SIM_WORKERS. Making
    a policy bound exact would add dialect-specific locking to buy a guarantee
    nothing needs.

    The README previously said this "holds across replicas". It does not, and
    that claim has been corrected rather than the code changed to match it.
    """
    own = session is None
    s = session or db.SessionLocal()
    try:
        return len(s.execute(select(db.simulation_run.c.simulation_run_id)
                             .where(db.simulation_run.c.status.in_(
                                 [QUEUED, RUNNING, CANCELLING]))).all())
    finally:
        if own:
            s.close()


# Retained under the old name for callers and tests that ask for the backlog.
queue_depth = backlog


def admit(session=None) -> int:
    """Decide whether to accept a *new* run. Call before creating its row.

    Admission and scheduling were one function, and conflating them caused two
    defects. Reclaim and resume were refused for exceeding a bound they should
    never have been measured against (C4-01, C4-05), and the caller created the
    row before asking - so the candidate counted itself and SIM_QUEUE_MAX=32
    admitted 31 others (C4-06). Asking first, and separately, fixes both by
    construction: at admission time the run does not exist yet, so the count is
    genuinely of other work.

    Returns the current backlog. Raises QueueFull if it is at the bound.
    """
    depth = backlog(session)
    if depth >= config.SIM_QUEUE_MAX:
        raise QueueFull(
            f"{depth} simulations already queued or running "
            f"(SIM_QUEUE_MAX={config.SIM_QUEUE_MAX}); retry shortly")
    return depth


def submit(run_id: str) -> dict:
    """Start a worker, or leave the run queued for one.

    Scheduling only. This never refuses on backlog - admission is `admit()`,
    called once, before the run exists. Reclaim, resume and drain schedule work
    that was admitted already and so do not call it.

    SIM_WORKERS bounds concurrent worker threads in this process. Exceeding it
    does not refuse the run; it leaves it QUEUED for _drain to collect.
    """
    with _lock:
        if run_id in _inflight:
            return {"simulation_run_id": run_id, "status": RUNNING,
                    "note": "already in flight in this process"}
        if len(_inflight) >= config.SIM_WORKERS:
            return {"simulation_run_id": run_id, "status": QUEUED,
                    "note": f"all {config.SIM_WORKERS} workers busy; queued"}
        _inflight.add(run_id)
    threading.Thread(target=_worker, args=(run_id,), daemon=True,
                     name=f"sim-{run_id[:8]}").start()
    return {"simulation_run_id": run_id, "status": RUNNING}


def _next_waiting(session) -> str | None:
    """Oldest queued run with no worker in this process."""
    rows = session.execute(
        select(db.simulation_run.c.simulation_run_id)
        .where(db.simulation_run.c.status == QUEUED)
        .order_by(db.simulation_run.c.created_at.asc())).all()
    with _lock:
        busy = set(_inflight)
    for r in rows:
        if r.simulation_run_id not in busy:
            return r.simulation_run_id
    return None


def _drain() -> None:
    """Fill freed worker slots from the queue. Admission already happened when
    each of these runs was accepted."""
    s = db.SessionLocal()
    try:
        while in_flight() < config.SIM_WORKERS:
            run_id = _next_waiting(s)
            if run_id is None:
                return
            started = submit(run_id)
            if started.get("status") != RUNNING:
                return
    except Exception:                                # noqa: BLE001
        log.exception("drain failed; queued runs await the next completion")
    finally:
        s.close()


def status(session, run_id: str) -> dict:
    row = _fetch(session, run_id)
    total = row.progress_total or row.ensemble_size or 1
    completed = row.progress_completed or 0
    return {"simulation_run_id": run_id, "status": row.status,
            "completed": completed, "total": total,
            "percent": round(100.0 * completed / total, 2),
            "seed": row.seed, "model_version": row.model_version,
            "output_hash": row.output_hash,
            "cancel_requested": bool(row.cancel_requested),
            "error": row.error}


def cancel(session, run_id: str) -> dict:
    row = _fetch(session, run_id)
    if row.status in TERMINAL:
        return {"simulation_run_id": run_id, "status": row.status,
                "note": "already finished; nothing to cancel"}
    _set(session, run_id, cancel_requested=True)
    return {"simulation_run_id": run_id, "status": row.status,
            "cancel_requested": True}


def resume(session, run_id: str) -> dict:
    row = _fetch(session, run_id)
    if row.status == SUCCEEDED:
        return {"simulation_run_id": run_id, "status": SUCCEEDED,
                "note": "nothing to resume"}
    completed = len((row.partial or {}).get("summaries", []))
    previous = row.status

    # A resume is not new work. It finishes something already accepted, exactly
    # as reclaim does, so it is not subject to the backlog bound and cannot be
    # refused on it. When every worker is busy the run stays QUEUED and the
    # drain collects it.
    #
    # `error` is deliberately not cleared here. run_job clears it when the run
    # actually starts, so clearing it on submission only meant that a resume
    # which then sat queued left the operator told the run had failed and no
    # longer why.
    _set(session, run_id, cancel_requested=False, status=QUEUED)
    try:
        started = submit(run_id)
    except Exception:                            # noqa: BLE001
        # Nothing here should raise, but a row claiming to be queued with
        # nothing scheduled is the failure this ordering exists to avoid.
        _set(session, run_id, status=previous)
        raise
    return {"simulation_run_id": run_id, "status": started.get("status", QUEUED),
            "resuming_from_pass": completed,
            "note": started.get("note")}


def reclaim_interrupted() -> dict:
    """Reclaim runs orphaned by a process that died mid-flight. Called from the
    application lifespan - see tests/test_wiring.py, which asserts that it is.

    In a fresh process no worker exists for anything, so every non-terminal row
    is orphaned by definition. The two cases deserve different answers:

      * CANCELLING - somebody asked for this to stop and the process died before
        it could. Honour the request rather than resurrecting a run the user
        had already abandoned. The checkpoint survives, so resume is still there
        if they change their mind.
      * RUNNING or QUEUED - nobody asked for it to stop, so continue it from its
        checkpoint.

    A run left QUEUED because the pool was full stays QUEUED: a visible,
    recoverable state that the next restart or an explicit resume will pick up.
    Leaving it RUNNING would make it indistinguishable from a live job.

    Renamed from requeue_interrupted, which was correctly wired into the
    lifespan but handled RUNNING only, and left a run QUEUED-but-unscheduled
    indistinguishable from a live one when the pool was full.
    """
    s = db.SessionLocal()
    # "deferred", not "queued": a run the pool could not take is deferred to
    # the next free worker. Two tests assert this exact shape, and the app was
    # emitting a third name for it - harmless until something reads the report.
    report = {"cancelled": 0, "requeued": 0, "deferred": 0}
    try:
        for row in s.execute(select(db.simulation_run.c.simulation_run_id,
                                    db.simulation_run.c.status)
                             .where(db.simulation_run.c.status == CANCELLING)).all():
            _set(s, row.simulation_run_id, status=CANCELLED, ended_at=_now())
            report["cancelled"] += 1
            log.info("honouring cancellation of interrupted simulation %s",
                     row.simulation_run_id)

        for row in s.execute(select(db.simulation_run.c.simulation_run_id)
                             .where(db.simulation_run.c.status.in_(
                                 [RUNNING, QUEUED]))).all():
            _set(s, row.simulation_run_id, status=QUEUED, cancel_requested=False,
                 ended_at=None)
            # Not new work: this run was admitted before the process died.
            # Beyond SIM_WORKERS it stays QUEUED and _drain collects it as
            # workers free, so a backlog larger than the bound still drains.
            # QueueFull is expected here, not exceptional: the docstring above
            # promises a run stays QUEUED when the pool is full. Without this
            # handler the exception propagated out of the loop, so the FIRST
            # full pool aborted reclaim for every remaining row - leaving them
            # RUNNING and indistinguishable from live jobs, which is precisely
            # the state this function exists to eliminate. main.py catches the
            # exception and starts anyway, so nothing surfaced.
            #
            # Found by the first real `make test` run against Postgres. The
            # offline harness saw it too and I misattributed it to worker-pool
            # state carried between tests.
            try:
                started = submit(row.simulation_run_id)
            except QueueFull:
                report["deferred"] += 1
                log.info("simulation %s left QUEUED: worker pool full. It will be "
                         "collected as a worker frees, or on the next restart.",
                         row.simulation_run_id)
                continue
            if started.get("status") == RUNNING:
                report["requeued"] += 1
                log.info("resuming interrupted simulation %s", row.simulation_run_id)
            else:
                # Same outcome as the QueueFull branch above: submit() declined
                # without raising. One key for one meaning - this wrote
                # "queued" while the exception path wrote "deferred", so a
                # report could carry both for the same situation.
                report["deferred"] += 1
        return report
    finally:
        s.close()
