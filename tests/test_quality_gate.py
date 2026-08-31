"""The per-call quality gate: accept, reject, retry with a reason, fail closed.

Schema validation answers "is this the right shape". It cannot answer "is this
a usable answer", and everything below is an example of the gap: schema-valid
output that would have flowed straight into a disposition.
"""
import pytest

from app.llm import quality, schemas
from app.llm.quality import Rejection


def _evidence(**over):
    payload = {"found": True, "subject": "Acme", "finding": "340 warehouses",
               "quantities": [], "sources": [{"url": "https://example.com/ar"}],
               "confidence_note": None, "abstention_reason": None}
    payload.update(over)
    return schemas.PublicEvidenceResult.model_validate(payload)


def test_a_well_formed_finding_is_accepted():
    v = quality.evaluate("llm01.public_evidence.extract", _evidence())
    assert v.accepted and not v.reasons


def test_a_finding_with_no_source_is_rejected():
    """The most common schema-valid uselessness: found=true, sources empty."""
    v = quality.evaluate("llm01.public_evidence.extract", _evidence(sources=[]))
    assert not v.accepted
    assert Rejection.CLAIMED_FINDING_WITHOUT_SOURCE in v.reasons
    assert v.retryable


def test_a_source_that_is_not_a_url_is_rejected():
    v = quality.evaluate("llm01.public_evidence.extract",
                         _evidence(sources=[{"url": "the annual report"}]))
    assert Rejection.SOURCE_NOT_RESOLVABLE in v.reasons


def test_an_empty_result_must_say_why():
    v = quality.evaluate("llm01.public_evidence.extract",
                         _evidence(found=False, sources=[], abstention_reason=None))
    assert Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION in v.reasons


def test_a_reply_that_both_asserts_and_abstains_is_rejected():
    v = quality.evaluate("llm01.public_evidence.extract",
                         _evidence(abstention_reason="NOT_IN_SOURCE"))
    assert Rejection.CONTRADICTS_ITSELF in v.reasons


def test_a_number_without_a_unit_is_rejected():
    v = quality.evaluate("llm01.public_evidence.extract", _evidence(
        quantities=[{"label": "WAREHOUSE", "value": "340", "unit": None,
                     "country": "DE", "bandwidth_mbps": None, "as_of": None}]))
    assert Rejection.QUANTITY_WITHOUT_UNIT in v.reasons


def test_an_entity_candidate_with_no_name_is_rejected():
    result = schemas.EntityResolutionResult.model_validate(
        {"candidates": [{"legal_name": "  ", "identifier": "X",
                         "identifier_type": None, "country_of_domicile": "DE",
                         "website": None, "industry": None, "group_parent": None,
                         "differentiators": [], "unresolved_attributes": []}],
         "unresolved_questions": []})
    v = quality.evaluate("entity.resolve.candidates", result)
    assert Rejection.CANDIDATE_WITHOUT_IDENTITY in v.reasons


def test_a_corroboration_that_did_not_search_is_rejected():
    result = schemas.CorroborationResult.model_validate(
        {"candidates": [], "search_attempted": False, "unresolved_reasons": []})
    v = quality.evaluate("known_fact.corroborate", result)
    assert Rejection.SEARCH_NOT_ATTEMPTED in v.reasons


# ------------------------------------------------------------- retryability
def test_a_perimeter_or_rights_rejection_is_not_retried():
    """The model has understood the task and answered about the wrong subject.
    A second sample arrives at the same place, more expensively."""
    for terminal in (Rejection.OUT_OF_PERIMETER_SUBJECT, Rejection.RIGHTS_VIOLATION):
        assert not quality.Verdict(False, [terminal]).retryable


def test_a_mixed_verdict_takes_the_terminal_reading():
    """A reply that is both under-sourced and about the wrong company will
    still be about the wrong company next time."""
    v = quality.Verdict(False, [Rejection.CLAIMED_FINDING_WITHOUT_SOURCE,
                                Rejection.OUT_OF_PERIMETER_SUBJECT])
    assert not v.retryable


def test_every_rejection_reason_carries_guidance_for_the_retry():
    """A retry that repeats the prompt unchanged is resampling, not
    correction, so every retryable reason must be able to say what to fix."""
    missing = [r.value for r in Rejection if r not in quality.GUIDANCE]
    assert not missing, missing


def test_the_guidance_is_an_instruction_not_a_diagnosis():
    v = quality.Verdict(False, [Rejection.CLAIMED_FINDING_WITHOUT_SOURCE])
    text = v.guidance()
    assert "cite" in text.lower() or "set found=false" in text.lower()


# ------------------------------------------------------------- registration
def test_every_registered_prompt_has_a_gate():
    """An unregistered gate is a gap, not a pass."""
    from app.llm import prompts
    missing = sorted(set(prompts.PROMPTS) - set(quality.RULES))
    assert not missing, missing


def test_an_unregistered_service_is_rejected_not_waved_through():
    v = quality.evaluate("no.such.service", object())
    assert not v.accepted
    assert "no quality gate registered" in " ".join(v.detail)


def test_the_verdict_serialises_for_the_audit_row():
    v = quality.evaluate("llm01.public_evidence.extract", _evidence(sources=[]))
    d = v.as_dict()
    assert d["accepted"] is False
    assert d["reasons"] == ["CLAIMED_FINDING_WITHOUT_SOURCE"]
    assert d["retryable"] is True
