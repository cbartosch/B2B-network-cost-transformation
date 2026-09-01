"""Tests for the stage model and V1 questionnaire (Tranche 3, first slice).

Same provider-adapter mocking as test_research.py and test_savings_advisory.py,
for the same reason: gateway.execute()'s real liveness/llm_run/idempotency
behaviour has to run for succeed()'s checks to behave as they do in production.

Not executed here - no SQLAlchemy in the environment this was written in.
Traced by hand; `make test` is the first real signal.
"""
import itertools
import json
from dataclasses import replace
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, select, update

from app import db
from app.domain import dispositions, questionnaire, stage
from app.llm.providers.base import ProviderCall

_response_ids = (f"msg_t3_{i}" for i in itertools.count())


def _case(session, *, stage_value=None) -> str:
    case_id = str(uuid.uuid4())
    values = {"case_id": case_id, "created_by": "test",
              "subject_entity_legal_name": "Acme Global Logistics",
              "resolved_entity_id": str(uuid.uuid4()),
              "entity_confirmed_by": "Jane Okafor"}
    if stage_value is not None:
        values["stage"] = stage_value
    session.execute(insert(db.case).values(**values))
    session.commit()
    return case_id


def _dispose_all(session, case_id, disposition="BENCHMARK_PRIOR"):
    """Every one of the 24 domains, so the disposition condition passes."""
    session.execute(insert(db.domain_disposition), [
        {"id": str(uuid.uuid4()), "case_id": case_id, "estimate_snapshot_id": None,
         "domain_no": no, "domain_name": name, "disposition": disposition,
         "reason": None} for no, name in dispositions.DOMAINS])
    session.commit()


def _snapshot(session, case_id, v0_status="COMPLETE") -> str:
    snap_id = str(uuid.uuid4())
    session.execute(insert(db.estimate_snapshot).values(
        estimate_snapshot_id=snap_id, case_id=case_id, version_label="V0",
        v0_status=v0_status, current_tco={"total": {"base": "1000000"}},
        target_tco={}, scenarios={}, gross_run_rate_savings={}, confidence={},
        coverage={}, simulated_share=0.05, asserted_share=0.0, pins={}, levers=[]))
    session.commit()
    return snap_id


def _answer_everything(session, case_id, who="Client Contact"):
    questionnaire.create(session, case_id=case_id)
    for key, _, _ in questionnaire.QUESTIONS:
        questionnaire.answer(session, case_id=case_id, question_key=key,
                             answer_value="an answer", answered_by=who)


def _ready_case(session) -> str:
    """A case that passes every V1 readiness condition.

    map_answers() is part of being ready, not an optional extra: an answer that
    never reached the disposition contract changed nothing, which is not what
    "the questionnaire is complete" implies. Adding the Answer-mapping
    condition to the gate broke this fixture until this line was added - which
    is the correct direction for a gate to break a fixture in.
    """
    case_id = _case(session)
    _dispose_all(session, case_id)
    _snapshot(session, case_id)
    _answer_everything(session, case_id)
    questionnaire.map_answers(session, case_id=case_id, mapped_by="Jane Okafor")
    return case_id


class _FakeAdapter:
    def __init__(self, text_fn, configured=True):
        self._text_fn, self._configured = text_fn, configured

    def configured(self):
        return self._configured

    def complete(self, *, system, prompt, max_tokens=1500):
        now = datetime.now(timezone.utc)
        return ProviderCall(
            provider="anthropic", model="fake-model",
            text=self._text_fn(system=system, prompt=prompt, max_tokens=max_tokens),
            provider_response_id=next(_response_ids),
            provider_request_id=str(uuid.uuid4()),
            provider_request_at=now, input_tokens=50, output_tokens=50,
            local_request_at=now, latency_ms=10, http_status=200,
            egress_proxy=None, raw={})

    def parse(self, *, system, prompt, schema, schema_name,
              max_tokens=4000, tools=None) -> ProviderCall:
        """The schema-enforced channel WP1 added to the provider protocol.

        Every fake was left with complete() only, so 34 tests died with
        "'_FakeAdapter' object has no attribute 'parse'" - the CR's WP0
        predicted exactly this and it was never done. The fake returns the same
        text its complete() would and parses it as the provider's structured
        channel does, so what the test author wrote as a response still drives
        the assertion.
        """
        call = self.complete(system=system, prompt=prompt,
                            max_tokens=max_tokens, tools=tools)
        try:
            parsed = json.loads(call.text)
        except ValueError:
            parsed = None
        return replace(call, parsed=parsed)


def _wire_fake_provider(monkeypatch, text_fn, *, configured=True):
    fake = _FakeAdapter(text_fn, configured=configured)
    monkeypatch.setattr(questionnaire.gateway, "_adapters",
                        lambda: {"anthropic": fake, "openai": fake})
    return fake


# --------------------------------------------------------------- stage basics

def test_a_case_with_no_stage_column_value_reads_as_v0(session):
    """Migration v13 adds the column without backfilling the default, so an
    existing row reads NULL - and a pre-stage-model case is at V0, not at
    'unknown'."""
    case_id = _case(session)
    session.execute(update(db.case).where(db.case.c.case_id == case_id)
                    .values(stage=None))
    session.commit()
    row = session.execute(select(db.case).where(db.case.c.case_id == case_id)).one()
    assert stage.current_stage(row) == "V0"


def test_only_v1_can_be_assessed_in_this_build(session):
    case_id = _case(session)
    with pytest.raises(ValueError, match="V2"):
        stage.assess(session, case_id=case_id, target_stage="V2")


def test_predecessor_refuses_v0_rather_than_wrapping_to_v5():
    """A bare STAGES[-1] would return 'V5' and read as a plausible answer."""
    with pytest.raises(ValueError):
        stage._predecessor("V0")


def test_assess_raises_lookup_error_for_an_unknown_case(session):
    with pytest.raises(LookupError):
        stage.assess(session, case_id="no-such-case")


# --------------------------------------------------------------- gate conditions

def test_a_bare_case_is_blocked_on_every_substantive_condition(session):
    case_id = _case(session)
    report = stage.assess(session, case_id=case_id)

    assert report["blocked"] is True
    blocked_items = {c["item"] for c in report["blocks"]}
    assert "V0 estimate" in blocked_items
    assert "Domain dispositions" in blocked_items
    assert "V1 questionnaire" in blocked_items


def test_a_refused_v0_estimate_blocks_advancement(session):
    case_id = _case(session)
    _dispose_all(session, case_id)
    _snapshot(session, case_id, v0_status="REFUSED")
    _answer_everything(session, case_id)

    report = stage.assess(session, case_id=case_id)
    assert report["blocked"] is True
    assert any(c["item"] == "V0 estimate" for c in report["blocks"])


def test_an_unanswered_questionnaire_blocks_advancement(session):
    case_id = _case(session)
    _dispose_all(session, case_id)
    _snapshot(session, case_id)
    questionnaire.create(session, case_id=case_id)   # created, not answered

    report = stage.assess(session, case_id=case_id)
    assert any(c["item"] == "V1 questionnaire" for c in report["blocks"])


def test_a_prefilled_but_unanswered_questionnaire_still_blocks(session, monkeypatch):
    """The distinction the whole slice rests on: a prefill is a suggestion,
    not an answer. A fully prefilled questionnaire that no client has
    returned is, correctly, zero answers."""
    case_id = _case(session)
    _dispose_all(session, case_id)
    _snapshot(session, case_id)
    questionnaire.create(session, case_id=case_id)
    _wire_fake_provider(monkeypatch, lambda **kw: json.dumps(
        {"prefill_value": "122 sites", "basis": "from public evidence"}))
    questionnaire.prefill(session, case_id=case_id, mode="LIVE")

    report = stage.assess(session, case_id=case_id)
    assert any(c["item"] == "V1 questionnaire" for c in report["blocks"]), (
        "a prefill must never count as an answer")


def test_an_unattributed_answer_blocks_advancement(session):
    case_id = _case(session)
    _dispose_all(session, case_id)
    _snapshot(session, case_id)
    questionnaire.create(session, case_id=case_id)
    # Write directly, bypassing answer()'s own validation, to prove the gate
    # catches it independently rather than relying on the writer.
    session.execute(update(db.questionnaire_item)
                    .where(db.questionnaire_item.c.case_id == case_id)
                    .values(answer_value="an answer", answered_by=None))
    session.commit()

    report = stage.assess(session, case_id=case_id)
    assert any(c["item"] == "V1 questionnaire" for c in report["blocks"])


def test_a_fully_ready_case_is_not_blocked(session):
    case_id = _ready_case(session)
    report = stage.assess(session, case_id=case_id)
    assert report["blocked"] is False, report["blocks"]
    # The stage-aware-confidence limitation is still reported, as a WARN.
    assert any(c["item"] == "Stage-aware confidence" for c in report["warns"])


# --------------------------------------------------------------- advance()

def test_advance_refuses_without_a_readiness_report(session):
    case_id = _ready_case(session)
    with pytest.raises(PermissionError, match="no stage-readiness report"):
        stage.advance(session, case_id=case_id, advanced_by="Jane Okafor")


def test_advance_refuses_while_a_block_is_open(session):
    case_id = _case(session)          # blocked on everything
    stage.assess(session, case_id=case_id)
    with pytest.raises(PermissionError, match="BLOCK"):
        stage.advance(session, case_id=case_id, advanced_by="Jane Okafor")


def test_advance_refuses_an_unacknowledged_report(session):
    case_id = _ready_case(session)
    stage.assess(session, case_id=case_id)
    with pytest.raises(PermissionError, match="acknowledged"):
        stage.advance(session, case_id=case_id, advanced_by="Jane Okafor")


def test_advance_requires_a_named_person(session):
    case_id = _ready_case(session)
    report = stage.assess(session, case_id=case_id)
    stage.acknowledge(session, report_id=report["report_id"],
                      acknowledged_by="Jane Okafor")
    with pytest.raises(ValueError):
        stage.advance(session, case_id=case_id, advanced_by="   ")


def test_a_clean_acknowledged_report_advances_the_case(session):
    case_id = _ready_case(session)
    report = stage.assess(session, case_id=case_id)
    stage.acknowledge(session, report_id=report["report_id"],
                      acknowledged_by="Jane Okafor")

    result = stage.advance(session, case_id=case_id, advanced_by="Sam Patel")
    assert result["stage"] == "V1"
    assert result["advanced_from"] == "V0"
    assert result["advanced_by"] == "Sam Patel"

    row = session.execute(select(db.case).where(db.case.c.case_id == case_id)).one()
    assert stage.current_stage(row) == "V1"
    assert row.stage_advanced_by == "Sam Patel"


def test_a_case_cannot_be_advanced_to_v1_twice(session):
    case_id = _ready_case(session)
    report = stage.assess(session, case_id=case_id)
    stage.acknowledge(session, report_id=report["report_id"],
                      acknowledged_by="Jane Okafor")
    stage.advance(session, case_id=case_id, advanced_by="Sam Patel")

    # The old report is still acknowledged and unblocked, but the case has
    # moved - advance() re-checks the live stage rather than trusting it.
    with pytest.raises(PermissionError, match="stale"):
        stage.advance(session, case_id=case_id, advanced_by="Sam Patel")


def test_reassessing_an_already_advanced_case_blocks_on_current_stage(session):
    case_id = _ready_case(session)
    report = stage.assess(session, case_id=case_id)
    stage.acknowledge(session, report_id=report["report_id"],
                      acknowledged_by="Jane Okafor")
    stage.advance(session, case_id=case_id, advanced_by="Sam Patel")

    again = stage.assess(session, case_id=case_id)
    assert again["blocked"] is True
    assert any(c["item"] == "Current stage" for c in again["blocks"])


# --------------------------------------------------------------- questionnaire

def test_create_is_idempotent_and_never_destroys_an_answer(session):
    case_id = _case(session)
    first = questionnaire.create(session, case_id=case_id)
    assert first["created"] == len(questionnaire.QUESTIONS)

    questionnaire.answer(session, case_id=case_id,
                         question_key=questionnaire.QUESTIONS[0][0],
                         answer_value="122 sites", answered_by="Client Contact")

    second = questionnaire.create(session, case_id=case_id)
    assert second["created"] == 0
    loaded = questionnaire.load(session, case_id)
    answered = [i for i in loaded["items"] if i["answer_value"]]
    assert len(answered) == 1
    assert answered[0]["answer_value"] == "122 sites", (
        "re-running create must not delete a client's answer")


def test_answer_rejects_an_unattributed_or_empty_response(session):
    case_id = _case(session)
    questionnaire.create(session, case_id=case_id)
    key = questionnaire.QUESTIONS[0][0]

    with pytest.raises(ValueError, match="answered_by"):
        questionnaire.answer(session, case_id=case_id, question_key=key,
                             answer_value="x", answered_by="  ")
    with pytest.raises(ValueError, match="answer_value"):
        questionnaire.answer(session, case_id=case_id, question_key=key,
                             answer_value="   ", answered_by="Client Contact")


def test_answer_rejects_an_unknown_question_key(session):
    case_id = _case(session)
    questionnaire.create(session, case_id=case_id)
    with pytest.raises(ValueError, match="unknown question_key"):
        questionnaire.answer(session, case_id=case_id, question_key="not_a_question",
                             answer_value="x", answered_by="Client Contact")


def test_every_question_maps_to_a_real_input_domain():
    real = {no for no, _ in dispositions.DOMAINS}
    assert {d for _, _, d in questionnaire.QUESTIONS} <= real


# --------------------------------------------------------------- prefill

def test_prefill_never_overwrites_a_client_answer(session, monkeypatch):
    case_id = _case(session)
    questionnaire.create(session, case_id=case_id)
    key = questionnaire.QUESTIONS[0][0]
    questionnaire.answer(session, case_id=case_id, question_key=key,
                         answer_value="the client's own answer",
                         answered_by="Client Contact")

    _wire_fake_provider(monkeypatch, lambda **kw: json.dumps(
        {"prefill_value": "a model's guess", "basis": "b"}))
    result = questionnaire.prefill(session, case_id=case_id, mode="LIVE",
                                   overwrite=True)   # even with overwrite

    skipped = [r for r in result["results"] if r["question_key"] == key]
    assert skipped and "already answered" in skipped[0]["skipped"]
    loaded = questionnaire.load(session, case_id)
    item = next(i for i in loaded["items"] if i["question_key"] == key)
    assert item["answer_value"] == "the client's own answer"


def test_prefill_labels_live_output_llm_proposed(session, monkeypatch):
    case_id = _case(session)
    questionnaire.create(session, case_id=case_id)
    _wire_fake_provider(monkeypatch, lambda **kw: json.dumps(
        {"prefill_value": "122 sites", "basis": "from the evidence"}))

    questionnaire.prefill(session, case_id=case_id, mode="LIVE")
    loaded = questionnaire.load(session, case_id)
    assert all(i["prefill_label"] == "LLM_PROPOSED" for i in loaded["items"])
    assert all(i["prefill_agent_run_id"] for i in loaded["items"])


def test_deterministic_prefill_proposes_no_value_and_creates_no_agent_run(session):
    """LLM-02 is registered LIVE-only, so the deterministic path must not go
    through the gateway at all - and it proposes nothing it cannot source."""
    case_id = _case(session)
    questionnaire.create(session, case_id=case_id)

    result = questionnaire.prefill(session, case_id=case_id, mode="DETERMINISTIC_ONLY")

    assert all(r.get("prefill_value") is None for r in result["results"])
    loaded = questionnaire.load(session, case_id)
    assert all(i["prefill_label"] == "DETERMINISTIC_PROPOSED" for i in loaded["items"])
    assert all(i["prefill_agent_run_id"] is None for i in loaded["items"])
    runs = session.execute(select(db.agent_run).where(
        db.agent_run.c.case_id == case_id)).all()
    assert runs == []


def test_prefill_only_draws_on_public_evidence_not_benchmark_priors(session):
    """Feeding a BENCHMARK_PRIOR back as a suggested answer would invite the
    client to confirm the system's own assumption, which would then read as
    client-confirmed data."""
    case_id = _case(session)
    _dispose_all(session, case_id, disposition="BENCHMARK_PRIOR")
    assert questionnaire._evidence_for_domain(session, case_id, 2) is None

    session.execute(update(db.domain_disposition)
                    .where(db.domain_disposition.c.case_id == case_id,
                           db.domain_disposition.c.domain_no == 2)
                    .values(disposition="EVIDENCED_PUBLIC",
                            evidence={"sources": [{"url": "https://example.com/1"}]}))
    session.commit()
    found = questionnaire._evidence_for_domain(session, case_id, 2)
    assert found and found["disposition"] == "EVIDENCED_PUBLIC"


def test_a_failed_prefill_call_terminates_its_run_and_writes_no_prefill(
        session, monkeypatch):
    case_id = _case(session)
    questionnaire.create(session, case_id=case_id)
    _wire_fake_provider(monkeypatch, lambda **kw: "{}", configured=False)

    result = questionnaire.prefill(session, case_id=case_id, mode="LIVE")

    assert result["failed"] == len(questionnaire.QUESTIONS)
    loaded = questionnaire.load(session, case_id)
    assert all(i["prefill_value"] is None for i in loaded["items"])
    runs = session.execute(select(db.agent_run).where(
        db.agent_run.c.case_id == case_id)).all()
    assert runs and all(r.status == "FAILED" for r in runs), (
        "every agent_run this created must reach a terminal state")


def test_malformed_prefill_output_terminates_its_run(session, monkeypatch):
    case_id = _case(session)
    questionnaire.create(session, case_id=case_id)
    _wire_fake_provider(monkeypatch, lambda **kw: json.dumps({"wrong": "shape"}))

    result = questionnaire.prefill(session, case_id=case_id, mode="LIVE")

    assert result["failed"] > 0
    runs = session.execute(select(db.agent_run).where(
        db.agent_run.c.case_id == case_id)).all()
    assert runs and all(r.status == "FAILED" for r in runs)


def test_prefill_raises_lookup_error_when_no_questionnaire_exists(session):
    case_id = _case(session)
    with pytest.raises(LookupError):
        questionnaire.prefill(session, case_id=case_id, mode="DETERMINISTIC_ONLY")


# --------------------------------------------------------------- idempotency scoping

def test_a_second_prefill_run_is_not_refused_as_an_already_completed_run(
        session, monkeypatch):
    """The bug this test exists for, found in Tranche 3 and present in all
    three tranches: idempotency keys were stable across separate invocations,
    so create_agent_run returned the *previous* run and execute() then refused
    it with "a completed run cannot be re-executed". Every deliberate re-run -
    research with overwrite=True, a second recommendation, a re-prefill - was
    permanently broken. Keys are now scoped per invocation unless the caller
    supplies one."""
    case_id = _case(session)
    questionnaire.create(session, case_id=case_id)
    _wire_fake_provider(monkeypatch, lambda **kw: json.dumps(
        {"prefill_value": "first pass", "basis": "b"}))

    first = questionnaire.prefill(session, case_id=case_id, mode="LIVE")
    assert first["failed"] == 0

    second = questionnaire.prefill(session, case_id=case_id, mode="LIVE",
                                   overwrite=True)
    assert second["failed"] == 0, (
        "a deliberate re-run must create fresh agent runs, not collide with "
        "the previous invocation's idempotency keys")

    runs = session.execute(select(db.agent_run).where(
        db.agent_run.c.case_id == case_id)).all()
    assert len(runs) == 2 * len(questionnaire.QUESTIONS)


def test_a_supplied_idempotency_key_still_collapses_a_repeat_submission(
        session, monkeypatch):
    """The other half of the contract: a caller who *wants* double-submit
    protection passes a key, and the repeat returns the original runs rather
    than spending twice at the provider."""
    case_id = _case(session)
    questionnaire.create(session, case_id=case_id)
    _wire_fake_provider(monkeypatch, lambda **kw: json.dumps(
        {"prefill_value": "v", "basis": "b"}))

    questionnaire.prefill(session, case_id=case_id, mode="LIVE",
                          idempotency_key="fixed-scope")
    before = session.execute(select(db.agent_run).where(
        db.agent_run.c.case_id == case_id)).all()

    # Same key, overwrite=True so the items are eligible again. The runs are
    # reused, so execute() refuses them - which is correct: this *is* the
    # same request, and it already happened.
    questionnaire.prefill(session, case_id=case_id, mode="LIVE",
                          idempotency_key="fixed-scope", overwrite=True)
    after = session.execute(select(db.agent_run).where(
        db.agent_run.c.case_id == case_id)).all()
    assert len(after) == len(before), (
        "a repeat submission under the same idempotency key must not create "
        "new runs or duplicate provider spend")


# --------------------------------------------------------------- evidence mapping

def test_client_answers_upgrade_a_benchmark_prior_domain(session):
    """A benchmark prior is the model's own default. First-party client data
    about their own estate beats it."""
    case_id = _case(session)
    _dispose_all(session, case_id, disposition="BENCHMARK_PRIOR")
    _answer_everything(session, case_id)

    result = questionnaire.map_answers(session, case_id=case_id,
                                       mapped_by="Jane Okafor")
    assert result["upgraded"] == len(questionnaire.QUESTIONS)
    assert result["requiring_adjudication"] == 0

    mapped_domains = {d for _, _, d in questionnaire.QUESTIONS}
    rows = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id)).all()
    for r in rows:
        if r.domain_no in mapped_domains:
            assert r.disposition == "CLIENT_CONFIRMED"
            assert r.evidence["answered_by"] == "Client Contact"
        else:
            assert r.disposition == "BENCHMARK_PRIOR", (
                "a domain with no question must be left alone")


def test_a_client_answer_never_silently_overwrites_public_evidence(session):
    """The load-bearing rule. Two independent sources disagreeing is
    information; letting whichever arrived last win would discard it."""
    case_id = _case(session)
    _dispose_all(session, case_id, disposition="EVIDENCED_PUBLIC")
    _answer_everything(session, case_id)

    result = questionnaire.map_answers(session, case_id=case_id,
                                       mapped_by="Jane Okafor")
    assert result["upgraded"] == 0
    assert result["requiring_adjudication"] == len(questionnaire.QUESTIONS)

    rows = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id)).all()
    assert all(r.disposition == "EVIDENCED_PUBLIC" for r in rows), (
        "public evidence must survive an unadjudicated client answer")


def test_a_simulated_domain_is_refused_not_overwritten(session):
    """Replacing a simulated quantity here would change the 0.6A simulated
    share without the simulation being re-run."""
    case_id = _case(session)
    _dispose_all(session, case_id, disposition="SIMULATED")
    _answer_everything(session, case_id)

    result = questionnaire.map_answers(session, case_id=case_id,
                                       mapped_by="Jane Okafor")
    assert result["upgraded"] == 0
    assert all(r["mapping_state"] == "REFUSED_SIMULATED" for r in result["results"])
    rows = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id)).all()
    assert all(r.disposition == "SIMULATED" for r in rows)


def test_map_answers_requires_a_named_person(session):
    case_id = _case(session)
    _answer_everything(session, case_id)
    with pytest.raises(ValueError, match="mapped_by"):
        questionnaire.map_answers(session, case_id=case_id, mapped_by="   ")


def test_superseding_public_evidence_requires_a_stated_reason(session):
    case_id = _case(session)
    _dispose_all(session, case_id, disposition="EVIDENCED_PUBLIC")
    _answer_everything(session, case_id)
    questionnaire.map_answers(session, case_id=case_id, mapped_by="Jane Okafor")
    key = questionnaire.QUESTIONS[0][0]

    with pytest.raises(ValueError, match="stated reason"):
        questionnaire.resolve_mapping(
            session, case_id=case_id, question_key=key,
            resolution="CLIENT_SUPERSEDES_PUBLIC", resolved_by="Jane Okafor",
            note="")


def test_supersede_rewrites_the_disposition_agreement_does_not(session):
    case_id = _case(session)
    _dispose_all(session, case_id, disposition="EVIDENCED_PUBLIC")
    _answer_everything(session, case_id)
    questionnaire.map_answers(session, case_id=case_id, mapped_by="Jane Okafor")
    k_supersede, k_agree = (questionnaire.QUESTIONS[0][0],
                            questionnaire.QUESTIONS[1][0])
    d_supersede, d_agree = (questionnaire.QUESTIONS[0][2],
                            questionnaire.QUESTIONS[1][2])

    questionnaire.resolve_mapping(
        session, case_id=case_id, question_key=k_supersede,
        resolution="CLIENT_SUPERSEDES_PUBLIC", resolved_by="Jane Okafor",
        note="the published filing predates the 2026 estate consolidation")
    questionnaire.resolve_mapping(
        session, case_id=case_id, question_key=k_agree,
        resolution="CLIENT_AGREES_WITH_PUBLIC", resolved_by="Jane Okafor")

    def _disp(domain_no):
        return session.execute(select(db.domain_disposition.c.disposition).where(
            db.domain_disposition.c.case_id == case_id,
            db.domain_disposition.c.domain_no == domain_no)).one().disposition

    assert _disp(d_supersede) == "CLIENT_CONFIRMED"
    assert _disp(d_agree) == "EVIDENCED_PUBLIC", (
        "two sources agreeing does not make either of them more public")


def test_an_unadjudicated_conflict_blocks_the_stage_gate(session):
    case_id = _case(session)
    _dispose_all(session, case_id, disposition="EVIDENCED_PUBLIC")
    _snapshot(session, case_id)
    _answer_everything(session, case_id)
    questionnaire.map_answers(session, case_id=case_id, mapped_by="Jane Okafor")

    report = stage.assess(session, case_id=case_id)
    assert any(c["item"] == "Client/public reconciliation" for c in report["blocks"])


def test_a_standing_contradiction_still_blocks_after_adjudication(session):
    """Adjudicating a disagreement as real does not make it go away."""
    case_id = _case(session)
    _dispose_all(session, case_id, disposition="EVIDENCED_PUBLIC")
    _snapshot(session, case_id)
    _answer_everything(session, case_id)
    questionnaire.map_answers(session, case_id=case_id, mapped_by="Jane Okafor")
    for key, _, _ in questionnaire.QUESTIONS:
        questionnaire.resolve_mapping(
            session, case_id=case_id, question_key=key,
            resolution="CLIENT_CONTRADICTS_PUBLIC", resolved_by="Jane Okafor",
            note="client disputes the filed figure")

    report = stage.assess(session, case_id=case_id)
    assert any(c["item"] == "Client/public reconciliation" for c in report["blocks"])


def test_unmapped_answers_block_the_stage_gate(session):
    """An answer that never reached the disposition contract changed nothing."""
    case_id = _case(session)
    _dispose_all(session, case_id)
    _snapshot(session, case_id)
    _answer_everything(session, case_id)      # answered, deliberately not mapped

    report = stage.assess(session, case_id=case_id)
    assert any(c["item"] == "Answer mapping" for c in report["blocks"])


def test_resolve_refuses_an_item_that_needs_no_adjudication(session):
    case_id = _case(session)
    _dispose_all(session, case_id, disposition="BENCHMARK_PRIOR")
    _answer_everything(session, case_id)
    questionnaire.map_answers(session, case_id=case_id, mapped_by="Jane Okafor")
    with pytest.raises(ValueError, match="nothing to adjudicate"):
        questionnaire.resolve_mapping(
            session, case_id=case_id, question_key=questionnaire.QUESTIONS[0][0],
            resolution="CLIENT_AGREES_WITH_PUBLIC", resolved_by="Jane Okafor")


# --------------------------------------------------------------- CLIENT_CONFIRMED placement

def test_client_confirmed_is_a_real_disposition_the_contract_accepts():
    recs = [{"domain_no": n, "disposition": "CLIENT_CONFIRMED"}
            for n, _ in dispositions.DOMAINS]
    assert dispositions.validate(recs) == []
    assert dispositions.summarise(recs)["declared_unknown"] == 0


def test_client_confirmed_does_not_trigger_the_asserted_ceiling(session):
    """The 0.6A asserted ceiling penalises leaning on an unverified *analyst*
    claim. A client's statement about their own estate is not that, and is
    discounted through the evidenced driver instead."""
    from app.domain import estimate
    comps = [estimate.Component(
        key="k", layer="L0", driver="sites", quantity=1,
        quantity_origin=estimate.CLIENT_CONFIRMED,
        unit_cost_origin="BENCHMARK_PRIOR",
        value=estimate.Range("100", "100", "100"))]
    assert float(estimate.asserted_share(comps)) == 0.0
    assert float(estimate.client_confirmed_share(comps)) == 1.0


# --------------------------------------------------------------- provenance preservation

def test_saving_dispositions_manually_does_not_destroy_provenance(session):
    """Found in audit. PUT .../domain-dispositions was a delete-and-reinsert
    that only wrote the six columns it knew about, so every save nulled
    `evidence` and `agent_run_id` for all 24 domains. Changing one dropdown
    destroyed every research source fragment and every client answer, while
    the disposition label survived - leaving EVIDENCED_PUBLIC rows with
    nothing behind them.

    Exercised through the domain layer the route now uses, so the behaviour is
    pinned even if the route is refactored again.
    """
    from app.routers.api import set_dispositions
    from app.routers.api import DispositionIn

    case_id = _case(session)
    run_id = str(uuid.uuid4())
    session.execute(insert(db.domain_disposition), [
        {"id": str(uuid.uuid4()), "case_id": case_id, "estimate_snapshot_id": None,
         "domain_no": no, "domain_name": name,
         "disposition": "EVIDENCED_PUBLIC" if no == 1 else "BENCHMARK_PRIOR",
         "reason": None,
         "agent_run_id": run_id if no == 1 else None,
         "evidence": {"sources": [{"url": "https://example.com/1"}]} if no == 1 else None}
        for no, name in dispositions.DOMAINS])
    session.commit()

    # Unchanged disposition for domain 1; a different domain edited.
    records = [DispositionIn(
        domain_no=no, domain_name=name,
        disposition=("EVIDENCED_PUBLIC" if no == 1 else
                     "ANALYST_ASSERTED_PRIOR" if no == 3 else "BENCHMARK_PRIOR"),
        reason=None) for no, name in dispositions.DOMAINS]
    result = set_dispositions(case_id, records)

    kept = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id,
        db.domain_disposition.c.domain_no == 1)).one()
    assert kept.evidence is not None, "unchanged disposition must keep its sources"
    assert kept.agent_run_id == run_id
    assert result["provenance_dropped"] == [], (
        "domain 3 carried no provenance, so nothing should be reported dropped")


def test_deliberately_redispositioning_drops_provenance_and_says_so(session):
    """The other half: sources gathered for one claim do not support a
    different one, so a deliberate change clears them - visibly."""
    from app.routers.api import set_dispositions, DispositionIn

    case_id = _case(session)
    session.execute(insert(db.domain_disposition), [
        {"id": str(uuid.uuid4()), "case_id": case_id, "estimate_snapshot_id": None,
         "domain_no": no, "domain_name": name,
         "disposition": "EVIDENCED_PUBLIC" if no == 1 else "BENCHMARK_PRIOR",
         "reason": None, "agent_run_id": None,
         "evidence": {"sources": [{"url": "https://example.com/1"}]} if no == 1 else None}
        for no, name in dispositions.DOMAINS])
    session.commit()

    records = [DispositionIn(
        domain_no=no, domain_name=name,
        disposition="ANALYST_ASSERTED_PRIOR" if no == 1 else "BENCHMARK_PRIOR",
        reason=None) for no, name in dispositions.DOMAINS]
    result = set_dispositions(case_id, records)

    row = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id,
        db.domain_disposition.c.domain_no == 1)).one()
    assert row.evidence is None
    assert result["provenance_dropped"] and \
        result["provenance_dropped"][0]["domain_no"] == 1, (
        "dropping provenance must be reported, not silent")
