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
        # "WHAT YOU MUST NOT DO", not "AUTHORITY". 4.108.0 rewrote the base
        # contract and renamed that section; the prohibition it anchors on is
        # unchanged and still there word for word - "Compute or alter
        # coverage, prices, confidence, savings ... Your output is a proposal;
        # approval is a named person's act." The heading has not existed
        # anywhere in the codebase since, so this half of the assertion has
        # been false for every prompt ever since, and the sibling assertion
        # below - which does pass - was carrying the whole test.
        assert "WHAT YOU MUST NOT DO" in d.system_template
        assert "approval is a named person's act" in d.system_template
        # Both anchors were stale, so this test has never passed - the
        # rewrite in 4.108.0 deleted the ABSTENTION section along with
        # AUTHORITY, and the sentence it quoted ("Abstaining on a fact the
        # source does carry is an error of the same weight as inventing one")
        # went with it. The property survived the rewrite and reads harder
        # than it did: withholding a finding because it is not certain "is
        # the one clearly wrong answer: it destroys the judgement you were
        # asked for and leaves the reader with nothing."
        assert "the one clearly wrong answer" in d.system_template, (
            "the contract must say a false abstention is an error too - "
            "without it, a mostly-prohibition prompt reads as an instruction "
            "to say nothing whenever nothing is safe")
        assert ("Return an empty result only when you genuinely found "
                "nothing") in d.system_template


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


# ------------------------------------------------------- known-fact hygiene
def test_a_fact_without_a_subject_or_value_cannot_be_registered(session):
    """Found in the field as an UNCORROBORATED result nobody could act on:
    "Location footprint - (None sites)" with an empty subject. The
    corroboration agent correctly reported there was no claim to check, and
    the deterministic comparison correctly returned UNCORROBORATED - every
    stage behaved properly on input that should never have been storable."""
    import datetime as _dt
    import uuid as _uuid

    from sqlalchemy import insert
    from app import db
    from app.domain import known_facts

    case_id = str(_uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="tester",
        subject_entity_legal_name="Acme Global Logistics"))
    session.commit()

    common = dict(case_id=case_id, fact_class="Location footprint",
                  asserted_by="Christian Bartosch",
                  assertion_date=_dt.date(2026, 8, 31),
                  basis="INDUSTRY_KNOWLEDGE",
                  verifiability="PUBLICLY_VERIFIABLE")

    with pytest.raises(ValueError, match="subject is mandatory"):
        known_facts.register(session, subject="  ", value_base=340, unit="sites",
                             **common)

    with pytest.raises(ValueError, match="must carry a value"):
        known_facts.register(session, subject="Acme Global Logistics DE",
                             unit="sites", **common)

    ok = known_facts.register(session, subject="Acme Global Logistics DE",
                              value_base=340, unit="sites", **common)
    assert ok["known_fact_id"]


def test_the_corroboration_prompt_tells_the_agent_where_site_counts_live():
    """A count of sites is rarely on one page, so "look for public sources"
    was not enough of an instruction to find one."""
    task = prompts.get("known_fact.corroborate").task
    for needle in ("sustainability", "location finder", "director"):
        assert needle in task.lower(), needle


# --------------------------------------------------- search must be reachable
def test_the_emit_tool_is_not_pinned_when_a_search_tool_is_present():
    """Observed in the field as three consecutive SEARCH_NOT_ATTEMPTED
    rejections on a well-formed fact.

    tool_choice {"type":"tool","name":X} forces X on the first turn, so with
    the emit tool pinned the model could never call web_search - every
    search-using service answered from memory and the gate correctly refused
    all three attempts. The gate was right; the adapter made searching
    impossible."""
    import inspect
    from app.llm.providers import anthropic_adapter

    src = inspect.getsource(anthropic_adapter.AnthropicAdapter.parse)
    assert '{"type": "any"} if tools' in src, (
        "with a search tool present the emit tool must not be pinned")
    assert 'else {"type": "tool", "name": schema_name}' in src, (
        "without other tools it should still be pinned - that is the "
        "stronger guarantee and costs nothing")


def test_the_search_using_services_declare_a_search_tool_policy():
    """If the policy says none, no tool is passed, the adapter pins, and the
    service is silently recall-only."""
    for prompt_id in ("llm01.public_evidence.extract",
                      "llm08.market_data.extract",
                      "known_fact.corroborate",
                      "entity.resolve.candidates"):
        d = prompts.get(prompt_id)
        assert d.tool_policy_version.startswith("web_search"), (
            f"{prompt_id} needs search but declares {d.tool_policy_version}")


def test_a_search_service_called_without_a_search_tool_fails_closed():
    """A declared tool policy the call site ignores makes the registry a
    statement of intent rather than a contract."""
    import inspect
    from app.llm import gateway
    src = inspect.getsource(gateway.structured_call)
    assert 'startswith("web_search") and not tools' in src


def test_every_search_service_passes_a_tool_at_its_call_site():
    """The enclosing function, not a character window.

    A window around the prompt id was the old mechanism and it was wrong
    twice over. research.py passes this id through a ternary, so the literal
    `prompt_id="..."` never appears and the call site read as missing. And it
    builds `tools = _web_search_tool(...)` far enough above the call that a
    1,200-character look-back lands inside a comment, so a call site that
    does pass a search tool read as one that does not.

    "Its call site" means the function making the call. That is what is
    checked here, and it does not depend on how far apart two lines happen to
    sit.
    """
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())

    def _enclosing_function(prompt_id):
        for path in sorted((app / "domain").rglob("*.py")):
            src = path.read_text()
            if f'"{prompt_id}"' not in src:
                continue
            for node in ast.walk(ast.parse(src)):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                segment = ast.get_source_segment(src, node) or ""
                if f'"{prompt_id}"' in segment:
                    return segment
        return None

    for prompt_id in ("llm01.public_evidence.extract",
                      "known_fact.corroborate",
                      "entity.resolve.candidates"):
        enclosing = _enclosing_function(prompt_id)
        assert enclosing is not None, f"{prompt_id} has no call site"
        assert "web_search" in enclosing, (
            f"{prompt_id} declares a search policy but the function calling "
            f"it passes no search tool")


# ------------------------------------------------- entity confirmation profile
def test_the_entity_profile_asks_for_two_paragraphs_and_the_aliases():
    """The aliases are the operative output. The prose is how a person decides
    whether to trust them."""
    task = prompts.get("entity.profile.summarise").task
    assert "what_it_is" in task and "what_is_current" in task
    assert "also_known_as" in task
    assert "disambiguation_note" in task, (
        "a group and its national subsidiary is the common ambiguity and the "
        "one that silently produces an estimate of the wrong perimeter")


def test_the_entity_profile_searches():
    d = prompts.get("entity.profile.summarise")
    assert d.tool_policy_version.startswith("web_search"), (
        "a profile from memory cannot tell an analyst whether the company is "
        "the one they meant today")


def test_a_profile_without_a_source_is_rejected():
    from app.llm import quality, schemas
    unsourced = schemas.EntityProfile.model_validate({
        "what_it_is": "A large German bank.",
        "what_is_current": "Recently restructured."})
    v = quality.evaluate("entity.profile.summarise", unsourced, {})
    assert not v.accepted

    sourced = schemas.EntityProfile.model_validate({
        "what_it_is": "A large German bank.",
        "what_is_current": "Recently restructured.",
        "sources": [{"url": "https://example.com/ar"}]})
    assert quality.evaluate("entity.profile.summarise", sourced, {}).accepted


def test_an_unidentifiable_entity_may_abstain():
    """A mistyped or invented name should produce an honest "I could not
    identify this", which is the most useful answer available."""
    from app.llm import quality, schemas
    abstained = schemas.EntityProfile.model_validate(
        {"abstention_reason": "NOT_IN_SOURCE"})
    assert quality.evaluate("entity.profile.summarise", abstained, {}).accepted


def test_the_profile_writes_nothing_to_the_case():
    """Confirmation stays a named act (0.1A). A profile that quietly set the
    legal name would be an auto-confirmation wearing a different label."""
    import inspect
    from app.domain import entity_resolution
    src = inspect.getsource(entity_resolution.profile)
    assert "update(db.case)" not in src and "insert(db.case" not in src


# ------------------------------------------------- public known-fact prefill
def test_a_proposal_without_a_source_is_rejected():
    """A sourceless proposal entering the register would borrow the accepting
    analyst's authority for something nobody checked - the confidence
    inflation 0.1B exists to prevent."""
    from app.llm import quality, schemas
    unsourced = schemas.PublicFactSweep.model_validate({"facts": [
        {"fact_class": "Location footprint", "subject": "Acme DE",
         "value_base": "340", "unit": "sites"}]})
    assert not quality.evaluate("known_fact.prefill_public", unsourced, {}).accepted

    sourced = schemas.PublicFactSweep.model_validate({"facts": [
        {"fact_class": "Location footprint", "subject": "Acme DE",
         "value_base": "340", "unit": "sites",
         "sources": [{"url": "https://example.com/ar"}]}]})
    assert quality.evaluate("known_fact.prefill_public", sourced, {}).accepted


def test_finding_nothing_is_an_acceptable_answer_if_it_says_so():
    """Which fact classes have no public answer is useful: it tells the
    analyst where their own knowledge is the only route."""
    from app.llm import quality, schemas
    empty = schemas.PublicFactSweep.model_validate(
        {"facts": [],
         # NotFoundClass, not a bare string: the class and what was
         # searched for are two things one string cannot hold, which is
         # why the schema changed.
         "not_found": [{"fact_class": "Public cost evidence"}]})
    assert quality.evaluate("known_fact.prefill_public", empty, {}).accepted

    silent = schemas.PublicFactSweep.model_validate({"facts": []})
    assert not quality.evaluate("known_fact.prefill_public", silent, {}).accepted


def test_a_proposal_can_carry_a_band_so_disagreement_is_not_hidden():
    from app.llm import schemas
    banded = schemas.ProposedKnownFact.model_validate({
        "fact_class": "Location footprint", "subject": "HVB",
        "value_base": "371", "value_low": "341", "value_high": "400",
        "unit": "sites", "sources": [{"url": "https://a"}, {"url": "https://b"}]})
    assert banded.value_low < banded.value_base < banded.value_high


def test_an_accepted_proposal_enters_as_a_third_party_report(session):
    """Not INDUSTRY_KNOWLEDGE. The analyst is attesting that a public source
    says this, which is a weaker and different claim from attesting that they
    know it - and conflating them lets a search result borrow their
    authority."""
    # Asserted on the stored row rather than on the source text. This read
    # `assert 'basis="THIRD_PARTY_REPORT"' in src`, and the code stopped
    # spelling it that way when it learned to distinguish an edited figure:
    # once the analyst changes the number, THIRD_PARTY_REPORT is a false
    # attestation and the basis becomes INDUSTRY_KNOWLEDGE. The scan went red
    # for a refinement that strengthened exactly the thing it guards, and
    # could not have told the difference between that and the conflation this
    # test is named for. Both branches are checked now.
    import uuid

    from sqlalchemy import select

    from app import db
    from app.domain import known_facts

    case_id = str(uuid.uuid4())
    base = {"fact_class": "Location footprint", "subject": "Acme GmbH",
            "value_base": 120, "unit": "sites"}

    def _basis(proposal):
        out = known_facts.accept_public_proposal(
            session, case_id=case_id, proposal=proposal,
            accepted_by="Priya Raman")
        return session.execute(select(db.known_fact.c.basis).where(
            db.known_fact.c.known_fact_id == out["known_fact_id"])).scalar()

    assert _basis(dict(base)) == "THIRD_PARTY_REPORT"
    assert _basis(dict(base, subject="Acme SARL", edited=True)) == (
        "INDUSTRY_KNOWLEDGE"), (
        "an edited figure is the analyst's judgement informed by a source, "
        "and must not borrow the source's standing")


def test_the_sweep_covers_the_classes_that_bind_a_driver():
    from app.domain.known_facts import BINDABLE, PREFILL_CLASSES
    missing = sorted(set(BINDABLE) - set(PREFILL_CLASSES))
    assert not missing, (
        f"a fact class that binds an estimate driver is the most valuable to "
        f"prefill and is not swept: {missing}")


def test_a_schema_failure_is_not_reported_as_a_self_contradiction():
    """Observed in the field: an address string in a Decimal field was
    reported as CONTRADICTS_ITSELF, which sent the reader looking for an
    inconsistency in the model's reasoning. The reply never became a result at
    all; that is a different fact about a different thing."""
    import inspect
    from app.llm import gateway, quality
    assert hasattr(quality.Rejection, "SCHEMA_INVALID")
    src = inspect.getsource(gateway.structured_call)
    assert "quality.Rejection.SCHEMA_INVALID" in src
    assert "CONTRADICTS_ITSELF" not in src


def test_the_prefill_sweep_only_asks_for_quantities():
    """The register stores value_base, value_low and value_high and has no
    column for text. Sweeping a qualitative class put an HQ address into a
    Decimal and failed three attempts - the model found the right thing and
    had nowhere to put it."""
    from app.domain.known_facts import PREFILL_CLASSES
    qualitative = {"Current vendor and product signals",
                   "Current architecture hypothesis",
                   "Data centre and cloud posture",
                   "Vendor and partner signals",
                   "Resilience assumptions"}
    assert not (set(PREFILL_CLASSES) & qualitative), (
        "a class with no number has nowhere to land in this register")

    task = prompts.get("known_fact.prefill_public").task
    assert "NUMBER with a unit" in task
    assert "not_found" in task, (
        "the agent needs somewhere to report a class that yielded only a "
        "description, or it will force it into value_base again")


def test_every_swept_class_is_one_the_register_offers():
    """An accepted proposal must land under a class an analyst can also select
    by hand, or the register grows a vocabulary only the agent uses."""
    import pathlib
    from app.domain.known_facts import PREFILL_CLASSES
    root = pathlib.Path(__file__).resolve().parents[1]
    page = (root / "analyst_ui" / "streamlit_app" / "pages"
            / "2_Known_facts.py").read_text()
    for fact_class in PREFILL_CLASSES:
        assert f'"{fact_class}"' in page, f"{fact_class} is not offered on page 2"


def test_a_swept_fact_without_a_unit_is_rejected():
    from app.llm import quality, schemas
    unitless = schemas.PublicFactSweep.model_validate({"facts": [
        {"fact_class": "Location footprint", "subject": "HVB",
         "value_base": "371",
         "sources": [{"url": "https://example.com/ar"}]}]})
    v = quality.evaluate("known_fact.prefill_public", unitless, {})
    assert not v.accepted and quality.Rejection.QUANTITY_WITHOUT_UNIT in v.reasons


# ------------------------------------------------------ provenance contract
PROVENANCE_KEYS = {
    # identity - which instructions produced this
    "prompt_id", "prompt_version", "prompt_hash", "output_schema_version",
    "tool_policy_version",
    # the call itself
    "provider", "model", "provider_response_id", "stop_reason",
    # cost and latency, which interfaces display
    "input_tokens", "output_tokens", "latency_ms",
    # the gate history
    "attempts",
}


def test_structured_call_provenance_carries_what_callers_display():
    """The second time a changed return shape reached the browser as a
    KeyError. WP1 replaced the gateway return that carried input_tokens and
    latency_ms, and page 1 kept indexing the old shape - so a successful agent
    run rendered as a stack trace.

    Asserted against the source because building a real provenance dict needs
    a provider call. Crude, and it fails when a key is removed, which is the
    event that matters."""
    import inspect
    from app.llm import gateway

    src = inspect.getsource(gateway.structured_call)
    missing = sorted(k for k in PROVENANCE_KEYS if f'"{k}"' not in src)
    assert not missing, (
        f"provenance no longer carries {missing}; a caller displaying one of "
        f"those will raise KeyError")


def test_the_audit_row_and_the_provenance_agree_on_the_call():
    """Both describe the same call, so a figure shown in the interface and one
    stored for audit must not be able to disagree about which response it
    came from."""
    import inspect
    from app.llm import gateway
    src = inspect.getsource(gateway.execute)
    for key in ("provider_response_id", "provider_request_id", "input_tokens",
                "output_tokens", "latency_ms"):
        assert key in src, f"execute() no longer records {key}"


def test_the_prefill_sweep_files_facts_under_the_case_wording():
    """Otherwise a proposal filed under a trading name and a fact registered
    under the legal name are two facts about the same thing, and the duplicate
    check - which matches on subject - never sees the collision."""
    task = prompts.get("known_fact.prefill_public").task
    assert "exactly as it is given to you" in task
    assert "duplicate check" in task


# ------------------------------------------- the contract fits the service
def test_a_service_that_does_not_search_is_not_told_how_to_search():
    """One contract for all ten meant a narrating agent - one field, no
    sources, no search - was given several hundred words about provenance,
    search discipline and disagreement between sources.

    Attention spent reading that is attention not spent on the task, and
    instructions that cannot apply teach a model to skim the ones that do."""
    narrate = prompts.get("llm07.advisory.narrate")
    template = narrate.system_template
    assert "SEARCHING EFFICIENTLY" not in template
    assert "REPORT THE PROVENANCE" not in template
    # The parts that apply to everything must survive.
    for section in ("WHAT YOU MUST NOT DO", "UNTRUSTED CONTENT",
                    "NORMALISATION", "SUBJECT AND RIGHTS"):
        assert section in template, section


def test_a_searching_service_still_gets_the_research_contract():
    template = prompts.get("llm01.public_evidence.extract").system_template
    for section in ("REPORT THE PROVENANCE", "SEARCHING EFFICIENTLY",
                    "DISAGREEMENT IS A FINDING", "UNTRUSTED CONTENT"):
        assert section in template, section


def test_whether_a_service_cites_sources_is_read_from_its_schema():
    """A separate flag would be one more thing to forget; the schema knows."""
    assert prompts.get("known_fact.corroborate").cites_sources is True
    assert prompts.get("llm07.advisory.narrate").cites_sources is False
    assert prompts.get("entity.resolve.candidates").cites_sources is True


def test_the_shorter_contract_is_materially_shorter():
    narrate = len(prompts.get("llm07.advisory.narrate").system_template.split())
    research = len(prompts.get("llm01.public_evidence.extract")
                   .system_template.split())
    assert narrate < research * 0.75, (
        f"a non-searching service reads {narrate} words against {research} - "
        f"if the split saves nothing it is complexity for nothing")


def test_splitting_the_contract_moved_every_affected_prompt_hash():
    """The system template changed for all ten, so prompt_hash changed for all
    ten - and a stored finding is interpreted against the version recorded
    beside it."""
    for definition in prompts.PROMPTS.values():
        assert definition.prompt_hash, definition.prompt_id
    assert prompts.validate_registry() == []


def test_the_sweep_must_account_for_every_class_it_was_asked_about():
    """Boots has around 1,800 UK stores stated on its own website. The sweep
    returned an empty facts list with two of five classes in not_found, so
    three were silently omitted - and the interface reported "no public figures
    found" for all five.

    A class the model did not mention is not a class where nothing exists.
    Those are different findings and they were indistinguishable."""
    from app.llm import quality, schemas

    # No "subject" here: PublicFactSweep is Strict and carries none - the
    # subject lives on each fact. The sweep gained that strictness and the
    # fixtures kept the old shape.
    reply = schemas.PublicFactSweep.model_validate({
        "facts": [],
        # not_found carries the class, what was searched and why. It was
        # list[str] while the prompt asked for the class "with what you
        # searched for" - two things one string cannot hold - so the agent
        # returned an empty object rather than an unsatisfiable shape.
        "not_found": [{"fact_class": "Remote-user population",
                       "searched_for": "remote headcount, work-from-home share",
                       "reason": "no public source isolates this from total "
                                 "headcount"}],
    })
    verdict = quality.evaluate(
        "known_fact.prefill_public", reply,
        {"fact_classes": ["Location footprint", "Remote-user population",
                          "Public cost evidence"]})
    assert not verdict.accepted
    assert quality.Rejection.INCOMPLETE_COVERAGE in verdict.reasons
    assert "Location footprint" in " ".join(verdict.detail)


def test_a_sweep_that_accounts_for_everything_is_accepted():
    from app.llm import quality, schemas

    # No "subject" here: PublicFactSweep is Strict and carries none - the
    # subject lives on each fact. The sweep gained that strictness and the
    # fixtures kept the old shape.
    reply = schemas.PublicFactSweep.model_validate({
        "facts": [{"fact_class": "Location footprint", "subject": "Boots",
                   "value_base": "1800", "unit": "sites",
                   "sources": [{"url": "https://boots-uk.example/about",
                                "publisher": "Boots UK"}]}],
        "not_found": [{"fact_class": "Remote-user population",
                       "reason": "no public source isolates this"}],
    })
    assert quality.evaluate(
        "known_fact.prefill_public", reply,
        {"fact_classes": ["Location footprint",
                          "Remote-user population"]}).accepted


def test_the_prompt_states_the_coverage_requirement():
    """The gate refuses on it, so the instruction has to say it - a rejection
    for a rule the prompt never stated is a retry that cannot succeed."""
    task = prompts.get("known_fact.prefill_public").task
    assert "Answer for every fact class" in task
    assert "stronger claim" in task
    # and it must name the fields the schema actually has, or the instruction
    # is unsatisfiable and the agent returns nothing rather than a shape it
    # cannot build
    assert "searched_for" in task and "reason" in task


def test_a_prompt_only_names_fields_its_schema_declares():
    """The defect twice over, and the second time it cost three attempts and
    an empty reply.

    The base contract asked every source for `source_class` while
    QuantityCandidate forbade extras - 26 validation errors for a correct
    reply. Then the sweep prompt asked for the class "with what you searched
    for" in a `not_found` declared list[str], which cannot hold both, and the
    agent returned an empty object rather than an unsatisfiable shape.

    Asking for a field the schema has no room for is the worst kind of
    instruction: the model is right to fail it and the failure looks like
    incompetence.
    """
    import ast
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "llm").exists())

    declared = set()
    for cls in ast.parse((app / "llm" / "schemas.py").read_text()).body:
        if isinstance(cls, ast.ClassDef):
            declared |= {n.target.id for n in cls.body
                         if isinstance(n, ast.AnnAssign)
                         and isinstance(n.target, ast.Name)}
    assert declared, "no schema fields found - the sweep is not seeing them"

    offenders = []
    for definition in prompts.PROMPTS.values():
        for name in set(re.findall(r"`(\w+)`", definition.task)):
            # Only names that look like fields: lowercase with an underscore,
            # or a known field name. A backticked ENUM value is not a field.
            if not (name.islower() and ("_" in name or name in declared)):
                continue
            if name not in declared:
                offenders.append(
                    f"{definition.prompt_id} asks for `{name}`, which no "
                    f"schema declares")
    assert not offenders, "\n".join(sorted(set(offenders)))


def test_the_sweep_asks_about_one_class_per_call():
    """A single call asking about five classes, each with a figure, a unit and
    its sources, and each triggering searches, ran past 8,000 output tokens and
    was cut off - so the whole sweep failed and nothing came back for any
    class. Raising the budget again just moves the cliff.

    Research already works this way: seventeen domains, one call each. The same
    reasons apply - a class that fails costs only itself, each reply is small
    enough that truncation is not a live risk, and the coverage gate becomes
    trivially satisfiable because each call is asked about exactly one thing."""
    import ast
    import inspect
    import textwrap

    from app.domain import known_facts

    src = inspect.getsource(known_facts.prefill_from_public)
    # dedent, not cleandoc - the third instance of this, after test_migrations
    # and test_footprint_resolution, both of which carry the same note.
    # cleandoc strips the indent common to every line AFTER the first, so a
    # function's source comes back with `def` at column 0 and its body
    # de-indented to meet it: an IndentationError before a single call site is
    # examined. dedent is a no-op on source that is already flush.
    tree = ast.parse(textwrap.dedent(src))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "structured_call"]
    assert len(calls) == 1, "one call site, inside the per-class loop"
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
             and "fact_class" in ast.unparse(n.target)]
    assert loops, "the call must sit inside a loop over the fact classes"
    assert any(call in ast.walk(loop) for loop in loops for call in calls)
    # and each call is told about exactly one class
    assert 'gate_context={"fact_classes": [fact_class]}' in src


def test_one_class_failing_does_not_lose_the_others():
    """The whole sweep used to be lost to whichever class was hardest."""
    import inspect

    from app.domain import known_facts

    src = inspect.getsource(known_facts.prefill_from_public)
    assert "failed.append(" in src
    assert "continue" in src, "a failed class must not abort the loop"
    assert '"failed": failed' in src, "and must be reported to the analyst"


def test_the_sweep_budget_is_governed():
    """Discovering the right number should not need a rebuild.

    ResearchPolicy, not ResearchBudgetProfile. No class of the latter name has
    ever existed here, and both this test and known_facts._sweep_budget named
    it - the call sat inside `except Exception: return 6000`, so the governed
    budget was the hardcoded fallback on every sweep ever run, and this test
    reported the symptom without anyone reading it as one.
    """
    from app.domain import policy

    assert hasattr(policy.ResearchPolicy, "max_output_tokens_per_sweep_call")


def test_the_sweep_budget_actually_reaches_the_sweep():
    """hasattr is not enough: the field existed all along, on a class nothing
    called. What was missing is the path from the governed row to the call."""
    import inspect

    from app.domain import known_facts

    src = inspect.getsource(known_facts._sweep_budget)
    assert "policy_module.ResearchPolicy.from_rows" in src
    assert "policy_module.ResearchBudgetProfile" not in src, (
        "a name that does not exist, inside `except Exception`, is a governed "
        "value that silently is not one")


def test_a_governed_sweep_budget_overrides_the_default(session):
    """The property the whole governance claim rests on: change the row,
    change the budget.

    It could not have held while the lookup named a class that does not
    exist - every sweep took the hardcoded 6000 from the except branch, and
    because the seeded value is also 6000 the two were indistinguishable from
    the outside. Raising it is the only way to tell them apart.
    """
    from sqlalchemy import insert, update

    from app import db, seed
    from app.domain import known_facts

    # The whole profile: ResearchPolicy.from_rows requires every field, so a
    # partial set raises and falls back - which is the behaviour under test.
    session.execute(insert(db.threshold).values([
        {"set_name": s, "key": k, "value": v, "version": 1,
         "approved_by": "seed", "note": ""}
        for s, k, v in seed.THRESHOLDS if s == "research_budget_profile"]))
    session.commit()
    assert known_facts._sweep_budget(session) == 6000, "the seeded value"

    session.execute(update(db.threshold)
                    .where(db.threshold.c.set_name == "research_budget_profile")
                    .where(db.threshold.c.key == "max_output_tokens_per_sweep_call")
                    .values(value="9000", approved_by="CB"))
    session.commit()

    assert known_facts._sweep_budget(session) == 9000, (
        "an approver raising the governed number must change the budget, or "
        "the row is decoration and the docstring's 'governed output budget' "
        "is not true")
