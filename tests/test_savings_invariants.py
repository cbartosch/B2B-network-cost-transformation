"""CR-07: the four properties a bottom-up savings build has to have.

Each one is a way the arithmetic could be wrong while every individual
number still looked reasonable, which is why they are tested as properties
rather than against expected figures:

* **additivity** - the total is the sum of its levers and nothing else
* **monotonic addition** - more addressable value cannot save less
* **perturbation independence** - switching one lever off moves no other
* **scenario identity** - all three hold in every scenario, not only the base

A build that violates any of them can still reconcile on the case somebody
checked by hand.
"""
import pytest

from app.domain import estimate
from app.domain.money import D, Range

TOL = D("0.000001")


def _component(key, layer, base, *, origin="ANALYST_ENTERED_SCOPE",
               service_class="IPVPN", product="IPVPN"):
    return estimate.Component(
        key=key, layer=layer, driver="circuits", quantity=100,
        quantity_origin=origin, unit_cost_origin="BENCHMARK_PRIOR",
        product=product, role="PRIMARY", service_class=service_class,
        access_technology="ETHERNET_FIBRE",
        value=Range(D(base) * D("0.8"), D(base), D(base) * D("1.3")))


def _lever(lever_id, layers, low, base, high, scenario="B", **over):
    out = {"lever_id": lever_id, "family": lever_id, "description": "",
           "cost_layers": list(layers), "saving_low": low,
           "saving_base": base, "saving_high": high,
           "applies_to_service_classes": None,
           "applies_to_access_technologies": None,
           "applies_to_platform_products": None, "scenario": scenario}
    out.update(over)
    return out


def _estate():
    return [_component("L0_circuits", "L0", "1000000"),
            _component("L1_transport", "L1", "300000"),
            _component("L2_overlay", "L2", "200000"),
            _component("OPS_ops", "OPS", "150000")]


def _levers(scenario="B"):
    return [
        _lever("LEV-A", ["L0"], "0.05", "0.10", "0.15", scenario),
        _lever("LEV-B", ["L1"], "0.08", "0.12", "0.18", scenario),
        _lever("LEV-C", ["L2", "OPS"], "0.10", "0.20", "0.30", scenario),
    ]


def _run(components=None, levers=None, scenario="B"):
    out = estimate.scenarios(components or _estate(),
                             levers or _levers(scenario))
    return out[scenario]


# ----------------------------------------------------------------- additivity

@pytest.mark.parametrize("bound", ["low", "base", "high"])
def test_the_total_is_the_sum_of_its_levers(bound):
    """On every bound, not only the base. A build that sums on the base and
    derives the bounds some other way reconciles on the number anybody
    checks and nowhere else."""
    sc = _run()
    lever_sum = sum((D(l[f"saving_{bound}"]) for l in sc["levers"]), D(0))
    assert abs(lever_sum - D(sc["gross_run_rate_savings"][bound])) < TOL, (
        bound, lever_sum, sc["gross_run_rate_savings"][bound])


def test_the_evidence_split_sums_to_the_lever_total():
    """A split that loses or duplicates value would let a headline exclude
    unevidenced saving and still overstate itself."""
    sc = _run()
    for lev in sc["levers"]:
        parts = (D(lev["saving_on_specified_baseline"])
                 + D(lev["saving_on_simulated_baseline"]))
        assert abs(parts - D(lev["saving_base"])) < TOL, lev["lever_id"]
    total = (D(sc["saving_on_specified_baseline"])
             + D(sc["saving_on_simulated_baseline"]))
    assert abs(total - D(sc["gross_run_rate_savings"]["base"])) < TOL


def test_the_scenario_split_is_rounded_once_not_per_lever():
    """The scenario's split was summed from each lever's figure after it had
    been rounded to the cent, so it drifted while the headline - rounded once -
    did not. Iberdrola's three levers put the halves 0.02 off its headline,
    and the validation gate refused to publish the sample summary.

    Four levers here, each leaving 0.004 in both halves. Rounded per lever,
    the halves lose 0.032 between them and miss the headline by 0.03. Summed
    first, they can miss it by no more than the gate's cent."""
    layers = ("L0", "L1", "L2", "L4")
    components = []
    for layer in layers:
        components += [
            _component(f"{layer}_specified", layer, "1000.04"),
            _component(f"{layer}_simulated", layer, "1000.04",
                       origin="SIMULATED")]
    sc = _run(components=components,
              levers=[_lever(f"LEV-{layer}", [layer], "0.05", "0.1", "0.15")
                      for layer in layers])
    halves = (D(sc["saving_on_specified_baseline"])
              + D(sc["saving_on_simulated_baseline"]))
    headline = D(sc["gross_run_rate_savings"]["base"])
    assert abs(halves - headline) <= D("0.01"), (
        f"the halves sum to {halves} against a headline of {headline}")


# --------------------------------------------------------- monotonic addition

def test_raising_a_levers_reach_strictly_increases_the_total():
    """More addressable value cannot save less. A compounding build that
    double-counts an overlap can fail this while every lever looks sane."""
    base = _run()
    stronger = _levers()
    stronger[0] = _lever("LEV-A", ["L0"], "0.05", "0.20", "0.30")
    after = _run(levers=stronger)
    assert (D(after["gross_run_rate_savings"]["base"])
            > D(base["gross_run_rate_savings"]["base"]))


def test_adding_baseline_a_lever_acts_on_strictly_increases_the_total():
    bigger = _estate()
    bigger.append(_component("L0_extra", "L0", "500000"))
    assert (D(_run(components=bigger)["gross_run_rate_savings"]["base"])
            > D(_run()["gross_run_rate_savings"]["base"]))


# -------------------------------------------------- perturbation independence

def test_switching_one_lever_off_moves_no_other_levers_saving():
    """The property that catches a shared accumulator. If LEV-C's saving
    changes when LEV-A is removed, the two are reading each other's state
    and the attribution is fiction."""
    before = {l["lever_id"]: l["saving_base"] for l in _run()["levers"]}

    without_a = [l for l in _levers() if l["lever_id"] != "LEV-A"]
    after = {l["lever_id"]: l["saving_base"]
             for l in _run(levers=without_a)["levers"]}

    assert "LEV-A" not in after
    for lid, value in after.items():
        assert value == before[lid], (
            f"removing LEV-A changed {lid}: {before[lid]} -> {value}")


def test_a_lever_acting_on_an_absent_layer_changes_nothing():
    """Offered and inapplicable must be free. A lever with no baseline that
    nonetheless perturbs the total is drawing from somewhere it should not."""
    base = _run()
    with_dead = _levers() + [_lever("LEV-DEAD", ["L4"], "0.5", "0.9", "0.99")]
    after = _run(levers=with_dead)
    assert (after["gross_run_rate_savings"]["base"]
            == base["gross_run_rate_savings"]["base"])
    assert any(n["lever_id"] == "LEV-DEAD"
               for n in after["levers_not_applicable"])


# ------------------------------------------------------------ scenario identity

@pytest.mark.parametrize("scenario", ["A", "B", "C", "D"])
def test_every_property_holds_in_every_scenario(scenario):
    """Not only the base scenario. The levers differ per scenario and so
    does the order they compound in, which is exactly where an
    order-dependent bug hides."""
    sc = _run(levers=_levers(scenario), scenario=scenario)

    lever_sum = sum((D(l["saving_base"]) for l in sc["levers"]), D(0))
    assert abs(lever_sum - D(sc["gross_run_rate_savings"]["base"])) < TOL

    split = (D(sc["saving_on_specified_baseline"])
             + D(sc["saving_on_simulated_baseline"]))
    assert abs(split - D(sc["gross_run_rate_savings"]["base"])) < TOL

    stronger = _levers(scenario)
    stronger[0] = _lever("LEV-A", ["L0"], "0.05", "0.20", "0.30", scenario)
    assert (D(_run(levers=stronger, scenario=scenario)
               ["gross_run_rate_savings"]["base"])
            > D(sc["gross_run_rate_savings"]["base"]))


# ----------------------------------------------------- the residual cannot sink

def test_levers_stacked_past_the_baseline_never_drive_it_negative():
    """Three levers at 90% of one layer is 243% of its value if they add,
    and a negative residual if they are subtracted without compounding."""
    greedy = [_lever(f"LEV-{i}", ["L0"], "0.8", "0.9", "0.95")
              for i in range(3)]
    sc = _run(levers=greedy)
    assert D(sc["target_tco"]["base"]) >= 0
    assert (D(sc["gross_run_rate_savings"]["base"])
            <= D("1000000") + TOL), "saving exceeds the layer it acts on"


def test_a_saving_on_drawn_value_is_reported_separately():
    """The headline must not quietly include value nobody measured."""
    mixed = [_component("L0_counted", "L0", "1000000"),
             _component("L0_drawn", "L0", "1000000", origin="SIMULATED")]
    sc = _run(components=mixed,
              levers=[_lever("LEV-A", ["L0"], "0.05", "0.10", "0.15")])
    assert D(sc["saving_on_simulated_baseline"]) > 0
    assert D(sc["saving_on_specified_baseline"]) > 0
    assert (abs(D(sc["saving_on_simulated_baseline"])
                - D(sc["saving_on_specified_baseline"])) < TOL), (
        "half the baseline is drawn, so half the saving should be")
