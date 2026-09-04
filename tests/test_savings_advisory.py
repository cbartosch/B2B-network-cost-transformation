"""Tests for savings advisory and narrative (Tranche 2: LLM-07, LLM-06).

Same provider-adapter mocking approach as test_research.py, for the same
reason: gateway.execute()'s own liveness/llm_run/idempotency logic needs to
actually run for succeed()'s checks to behave as they do in production.

Not executed here - no SQLAlchemy in the environment this was written in.
Written and traced by hand; `make test` is the first real signal.
"""
import itertools
import json
from dataclasses import replace
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import insert, select

from app import db
from app.domain import savings_advisory as sa
from app.domain.policy import RecommendationPolicy
from app.llm import errors
from app.llm.providers.base import ProviderCall


def _seeded(set_name):
    from app.seed import THRESHOLDS
    return {k: v for sn, k, v in THRESHOLDS if sn == set_name}


POLICY = RecommendationPolicy.from_rows(_seeded("recommendation_policy"))

_response_ids = (f"msg_sa_{i}" for i in itertools.count())


def _case(session) -> str:
    case_id = str(uuid.uuid4())
    session.execute(insert(db.case).values(
        case_id=case_id, created_by="test",
        resolved_entity_id=str(uuid.uuid4()), entity_confirmed_by="Jane Okafor"))
    session.commit()
    return case_id


def _lever(lever_id, family, saving_base, cost_layers=("L0",)):
    return {"lever_id": lever_id, "family": family, "description": "x",
           "cost_layers": list(cost_layers), "saving_base": saving_base}


def _scenario(label, base_saving, pct, levers):
    return {"label": label,
           "target_tco": {"low": "900000", "base": "950000", "high": "980000"},
           "gross_run_rate_savings": {"low": str(int(base_saving) - 20000),
                                      "base": str(base_saving),
                                      "high": str(int(base_saving) + 30000)},
           "savings_pct_base": pct, "levers": levers, "simulated_share": "0.0500",
           "origin_breakdown": {}, "target_components": []}


def _snapshot(session, *, case_id: str, current_tco_base="1000000",
             scenarios: dict | None = None) -> str:
    """B is the highest-savings scenario by default, so deterministic_recommend
    is exercised against a non-alphabetically-first answer - a test that only
    ever saw A win would not catch a bug that hardcoded A."""
    scenarios = scenarios or {
        "A": _scenario("Reprice current state", 40000, "0.040",
                      [_lever("LEV-REPRICE-001", "Same-service repricing", "40000")]),
        "B": _scenario("Optimized SD-WAN", 90000, "0.090",
                      [_lever("LEV-MPLS-001", "MPLS substitution", "90000")]),
        "C": _scenario("SASE northstar", 60000, "0.060",
                      [_lever("LEV-SASE-001", "Platform consolidation", "60000")]),
        "D": _scenario("Carrier-managed NaaS", 20000, "0.020",
                      [_lever("LEV-NAAS-001", "Supplier consolidation", "20000")]),
    }
    snap_id = str(uuid.uuid4())
    session.execute(insert(db.estimate_snapshot).values(
        estimate_snapshot_id=snap_id, case_id=case_id, version_label="V0",
        v0_status="COMPLETE",
        current_tco={"total": {"low": "0", "base": current_tco_base, "high": "0"}},
        target_tco={}, scenarios=scenarios, gross_run_rate_savings={},
        confidence={}, coverage={}, simulated_share=0.05, asserted_share=0.0,
        pins={}, levers=[]))
    session.commit()
    return snap_id


def _found_recommend_text(scenario_code="B", percentile="base", basis="a reason"):
    return json.dumps({"scenario_code": scenario_code, "percentile": percentile,
                       "basis": basis})


def _found_narrate_text(text="a narrative"):
    return json.dumps({"narrative": text})


class _FakeAdapter:
    def __init__(self, text_fn, configured=True):
        self._text_fn = text_fn
        self._configured = configured

    def configured(self):
        return self._configured

    def complete(self, *, system, prompt, max_tokens=1500):
        now = datetime.now(timezone.utc)
        return ProviderCall(
            provider="anthropic", model="fake-model",
            text=self._text_fn(system=system, prompt=prompt, max_tokens=max_tokens),
            provider_response_id=next(_response_ids), provider_request_id=str(uuid.uuid4()),
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
    monkeypatch.setattr(sa.gateway, "_adapters",
                        lambda: {"anthropic": fake, "openai": fake})
    return fake


# --------------------------------------------------------------- registry wiring

def test_llm06_llm07_permit_deterministic_only_with_a_real_endpoint():
    from app.llm import registry
    for agent_id in ("LLM-06", "LLM-07"):
        agent = registry.AGENTS[agent_id]
        assert "DETERMINISTIC_ONLY" in agent["permitted_execution_modes"]
        assert agent["deterministic_fallback_endpoint"]


def test_the_other_five_agents_still_do_not_permit_deterministic_only():
    from app.llm import registry
    for agent_id, agent in registry.AGENTS.items():
        if agent_id in ("LLM-06", "LLM-07"):
            continue
        assert "DETERMINISTIC_ONLY" not in agent["permitted_execution_modes"], (
            f"{agent_id} should still be LIVE-only")


def test_deterministic_only_is_actually_permitted_for_llm07_end_to_end(session):
    from app.llm import gateway
    case_id = _case(session)
    # No ModeNotPermitted - this is the fix: before Tranche 2, this agent
    # didn't exist, and DETERMINISTIC_ONLY had no registered agent anywhere.
    run_id = gateway.create_agent_run(session, agent_id="LLM-07",
                                      mode="DETERMINISTIC_ONLY", case_id=case_id)
    assert run_id


def test_deterministic_only_is_still_refused_for_llm01(session):
    from app.llm import errors as gw_errors, gateway
    case_id = _case(session)
    with pytest.raises(gw_errors.ModeNotPermitted):
        gateway.create_agent_run(session, agent_id="LLM-01",
                                 mode="DETERMINISTIC_ONLY", case_id=case_id)


def test_succeed_sets_produced_without_llm_for_deterministic_only_not_live(
        session, monkeypatch):
    from app.llm import gateway
    case_id = _case(session)
    det_run = gateway.create_agent_run(session, agent_id="LLM-07",
                                       mode="DETERMINISTIC_ONLY", case_id=case_id)
    gateway.succeed(session, det_run, {"ok": True})
    row = session.execute(select(db.agent_run)
                          .where(db.agent_run.c.agent_run_id == det_run)).one()
    assert row.produced_without_llm is True

    _wire_fake_provider(monkeypatch, lambda **kw: "{}")
    live_run = gateway.create_agent_run(session, agent_id="LLM-07", mode="LIVE",
                                        case_id=case_id)
    gateway.execute(session, agent_run_id=live_run, provider="anthropic",
                    system="s", prompt="p")
    gateway.succeed(session, live_run, {"ok": True})
    row = session.execute(select(db.agent_run)
                          .where(db.agent_run.c.agent_run_id == live_run)).one()
    assert row.produced_without_llm is False


# --------------------------------------------------------------- deterministic_recommend

def test_deterministic_recommend_picks_the_highest_base_saving_scenario():
    scenarios = {
        "A": _scenario("A", 40000, "0.040", []),
        "B": _scenario("B", 90000, "0.090", []),
        "C": _scenario("C", 60000, "0.060", []),
        "D": _scenario("D", 20000, "0.020", []),
    }
    code, percentile, basis = sa.deterministic_recommend(scenarios)
    assert code == "B"
    assert percentile == "base"
    assert "B" in basis or "highest" in basis


def test_deterministic_narrate_flags_pending_only_when_material_and_unapproved():
    scenario = _scenario("Optimized SD-WAN", 90000, "0.090",
                        [_lever("LEV-MPLS-001", "MPLS substitution", "90000")])
    record = {"scenario_code": "B", "percentile": "base", "basis": "x",
             "gross_run_rate_savings": scenario["gross_run_rate_savings"],
             "material_levers": ["LEV-MPLS-001"], "approved_by": None}
    text = sa.deterministic_narrate(record, scenario)
    assert "not yet been approved" in text

    record["approved_by"] = "Jane Okafor"
    assert "not yet been approved" not in sa.deterministic_narrate(record, scenario)

    record["approved_by"] = None
    record["material_levers"] = []
    assert "not yet been approved" not in sa.deterministic_narrate(record, scenario)


# --------------------------------------------------------------- recommend()

def test_recommend_raises_lookup_error_for_an_unknown_snapshot(session):
    with pytest.raises(LookupError):
        sa.recommend(session, estimate_snapshot_id="no-such-snapshot",
                    recommendation_policy=POLICY)


def test_recommend_raises_value_error_for_an_unsupported_mode(session):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    with pytest.raises(ValueError):
        sa.recommend(session, estimate_snapshot_id=snap_id, mode="MOCK",
                    recommendation_policy=POLICY)


def test_deterministic_recommend_mode_writes_a_correctly_labelled_record(session):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)   # B wins, saving_base=90000

    rec = sa.recommend(session, estimate_snapshot_id=snap_id,
                       mode="DETERMINISTIC_ONLY", recommendation_policy=POLICY)

    assert rec["label"] == "DETERMINISTIC_PROPOSED"
    assert rec["scenario_code"] == "B"
    assert rec["percentile"] == "base"
    assert rec["gross_run_rate_savings"]["base"] == "90000"     # looked up, not guessed
    assert "LEV-MPLS-001" in rec["material_levers"]             # 90000/1000000 = 9% >= 3%
    assert rec["approved_by"] is None
    assert rec["agent_run_id"] is not None


def test_live_mode_recommendation_is_labelled_llm_proposed_and_recalculated(
        session, monkeypatch):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    _wire_fake_provider(monkeypatch,
                       lambda **kw: _found_recommend_text(
                           scenario_code="C", percentile="high",
                           basis="the model's own reasoning, restating no numbers"))

    rec = sa.recommend(session, estimate_snapshot_id=snap_id, mode="LIVE",
                       recommendation_policy=POLICY)

    assert rec["label"] == "LLM_PROPOSED"
    assert rec["scenario_code"] == "C"
    assert rec["percentile"] == "high"
    # C's high figure per _scenario(): base=60000 -> high=90000
    assert rec["gross_run_rate_savings"]["high"] == "90000"


def test_live_mode_rejects_a_scenario_code_the_snapshot_does_not_have(session, monkeypatch):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    _wire_fake_provider(monkeypatch,
                       lambda **kw: _found_recommend_text(scenario_code="Z"))

    with pytest.raises(errors.StructuredOutputInvalid):
        sa.recommend(session, estimate_snapshot_id=snap_id, mode="LIVE",
                    recommendation_policy=POLICY)

    # No recommendation row should exist for this snapshot - a rejected shape
    # is a technical failure, not a recommendation (same principle as Tranche 1).
    rows = session.execute(select(db.recommendation).where(
        db.recommendation.c.estimate_snapshot_id == snap_id)).all()
    assert rows == []


def test_a_non_material_scenario_has_no_material_levers(session):
    case_id = _case(session)
    scenarios = {
        "A": _scenario("A", 1000, "0.001", [_lever("LEV-CLEANUP-001", "Billing cleanup", "1000")]),
        "B": _scenario("B", 500, "0.0005", []),
        "C": _scenario("C", 200, "0.0002", []),
        "D": _scenario("D", 100, "0.0001", []),
    }
    snap_id = _snapshot(session, case_id=case_id, scenarios=scenarios,
                       current_tco_base="1000000")   # 1000/1000000 = 0.1%, well under 3%

    rec = sa.recommend(session, estimate_snapshot_id=snap_id,
                       mode="DETERMINISTIC_ONLY", recommendation_policy=POLICY)
    assert rec["material_levers"] == []


# --------------------------------------------------------------- approve()

def test_approve_requires_a_non_empty_name(session):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    rec = sa.recommend(session, estimate_snapshot_id=snap_id,
                       mode="DETERMINISTIC_ONLY", recommendation_policy=POLICY)
    with pytest.raises(ValueError):
        sa.approve(session, recommendation_id=rec["recommendation_id"], approved_by="   ")


def test_approve_sets_approved_by_and_approved_at(session):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    rec = sa.recommend(session, estimate_snapshot_id=snap_id,
                       mode="DETERMINISTIC_ONLY", recommendation_policy=POLICY)

    approved = sa.approve(session, recommendation_id=rec["recommendation_id"],
                          approved_by="Jane Okafor")
    assert approved["approved_by"] == "Jane Okafor"
    assert approved["approved_at"] is not None


# --------------------------------------------------------------- narrate()

def test_narrate_final_true_is_refused_when_material_and_unapproved(session):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)   # B: 90000/1000000 = 9%, material
    rec = sa.recommend(session, estimate_snapshot_id=snap_id,
                       mode="DETERMINISTIC_ONLY", recommendation_policy=POLICY)

    with pytest.raises(PermissionError):
        sa.narrate(session, recommendation_id=rec["recommendation_id"],
                  mode="DETERMINISTIC_ONLY", final=True)


def test_narrate_final_false_produces_a_marked_draft_instead_of_refusing(session):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    rec = sa.recommend(session, estimate_snapshot_id=snap_id,
                       mode="DETERMINISTIC_ONLY", recommendation_policy=POLICY)

    draft = sa.narrate(session, recommendation_id=rec["recommendation_id"],
                       mode="DETERMINISTIC_ONLY", final=False)
    assert draft["narrative"].startswith("[DRAFT")


def test_narrate_final_true_succeeds_once_approved(session):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    rec = sa.recommend(session, estimate_snapshot_id=snap_id,
                       mode="DETERMINISTIC_ONLY", recommendation_policy=POLICY)
    sa.approve(session, recommendation_id=rec["recommendation_id"],
              approved_by="Jane Okafor")

    final = sa.narrate(session, recommendation_id=rec["recommendation_id"],
                       mode="DETERMINISTIC_ONLY", final=True)
    assert not final["narrative"].startswith("[DRAFT")
    assert final["narrative_label"] == "DETERMINISTIC_PROPOSED"


def test_live_mode_narrative_is_labelled_llm_proposed(session, monkeypatch):
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    rec = sa.recommend(session, estimate_snapshot_id=snap_id,
                       mode="DETERMINISTIC_ONLY", recommendation_policy=POLICY)
    sa.approve(session, recommendation_id=rec["recommendation_id"],
              approved_by="Jane Okafor")

    _wire_fake_provider(monkeypatch, lambda **kw: _found_narrate_text("prose"))
    final = sa.narrate(session, recommendation_id=rec["recommendation_id"],
                       mode="LIVE", final=True)
    assert final["narrative"] == "prose"
    assert final["narrative_label"] == "LLM_PROPOSED"


def test_narrate_raises_lookup_error_for_an_unknown_recommendation(session):
    with pytest.raises(LookupError):
        sa.narrate(session, recommendation_id="no-such-id")


# --------------------------------------------------------------- no automatic downgrade

def test_a_live_failure_never_produces_a_deterministic_only_result(session, monkeypatch):
    """The regression this whole tranche's framing depends on: gateway.py
    guarantees no automatic mode downgrade, and this module must not
    reintroduce one at a higher layer by, say, catching ProviderUnavailable
    and quietly retrying with DETERMINISTIC_ONLY. A LIVE failure must fail;
    a deterministic result requires a new, separate, explicit call."""
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    _wire_fake_provider(monkeypatch, lambda **kw: _found_recommend_text(), configured=False)

    with pytest.raises(errors.ProviderUnavailable):
        sa.recommend(session, estimate_snapshot_id=snap_id, mode="LIVE",
                    recommendation_policy=POLICY)

    # No recommendation was written for the failed LIVE attempt.
    rows = session.execute(select(db.recommendation).where(
        db.recommendation.c.estimate_snapshot_id == snap_id)).all()
    assert rows == [], (
        "a failed LIVE call must not silently produce any recommendation, "
        "deterministic or otherwise")

    # The failed run itself reached a terminal FAILED state - not left QUEUED,
    # and specifically not SUCCEEDED via some fallback path.
    from app import db as db_module
    failed_runs = session.execute(select(db_module.agent_run).where(
        db_module.agent_run.c.case_id == case_id,
        db_module.agent_run.c.agent_id == "LLM-07")).all()
    assert len(failed_runs) == 1
    assert failed_runs[0].status == "FAILED"
    assert failed_runs[0].execution_mode == "LIVE", (
        "the failed run's own mode must still read LIVE - it was never "
        "rewritten to DETERMINISTIC_ONLY by any fallback logic")

    # A second, explicit, separate call with DETERMINISTIC_ONLY does succeed -
    # proving the deterministic path exists and is reachable, just never
    # automatically.
    rec = sa.recommend(session, estimate_snapshot_id=snap_id, mode="DETERMINISTIC_ONLY",
                       recommendation_policy=POLICY)
    assert rec["label"] == "DETERMINISTIC_PROPOSED"


# --------------------------------------------------------------- orphan-row fix

def test_a_rejected_shape_terminates_the_run_rather_than_leaving_it_queued(
        session, monkeypatch):
    """Found while building this tranche: execute()'s own failure handling
    only covers what execute() itself detects (no provider, failed liveness
    proof). A caller-side rejection of an otherwise-successful response - here,
    an unknown scenario_code - happens after execute() has already returned,
    so nothing was marking that row FAILED. It sat in QUEUED forever. Same
    defect class as test_unimplemented_mode_creates_no_orphan_run in
    test_wiring.py, reached by a different path; fixed in research.py too,
    not just here."""
    case_id = _case(session)
    snap_id = _snapshot(session, case_id=case_id)
    _wire_fake_provider(monkeypatch,
                       lambda **kw: _found_recommend_text(scenario_code="Z"))

    with pytest.raises(errors.StructuredOutputInvalid):
        sa.recommend(session, estimate_snapshot_id=snap_id, mode="LIVE",
                    recommendation_policy=POLICY)

    from app import db as db_module
    runs = session.execute(select(db_module.agent_run).where(
        db_module.agent_run.c.case_id == case_id,
        db_module.agent_run.c.agent_id == "LLM-07")).all()
    assert len(runs) == 1
    assert runs[0].status == "FAILED", (
        "a rejected response shape must terminate the run as FAILED, not "
        "leave it QUEUED indefinitely")


# ------------------- C-10: a layer match is not proof that a lever applies
def _lever(lever_id, family, layers, products, base="0.25"):
    return {"lever_id": lever_id, "family": family, "description": "",
            "cost_layers": layers, "saving_low": "0.15",
            "saving_base": base, "saving_high": "0.35",
            "applies_to_products": products, "scenario": "B"}


def _components(*pairs):
    from app.domain.estimate import Component
    from app.domain.money import D, Range
    return [Component(key=f"L0_{p.lower()}", layer=layer, driver="circuits",
                      quantity=100, quantity_origin="ANALYST_ENTERED_SCOPE",
                      unit_cost_origin="BENCHMARK_PRIOR", product=p,
                      role="PRIMARY",
                      value=Range(D("80000"), D("96000"), D("120000")))
            for p, layer in pairs]


def test_no_mpls_substitution_savings_in_an_estate_with_no_mpls():
    """External audit finding C-10, demonstrated by controlled probe.

    A lever's cost_layers was the whole eligibility test, and L0 is the entire
    access layer - so LEV-MPLS-001 applied MPLS substitution to broadband and
    mobile circuits. On 100 HFC stores that booked 24,000 of savings from
    replacing MPLS in an estate holding none.

    The arithmetic was correct throughout. The result was semantically false,
    which is worse than an arithmetic error because nothing in the output looks
    wrong."""
    from app.domain import estimate

    scenarios = estimate.scenarios(
        components=_components(("BROADBAND_HFC", "L0"), ("MOBILE_5G", "L0")),
        levers=[_lever("LEV-MPLS-001", "MPLS substitution", ["L0"], ["MPLS"])])
    booked = [l for l in scenarios["B"]["levers"]
              if l["lever_id"] == "LEV-MPLS-001"]
    assert not booked, (
        f"MPLS substitution booked {booked} against an estate with no MPLS")
    assert scenarios["B"]["gross_run_rate_savings"]["base"] in ("0.00", "0")


def test_the_same_lever_still_applies_where_mpls_is_present():
    """A constraint that blocks everything is not a control, it is a bug."""
    from app.domain import estimate

    scenarios = estimate.scenarios(
        components=_components(("MPLS", "L0")),
        levers=[_lever("LEV-MPLS-001", "MPLS substitution", ["L0"], ["MPLS"])])
    booked = [l for l in scenarios["B"]["levers"]
              if l["lever_id"] == "LEV-MPLS-001"]
    assert booked, "MPLS substitution must apply to an MPLS circuit"


def test_an_inapplicable_lever_is_reported_not_silently_dropped():
    """A scenario quietly containing fewer levers than it declares reads as a
    weaker opportunity rather than a different estate - and "no MPLS to
    substitute" is a fact about the client worth surfacing."""
    from app.domain import estimate

    scenarios = estimate.scenarios(
        components=_components(("BROADBAND_HFC", "L0")),
        levers=[_lever("LEV-MPLS-001", "MPLS substitution", ["L0"], ["MPLS"])])
    skipped = scenarios["B"]["levers_not_applicable"]
    assert len(skipped) == 1
    assert skipped[0]["lever_id"] == "LEV-MPLS-001"
    assert "BROADBAND_HFC" in skipped[0]["products_present"]
    assert "contain none of them" in skipped[0]["reason"]


def test_an_unconstrained_lever_still_acts_on_any_circuit():
    """Repricing and billing cleanup act on any circuit whatever its
    technology. Requiring them to enumerate every product would be a list to
    maintain rather than a control."""
    from app.domain import estimate

    scenarios = estimate.scenarios(
        components=_components(("BROADBAND_HFC", "L0")),
        levers=[_lever("LEV-REPRICE-001", "Same-service repricing", ["L0"],
                       None, base="0.12")])
    assert scenarios["B"]["levers"], "an unconstrained lever must still apply"


def test_right_sizing_does_not_apply_to_a_shared_best_effort_service():
    """A 100 Mbps HFC line is not sold at 60, so there is no headroom to
    reprice - the audit's point about eligibility beyond the layer."""
    from app.domain import estimate

    scenarios = estimate.scenarios(
        components=_components(("DIA", "L0"), ("BROADBAND_PON", "L0")),
        levers=[_lever("LEV-BANDWIDTH-001", "Right-sizing", ["L0"],
                       ["DIA", "ETHERNET", "MPLS"], base="0.07")])
    applied = scenarios["B"]["levers"]
    assert applied, "right-sizing must apply to the DIA circuit"
    # and the PON component must be untouched
    pon = next(c for c in scenarios["B"]["target_components"]
               if c["product"] == "BROADBAND_PON")
    assert pon["value"]["base"] == "96000.00", (
        "a shared best-effort circuit must not be right-sized")


def test_every_seeded_lever_declares_its_eligibility_deliberately():
    """None means unconstrained and is a decision; a missing key is an
    oversight. The distinction has to be visible in the seed."""
    from app.seed import LEVERS

    for row in LEVERS:
        assert len(row) == 10, f"{row[0]} has no applies_to_products slot"
        products = row[7]
        assert products is None or (isinstance(products, list) and products), (
            f"{row[0]} declares an empty product list, which blocks everything")
