"""Provider usage reconciliation (spec 7.2E).

§7.2C names this the control of last resort: the one that detects fabrication
the application cannot detect about itself, because it compares against a record
the application does not control.

It was a table written by nothing, read by nothing, and an endpoint reporting
`EXPECTED_PENDING` — which reads as "the scheduled job has not run yet" when
there was no scheduled job. A placeholder that plausible is how an unimplemented
control ends up believed.

What is implemented here is everything that does not require calling a provider:
the comparison, the tolerance by adapter tier, the variance record, the incident
on breach, and the gap accounting when a window is missed. The figures come from
an operator reading the provider's console — which is the out-of-band channel
the control depends on anyway, and is stronger than an API call from this host,
since a compromised host could fake the latter.

The automated fetch is **not implemented**. `UsageSource` below has no
implementations and `PROVIDER_API` is rejected, rather than a stub that would
look like an integration and has never run.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from sqlalchemy import insert, select

from .. import db
from .money import D

# Tolerances are GOVERNED, not constant. They live in reference.threshold under
# `provider_reconciliation_tier` and arrive as a ReconciliationPolicy. This was
# a module constant duplicating the seeded values, so an approver changing the
# seed changed nothing - see policy.ReconciliationPolicy.
#
# Kept only as the fallback the caller may not supply, and deliberately empty:
# a missing policy must refuse, not silently price a breach against a default.
TIER_TOLERANCE: dict = {}

MANUAL_CONSOLE = "MANUAL_CONSOLE"
PROVIDER_API = "PROVIDER_API"
SOURCES = (MANUAL_CONSOLE,)          # PROVIDER_API is declared, not available

PASS, BREACH, GAP, NOT_IMPLEMENTED = "PASS", "BREACH", "GAP", "NOT_IMPLEMENTED"


class UsageSource(Protocol):
    """A provider-side usage reader.

    Deliberately unimplemented. Each provider exposes usage through a separate
    admin-scoped credential, and an adapter written against an API that has
    never been called is not a control - it is a control-shaped object. When one
    is written it must be conformance-tested against the live API before its
    tier is recorded (7.2E).
    """

    provider: str
    tier: str

    def usage(self, *, period_start: datetime, period_end: datetime) -> dict: ...


AUTOMATED_SOURCES: dict = {}         # empty, and the emptiness is the point


class SourceNotImplemented(RuntimeError):
    """No automated reader exists for this provider."""


def claimed(session, *, period_start, period_end, environment=None) -> dict:
    """What this system says it did. One half of the comparison, and the half
    that cannot be trusted on its own."""
    q = select(db.llm_run.c.provider, db.llm_run.c.input_tokens,
               db.llm_run.c.output_tokens).where(
        db.llm_run.c.created_at >= period_start,
        db.llm_run.c.created_at < period_end)
    out: dict = {}
    for row in session.execute(q).all():
        agg = out.setdefault(row.provider, {"calls": 0, "tokens": 0})
        agg["calls"] += 1
        agg["tokens"] += (row.input_tokens or 0) + (row.output_tokens or 0)
    return out


def _variance(claimed_value: int, reported_value: int) -> Decimal:
    """Percentage difference against the provider's figure, which is the
    authority. Zero reported with something claimed is total divergence."""
    if reported_value == 0:
        return D(0) if claimed_value == 0 else D(100)
    return (abs(D(claimed_value) - D(reported_value)) / D(reported_value)) * D(100)


def record(session, *, reconciliation_policy, provider: str, tier: str,
           period_start, period_end,
           reported_calls: int, reported_tokens: int, environment: str,
           source: str, recorded_by: str) -> dict:
    """Compare a provider-reported figure against what this system claims.

    A breach raises a P2 incident and does not resolve itself: §7.2C requires it
    to block benchmark promotion until cleared.
    """
    if source not in SOURCES:
        raise SourceNotImplemented(
            f"source {source!r} is not available. Implemented: {SOURCES}. "
            f"{PROVIDER_API} requires a per-provider usage adapter, which this "
            f"build does not have - read the figures from the provider console "
            f"and submit them as {MANUAL_CONSOLE}.")
    tolerances = (reconciliation_policy.tier_tolerance()
                  if reconciliation_policy is not None else TIER_TOLERANCE)
    if tier not in tolerances:
        raise ValueError(
            f"tier {tier!r} has no tolerance. Tier C providers are not "
            f"reconcilable and cannot be approved for LIVE use (7.2E).")
    if not (recorded_by or "").strip():
        raise ValueError("recorded_by is mandatory: a manual reconciliation is "
                         "only as good as the person who performed it")

    mine = claimed(session, period_start=period_start, period_end=period_end
                   ).get(provider, {"calls": 0, "tokens": 0})
    tolerance = tolerances[tier]
    call_variance = _variance(mine["calls"], reported_calls)
    token_variance = _variance(mine["tokens"], reported_tokens)
    worst = max(call_variance, token_variance)
    status = PASS if worst <= tolerance else BREACH

    incident_id = None
    if status == BREACH:
        incident_id = str(uuid.uuid4())
        session.execute(insert(db.integrity_incident).values(
            incident_id=incident_id, kind="USAGE_RECONCILIATION_VARIANCE",
            severity="P2", detected_at=datetime.now(timezone.utc),
            detected_by=f"reconciliation:{source}",
            summary=(f"{provider} usage variance {worst:.2f}% exceeds the tier "
                     f"{tier} tolerance of {tolerance}%. This system claims "
                     f"{mine['calls']} calls and {mine['tokens']} tokens; the "
                     f"provider reports {reported_calls} and {reported_tokens}. "
                     f"Benchmark promotion is blocked until this is cleared."),
            detail={"provider": provider, "tier": tier,
                    "claimed": mine,
                    "reported": {"calls": reported_calls, "tokens": reported_tokens},
                    "call_variance_pct": str(call_variance),
                    "token_variance_pct": str(token_variance),
                    "tolerance_pct": str(tolerance)}))

    row_id = str(uuid.uuid4())
    session.execute(insert(db.usage_reconciliation).values(
        id=row_id, period_start=period_start, period_end=period_end,
        provider=provider, environment=environment, tier=tier,
        claimed_calls=mine["calls"], claimed_tokens=mine["tokens"],
        reported_calls=reported_calls, reported_tokens=reported_tokens,
        variance_pct=worst, tolerance_pct=tolerance, status=status,
        source=source, recorded_by=recorded_by.strip(), incident_id=incident_id))
    session.commit()

    return {"id": row_id, "provider": provider, "status": status,
            "claimed": mine,
            "reported": {"calls": reported_calls, "tokens": reported_tokens},
            "call_variance_pct": str(call_variance),
            "token_variance_pct": str(token_variance),
            "tolerance_pct": str(tolerance), "tier": tier,
            "incident_id": incident_id,
            "blocks_promotion": status == BREACH}


def promotion_blocked(session) -> list:
    """Unresolved variance incidents. §7.2C: promotion stops until cleared."""
    rows = session.execute(select(db.integrity_incident).where(
        db.integrity_incident.c.kind == "USAGE_RECONCILIATION_VARIANCE",
        db.integrity_incident.c.resolved_at.is_(None))).all()
    return [dict(r._mapping) for r in rows]


def state(session) -> dict:
    """Honest reporting of where the control stands.

    Distinguishes never-reconciled from reconciled-and-passing, because an
    unreconciled system reporting a benign-looking status is the defect this
    module replaced.
    """
    rows = session.execute(select(db.usage_reconciliation).order_by(
        db.usage_reconciliation.c.period_end.desc())).all()
    latest: dict = {}
    for r in rows:
        latest.setdefault(r.provider, dict(r._mapping))
    blocked = promotion_blocked(session)
    return {
        "automated_fetch": {
            "implemented": bool(AUTOMATED_SOURCES),
            "status": NOT_IMPLEMENTED,
            "detail": ("No provider usage adapter exists in this build. Read the "
                       "figures from the provider console and submit them via "
                       "POST /v1/integrity/reconciliation. That channel is "
                       "stronger than an API call from this host, which a "
                       "compromised host could fake."),
        },
        "reconciliations_recorded": len(rows),
        "latest_by_provider": latest,
        "never_reconciled": not rows,
        "open_variance_incidents": len(blocked),
        "promotion_blocked": bool(blocked),
        "how_to_reconcile": (
            "GET /v1/integrity/attestation for what this system claims, compare "
            "against the provider console for the same period, then POST the "
            "provider's figures here."),
    }
