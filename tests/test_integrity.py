"""Integrity tests drawn from specification section 16.

These are the tests that matter most: they assert the system cannot fake a
provider call, cannot inflate confidence, and cannot publish a V0 it should not.
Run with `make test`.
"""
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, "/app")

from app.domain import confidence, coverage, dispositions, policy, simulation  # noqa: E402


def _seeded(set_name):
    """Tests run against the values that actually ship, so a seed change that
    breaks the model is caught here rather than in production."""
    from app.seed import THRESHOLDS
    return {k: v for sn, k, v in THRESHOLDS if sn == set_name}


POLICY = policy.ConfidencePolicy.from_rows(_seeded("confidence_policy"))
COV_POLICY = policy.CoveragePolicy.from_rows(_seeded("v0_coverage_threshold_set"))
from app.domain.money import D, Range                                   # noqa: E402
from app.llm import errors, gateway, registry                           # noqa: E402
from app.llm.providers.base import ProviderCall                         # noqa: E402


# ------------------------------------------------------- simulation determinism
FOOTPRINT = [{"country": "GB", "archetype": "BRANCH", "sites": 60},
             {"country": "DE", "archetype": "DC", "sites": 3}]
ARCH = {"BRANCH": {"dual_access_probability": 0.6, "primary_product": "DIA",
                   "backup_product": "BROADBAND"},
        "DC": {"dual_access_probability": 1.0, "primary_product": "ETHERNET",
               "backup_product": "ETHERNET"}}


def _sim(seed, size=9):
    return simulation.run_ensemble(seed=seed, ensemble_size=size, footprint=FOOTPRINT,
                                   archetypes=ARCH, model_version="sim-1.0.0")


def test_simulation_is_byte_identical_on_rerun():
    assert simulation.output_hash(_sim(7)) == simulation.output_hash(_sim(7))


def test_simulation_changes_with_seed():
    assert simulation.output_hash(_sim(7)) != simulation.output_hash(_sim(8))


def test_simulation_emits_only_simulated_diversity_state():
    edges = _sim(7)["sample_topology"]["edges"]
    assert edges, "expected simulated edges"
    assert {e["diversity_state"] for e in edges} == {"SIMULATED"}


def test_simulation_never_claims_evidenced():
    assert "EVIDENCED" not in simulation.output_hash(_sim(7))
    assert simulation.DIVERSITY_STATE == "SIMULATED"


# ------------------------------------------------------- confidence ceilings
def test_confidence_falls_monotonically_with_simulated_share():
    scores = [float(confidence.compute(policy=POLICY, current_baseline="0.60", target_cost="0.95",
                                       realization="0.50", simulated_share=s,
                           asserted_share="0",
                           v0_status="COMPLETE")["overall"])
              for s in ("0.00", "0.20", "0.50", "0.90")]
    assert scores == sorted(scores, reverse=True), scores


def test_wholly_simulated_v0_cannot_outscore_evidenced_one():
    sim_heavy = confidence.compute(policy=POLICY, current_baseline="0.60", target_cost="0.95",
                                   realization="0.50", simulated_share="0.90",
                           asserted_share="0",
                           v0_status="COMPLETE")
    evidenced = confidence.compute(policy=POLICY, current_baseline="0.60", target_cost="0.95",
                                   realization="0.50", simulated_share="0.00",
                           asserted_share="0",
                           v0_status="COMPLETE")
    assert float(sim_heavy["overall"]) < float(evidenced["overall"])


def test_ceilings_compose_downward_only():
    both = confidence.compute(policy=POLICY, current_baseline="0.90", target_cost="0.90",
                              realization="0.90", simulated_share="0.90",
                              asserted_share="0.90", v0_status="PARTIAL")
    neither = confidence.compute(policy=POLICY, current_baseline="0.90", target_cost="0.90",
                                 realization="0.90",
                           simulated_share="0",
                           asserted_share="0",
                           v0_status="COMPLETE")
    assert float(both["overall"]) < float(neither["overall"])
    assert len(both["ceilings_applied"]) >= 2


def test_asserted_share_below_trigger_applies_no_ceiling():
    r = confidence.compute(policy=POLICY, current_baseline="0.80", target_cost="0.80",
                           realization="0.80", asserted_share="0.10",
                           simulated_share="0",
                           v0_status="COMPLETE")
    assert not any("asserted" in c for c in r["ceilings_applied"])


# ------------------------------------------------------- coverage gate
LAYERS = ["L0", "L2", "L4"]
ALL_PRIORS = {("GB", "DIA"): {"low": 380, "base": 520, "high": 720, "price_year": 2026},
              ("DE", "DIA"): {"low": 420, "base": 580, "high": 800, "price_year": 2026},
              ("BR", "DIA"): {"low": 500, "base": 700, "high": 950, "price_year": 2026},
              ("IN", "DIA"): {"low": 300, "base": 420, "high": 600, "price_year": 2026}}
SIM = {"products": [{"country": "GB", "product": "DIA", "role": "PRIMARY", "count": 800},
                    {"country": "DE", "product": "DIA", "role": "PRIMARY", "count": 430},
                    {"country": "BR", "product": "DIA", "role": "PRIMARY", "count": 180},
                    {"country": "IN", "product": "DIA", "role": "PRIMARY", "count": 80}]}


def _cov(priors, layers_priced=None):
    scope = coverage.derive_scope(sim_output=SIM, priors=priors)
    return coverage.assess(scope=scope, layers_in_scope=LAYERS,
                           layers_priced=layers_priced or set(LAYERS),
                           policy=COV_POLICY)


def test_v0_publishes_with_empty_benchmark_vault():
    assert _cov(ALL_PRIORS)["status"] == "COMPLETE"


def test_material_country_floor_catches_high_aggregate():
    partial = {k: v for k, v in ALL_PRIORS.items() if k[0] != "BR"}
    r = _cov(partial)
    assert r["status"] == "PARTIAL"
    assert "BR" in r["material_country_breaches"]


def test_publication_refused_below_absolute_floor():
    assert _cov({("IN", "DIA"): ALL_PRIORS[("IN", "DIA")]})["status"] == "REFUSED"


def test_unpriced_scope_is_excluded_not_zeroed():
    r = _cov({k: v for k, v in ALL_PRIORS.items() if k[0] in ("GB", "DE")})
    assert r["unpriced_scope_treatment"] == "EXCLUDED_FROM_HEADLINE"
    assert set(r["unpriced_countries"]) == {"BR", "IN"}


def test_every_seeded_backup_product_has_a_prior():
    """MOBILE_5G is the STORE archetype's backup and had no prior in any country,
    so the default demo path would have been permanently PARTIAL. Surfacing that
    is the fix working; leaving it would be a spurious gap."""
    from app.seed import ARCHETYPES, PRIORS
    priced_products = {p for _c, p, *_ in PRIORS}
    used = {a[4] for a in ARCHETYPES} | {a[5] for a in ARCHETYPES}
    assert not (used - priced_products), f"unpriced products: {used - priced_products}"


def test_coverage_denominator_is_derived_not_caller_supplied():
    """The audit bypass: omitting unpriced markets from a declared spend figure
    used to flip PARTIAL to COMPLETE. The declaration is now a cross-check."""
    priors = {k: v for k, v in ALL_PRIORS.items() if k[0] in ("GB", "DE")}
    scope = coverage.derive_scope(sim_output=SIM, priors=priors)
    gamed = coverage.assess(scope=scope, layers_in_scope=LAYERS,
                           layers_priced=set(LAYERS), policy=COV_POLICY,
                            declared_spend_by_country={"GB": 1, "DE": 1})
    assert gamed["status"] == "PARTIAL"
    assert gamed["spend_basis"] == "DERIVED_FROM_SIMULATED_SCOPE_AND_PRIORS"
    assert set(gamed["declared_spend_crosscheck"]
               ["countries_in_scope_but_not_declared"]) == {"BR", "IN"}


def test_coverage_is_assessed_per_country_product_pair():
    """One broadband prior used to make an all-MPLS country count as priced."""
    sim = {"products": [{"country": "GB", "product": "MPLS", "role": "PRIMARY", "count": 500},
                        {"country": "GB", "product": "BROADBAND", "role": "BACKUP", "count": 10}]}
    priors = {("GB", "BROADBAND"): {"low": 45, "base": 70, "high": 110, "price_year": 2026},
              ("DE", "MPLS"): {"low": 700, "base": 980, "high": 1400, "price_year": 2026}}
    r = coverage.assess(scope=coverage.derive_scope(sim_output=sim, priors=priors),
                        layers_in_scope=["L0"], layers_priced={"L0"},
                        policy=COV_POLICY)
    assert r["status"] == "REFUSED"
    assert "GB/MPLS" in r["unpriced_pairs"]


# --- C2-02: scope that cannot be sized must not vanish from the gate --------
UNSIZABLE_SIM = {"products": [
    {"country": "GB", "product": "DIA", "role": "PRIMARY", "count": 800},
    {"country": "BR", "product": "MPLS", "role": "PRIMARY", "count": 300},
    {"country": "IN", "product": "MPLS", "role": "PRIMARY", "count": 200}]}
GB_ONLY = {("GB", "DIA"): {"low": 380, "base": 520, "high": 720, "price_year": 2026}}


def test_unsizable_scope_cannot_report_complete():
    """The audit finding: no MPLS prior in any country meant those rows were
    valued at zero, so 500 circuits vanished from the denominator and the gate
    reported COMPLETE at 100%."""
    scope = coverage.derive_scope(sim_output=UNSIZABLE_SIM, priors=GB_ONLY)
    r = coverage.assess(scope=scope, layers_in_scope=["L0"],
                           layers_priced={"L0"}, policy=COV_POLICY)
    assert r["status"] != "COMPLETE"
    assert r["unsizable_circuits"] == 500
    assert set(r["unsizable_pairs"]) == {"BR/MPLS", "IN/MPLS"}


def test_value_coverage_alone_is_still_defeatable_so_circuits_govern():
    """Value coverage still reads 1.000 - that is the measure unsizable scope can
    hide from. The point of the fix is that it no longer decides the outcome."""
    scope = coverage.derive_scope(sim_output=UNSIZABLE_SIM, priors=GB_ONLY)
    r = coverage.assess(scope=scope, layers_in_scope=["L0"],
                           layers_priced={"L0"}, policy=COV_POLICY)
    assert r["priced_spend_pct"] == "1.000"
    assert D(r["circuit_coverage_pct"]) < D("0.7")
    assert r["effective_coverage_pct"] == r["circuit_coverage_pct"]
    assert r["coverage_basis"] == "MIN_OF_VALUE_AND_CIRCUIT_COVERAGE"


def test_wholly_unsizable_country_still_breaches_the_material_floor():
    """It could not breach before: the floor skipped any country whose value was
    zero, which is exactly the unsizable case."""
    scope = coverage.derive_scope(sim_output=UNSIZABLE_SIM, priors=GB_ONLY)
    r = coverage.assess(scope=scope, layers_in_scope=["L0"],
                           layers_priced={"L0"}, policy=COV_POLICY)
    assert set(r["material_country_breaches"]) == {"BR", "IN"}


def test_sizing_priors_size_without_pricing():
    """A German MPLS rate cannot price a Brazilian circuit but can size one, so
    the unsizable population shrinks without anything being priced wrongly."""
    sizing = {**GB_ONLY,
              ("DE", "MPLS"): {"low": 760, "base": 1050, "high": 1500, "price_year": 2026}}
    scope = coverage.derive_scope(sim_output=UNSIZABLE_SIM, priors=GB_ONLY,
                                  sizing_priors=sizing)
    br = [r for r in scope if r["country"] == "BR"][0]
    assert br["priced"] is False, "a foreign prior must never price a circuit"
    assert br["rate_basis"] == "CROSS_COUNTRY_MEDIAN"
    assert D(br["annual_value"]) > 0, "but it must contribute to the denominator"
    r = coverage.assess(scope=scope, layers_in_scope=["L0"],
                           layers_priced={"L0"}, policy=COV_POLICY)
    assert not r["unsizable_pairs"] and r["status"] == "PARTIAL"


def test_fully_priced_estate_still_reaches_complete():
    """The conservative direction must not swallow the normal case."""
    sim = {"products": [{"country": "GB", "product": "DIA", "role": "PRIMARY", "count": 800},
                        {"country": "DE", "product": "DIA", "role": "PRIMARY", "count": 430}]}
    priors = {("GB", "DIA"): {"low": 380, "base": 520, "high": 720, "price_year": 2026},
              ("DE", "DIA"): {"low": 420, "base": 580, "high": 800, "price_year": 2026}}
    r = coverage.assess(scope=coverage.derive_scope(sim_output=sim, priors=priors),
                        layers_in_scope=["L0"], layers_priced={"L0"},
                        policy=COV_POLICY)
    assert r["status"] == "COMPLETE" and r["effective_coverage_pct"] == "1.000"


def test_layer_coverage_responds_to_the_priced_layer_set():
    """It was a hardcoded literal in the endpoint, so the test could never fire."""
    full = _cov(ALL_PRIORS, layers_priced={"L0", "L2", "L4"})
    thin = _cov(ALL_PRIORS, layers_priced={"L0"})
    assert full["layer_coverage_pct"] != thin["layer_coverage_pct"]
    assert thin["status"] == "PARTIAL"


# ------------------------------------------------------- dispositions
def test_v0_cannot_publish_with_undisposed_domain():
    recs = [{"domain_no": n, "disposition": "BENCHMARK_PRIOR"}
            for n, _ in dispositions.DOMAINS[:-1]]
    assert dispositions.validate(recs), "an undisposed domain must block publication"


def test_declared_unknown_requires_controlled_reason():
    recs = [{"domain_no": n, "disposition": "BENCHMARK_PRIOR"}
            for n, _ in dispositions.DOMAINS]
    recs[0] = {"domain_no": 1, "disposition": "DECLARED_UNKNOWN", "reason": "because"}
    assert any("controlled reason" in p for p in dispositions.validate(recs))


def test_budget_exhausted_recorded_distinctly():
    recs = [{"domain_no": n, "disposition": "BENCHMARK_PRIOR"}
            for n, _ in dispositions.DOMAINS]
    recs[3] = {"domain_no": 4, "disposition": "DECLARED_UNKNOWN", "reason": "BUDGET_EXHAUSTED"}
    recs[4] = {"domain_no": 5, "disposition": "DECLARED_UNKNOWN", "reason": "NO_PUBLIC_EVIDENCE"}
    s = dispositions.summarise(recs)
    assert s["budget_exhausted_domains"] == [4]
    assert s["declared_unknown"] == 2


# ------------------------------------------------------- anti-fake / liveness
def _call(**kw):
    now = datetime.now(timezone.utc)
    base = dict(provider="anthropic", model="m", text="{}",
                provider_response_id="msg_1", provider_request_id="req_1",
                provider_request_at=now, input_tokens=10, output_tokens=5,
                local_request_at=now, latency_ms=100, http_status=200,
                egress_proxy=None, raw={})
    base.update(kw)
    return ProviderCall(**base)


def test_liveness_rejects_missing_response_id():
    now = datetime.now(timezone.utc)
    with pytest.raises(errors.LivenessProofFailed):
        gateway.verify_liveness(_call(provider_response_id=""), now, now)


def test_liveness_rejects_zero_tokens():
    now = datetime.now(timezone.utc)
    with pytest.raises(errors.LivenessProofFailed):
        gateway.verify_liveness(_call(output_tokens=0), now, now)


def test_liveness_rejects_a_provider_clock_far_from_ours():
    """The provider timestamp now comes from the provider, so this compares two
    independent clocks rather than one clock against itself."""
    now = datetime.now(timezone.utc)
    stale = _call(provider_request_at=now - timedelta(hours=6), local_request_at=now)
    with pytest.raises(errors.LivenessProofFailed):
        gateway.verify_liveness(stale, now, now)


def test_liveness_accepts_a_real_looking_call():
    now = datetime.now(timezone.utc)
    gateway.verify_liveness(_call(), now, now)      # must not raise


def test_deterministic_only_is_not_offered_without_an_executor():
    with pytest.raises(errors.ModeNotPermitted):
        gateway._assert_mode_permitted("LLM-01", "DETERMINISTIC_ONLY")


def test_unregistered_agent_is_rejected():
    with pytest.raises(errors.ModeNotPermitted):
        gateway._assert_mode_permitted("LLM-99", "LIVE")


def test_no_agent_declares_a_fallback_it_does_not_have():
    for aid, a in registry.AGENTS.items():
        if "DETERMINISTIC_ONLY" in a["permitted_execution_modes"]:
            assert a["deterministic_fallback_endpoint"], \
                f"{aid} offers DETERMINISTIC_ONLY without a registered endpoint"


def test_structured_output_abstains_rather_than_salvaging():
    with pytest.raises(errors.StructuredOutputInvalid):
        gateway.parse_json_strict("Here are some candidates: Acme Corp, Acme Ltd")


# The former source-grep "anti-stub" test lived here. It asserted that four
# self-chosen identifiers were absent from the gateway, which any real stub
# would trivially pass. Replaced by behavioural tests in test_controls_db.py.


# ------------------------------------------------------- money
def test_money_is_decimal_not_float():
    r = Range("100.10", "200.20", "300.30") + Range("0.01", "0.02", "0.03")
    assert r.base == D("200.22")


def test_cost_increases_stay_negative():
    current, target = Range(100, 100, 100), Range(150, 150, 150)
    saving = current - target
    assert saving.base < 0, "a cost increase must remain visible, not floor at zero"


# ------------------------------------------------------- derived simulated share
from app.domain import estimate                                          # noqa: E402

PRIORS = {("GB", "DIA"): {"low": 380, "base": 520, "high": 720},
          ("GB", "BROADBAND"): {"low": 45, "base": 70, "high": 110},
          ("GB", "ETHERNET"): {"low": 550, "base": 780, "high": 1100}}
OPS = {"low": 720, "base": 900, "high": 1170}
# Platform priors now come from reference.platform_unit_cost. There is no code
# constant fallback: a missing platform prior is unpriced scope (M-01).
OVERLAY = {"low": 40, "base": 55, "high": 75}
SSE = {"low": 6, "base": 9, "high": 13}
BIG_FOOTPRINT = [{"country": "GB", "archetype": "BRANCH", "sites": 120},
                 {"country": "GB", "archetype": "DC", "sites": 2}]
BIG_ARCH = {"BRANCH": {"dual_access_probability": 0.55, "primary_product": "DIA",
                       "backup_product": "BROADBAND"},
            "DC": {"dual_access_probability": 1.0, "primary_product": "ETHERNET",
                   "backup_product": "ETHERNET"}}


def _components(dual_probability=0.55, users=5000,
                footprint_origin=estimate.ANALYST_ENTERED_SCOPE,
                driver_refs=None):
    arch = {k: {**v, "dual_access_probability": dual_probability}
            for k, v in BIG_ARCH.items()}
    sim = simulation.run_ensemble(seed=42, ensemble_size=15, footprint=BIG_FOOTPRINT,
                                  archetypes=arch, model_version="sim-1.0.0")
    comps, _ = estimate.build_components(
        sim_output=sim, users=users, ops_cost_per_site=OPS, priors=PRIORS,
        driver_origins={"sites": footprint_origin, "users": footprint_origin},
        driver_refs=driver_refs, overlay_unit=OVERLAY, sse_unit=SSE)
    return comps


def test_simulated_share_is_derived_not_constant():
    """The bug this replaces: a hardcoded 0.70 regardless of the estate."""
    low = estimate.simulated_share(_components(dual_probability=0.05))
    high = estimate.simulated_share(_components(dual_probability=1.0))
    assert low < high, "share must respond to how much the simulation actually decided"
    assert float(low) < 0.70 and float(high) < 0.70


def test_no_dual_access_means_almost_no_simulated_value():
    share = estimate.simulated_share(_components(dual_probability=0.0))
    assert float(share) == 0.0, "with no backup circuits nothing was simulated"


def test_primary_circuits_inherit_footprint_origin_not_simulated():
    """Only the backup draw is the simulation's decision. Primary count follows
    deterministically from the supplied footprint."""
    comps = _components()
    primary = [c for c in comps if c.key.startswith("L0_primary")]
    assert primary and all(c.quantity_origin == estimate.ANALYST_ENTERED_SCOPE
                           for c in primary)
    backup = [c for c in comps if c.key.startswith("L0_backup")]
    assert backup and all(c.quantity_origin == "SIMULATED" for c in backup)


def test_simulated_footprint_propagates_to_every_dependent_component():
    comps = _components(footprint_origin="SIMULATED")
    assert all(c.quantity_origin == "SIMULATED" for c in comps
               if c.driver in ("circuits", "sites"))
    assert float(estimate.simulated_share(comps)) > 0.5


def test_non_simulated_layer_growth_dilutes_the_share():
    small = estimate.simulated_share(_components(users=1000))
    large = estimate.simulated_share(_components(users=50000))
    assert large < small, "growing an unsimulated layer must lower the simulated share"


def test_origin_breakdown_shares_sum_to_one():
    b = estimate.origin_breakdown(_components())
    assert abs(sum(float(v["share"]) for v in b.values()) - 1.0) < 0.001


LEVERS = [
    {"lever_id": "LEV-A", "family": "Repricing", "description": "x",
     "cost_layers": ["L0"], "saving_low": "0.06", "saving_base": "0.12",
     "saving_high": "0.18", "scenario": "A"},
    {"lever_id": "LEV-C1", "family": "Platform", "description": "x",
     "cost_layers": ["L2", "L4"], "saving_low": "0.12", "saving_base": "0.22",
     "saving_high": "0.32", "scenario": "C"},
]


def test_levers_only_touch_their_own_cost_layers():
    comps = _components()
    scen = estimate.scenarios(comps, LEVERS)
    before = {c.key: c.value.base for c in comps}
    after = {c["key"]: D(c["value"]["base"]) for c in scen["A"]["target_components"]}
    for c in comps:
        if c.layer == "L0":
            assert after[c.key] < before[c.key], f"{c.key} should be reduced"
        else:
            assert after[c.key] == before[c.key], f"{c.key} must be untouched by an L0 lever"


def test_scenario_shares_differ_when_levers_hit_unsimulated_layers():
    """Scenario C strips L2 and L4, which are not simulated, so the remaining
    target is proportionally more simulated than scenario A's."""
    scen = estimate.scenarios(_components(), LEVERS)
    assert D(scen["C"]["simulated_share"]) > D(scen["A"]["simulated_share"])


def test_target_share_is_computed_on_the_target_not_the_baseline():
    comps = _components()
    scen = estimate.scenarios(comps, LEVERS)
    assert D(scen["C"]["simulated_share"]) != estimate.simulated_share(comps)


def test_unpriced_components_are_reported_and_excluded():
    sim = simulation.run_ensemble(seed=42, ensemble_size=5, footprint=BIG_FOOTPRINT,
                                  archetypes=BIG_ARCH, model_version="sim-1.0.0")
    comps, unpriced = estimate.build_components(
        sim_output=sim, users=1000, ops_cost_per_site=OPS,
        priors={("GB", "DIA"): {"low": 380, "base": 520, "high": 720}},
        overlay_unit=OVERLAY, sse_unit=SSE)
    assert unpriced, "missing priors must be reported"
    assert all("BROADBAND" not in c.key for c in comps), "unpriced scope must be excluded"


def test_missing_platform_prior_is_unpriced_not_a_code_constant():
    """Overlay and SSE rates were hardcoded fallbacks in an earlier revision -
    about 40% of modelled TCO living only in code (spec 18.1 forbids it)."""
    sim = simulation.run_ensemble(seed=42, ensemble_size=5, footprint=BIG_FOOTPRINT,
                                  archetypes=BIG_ARCH, model_version="sim-1.0.0")
    comps, unpriced = estimate.build_components(
        sim_output=sim, users=1000, ops_cost_per_site=OPS, priors=PRIORS,
        overlay_unit=None, sse_unit=None)
    assert {u["product"] for u in unpriced} >= {"SDWAN_OVERLAY", "SSE_LICENCE"}
    assert not [c for c in comps if c.layer in ("L2", "L4")]


def test_derived_share_feeds_the_ceiling_correctly():
    """End to end: a lightly simulated estate must not be penalised as if it
    were wholly simulated - which the hardcoded 0.70 did."""
    share = estimate.simulated_share(_components(dual_probability=0.55))
    derived = confidence.compute(policy=POLICY, current_baseline="0.42", target_cost="0.68",
                                 realization="0.35", simulated_share=share,
                           asserted_share="0",
                           v0_status="COMPLETE")
    hardcoded = confidence.compute(policy=POLICY, current_baseline="0.42", target_cost="0.68",
                                   realization="0.35", simulated_share="0.70",
                           asserted_share="0",
                           v0_status="COMPLETE")
    assert float(derived["overall"]) > float(hardcoded["overall"])
    assert not derived["ceilings_applied"], "4-5% simulated should trip no ceiling"


# ------------------------------------------------------- derived confidence
def test_confidence_components_respond_to_evidence():
    """They were literals (0.42 / 0.68 / 0.35), so every V0 published the same
    score whatever the evidence."""
    weak = confidence.derive_components(policy=POLICY, priced_spend_pct="0.45", origin_breakdown={},
        domain_completeness="0.5", prior_recency="0.4", prior_coverage="0.4",
        lever_stage_mix={"V4": "100"})
    strong = confidence.derive_components(policy=POLICY, priced_spend_pct="1.0",
        origin_breakdown={"EVIDENCED_PUBLIC": {"share": "0.8"}},
        domain_completeness="1.0", prior_recency="1.0", prior_coverage="1.0",
        lever_stage_mix={"V2": "100"})
    for k in ("current_baseline", "target_cost", "realization"):
        assert strong[k] > weak[k], k


def test_v0_realization_is_structurally_bounded():
    """V0 cannot have contractual or serviceability evidence, so realization is
    capped by stage no matter how favourable the lever mix."""
    d = confidence.derive_components(policy=POLICY, priced_spend_pct="1.0", origin_breakdown={"EVIDENCED_PUBLIC": {"share": "1.0"}},
        domain_completeness="1.0", prior_recency="1.0", prior_coverage="1.0",
        lever_stage_mix={"V2": "100"})
    assert d["realization"] <= POLICY.stage_ceilings["V0"]["realization"]


def test_later_stage_levers_lower_realization_confidence():
    early = confidence.derive_components(policy=POLICY, priced_spend_pct="1.0", origin_breakdown={}, domain_completeness="1.0",
        prior_recency="1.0", prior_coverage="1.0", lever_stage_mix={"V2": "100"})
    late = confidence.derive_components(policy=POLICY, priced_spend_pct="1.0", origin_breakdown={}, domain_completeness="1.0",
        prior_recency="1.0", prior_coverage="1.0", lever_stage_mix={"V4": "100"})
    assert late["realization"] < early["realization"]


def test_partial_penalty_applies_below_the_indicative_floor():
    """It silently did nothing under 0.50."""
    a = confidence.compute(policy=POLICY, current_baseline="0.20", target_cost="0.20",
                           realization="0.20", v0_status="COMPLETE",
                           simulated_share="0",
                           asserted_share="0")
    b = confidence.compute(policy=POLICY, current_baseline="0.20", target_cost="0.20",
                           realization="0.20", v0_status="PARTIAL",
                           simulated_share="0",
                           asserted_share="0")
    assert float(b["overall"]) < float(a["overall"])


def test_asserted_share_is_value_weighted():
    """It was a count over a hardcoded denominator of 24."""
    comps = _components(footprint_origin=estimate.ANALYST_ASSERTED_PRIOR)
    share = estimate.asserted_share(comps)
    total = sum(float(c.value.base) for c in comps)
    asserted = sum(float(c.value.base) for c in comps
                   if c.quantity_origin == estimate.ANALYST_ASSERTED_PRIOR)
    assert abs(float(share) - asserted / total) < 0.001


# ------------------------------------------------- typed scope vs known fact
def test_typed_scope_does_not_read_as_an_assertion():
    """The defect: one origin meant both 'the analyst typed a site count' and
    'someone registered a known fact', so asserted share read ~0.96 on every
    default run and the ceiling fired every time."""
    comps = _components()
    assert float(estimate.asserted_share(comps)) == 0.0
    assert float(estimate.entered_share(comps)) > 0.9


def test_the_asserted_ceiling_no_longer_fires_on_a_default_run():
    comps = _components()
    r = confidence.compute(policy=POLICY, current_baseline="0.80",
                           target_cost="0.80", realization="0.30",
                           asserted_share=estimate.asserted_share(comps),
                           simulated_share="0",
                           v0_status="COMPLETE")
    assert not any("asserted" in c for c in r["ceilings_applied"])


def test_the_asserted_ceiling_still_fires_when_a_known_fact_drives_the_model():
    """It has to remain a control, not just stop being a constant."""
    comps = _components(footprint_origin=estimate.ANALYST_ASSERTED_PRIOR)
    r = confidence.compute(policy=POLICY, current_baseline="0.80",
                           target_cost="0.80", realization="0.30",
                           asserted_share=estimate.asserted_share(comps),
                           simulated_share="0",
                           v0_status="COMPLETE")
    assert any("asserted" in c for c in r["ceilings_applied"])


def test_typed_scope_still_depresses_the_baseline():
    """Splitting the origin must not make typed scope free. It earns no
    evidenced credit, which is the correct mechanism."""
    typed = confidence.derive_components(
        policy=POLICY, priced_spend_pct="1.0",
        origin_breakdown={"ANALYST_ENTERED_SCOPE": {"share": "1.0"}},
        domain_completeness="1.0", prior_recency="1.0", prior_coverage="1.0",
        lever_stage_mix={"V2": "100"})
    evidenced = confidence.derive_components(
        policy=POLICY, priced_spend_pct="1.0",
        origin_breakdown={"EVIDENCED_PUBLIC": {"share": "1.0"}},
        domain_completeness="1.0", prior_recency="1.0", prior_coverage="1.0",
        lever_stage_mix={"V2": "100"})
    assert typed["current_baseline"] < evidenced["current_baseline"]


def test_corroboration_moves_a_fact_from_assertion_to_evidence():
    """Spec 0.1B supersession. This is what makes corroborating worth doing
    rather than merely recorded - and it is why known facts now influence
    confidence at all, which they had stopped doing (C2-08)."""
    from app.domain import known_facts as kf
    assert kf.origin_for("CORROBORATED") == "EVIDENCED_PUBLIC"
    for state in ("PENDING", "UNCORROBORATED"):
        assert kf.origin_for(state) == "ANALYST_ASSERTED_PRIOR"


def test_corroborating_a_fact_raises_confidence():
    """End to end: the same quantity, corroborated versus not."""
    uncorroborated = _components(footprint_origin=estimate.ANALYST_ASSERTED_PRIOR)
    corroborated = _components(footprint_origin="EVIDENCED_PUBLIC")

    def score(comps):
        d = confidence.derive_components(
            policy=POLICY, priced_spend_pct="1.0",
            origin_breakdown=estimate.origin_breakdown(comps),
            domain_completeness="1.0", prior_recency="1.0", prior_coverage="1.0",
            lever_stage_mix={"V2": "100"})
        return float(confidence.compute(
            policy=POLICY, current_baseline=d["current_baseline"],
            target_cost=d["target_cost"], realization=d["realization"],
            asserted_share=estimate.asserted_share(comps),
                           simulated_share="0",
                           v0_status="COMPLETE")["overall"])

    assert score(corroborated) > score(uncorroborated)


def test_shares_do_not_double_count():
    comps = _components(footprint_origin=estimate.ANALYST_ASSERTED_PRIOR)
    total = (float(estimate.asserted_share(comps))
             + float(estimate.entered_share(comps))
             + float(estimate.simulated_share(comps)))
    assert total <= 1.0001


# ------------------------------------------------------- governed policy
def test_seeded_confidence_policy_is_complete_and_valid():
    """Catches the 'added a knob, forgot to seed it' failure, which is the
    C2-03 seed hole in a different guise."""
    POLICY.validate()
    assert POLICY.set_name == "confidence_policy"


def test_seeded_coverage_policy_is_complete_and_valid():
    COV_POLICY.validate()


def test_every_key_the_loader_needs_is_seeded():
    rows = _seeded("confidence_policy")
    needed = ({f"weight_{c}" for c in policy.ConfidencePolicy.COMPONENTS}
              | {f"lever_stage_weight_{s}" for s in policy.ConfidencePolicy.LEVER_STAGES}
              | {f"baseline_driver_{d}" for d in policy.ConfidencePolicy.BASELINE_DRIVERS}
              | {f"target_driver_{d}" for d in policy.ConfidencePolicy.TARGET_DRIVERS}
              | {"component_cap_headroom", "band_a_floor", "band_b_floor", "band_c_floor",
                 "asserted_baseline_confidence_ceiling", "asserted_share_trigger",
                 "simulated_display_badge_threshold", "partial_penalty_factor",
                 "client_confirmed_evidence_weight"})
    assert not (needed - set(rows)), f"unseeded: {sorted(needed - set(rows))}"


def test_a_missing_governed_value_raises_rather_than_defaulting():
    """The point of the fix: no code fallback. A fallback constant is a code
    constant with extra steps."""
    rows = dict(_seeded("confidence_policy"))
    del rows["weight_target_cost"]
    with pytest.raises(policy.PolicyIncomplete):
        policy.ConfidencePolicy.from_rows(rows)


def test_weights_that_do_not_sum_to_one_are_rejected():
    rows = dict(_seeded("confidence_policy"))
    rows["weight_target_cost"] = "0.65"
    with pytest.raises(policy.PolicyInvalid):
        policy.ConfidencePolicy.from_rows(rows)


def test_driver_blends_that_do_not_sum_to_one_are_rejected():
    rows = dict(_seeded("confidence_policy"))
    rows["baseline_driver_evidenced"] = "0.60"
    with pytest.raises(policy.PolicyInvalid):
        policy.ConfidencePolicy.from_rows(rows)


def test_simulated_bands_that_rise_with_share_are_rejected():
    """A ceiling that rises as simulation increases would invert the control."""
    rows = dict(_seeded("confidence_policy"))
    rows["simulated_band_4_ceiling"] = "0.95"
    with pytest.raises(policy.PolicyInvalid):
        policy.ConfidencePolicy.from_rows(rows)


def test_simulated_bands_must_cover_a_full_share():
    rows = dict(_seeded("confidence_policy"))
    rows["simulated_band_4_upper"] = "0.80"
    with pytest.raises(policy.PolicyInvalid):
        policy.ConfidencePolicy.from_rows(rows)


def test_band_floors_must_descend():
    rows = dict(_seeded("confidence_policy"))
    rows["band_b_floor"] = "0.90"
    with pytest.raises(policy.PolicyInvalid):
        policy.ConfidencePolicy.from_rows(rows)


def test_coverage_floor_above_the_minimum_is_rejected():
    """Nothing could ever publish PARTIAL - the band between them would be empty."""
    rows = dict(_seeded("v0_coverage_threshold_set"))
    rows["v0_prior_coverage_floor"] = "0.90"
    with pytest.raises(policy.PolicyInvalid):
        policy.CoveragePolicy.from_rows(rows)


def test_changing_a_governed_weight_changes_the_result():
    """Proof the policy is actually consumed rather than shadowed by constants."""
    base = confidence.compute(policy=POLICY, current_baseline="0.50",
                              target_cost="0.50", realization="0.20",
                           simulated_share="0",
                           asserted_share="0",
                           v0_status="COMPLETE")
    rows = dict(_seeded("confidence_policy"))
    rows["weight_realization"] = "0.60"
    rows["weight_current_baseline"] = "0.20"
    rows["weight_target_cost"] = "0.20"
    shifted = confidence.compute(policy=policy.ConfidencePolicy.from_rows(rows),
                                 current_baseline="0.50", target_cost="0.50",
                                 realization="0.20",
                           simulated_share="0",
                           asserted_share="0",
                           v0_status="COMPLETE")
    assert float(shifted["overall"]) < float(base["overall"])


def test_result_records_which_policy_set_produced_it():
    r = confidence.compute(policy=POLICY, current_baseline="0.5",
                           target_cost="0.5", realization="0.3",
                           simulated_share="0",
                           asserted_share="0",
                           v0_status="COMPLETE")
    assert r["policy_set"] == "confidence_policy"


def test_domain_modules_declare_no_governed_defaults():
    """The regression guard. If a DEFAULTS-style constant reappears in either
    module, this fails - which is what happened last time."""
    from app.domain import confidence as c, coverage as cv
    for mod in (c, cv):
        for name, value in vars(mod).items():
            if name.isupper() and isinstance(value, dict) and value:
                assert name in ("WEIGHTS_DOC",), \
                    f"{mod.__name__}.{name} looks like a governed default"


# ------------------------------------------------------- known-fact sourcing
# The previous tests here exercised select_bindings/bind_quantities, which the
# estimate endpoint never called - two implementations existed and the tested
# one was the dead one. Both are deleted; these now target the wired function.
# Its behaviour needs a session, so the cases live in test_controls_db.py.


# ------------------------------------------------------- C2-07: overloading
def test_a_default_run_no_longer_trips_the_assertion_ceiling():
    """The finding: the typed footprint carried ANALYST_ASSERTED_PRIOR, so
    asserted share read ~0.96 on every run and the ceiling fired every time -
    a constant wearing a control's clothing."""
    comps = _components()
    assert float(estimate.asserted_share(comps)) == 0.0
    assert float(estimate.entered_scope_share(comps)) > 0.9
    r = confidence.compute(policy=POLICY, current_baseline="0.55",
                           target_cost="0.60", realization="0.30",
                           asserted_share=estimate.asserted_share(comps),
                           simulated_share="0",
                           v0_status="COMPLETE")
    assert not any("asserted" in c for c in r["ceilings_applied"])


def test_the_ceiling_still_fires_when_a_known_fact_drives_the_model():
    """It must remain a live control, not merely a silent one."""
    comps = _components(footprint_origin="ANALYST_ASSERTED_PRIOR")
    share = estimate.asserted_share(comps)
    assert float(share) > 0.9
    r = confidence.compute(policy=POLICY, current_baseline="0.55",
                           target_cost="0.60", realization="0.30",
                           asserted_share=share,
                           simulated_share="0",
                           v0_status="COMPLETE")
    assert any("asserted" in c for c in r["ceilings_applied"])


def test_declared_scope_and_an_asserted_claim_are_distinguishable():
    scope = _components()
    asserted = _components(footprint_origin="ANALYST_ASSERTED_PRIOR")
    assert estimate.asserted_share(scope) != estimate.asserted_share(asserted)
    assert set(estimate.origin_breakdown(scope)) != \
        set(estimate.origin_breakdown(asserted))


def test_corroborated_binding_raises_baseline_confidence():
    """End to end for C2-08: the same estate, the same numbers, differing only
    in whether the claim behind them was checked."""
    unchecked = _components(footprint_origin="ANALYST_ASSERTED_PRIOR")
    checked = _components(footprint_origin="EVIDENCED_PUBLIC")

    def _baseline(comps):
        return confidence.derive_components(
            policy=POLICY, priced_spend_pct="0.9",
            origin_breakdown=estimate.origin_breakdown(comps),
            domain_completeness="1.0", prior_recency="1.0", prior_coverage="1.0",
            lever_stage_mix={"V2": "100"})["current_baseline"]

    assert _baseline(checked) > _baseline(unchecked)


def test_binding_records_the_fact_behind_each_component():
    comps = _components(footprint_origin="ANALYST_ASSERTED_PRIOR",
                        driver_refs={"sites": "kf-1", "users": "kf-2"})
    refs = {c.source_ref for c in comps if c.driver == "sites"}
    assert refs == {"kf-1"}, "a figure must be traceable to who asserted it"


def test_confidence_guard_inputs_are_required():
    """simulated_share, asserted_share and v0_status all defaulted to the
    unpenalised state. A caller that forgot one published a higher confidence
    than the evidence supported."""
    import inspect
    params = inspect.signature(confidence.compute).parameters
    for name in ("simulated_share", "asserted_share", "v0_status"):
        assert params[name].default is inspect.Parameter.empty, \
            f"{name} defaults to the permissive value again"


def test_omitting_a_confidence_guard_input_fails_loudly():
    with pytest.raises(TypeError):
        confidence.compute(policy=POLICY, current_baseline="0.5",
                           target_cost="0.5", realization="0.3")
