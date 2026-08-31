"""Quality gates: the accept/reject decision on every registered LLM call.

Schema validation says the reply has the right *shape*. It says nothing about
whether the reply is usable: a `PublicEvidenceResult` with `found=true`, no
sources and no quantities validates perfectly and is worth nothing. Until this
module those checks lived scattered through the domain modules that happened
to think of them, in different forms, and a failure produced an exception
rather than a recorded verdict.

A gate is a named, versioned, **deterministic** function from a typed result to
accept or reject. Deterministic matters: a model judging its own output is not
a control, it is the same judgement twice.

**Rejection reasons are typed.** Free text cannot be aggregated, so "why did
this agent's acceptance rate fall" would be unanswerable - which is the same
argument that made abstention reasons an enumeration.

**Retry feeds the reason back, and deliberately reiterates that abstaining is
allowed.** This is the part worth being careful about. Telling a model "you
returned no sources, try again" is pressure to produce sources, and the
cheapest way to satisfy that pressure is to invent them. So the retry text
names the defect factually and repeats that returning nothing is a valid
answer when there is nothing to return. A gate that raises the fabrication
rate to raise the acceptance rate has made the system worse while improving
its own metric.

**Exhausting attempts fails closed.** There is no partial accept and no
best-of. The run ends FAILED with the last reason recorded, because a reply
that never passed the gate is not evidence of anything.
"""
from enum import Enum


class RejectionReason(str, Enum):
    SCHEMA_INVALID = "SCHEMA_INVALID"
    EMPTY_RESULT = "EMPTY_RESULT"
    CLAIM_WITHOUT_SOURCE = "CLAIM_WITHOUT_SOURCE"
    SOURCE_NOT_OBSERVED = "SOURCE_NOT_OBSERVED"
    VALUE_WITHOUT_UNIT = "VALUE_WITHOUT_UNIT"
    ABSTENTION_INCOHERENT = "ABSTENTION_INCOHERENT"
    OPTION_NOT_SUPPLIED = "OPTION_NOT_SUPPLIED"
    IDENTIFIER_MISSING = "IDENTIFIER_MISSING"
    TRUNCATED = "TRUNCATED"


class GateVerdict:
    __slots__ = ("accepted", "reason", "detail", "gate")

    def __init__(self, accepted: bool, gate: str = "",
                 reason: RejectionReason | None = None, detail: str = ""):
        self.accepted, self.gate, self.reason, self.detail = (
            accepted, gate, reason, detail)

    def __bool__(self):
        return self.accepted

    def as_dict(self) -> dict:
        return {"accepted": self.accepted, "gate": self.gate,
                "reason": self.reason.value if self.reason else None,
                "detail": self.detail}


ACCEPT = GateVerdict(True)


def _reject(gate, reason, detail):
    return GateVerdict(False, gate=gate, reason=reason, detail=detail)


# --------------------------------------------------------------- universal
def abstention_is_coherent(result, ctx) -> GateVerdict:
    """A result cannot both carry a value and say it could not find one.

    Cheap, and it catches a specific failure: a model that populates the
    fields and then adds an abstention reason to hedge. The hedge is the part
    that would be believed downstream, so the pair has to be refused rather
    than one half quietly preferred.
    """
    reason = getattr(result, "abstention_reason", None)
    if reason is None:
        return ACCEPT
    populated = [f for f in ("subject", "finding", "prefill_value")
                 if getattr(result, f, None)]
    if getattr(result, "quantities", None):
        populated.append("quantities")
    if getattr(result, "found", False) or populated:
        return _reject("abstention_is_coherent", RejectionReason.ABSTENTION_INCOHERENT,
                       f"abstention_reason is {reason} but {populated or 'found'} "
                       f"is populated. Either the fact was found or it was not.")
    return ACCEPT


def not_truncated(result, ctx) -> GateVerdict:
    if ctx.get("stop_reason") == "max_tokens":
        return _reject("not_truncated", RejectionReason.TRUNCATED,
                       "the reply hit the output-token limit, so it is "
                       "incomplete whatever it contains")
    return ACCEPT


# ------------------------------------------------------------ public evidence
def a_finding_carries_a_source(result, ctx) -> GateVerdict:
    if not getattr(result, "found", False):
        return ACCEPT
    if not result.sources:
        return _reject("a_finding_carries_a_source",
                       RejectionReason.CLAIM_WITHOUT_SOURCE,
                       "found=true with no source. A claim nobody can check "
                       "is not evidence; return found=false instead.")
    return ACCEPT


def a_finding_says_something(result, ctx) -> GateVerdict:
    if not getattr(result, "found", False):
        return ACCEPT
    if not (result.finding or result.quantities):
        return _reject("a_finding_says_something", RejectionReason.EMPTY_RESULT,
                       "found=true with neither a finding nor a quantity")
    return ACCEPT


def sources_were_actually_returned(result, ctx) -> GateVerdict:
    """Every cited URL must have come back from a search this turn.

    Moved here from research.py, where it was an inline filter that silently
    dropped unobserved sources. Dropping them quietly meant a reply that cited
    three recalled URLs and no real ones looked like a reply that found
    nothing, and the two need different responses.
    """
    observed = ctx.get("observed_urls")
    if observed is None or not getattr(result, "sources", None):
        return ACCEPT
    unobserved = [s.url for s in result.sources if s.url not in observed]
    if unobserved and len(unobserved) == len(result.sources):
        return _reject("sources_were_actually_returned",
                       RejectionReason.SOURCE_NOT_OBSERVED,
                       f"none of the cited sources came back from a search "
                       f"this turn: {unobserved[:3]}. A recalled URL is not a "
                       f"source.")
    return ACCEPT


def quantities_are_usable(result, ctx) -> GateVerdict:
    for q in getattr(result, "quantities", None) or []:
        if not q.unit and q.value is not None:
            return _reject("quantities_are_usable",
                           RejectionReason.VALUE_WITHOUT_UNIT,
                           f"quantity {q.label!r} has value {q.value} and no "
                           f"unit, so nothing downstream can interpret it")
    return ACCEPT


# ------------------------------------------------------------- other services
def candidates_are_named(result, ctx) -> GateVerdict:
    for c in getattr(result, "candidates", None) or []:
        if not getattr(c, "legal_name", None) and not getattr(c, "url", None):
            return _reject("candidates_are_named",
                           RejectionReason.IDENTIFIER_MISSING,
                           "a candidate carries neither a name nor a source URL")
    return ACCEPT


def scenario_was_offered(result, ctx) -> GateVerdict:
    """The selection must be one of the scenarios actually supplied.

    Moved out of savings_advisory.py's inline check so it is recorded as a
    verdict rather than raised as an exception - the distinction matters
    because a model picking a scenario that was not on the table is a
    measurable behaviour, not just a failed run.
    """
    offered = ctx.get("offered_scenarios")
    code = getattr(result, "scenario_code", None)
    if offered and code and code not in offered:
        return _reject("scenario_was_offered", RejectionReason.OPTION_NOT_SUPPLIED,
                       f"scenario {code!r} was not among the eligible "
                       f"scenarios {sorted(offered)}")
    return ACCEPT


def observations_are_usable(result, ctx) -> GateVerdict:
    for o in getattr(result, "observations", None) or []:
        if o.value is not None and not o.unit:
            return _reject("observations_are_usable",
                           RejectionReason.VALUE_WITHOUT_UNIT,
                           f"observation {o.metric!r} has a value and no unit")
    return ACCEPT


# ---------------------------------------------------------------------------
_UNIVERSAL = (not_truncated, abstention_is_coherent)

GATE_SETS = {
    "llm01.public_evidence.extract": _UNIVERSAL + (
        a_finding_carries_a_source, a_finding_says_something,
        sources_were_actually_returned, quantities_are_usable),
    "llm08.market_data.extract": _UNIVERSAL + (
        a_finding_carries_a_source, a_finding_says_something,
        sources_were_actually_returned, quantities_are_usable),
    "llm02.questionnaire.prefill": _UNIVERSAL,
    "llm07.advisory.select": _UNIVERSAL + (scenario_was_offered,),
    "llm07.advisory.narrate": _UNIVERSAL,
    "known_fact.corroborate": _UNIVERSAL + (candidates_are_named,),
    "entity.resolve.candidates": _UNIVERSAL + (candidates_are_named,),
    "llm09.benchmark.extract": _UNIVERSAL + (observations_are_usable,),
}

GATE_SET_VERSION = "1.0.0"


def evaluate(prompt_id: str, result, ctx: dict) -> GateVerdict:
    """Run the registered gates in order and return the first rejection.

    First rejection, not all of them: the retry carries one reason, and a
    model handed four simultaneous complaints tends to satisfy the easiest.
    """
    for gate in GATE_SETS.get(prompt_id, _UNIVERSAL):
        verdict = gate(result, ctx)
        if not verdict:
            return verdict
    return ACCEPT


def retry_instruction(verdict: GateVerdict) -> str:
    """What the next attempt is told.

    Names the defect and then repeats that abstaining is allowed. Without
    that second sentence the instruction reads as "produce sources", and the
    cheapest way to satisfy it is to invent them - a gate that raises the
    fabrication rate to raise its own pass rate has made the system worse.
    """
    return (
        f"\n\nYOUR PREVIOUS ANSWER WAS REJECTED\n"
        f"Reason: {verdict.reason.value if verdict.reason else 'REJECTED'}. "
        f"{verdict.detail}\n"
        f"Correct that specific problem. Do not invent anything to satisfy "
        f"this instruction: if the evidence genuinely is not there, returning "
        f"nothing with an abstention reason is the correct answer and will be "
        f"accepted.")
