"""Turning a completed engagement into a validation case.

The harness has been able to compare an estimate against an outturn since
4.160 and the corpus has been empty, because nothing produced a case. A folder
somebody has to remember to fill is not a workflow.

The integrity property that matters: **the estimated half is derived from the
snapshot, never typed.** A case opened after the actuals are known would let
someone adjust what the model "said" to match what happened, and a corpus that
can be fitted measures nothing. So the estimate is read out of an immutable
snapshot, and the only thing anyone enters is what turned out to be true.

The two halves are recorded at different times by different people, which is
the shape of the thing: an estimate exists at the start of an engagement and an
outturn at the end, often a year apart and often not the same analyst.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .validation import EMPIRICAL_TIERS, MEASURES, TIER_SYNTHETIC


class CaseIncomplete(ValueError):
    """A case missing the half that makes it evidence."""


def _num(value):
    """A figure, or None. Never a zero standing in for a missing number."""
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def estimated_from(snapshot, *, simulation_output: dict | None = None) -> dict:
    """The seven measures, read out of a snapshot.

    Derived rather than entered, so what the model said cannot be revised once
    the outturn is known. Anything the snapshot does not carry is omitted, not
    guessed - a missing measure is reported NOT_COMPARABLE and a fabricated one
    would quietly improve the error statistics.
    """
    current = snapshot.current_tco or {}
    target = snapshot.target_tco or {}
    savings = snapshot.gross_run_rate_savings or {}
    sim = simulation_output or {}

    out = {
        "current_annual_cost": _num(current.get("base")),
        "target_annual_cost": _num(target.get("base")),
        "feasible_annual_savings": _num(savings.get("base")),
        "site_count": _num(sim.get("sites")),
        "circuit_count": _num((sim.get("circuits") or {}).get("base")
                              if isinstance(sim.get("circuits"), dict)
                              else sim.get("circuits")),
        "bandwidth_mbps_total": _num(sim.get("bandwidth_mbps_total")),
    }
    # One-time cost lives on the scenario rather than the snapshot header,
    # because it belongs to a plan rather than to a baseline.
    for scenario in (snapshot.scenarios or {}).values():
        transition = (scenario or {}).get("transition") or {}
        one_time = (transition.get("one_time_cost") or {}).get("base")
        if one_time is not None:
            out["one_time_cost"] = _num(one_time)
            break

    return {k: str(v) for k, v in out.items() if v is not None}


def open_case(snapshot, *, simulation_output=None, opened_by: str) -> dict:
    """A case with its estimated half filled and its actual half waiting.

    Opened at the time of the estimate, which is the point: a case created
    afterwards could carry an estimate chosen to match the answer.
    """
    estimated = estimated_from(snapshot, simulation_output=simulation_output)
    return {
        "estimate_snapshot_id": snapshot.estimate_snapshot_id,
        "case_id": snapshot.case_id,
        "estimated": estimated,
        "estimated_at": datetime.now(timezone.utc).isoformat(),
        "opened_by": opened_by,
        "actual": None,
        "evidence_tier": None,
        "note": (
            f"{len(estimated)} of {len(MEASURES)} measure(s) captured from the "
            f"snapshot. The rest are absent from it and are recorded as "
            f"missing rather than estimated - a fabricated measure would "
            f"improve the error statistics without improving the model."),
    }


def record_actuals(case: dict, *, actual: dict, evidence_tier: str,
                   recorded_by: str) -> dict:
    """What turned out to be true, against a case that already said otherwise.

    Refuses a tier it does not know, because a mislabelled synthetic case is
    the one thing that makes the whole corpus untrustworthy: the statistics
    exclude synthetic cases by name, and a synthetic case labelled
    HISTORICAL_ACTUAL is counted as evidence.
    """
    if evidence_tier not in EMPIRICAL_TIERS + (TIER_SYNTHETIC,):
        raise CaseIncomplete(
            f"{evidence_tier!r} is not an evidence tier. Empirical: "
            f"{list(EMPIRICAL_TIERS)}; or {TIER_SYNTHETIC} for a case that "
            f"exercises the harness and is excluded from every statistic.")

    kept = {k: str(_num(v)) for k, v in (actual or {}).items()
            if k in MEASURES and _num(v) is not None}
    if not kept:
        raise CaseIncomplete(
            f"no comparable measure was supplied. One of {list(MEASURES)} is "
            f"needed, and a case with none is a record that an engagement "
            f"finished rather than evidence about the model.")

    unknown = sorted(set(actual or {}) - set(MEASURES))
    return {**case, "actual": kept, "evidence_tier": evidence_tier,
            "recorded_by": recorded_by,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "ignored_fields": unknown,
            "note": (
                f"{len(kept)} measure(s) recorded"
                + (f"; {unknown} are not measures this harness compares and "
                   f"were kept out rather than silently dropped"
                   if unknown else "")),
            }


def comparable(case: dict) -> bool:
    """Both halves present, and at least one measure in common.

    A case with an estimate and no outturn is not evidence yet, and one where
    the two halves share no measure compares nothing - both are worth holding
    and neither belongs in a statistic.
    """
    estimated, actual = case.get("estimated") or {}, case.get("actual") or {}
    return bool(estimated and actual and (set(estimated) & set(actual)))
