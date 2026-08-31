"""The accept/reject decision on every registered agent call.

Schema validation says the reply has the right shape. It says nothing about
whether the reply is usable: a PublicEvidenceResult with found=true, no
sources and no quantities validates perfectly and is worth nothing. These
cover the gates, the retry that carries the reason back, and the two
properties that stop a retry loop becoming a fabrication loop.
"""
import pytest

from app.llm import gates, schemas


def _evidence(**kw):
    base = {"found": True, "subject": "DHL Group", "finding": "340 warehouses",
            "sources": [{"url": "https://example.com/ar"}]}
    base.update(kw)
    return schemas.PublicEvidenceResult.model_validate(base)


# ----------------------------------------------------------------- accepting
def test_a_well_formed_finding_is_accepted():
    v = gates.evaluate("llm01.public_evidence.extract", _evidence(), {})
    assert v.accepted


def test_an_honest_abstention_is_accepted():
    """The gates must not push toward answering. A clean abstention is a
    correct outcome and has to pass, or the retry loop becomes pressure to
    produce something."""
    result = schemas.PublicEvidenceResult.model_validate(
        {"found": False, "abstention_reason": "NOT_IN_SOURCE"})
    assert gates.evaluate("llm01.public_evidence.extract", result, {}).accepted


# ----------------------------------------------------------------- rejecting
def test_a_claim_with_no_source_is_rejected():
    v = gates.evaluate("llm01.public_evidence.extract",
                       _evidence(sources=[]), {})
    assert not v.accepted
    assert v.reason is gates.RejectionReason.CLAIM_WITHOUT_SOURCE


def test_a_finding_that_says_nothing_is_rejected():
    v = gates.evaluate("llm01.public_evidence.extract",
                       _evidence(finding=None, quantities=[]), {})
    assert v.reason is gates.RejectionReason.EMPTY_RESULT


def test_a_reply_citing_only_unobserved_sources_is_rejected():
    """Previously these were stripped silently, so "cited three URLs, none
    real" looked identical to "found nothing" - two situations needing
    different responses."""
    v = gates.evaluate("llm01.public_evidence.extract", _evidence(),
                       {"observed_urls": {"https://other.example"}})
    assert v.reason is gates.RejectionReason.SOURCE_NOT_OBSERVED


def test_a_value_without_a_unit_is_rejected():
    v = gates.evaluate(
        "llm01.public_evidence.extract",
        _evidence(quantities=[{"label": "WAREHOUSE", "value": "340"}]), {})
    assert v.reason is gates.RejectionReason.VALUE_WITHOUT_UNIT


def test_hedging_with_both_a_value_and_an_abstention_is_rejected():
    """The hedge is the half that would be believed downstream, so the pair
    is refused rather than one side quietly preferred."""
    v = gates.evaluate("llm01.public_evidence.extract",
                       _evidence(abstention_reason="SOURCE_AMBIGUOUS"), {})
    assert v.reason is gates.RejectionReason.ABSTENTION_INCOHERENT


def test_a_truncated_reply_is_rejected_whatever_it_contains():
    v = gates.evaluate("llm01.public_evidence.extract", _evidence(),
                       {"stop_reason": "max_tokens"})
    assert v.reason is gates.RejectionReason.TRUNCATED


def test_a_scenario_that_was_not_offered_is_rejected():
    sel = schemas.ScenarioSelection.model_validate(
        {"scenario_code": "D", "percentile": "base", "basis": "because"})
    v = gates.evaluate("llm07.advisory.select", sel,
                       {"offered_scenarios": {"A", "B"}})
    assert v.reason is gates.RejectionReason.OPTION_NOT_SUPPLIED


# --------------------------------------------------------------- the retry
def test_the_retry_names_the_defect_and_permits_abstaining():
    """The property that stops this being a fabrication loop. "You returned no
    sources, try again" is pressure to produce sources, and inventing them is
    the cheapest way to comply."""
    v = gates.evaluate("llm01.public_evidence.extract", _evidence(sources=[]), {})
    text = gates.retry_instruction(v)
    assert "CLAIM_WITHOUT_SOURCE" in text
    assert "Do not invent" in text
    assert "abstention" in text.lower()


def test_every_registered_prompt_has_a_gate_set():
    from app.llm import prompts
    missing = sorted(set(prompts.PROMPTS) - set(gates.GATE_SETS))
    assert not missing, f"registered prompts with no quality gate: {missing}"


def test_every_gate_set_includes_the_universal_gates():
    for prompt_id, gate_set in gates.GATE_SETS.items():
        names = {g.__name__ for g in gate_set}
        assert "not_truncated" in names, prompt_id
        assert "abstention_is_coherent" in names, prompt_id


def test_rejection_reasons_are_typed_so_they_aggregate():
    """Free text cannot answer "why did this agent's acceptance rate fall"."""
    v = gates.evaluate("llm01.public_evidence.extract", _evidence(sources=[]), {})
    assert isinstance(v.reason, gates.RejectionReason)
    assert v.as_dict()["reason"] == "CLAIM_WITHOUT_SOURCE"


def test_the_retry_limit_refuses_to_become_an_endurance_contest():
    from decimal import Decimal
    from app.domain.policy import AgentQualityPolicy, PolicyInvalid
    with pytest.raises(PolicyInvalid, match="pressing a model"):
        AgentQualityPolicy(set_name="t", max_attempts_per_call=9).validate()
    with pytest.raises(PolicyInvalid):
        AgentQualityPolicy(set_name="t", max_attempts_per_call=0).validate()
