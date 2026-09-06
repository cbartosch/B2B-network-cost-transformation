"""What is assumed, and what would settle it.

Specification 0.4. Stage 0 evidence prepopulates `assumption_register` and
`data_request`: "Create a reviewable assumption and a targeted question for
material gaps", with the control "Assumption remains visible after
replacement."

Neither table existed, so the workbench computed its gaps, displayed them, and
forgot them. It could say what it did not know and could not ask for it - which
is half of what Stage 0 is for. A gap that is not written down is a gap
somebody has to notice again next week.

Two records, and the distinction is the point:

**An assumption** is what the estimate is standing on right now. It has a
value, and something is being priced with it. It is superseded, never deleted:
the spec's replacement rule is that client evidence "supersedes a prior for the
active estimate but does not delete it", so the register keeps both and records
who replaced what and why. An estimate whose assumptions vanish as they are
answered cannot be audited afterwards.

**A data request item** is the question that would settle it. It has an owner
and a due date and no value at all. It is the thing an analyst sends to a
client, and it exists so that "coverage is 55%" becomes "send these eleven
questions to the CIO's team".
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

# What an assumption is worth, which decides what to ask for first.
#
# Not a severity: a gap that costs the estimate a lot and is easy to answer
# outranks one that costs more and needs a survey. The register carries both
# and the request is ordered by the product.
MATERIALITY = ("HIGH", "MEDIUM", "LOW")
EFFORT = ("ASK", "EXTRACT", "SURVEY")

# How an assumption ends. Superseded is not resolved: the value was replaced by
# evidence. Retired means the question stopped mattering - a country left
# scope, a site type disappeared - and that is a different fact about the
# engagement.
OPEN = "OPEN"
SUPERSEDED = "SUPERSEDED"
RETIRED = "RETIRED"
STATES = (OPEN, SUPERSEDED, RETIRED)

# Ordering weights. Deliberately coarse: a finer scale would imply the
# prioritisation is measured when it is a judgement about what to ask first.
_MATERIALITY_WEIGHT = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
_EFFORT_WEIGHT = {"ASK": 3, "EXTRACT": 2, "SURVEY": 1}


class AssumptionInvalid(ValueError):
    """A record that would not be reviewable."""


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def from_gap(gap: dict, *, case_id: str, raised_by: str,
             materiality: str = "MEDIUM", effort: str = "ASK") -> dict:
    """One computed gap, as an assumption and the question that would close it.

    `estimate_qa.gaps` already names the thing missing, what it costs and the
    act that would close it. This makes those durable: the gap is recomputed
    from a snapshot every time and disappears when the snapshot changes, and an
    assumption has to outlive the estimate that revealed it.
    """
    if materiality not in MATERIALITY:
        raise AssumptionInvalid(
            f"{materiality!r} is not one of {list(MATERIALITY)}")
    if effort not in EFFORT:
        raise AssumptionInvalid(f"{effort!r} is not one of {list(EFFORT)}")
    if not (gap.get("gap") and gap.get("detail")):
        raise AssumptionInvalid(
            "an assumption needs the thing assumed and why it matters; a bare "
            "label is not reviewable")

    return {
        "case_id": case_id,
        "assumption": gap["gap"],
        "detail": gap["detail"],
        "costs": gap.get("costs"),
        # The act that closes it, carried straight through. This is the
        # difference between a register of worries and a list of next steps.
        "closes_it": gap.get("closes_it"),
        "materiality": materiality,
        "effort": effort,
        "priority": priority(materiality=materiality, effort=effort),
        "state": OPEN,
        "raised_by": raised_by,
        "raised_at": datetime.now(timezone.utc).isoformat(),
        "superseded_by_value": None,
        "superseded_reason": None,
    }


def priority(*, materiality: str, effort: str) -> int:
    """What to ask for first: worth the most, cheapest to answer.

    A gap that costs the estimate a lot and needs a site survey outranks
    nothing, because the client cannot answer it this quarter. Materiality
    alone would put it at the top of a list nobody can action.
    """
    return (_MATERIALITY_WEIGHT.get(materiality, 1)
            * _EFFORT_WEIGHT.get(effort, 1))


def supersede(assumption: dict, *, value, reason: str, approved_by: str) -> dict:
    """Client evidence replaces the assumed value, and the record stays.

    Specification 0.4: evidence "supersedes a prior for the active estimate but
    does not delete it. The system stores both values, the replacement reason,
    approver and delta attribution."

    So the original value is kept beside the new one. An estimate whose
    assumptions vanish as they are answered cannot be explained afterwards -
    and "why did the baseline move" is the first question anyone asks.
    """
    if assumption.get("state") != OPEN:
        raise AssumptionInvalid(
            f"this assumption is already {assumption.get('state')}. "
            f"Superseding it twice would lose the first replacement, which is "
            f"the record of how the estimate got here.")
    if not str(reason or "").strip():
        raise AssumptionInvalid(
            "a replacement needs its reason. A value that changed for no "
            "recorded cause is indistinguishable from a typo.")
    return {**assumption, "state": SUPERSEDED,
            "superseded_by_value": None if value is None else str(value),
            "superseded_reason": reason, "approved_by": approved_by,
            "superseded_at": datetime.now(timezone.utc).isoformat()}


def retire(assumption: dict, *, reason: str, approved_by: str) -> dict:
    """The question stopped mattering, which is not the same as being answered.

    A country leaving scope retires its price assumption; it does not supersede
    it. Collapsing the two would make an engagement look better evidenced than
    it is - the gap did not close, it left.
    """
    if assumption.get("state") != OPEN:
        raise AssumptionInvalid(
            f"this assumption is already {assumption.get('state')}")
    return {**assumption, "state": RETIRED, "superseded_reason": reason,
            "approved_by": approved_by,
            "superseded_at": datetime.now(timezone.utc).isoformat()}


def request_items(assumptions: list, *, due_in_days: int = 14,
                  owner: str | None = None) -> list:
    """The open assumptions as a client-facing question list, best first.

    Only OPEN ones: a superseded assumption has been answered and asking again
    wastes the goodwill a data request runs on.

    Each item carries the act that closes it rather than the gap that caused
    it, because a client can act on "confirm the committed bandwidth on your
    MPLS circuits" and cannot act on "coverage is 55%".
    """
    due = (date.today() + timedelta(days=due_in_days)).isoformat()
    items = [
        {"assumption": a["assumption"],
         "question": a.get("closes_it") or a["detail"],
         "why_it_matters": a.get("costs"),
         "materiality": a.get("materiality"),
         "effort": a.get("effort"),
         "priority": a.get("priority", 0),
         "owner": owner,
         "due": due}
        for a in assumptions if a.get("state") == OPEN
    ]
    return sorted(items, key=lambda i: (-i["priority"], i["assumption"]))


def summarise(assumptions: list) -> dict:
    """What the estimate is standing on, in one line.

    Counts by state, because "eleven open assumptions" is the number that
    belongs beside a confidence score and does not currently appear anywhere.
    """
    by_state = {state: sum(1 for a in assumptions
                           if a.get("state") == state) for state in STATES}
    open_high = sum(1 for a in assumptions
                    if a.get("state") == OPEN
                    and a.get("materiality") == "HIGH")
    return {
        "by_state": by_state,
        "open_high_materiality": open_high,
        "note": (
            f"{by_state[OPEN]} open assumption(s), {open_high} of high "
            f"materiality. {by_state[SUPERSEDED]} superseded by evidence and "
            f"kept, {by_state[RETIRED]} retired because the question stopped "
            f"applying - which is not the same as being answered."
            if assumptions else
            "No assumptions registered. An estimate always rests on some; a "
            "register with none means they have not been written down rather "
            "than that there are none."),
    }
