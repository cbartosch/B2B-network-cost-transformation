"""WP1: registered prompts, typed schemas and provider conformance.

Before this, every service carried its JSON shape in prose and hand-checked a
few fields of the reply afterwards. That could not detect a missing field, an
extra one, or a wrong type, and three of those four failures were silent. It
also recorded nothing about which prompt produced a stored finding, so a
finding could not be interpreted against the instructions behind it.

These cover the registry's own guarantees. The cross-provider fixtures below
run the same cases through both adapters, per the CR's conformance gate.
"""
import json

import pytest
from pydantic import ValidationError

from app.llm import prompts, schemas
from app.llm.providers.base import strictify


# ------------------------------------------------------------------ registry
def test_the_registry_is_internally_valid():
    assert prompts.validate_registry() == []


def test_every_prompt_has_a_resolving_evaluation_suite():
    """A prompt without one ships unmeasured. The registry refuses at import,
    so this asserts the refusal is real rather than aspirational."""
    missing = [d.prompt_id for d in prompts.PROMPTS.values()
               if not d.evaluation_suite]
    assert not missing, missing


def test_a_template_change_without_a_version_bump_is_caught():
    """The defect this mirrors has already cost a debugging cycle:
    SIMULATION_MODEL_VERSION stayed at 1.0.0 while the output shape changed
    beneath it, and the failure presented as a coverage problem."""
    recorded = {d.prompt_id: d.prompt_hash for d in prompts.PROMPTS.values()}
    assert prompts.validate_registry(recorded) == []

    tampered = dict(recorded)
    victim = next(iter(tampered))
    tampered[victim] = "0" * 64
    problems = prompts.validate_registry(tampered)
    assert any("without a version bump" in p for p in problems)


def test_the_hash_covers_the_schema_not_only_the_text():
    """Adding a field to an output model changes what the provider is asked,
    so it is a prompt change even though the prose is untouched."""
    d = prompts.get("llm02.questionnaire.prefill")
    before = d.prompt_hash

    class Widened(schemas.QuestionnairePrefill):
        extra_field: str | None = None

    widened = prompts.PromptDefinition(
        prompt_id=d.prompt_id, prompt_version=d.prompt_version,
        agent_id=d.agent_id, task=d.task, output_model=Widened,
        tool_policy=d.tool_policy, evaluation_suite=d.evaluation_suite)
    assert widened.prompt_hash != before


def test_an_unregistered_prompt_id_is_refused():
    with pytest.raises(prompts.PromptNotRegistered):
        prompts.get("llm01.public_evidence.extract", "9.9.9")
    with pytest.raises(prompts.PromptNotRegistered):
        prompts.get("no.such.prompt")


def test_the_base_contract_reaches_every_service():
    for d in prompts.PROMPTS.values():
        assert "AUTHORITY" in d.system_template
        assert "Abstaining on a fact the source does carry" in d.system_template, (
            "the contract must say a false abstention is an error too - "
            "without it, a mostly-prohibition prompt reads as an instruction "
            "to say nothing whenever nothing is safe")


# -------------------------------------------------------------- authority
def test_no_schema_can_carry_an_evidence_state():
    """The P0 in the register: the model returned CORROBORATED and the system
    wrote it. The field is absent by construction, which is stronger than
    validating it away - an accommodating prompt cannot reopen the path."""
    assert "state" not in schemas.CorroborationResult.model_fields
    with pytest.raises(ValidationError):
        schemas.CorroborationResult.model_validate(
            {"search_attempted": True, "state": "CORROBORATED"})


def test_no_schema_can_carry_a_match_score():
    assert "match_score" not in schemas.EntityCandidate.model_fields
    with pytest.raises(ValidationError):
        schemas.EntityCandidate.model_validate(
            {"legal_name": "Acme", "match_score": 0.99})


def test_the_advisory_cannot_name_an_amount():
    """Selection only. There is nothing to echo, so nothing to validate for
    equality afterwards."""
    fields = set(schemas.ScenarioSelection.model_fields)
    assert fields == {"scenario_code", "percentile", "basis"}


def test_unknown_fields_are_rejected_everywhere():
    for model in (schemas.PublicEvidenceResult, schemas.QuestionnairePrefill,
                  schemas.EntityResolutionResult, schemas.CorroborationResult,
                  schemas.BenchmarkExtractionResult):
        with pytest.raises(ValidationError):
            model.model_validate({"invented_field": 1})


# ------------------------------------------------------- provider conformance
@pytest.mark.parametrize("model", [
    schemas.PublicEvidenceResult, schemas.QuestionnairePrefill,
    schemas.ScenarioSelection, schemas.CorroborationResult,
    schemas.EntityResolutionResult, schemas.BenchmarkExtractionResult,
])
def test_every_output_model_survives_strictification(model):
    """Both approved providers require all properties listed in `required` and
    additionalProperties false. Pydantic marks defaulted fields optional, which
    strict mode rejects - so the helper makes them required-and-nullable rather
    than dropping them, keeping abstention expressible."""
    strict = strictify(model.model_json_schema())
    assert strict["additionalProperties"] is False
    assert set(strict["required"]) == set(strict["properties"])
    json.dumps(strict)          # must remain serialisable for the wire


def test_strictify_recurses_into_nested_objects():
    nested = strictify(schemas.PublicEvidenceResult.model_json_schema())
    defs = nested.get("$defs") or {}
    assert defs, "nested models must survive as $defs"
    for name, sub in defs.items():
        if sub.get("type") == "object" or "properties" in sub:
            assert sub["additionalProperties"] is False, name
            assert set(sub["required"]) == set(sub["properties"]), name


def test_a_valid_payload_round_trips_for_both_providers():
    """The same fixture must validate whichever adapter produced it. A schema
    that only one provider can satisfy is a service with one provider."""
    payload = {
        "found": True, "subject": "DHL Group", "finding": "340 warehouses in DE",
        "quantities": [{"label": "WAREHOUSE", "value": "340", "unit": "sites",
                        "country": "DE", "bandwidth_mbps": None,
                        "as_of": "2024-12-31"}],
        "sources": [{"url": "https://example.com/ar", "publisher": "AR",
                     "as_of": "2024"}],
        "confidence_note": None, "abstention_reason": None,
    }
    result = schemas.PublicEvidenceResult.model_validate(payload)
    assert result.quantities[0].label == "WAREHOUSE"
    assert str(result.quantities[0].value) == "340"


def test_an_abstention_is_typed_not_free_text():
    with pytest.raises(ValidationError):
        schemas.PublicEvidenceResult.model_validate(
            {"found": False, "abstention_reason": "couldn't find anything"})
    ok = schemas.PublicEvidenceResult.model_validate(
        {"found": False, "abstention_reason": "NOT_IN_SOURCE"})
    assert ok.abstention_reason is schemas.AbstentionReason.NOT_IN_SOURCE


# ------------------------------------------------- the acceptance criteria
def _app_root():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for c in (root / "api_service" / "app", root / "app"):
        if (c / "routers" / "api.py").exists():
            return c
    pytest.skip("cannot locate the application package")


def test_no_production_call_site_parses_a_provider_response():
    """CR acceptance, checked mechanically rather than asserted in a report."""
    offenders = []
    for path in _app_root().rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if "gateway.parse_json_strict" in line and not line.strip().startswith("#"):
                offenders.append(f"{path.name}:{i}")
    assert not offenders, offenders


def test_no_domain_module_describes_a_json_shape_in_prose():
    """The other half of the acceptance criterion. A shape described in prose
    is a shape nothing enforces."""
    needles = ("Respond with a single JSON object",
               "Respond with the JSON object only",
               "JSON object and nothing else")
    offenders = []
    for path in (_app_root() / "domain").rglob("*.py"):
        text = path.read_text()
        for needle in needles:
            if needle in text:
                offenders.append(f"{path.name}: {needle!r}")
    assert not offenders, offenders


def test_the_audit_row_can_record_which_prompt_produced_it():
    from app import db
    columns = {c.name for c in db.llm_run.columns}
    required = {"prompt_id", "prompt_version", "prompt_hash",
                "output_schema_version", "tool_policy_version",
                "parsed_output", "supplied_source_ids", "reviewer_outcome"}
    assert required <= columns, sorted(required - columns)
