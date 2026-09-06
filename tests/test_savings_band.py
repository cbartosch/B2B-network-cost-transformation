"""What a saving band is, and what it is not.

Red-team finding. `saving = current - target` crossed the bounds - low minus
other's high - which is correct for two independent distributions. The target
is not independent: it is the current cost with a lever share taken off it.

Worse, the cut was already crossed once before the subtraction crossed again.
Two crossings compound rather than cancel. On a 0.15/0.25/0.35 lever against a
cost band of 80,000/100,000/130,000 that produced:

    saving  -30,500 / 25,000 / 78,000
    true     12,000 / 25,000 / 45,500

The optimistic case was overstated by 71%, and the floor was reported as a
negative saving that cannot occur. Every scenario in the system carried it.
"""
import types

import pytest

from app.domain.estimate import Component, scenarios
from app.domain.money import D, Range

COST = Range(D("80000"), D("100000"), D("130000"))


def _component(**over):
    fields = dict(key="L0_x", layer="L0", driver="circuits", quantity=100,
                  quantity_origin="ANALYST_ENTERED_SCOPE",
                  unit_cost_origin="BENCHMARK_PRIOR", product="X",
                  role="PRIMARY", service_class="IPVPN",
                  access_technology="ETHERNET_FIBRE", value=COST)
    fields.update(over)
    return Component(**fields)


def _lever(lever_id="LEV-X", low="0.15", base="0.25", high="0.35"):
    return {"lever_id": lever_id, "family": lever_id, "description": "",
            "cost_layers": ["L0"], "saving_low": low, "saving_base": base,
            "saving_high": high, "applies_to_service_classes": None,
            "applies_to_access_technologies": None,
            "applies_to_platform_products": None, "scenario": "B"}


def _scenario(levers=None):
    return scenarios([_component()], levers or [_lever()])["B"]


def test_each_bound_is_paired_with_its_own_share():
    """The low saving is the low cost meeting the low share. Pairing the low
    cost with a target derived from the high cost describes no world."""
    saving = _scenario()["gross_run_rate_savings"]
    assert D(saving["low"]) == D("80000") * D("0.15")
    assert D(saving["base"]) == D("100000") * D("0.25")
    assert D(saving["high"]) == D("130000") * D("0.35")


def test_the_floor_of_a_saving_is_never_negative_for_a_positive_lever():
    """A lever that takes between 15% and 35% cannot cost money. The crossed
    subtraction reported -30,500 on exactly this input."""
    saving = _scenario()["gross_run_rate_savings"]
    assert D(saving["low"]) > 0


def test_the_optimistic_case_is_not_inflated_by_the_crossing():
    """78,000 against a true 45,500 - a 71% overstatement, and the tail a
    reader takes as the upside."""
    saving = _scenario()["gross_run_rate_savings"]
    assert D(saving["high"]) == D("45500.00")
    assert D(saving["high"]) < D("78000")


def test_saving_and_target_reconcile_at_base():
    """The number anyone checks. The bounds do not subtract - that is a fact
    about correlated uncertainty rather than an inconsistency - but the base
    must tie exactly."""
    out = _scenario()
    assert (D("100000") - D(out["target_tco"]["base"])
            == D(out["gross_run_rate_savings"]["base"]))


def test_the_target_band_is_unchanged_because_it_was_correct():
    """The lowest target is the lowest cost meeting the biggest cut, which is
    a world that can happen. Only the saving was wrong."""
    target = _scenario()["target_tco"]
    assert D(target["low"]) == D("80000") * (1 - D("0.35"))
    assert D(target["high"]) == D("130000") * (1 - D("0.15"))


def test_two_levers_compound_rather_than_add_on_every_bound():
    """The waterfall property has to survive the fix. 100,000 x 0.12 then
    88,000 x 0.25 is 34,000, not 37,000."""
    out = _scenario([_lever("A", "0.06", "0.12", "0.18"),
                     _lever("B", "0.15", "0.25", "0.35")])
    saving = out["gross_run_rate_savings"]
    assert D(saving["base"]) == D("34000.00")
    assert D(saving["base"]) < D("100000") * D("0.37")


@pytest.mark.parametrize("levers", [
    [_lever()],
    [_lever("A", "0.06", "0.12", "0.18"), _lever("B", "0.15", "0.25", "0.35")],
    [_lever("A", "0.00", "0.00", "0.00")],
])
def test_a_saving_band_is_always_ordered(levers):
    saving = _scenario(levers)["gross_run_rate_savings"]
    assert D(saving["low"]) <= D(saving["base"]) <= D(saving["high"])


def test_a_zero_lever_saves_nothing_on_every_bound():
    """A degenerate case the crossing got wrong too: with a 0% share the
    crossed low was 80,000 - 130,000 = -50,000."""
    saving = _scenario([_lever("A", "0.00", "0.00", "0.00")])
    assert D(saving["low"]) == 0
    assert D(saving["high"]) == 0


def test_the_saving_is_not_computed_by_subtracting_the_bands():
    """The guard for the finding itself."""
    import inspect

    source = inspect.getsource(scenarios)
    assert "saving = current - target" not in source
    assert "matched" in source, (
        "the saving must be accumulated with matched pairing")


# ------------------- a lever that reduces a rate is capped by the headroom
def _sized(bearer, committed, **over):
    fields = dict(key="L0_x", layer="L0", driver="circuits", quantity=100,
                  quantity_origin="ANALYST_ENTERED_SCOPE",
                  unit_cost_origin="BENCHMARK_PRIOR", product="X",
                  role="PRIMARY", service_class="IPVPN",
                  access_technology="ETHERNET_FIBRE",
                  bearer_mbps=bearer, committed_mbps=committed, value=COST)
    fields.update(over)
    return Component(**fields)


def _rightsizing():
    return {"lever_id": "LEV-BANDWIDTH-001", "family": "Right-sizing",
            "description": "", "cost_layers": ["L0"], "saving_low": "0.03",
            "saving_base": "0.07", "saving_high": "0.12",
            "applies_to_service_classes": ["IPVPN"],
            "applies_to_access_technologies": None,
            "applies_to_platform_products": None, "scenario": "B"}


def test_right_sizing_cannot_take_more_than_the_headroom():
    """Its whole job is to reduce a committed rate, and it applied a flat
    3/7/12% with no knowledge of what the committed rate was - so a 100/95
    branch, with a twentieth to give back, was right-sized as hard as a 100/50
    one.

    The band stays the band; the headroom is a ceiling on it."""
    from app.domain.estimate import headroom_share, scenarios

    tight = _sized(100, 95)
    assert headroom_share(tight) == D("0.05")
    saving = scenarios([tight], [_rightsizing()])["B"][
        "gross_run_rate_savings"]
    # 5% of the base cost, not the lever's 7%
    assert D(saving["base"]) == D("100000") * D("0.05")


def test_a_circuit_with_room_takes_the_full_band():
    """A ceiling that binds everywhere is not a ceiling, it is a different
    lever."""
    from app.domain.estimate import scenarios

    saving = scenarios([_sized(100, 50)], [_rightsizing()])["B"][
        "gross_run_rate_savings"]
    assert D(saving["base"]) == D("100000") * D("0.07")


def test_a_component_with_no_pair_behaves_exactly_as_before():
    """A snapshot written before 4.189 carries no bearer, and a best-effort
    circuit has no committed rate to reduce. Neither is a reason to change the
    answer."""
    from app.domain.estimate import headroom_share, scenarios

    assert headroom_share(_sized(None, None)) is None
    saving = scenarios([_sized(None, None)], [_rightsizing()])["B"][
        "gross_run_rate_savings"]
    assert D(saving["base"]) == D("100000") * D("0.07")


def test_a_fully_committed_circuit_has_no_headroom():
    """Committed equal to the bearer is a circuit sold at its size. None
    rather than zero: zero would be a share and this is the absence of one."""
    from app.domain.estimate import headroom_share

    assert headroom_share(_sized(100, 100)) is None


def test_only_the_named_lever_is_bounded():
    """Repricing a circuit does not depend on its headroom - a better rate for
    the same service is available whatever the commitment."""
    from app.domain.estimate import HEADROOM_BOUNDED, scenarios

    assert HEADROOM_BOUNDED == ("LEV-BANDWIDTH-001",)
    reprice = {**_rightsizing(), "lever_id": "LEV-REPRICE-001",
               "applies_to_service_classes": None}
    saving = scenarios([_sized(100, 95)], [reprice])["B"][
        "gross_run_rate_savings"]
    assert D(saving["base"]) == D("100000") * D("0.07")


def test_both_ledgers_use_the_bounded_share():
    """The target and the saving are two ledgers over one lever. If only one
    is bounded they disagree, and the base reconciliation breaks."""
    from app.domain.estimate import scenarios

    out = scenarios([_sized(100, 95)], [_rightsizing()])["B"]
    assert (D("100000") - D(out["target_tco"]["base"])
            == D(out["gross_run_rate_savings"]["base"]))
