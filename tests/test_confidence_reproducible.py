"""CR-08: a confidence score that can be checked rather than taken.

F10 says the breakdown is missing. It is not - `confidence.compute` has
always published the three components, the ceilings it applied and the
weighted figure. What it did not publish were the **weights**, so a reader
holding the output could see 0.344 and the parts it came from and still not
get from one to the other.

These pin the acceptance criterion literally: the score reproduces from the
published output and nothing else. No policy object, no database.
"""
import itertools

import pytest

from app.domain import confidence, policy as policy_mod
from app.domain.money import D


def _seeded(set_name):
    """The values that actually ship, so a seed change that breaks the
    reproduction is caught here rather than in production. Same helper the
    integrity suite uses."""
    from app.seed import THRESHOLDS
    return {k: v for sn, k, v in THRESHOLDS if sn == set_name}


POLICY = policy_mod.ConfidencePolicy.from_rows(_seeded("confidence_policy"))


def _recompute(out):
    """Includes the PARTIAL penalty, which the first version of this helper
    omitted - every case below used v0_status=COMPLETE, so the gap was
    invisible here and surfaced only when the validation gate ran against a
    real set with three PARTIAL companies in it."""
    """`overall`, from the published fields alone.

    Deliberately written against the output dict rather than by importing
    the engine's own arithmetic - a reimplementation that called the same
    helper would pass whatever the helper did.
    """
    comps = {k: D(out[k])
             for k in ("current_baseline", "target_cost", "realization")}
    weighted = sum(v * D(out["weights"][k]) for k, v in comps.items())
    capped = min(weighted,
                 min(comps.values()) + D(out["component_cap_headroom"]))
    if (out.get("v0_status") == "PARTIAL"
            and "unpriced_scope_confidence_penalty=one_band"
            in (out.get("ceilings_applied") or [])):
        floors = {k.upper(): D(v) for k, v in out["band_floors"].items()}
        lowered = next((floors[k] - D("0.01") for k in ("A", "B", "C")
                        if k in floors and capped >= floors[k]), None)
        if lowered is None:
            lowered = capped * D(out["partial_penalty_factor"])
        capped = min(capped, lowered)
    return weighted, capped


def _band_from(out, score):
    # Keys as the engine holds them: band() reads f["A"], not f["a"].
    floors = {k.upper(): D(v) for k, v in out["band_floors"].items()}
    if score >= floors["A"]:
        return "A - Confirmed"
    if score >= floors["B"]:
        return "B - Supported"
    if score >= floors["C"]:
        return "C - Directional"
    return "D - Indicative"


CASES = list(itertools.product(
    ("0.20", "0.55", "0.90"),      # current_baseline
    ("0.30", "0.60", "0.95"),      # target_cost
    ("0.10", "0.30", "0.80"),      # realization
    ("0.05", "0.40"),              # simulated_share
))


@pytest.mark.parametrize("cb,tc,rz,sim", CASES)
def test_the_score_reproduces_from_the_published_output(cb, tc, rz, sim):
    out = confidence.compute(
        policy=POLICY, current_baseline=cb, target_cost=tc, realization=rz,
        simulated_share=sim, asserted_share="0.00", v0_status="COMPLETE")

    weighted, capped = _recompute(out)
    assert abs(weighted - D(out["weighted"])) < D("0.001"), out
    assert abs(capped - D(out["overall"])) < D("0.001"), out


@pytest.mark.parametrize("cb,tc,rz,sim", CASES)
def test_the_band_reproduces_from_the_published_floors(cb, tc, rz, sim):
    out = confidence.compute(
        policy=POLICY, current_baseline=cb, target_cost=tc, realization=rz,
        simulated_share=sim, asserted_share="0.00", v0_status="COMPLETE")
    assert _band_from(out, D(out["overall"])) == out["band"]


def test_the_output_carries_everything_needed_to_check_it():
    """A reader with the JSON and no access to the policy table."""
    out = confidence.compute(
        policy=POLICY,
        current_baseline="0.55", target_cost="0.60", realization="0.30",
        simulated_share="0.10", asserted_share="0.00", v0_status="COMPLETE")
    for key in ("current_baseline", "target_cost", "realization", "weights",
                "component_cap_headroom", "band_floors", "weighted",
                "overall", "band", "ceilings_applied", "arithmetic"):
        assert key in out, f"missing {key}"
    assert set(out["weights"]) == {"current_baseline", "target_cost",
                                   "realization"}


def test_a_ceiling_is_applied_to_the_component_before_it_is_published():
    """Otherwise the reproduction would not work: a reader recomputing from
    pre-ceiling components would get a higher score than the one published
    and conclude the engine was wrong."""
    out = confidence.compute(
        policy=POLICY, current_baseline="0.95", target_cost="0.95",
        realization="0.95", simulated_share="0.90", asserted_share="0.00",
        v0_status="COMPLETE")
    assert out["ceilings_applied"], "this case should hit a ceiling"
    # The published target_cost is the capped one, so the arithmetic closes.
    _, capped = _recompute(out)
    assert abs(capped - D(out["overall"])) < D("0.001")


# ------------------------------------------- process is not evidence

PROCESS_METRICS = ("research_minutes", "research_sources", "queries_used",
                   "captures_used", "sources_count", "domains_requested")


def test_no_process_metric_is_an_input_to_confidence():
    """CR-08's one substantive requirement: time spent and pages fetched
    must not raise a score on their own. An agent that searched for an hour
    and found nothing has not made the estimate more certain, and a model
    that rewarded effort would reward exactly the wrong thing."""
    import inspect

    src = inspect.getsource(confidence)
    for metric in PROCESS_METRICS:
        assert metric not in src, (
            f"{metric} appears in the confidence model; effort is not "
            f"evidence")


def test_the_confidence_signature_takes_only_evidence_and_scope():
    import inspect

    params = set(inspect.signature(confidence.compute).parameters)
    assert params == {
        "policy", "current_baseline", "target_cost", "realization",
        "simulated_share", "asserted_share", "v0_status",
        "unsourced_price_share", "drivers"}, sorted(params)

@pytest.mark.parametrize("cb,tc,rz", [
    ("0.20", "0.30", "0.10"), ("0.55", "0.60", "0.30"),
    ("0.90", "0.95", "0.80"), ("0.45", "0.50", "0.40")])
def test_a_partial_estimate_reproduces_too(cb, tc, rz):
    """The case the first version of these tests missed entirely.

    Every parameterised case above passes v0_status=COMPLETE, so the
    one-band penalty was never exercised and partial_penalty_factor was
    never needed - and it was not published. Three of the twenty sample
    companies are PARTIAL, and the validation gate failed all three against
    an engine that was computing them correctly.
    """
    out = confidence.compute(
        policy=POLICY, current_baseline=cb, target_cost=tc, realization=rz,
        simulated_share="0.10", asserted_share="0.00", v0_status="PARTIAL")
    _, capped = _recompute(out)
    assert abs(capped - D(out["overall"])) < D("0.001"), out


def test_the_partial_penalty_publishes_both_of_its_halves():
    """It has two branches - drop to the floor below, or scale when there is
    no floor below - and only the first was derivable from the output."""
    out = confidence.compute(
        policy=POLICY, current_baseline="0.30", target_cost="0.30",
        realization="0.30", simulated_share="0.10", asserted_share="0.00",
        v0_status="PARTIAL")
    assert out["v0_status"] == "PARTIAL"
    assert out["partial_penalty_factor"]
    assert "partial_penalty_factor" in out["arithmetic"]
