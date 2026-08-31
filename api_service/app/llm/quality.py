"""Quality gate: every registered call is accepted or rejected, with a reason.

Schema validation answers "is this the right shape". It cannot answer "is this
a usable answer", and the gap between those two is where most of the bad output
in this system has lived: a research reply with `found: true` and no sources, a
corroboration reply with candidates that carry no URL, an entity candidate with
no legal name. All of those are schema-valid and all of them are useless, and
until now every one of them flowed straight into a disposition.

Four things this deliberately does, each of which it would be easy to skip:

**Reasons are typed.** A rejection carries a code from a closed enumeration,
not a sentence. Free text cannot be aggregated, so a service that has started
failing in a new way looks exactly like one that has always failed sometimes.
The codes are what makes "which gate is firing, and since when" answerable.

**Not every rejection is worth retrying.** A missing source is a drafting
failure and a different sample may fix it. An out-of-perimeter subject or a
rights violation will not improve on the second attempt: the model has
understood the task and answered about the wrong thing, and retrying spends
money and wall-clock to arrive at the same place. Retryability is a property
of the reason, not of the caller's patience.

**A retry is told what was wrong.** Re-issuing the same prompt is resampling,
not correction; it fails the same way at roughly the same rate. The rejection
reasons go back into the next attempt in plain terms.

**Exhaustion fails closed.** When the attempts are spent the run fails with the
reasons attached. It does not return the least-bad attempt, because a caller
that receives an answer has no way to know it was the one the gate refused.
"""
from enum import Enum


class Rejection(str, Enum):
    """Closed set. A new failure mode gets a new member, not a new sentence."""
    # --- content
    CLAIMED_FINDING_WITHOUT_SOURCE = "CLAIMED_FINDING_WITHOUT_SOURCE"
    EMPTY_RESULT_WITHOUT_ABSTENTION = "EMPTY_RESULT_WITHOUT_ABSTENTION"
    QUANTITY_WITHOUT_UNIT = "QUANTITY_WITHOUT_UNIT"
    CANDIDATE_WITHOUT_IDENTITY = "CANDIDATE_WITHOUT_IDENTITY"
    SOURCE_NOT_RESOLVABLE = "SOURCE_NOT_RESOLVABLE"
    CONTRADICTS_ITSELF = "CONTRADICTS_ITSELF"
    # The reply did not match the registered output model. Distinct from
    # CONTRADICTS_ITSELF, which is a judgement about what the model said: this
    # one says the reply never became a result at all, and reporting it as a
    # self-contradiction sent a reader looking for an inconsistency that was
    # not there.
    SCHEMA_INVALID = "SCHEMA_INVALID"
    # --- task compliance
    SEARCH_NOT_ATTEMPTED = "SEARCH_NOT_ATTEMPTED"
    DERIVED_VALUE_PRESENTED_AS_OBSERVED = "DERIVED_VALUE_PRESENTED_AS_OBSERVED"
    # --- not worth retrying
    OUT_OF_PERIMETER_SUBJECT = "OUT_OF_PERIMETER_SUBJECT"
    RIGHTS_VIOLATION = "RIGHTS_VIOLATION"


# Retrying these produces the same answer more expensively: the model has
# understood the task and answered about the wrong subject, or under the wrong
# rights. That is a decision for a person, not another sample.
TERMINAL = frozenset({
    Rejection.OUT_OF_PERIMETER_SUBJECT,
    Rejection.RIGHTS_VIOLATION,
})

# What each code should tell the model on the next attempt. Written as an
# instruction rather than a diagnosis, because the retry has to act on it.
GUIDANCE = {
    Rejection.CLAIMED_FINDING_WITHOUT_SOURCE:
        "You reported a finding but cited no source. Either cite the source "
        "that states it, or set found=false with an abstention_reason.",
    Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION:
        "You returned nothing and gave no abstention_reason. If the searches "
        "turned up nothing attributable, say so with a reason from the "
        "enumeration.",
    Rejection.QUANTITY_WITHOUT_UNIT:
        "A number with no unit cannot be used. Give the unit for every "
        "quantity, or omit the quantity.",
    Rejection.CANDIDATE_WITHOUT_IDENTITY:
        "A candidate with no legal name identifies nothing. Give the name, or "
        "drop the candidate.",
    Rejection.SOURCE_NOT_RESOLVABLE:
        "A source must be a resolvable http or https URL. A title, a search "
        "phrase or a description of where to look is not a source.",
    Rejection.CONTRADICTS_ITSELF:
        "Your reply asserts and abstains on the same field. Do one.",
    Rejection.SEARCH_NOT_ATTEMPTED:
        "You answered without searching. Search first; an answer from memory "
        "is not evidence here.",
    Rejection.DERIVED_VALUE_PRESENTED_AS_OBSERVED:
        "You combined or calculated a value and reported it as observed. "
        "Report the source figures instead and say what you would have "
        "derived, or abstain.",
    Rejection.OUT_OF_PERIMETER_SUBJECT:
        "Your reply is about a subject outside the confirmed perimeter.",
    Rejection.RIGHTS_VIOLATION:
        "Your reply uses material the supplied rights do not permit.",
}


class Verdict:
    __slots__ = ("accepted", "reasons", "detail")

    def __init__(self, accepted: bool, reasons=None, detail=None):
        self.accepted = accepted
        self.reasons = list(reasons or [])
        self.detail = list(detail or [])

    @property
    def retryable(self) -> bool:
        """Retry only when every reason is one a further attempt could fix.

        Any terminal reason makes the whole verdict terminal: a reply that is
        both under-sourced and about the wrong company will still be about the
        wrong company next time.
        """
        return bool(self.reasons) and not any(r in TERMINAL for r in self.reasons)

    def as_dict(self) -> dict:
        return {"accepted": self.accepted,
                "reasons": [r.value for r in self.reasons],
                "detail": self.detail,
                "retryable": self.retryable}

    def guidance(self) -> str:
        lines = [GUIDANCE[r] for r in self.reasons if r in GUIDANCE]
        return " ".join(lines)


def _url_ok(value) -> bool:
    return isinstance(value, str) and value.lower().startswith(("http://", "https://"))


# --------------------------------------------------------------- rule sets
def public_evidence(result, context) -> Verdict:
    """Legibility, not sufficiency.

    Thin is now a grade, not a rejection: a finding with one snippet-only
    source is UNRELIABLE and kept. So this gate checks only that the reply can
    be read and graded - a claim with no source at all cannot be, because
    there is no provenance to compute a grade from.
    """
    """LLM-01 and LLM-08."""
    reasons, detail = [], []
    if result.found:
        if not result.sources:
            reasons.append(Rejection.CLAIMED_FINDING_WITHOUT_SOURCE)
            detail.append("found=true with an empty sources list")
        bad = [s.url for s in result.sources if not _url_ok(s.url)]
        if bad:
            reasons.append(Rejection.SOURCE_NOT_RESOLVABLE)
            detail.append(f"not resolvable URLs: {bad[:3]}")
        unitless = [q.label for q in result.quantities if not (q.unit or "").strip()]
        if unitless:
            reasons.append(Rejection.QUANTITY_WITHOUT_UNIT)
            detail.append(f"quantities with no unit: {unitless[:5]}")
        if result.abstention_reason is not None:
            reasons.append(Rejection.CONTRADICTS_ITSELF)
            detail.append("found=true alongside an abstention_reason")
    else:
        if result.abstention_reason is None:
            reasons.append(Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION)
            detail.append("found=false with no abstention_reason")
    return Verdict(not reasons, reasons, detail)


def corroboration(result, context) -> Verdict:
    reasons, detail = [], []
    if not result.search_attempted and not result.candidates:
        reasons.append(Rejection.SEARCH_NOT_ATTEMPTED)
        detail.append("no search attempted and no candidates returned")
    bad = [c.url for c in result.candidates if not _url_ok(c.url)]
    if bad:
        reasons.append(Rejection.SOURCE_NOT_RESOLVABLE)
        detail.append(f"candidate URLs not resolvable: {bad[:3]}")
    if result.candidates and not result.search_attempted:
        reasons.append(Rejection.CONTRADICTS_ITSELF)
        detail.append("candidates returned while reporting no search")
    return Verdict(not reasons, reasons, detail)


def entity_candidates(result, context) -> Verdict:
    reasons, detail = [], []
    nameless = [i for i, c in enumerate(result.candidates)
                if not (c.legal_name or "").strip()]
    if nameless:
        reasons.append(Rejection.CANDIDATE_WITHOUT_IDENTITY)
        detail.append(f"candidates with no legal name at positions {nameless[:5]}")
    if not result.candidates and not result.unresolved_questions:
        reasons.append(Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION)
        detail.append("no candidates and nothing said about why")
    return Verdict(not reasons, reasons, detail)


def benchmark_observations(result, context) -> Verdict:
    reasons, detail = [], []
    if not result.observations and not result.unresolved_questions:
        reasons.append(Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION)
        detail.append("no observations and nothing said about why")
    unitless = [o.metric for o in result.observations if not (o.unit or "").strip()]
    if unitless:
        reasons.append(Rejection.QUANTITY_WITHOUT_UNIT)
        detail.append(f"observations with no unit: {unitless[:5]}")
    # A currency conversion the extractor was told not to perform usually
    # shows up as a currency that appears nowhere in the source it cites.
    derived = [o.metric for o in result.observations
               if o.note and "converted" in o.note.lower()]
    if derived:
        reasons.append(Rejection.DERIVED_VALUE_PRESENTED_AS_OBSERVED)
        detail.append(f"observation notes describe a conversion: {derived[:3]}")
    return Verdict(not reasons, reasons, detail)


def questionnaire_prefill(result, context) -> Verdict:
    reasons, detail = [], []
    has_value = bool((result.prefill_value or "").strip())
    if has_value and not (result.basis or "").strip():
        reasons.append(Rejection.CLAIMED_FINDING_WITHOUT_SOURCE)
        detail.append("a proposed answer with no basis")
    if not has_value and result.abstention_reason is None:
        reasons.append(Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION)
        detail.append("no proposed answer and no abstention_reason")
    if has_value and result.abstention_reason is not None:
        reasons.append(Rejection.CONTRADICTS_ITSELF)
        detail.append("a value and an abstention on the same answer")
    return Verdict(not reasons, reasons, detail)


def entity_profile(result, context) -> Verdict:
    """A profile a person cannot check is not a check.

    Both paragraphs and at least one source are required, because the whole
    purpose is for a human to compare what the system found against what they
    meant - and prose with no source behind it gives them nothing to compare.
    """
    reasons, detail = [], []
    if result.abstention_reason is not None:
        # An honest "I could not identify this entity" is a useful answer and
        # is exactly what should happen for a mistyped or invented name.
        return Verdict(True)
    for field in ("what_it_is", "what_is_current"):
        if not (getattr(result, field, None) or "").strip():
            reasons.append(Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION)
            detail.append(f"{field} is empty and nothing was abstained on")
    if not result.sources:
        reasons.append(Rejection.CLAIMED_FINDING_WITHOUT_SOURCE)
        detail.append("a profile with no source is a recollection")
    return Verdict(not reasons, reasons, detail)


def public_fact_prefill(result, context) -> Verdict:
    """Every proposal must carry a source and a usable value.

    A sourceless proposal is a recollection wearing the shape of a finding,
    and it would enter the register as though it had been checked - which is
    precisely the confidence inflation the register exists to prevent.
    """
    reasons, detail = [], []
    for fact in result.facts:
        if not fact.sources:
            reasons.append(Rejection.CLAIMED_FINDING_WITHOUT_SOURCE)
            detail.append(f"{fact.fact_class!r} proposed with no source")
            break
        if fact.value_base is None and fact.value_low is None:
            reasons.append(Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION)
            detail.append(f"{fact.fact_class!r} proposed with no value")
            break
        if not (fact.subject or "").strip():
            reasons.append(Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION)
            detail.append(f"{fact.fact_class!r} proposed with no subject")
            break
        if fact.value_base is not None and not (fact.unit or "").strip():
            # A number with no unit cannot be compared with anything, which
            # is the only thing this register does with it.
            reasons.append(Rejection.QUANTITY_WITHOUT_UNIT)
            detail.append(f"{fact.fact_class!r} proposed {fact.value_base} with "
                          f"no unit")
            break
    if not result.facts and not result.not_found and \
            result.abstention_reason is None:
        reasons.append(Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION)
        detail.append("nothing found, nothing listed as not found, and no "
                      "abstention")
    return Verdict(not reasons, reasons, detail)


def accept_all(result, context) -> Verdict:
    """For services whose whole output is already constrained by the schema.

    Named rather than implied: a service with no gate should say so, so the
    absence is a decision on the record instead of an oversight nobody sees.
    """
    return Verdict(True)


RULES = {
    "llm01.public_evidence.extract": public_evidence,
    "llm08.market_data.extract": public_evidence,
    "known_fact.corroborate": corroboration,
    "entity.resolve.candidates": entity_candidates,
    "entity.profile.summarise": entity_profile,
    "known_fact.prefill_public": public_fact_prefill,
    "llm09.benchmark.extract": benchmark_observations,
    "llm02.questionnaire.prefill": questionnaire_prefill,
    # Scenario selection is a two-field enum-constrained choice, and the
    # narrative has no checkable property beyond being present.
    "llm07.advisory.select": accept_all,
    "llm07.advisory.narrate": accept_all,
}


def evaluate(prompt_id: str, result, context=None) -> Verdict:
    rule = RULES.get(prompt_id)
    if rule is None:
        # An unregistered gate is a gap, not a pass. Saying so beats letting a
        # new service inherit "accepted" by default.
        return Verdict(False, [Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION],
                       [f"no quality gate registered for {prompt_id}"])
    return rule(result, context or {})
