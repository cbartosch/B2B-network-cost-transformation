"""What it costs to get from the current estate to the target one.

Audit finding P3. The model had no one-time, transition or dual-running cost at
all: every scenario reported `gross_run_rate_savings` and nothing net, so
payback could not be computed and a reader comparing scenarios was comparing
prizes without their price.

The bias probe called the understatement total rather than partial, which was
right - and the direction matters. Adding these costs makes the model more
conservative, which is the correct direction for an addition that carries no
transaction evidence behind it.
"""
import types

import pytest

from app.domain import transition
from app.domain.money import D, Range

POLICY = types.SimpleNamespace(
    one_time_cost_per_site_low="400", one_time_cost_per_site_base="900",
    one_time_cost_per_site_high="1800", dual_running_months="3",
    sites_migrated_per_month="120", evidence_grade="E")


def _net(sites=1842, gross=("1000000", "1500000", "2000000"),
         monthly="700000", policy=POLICY):
    return transition.net(
        gross_annual=Range(D(gross[0]), D(gross[1]), D(gross[2])),
        sites=sites, monthly_run_rate=D(monthly), policy=policy)


def test_a_gross_saving_is_no_longer_reported_as_the_answer():
    """The finding. 1,842 sites at 900 apiece is 1.66m of one-time cost against
    a 1.5m annual saving - so the first year is negative, and every scenario
    used to report the 1.5m alone."""
    out = _net()
    assert D(out["total_transition_cost"]["base"]) > D("1500000")
    assert D(out["first_year_net"]) < 0, (
        "a transition costing more than a year's saving must show a negative "
        "first year")


def test_payback_pairs_the_high_cost_with_the_low_saving():
    """Deliberately crossed. The pessimistic case is the high cost and the low
    saving, because those are the same world - pairing high with high reports a
    payback nobody could have."""
    out = _net()
    months = out["payback_months"]
    assert months["optimistic"] < months["base"] < months["pessimistic"]


def test_a_saving_that_cannot_repay_the_cost_has_no_payback():
    """None, not a very large number. A 400-month payback reads as a long one;
    the truth is that it never repays."""
    out = _net(gross=("0", "0", "0"))
    assert out["payback_months"]["base"] is None


def test_the_programme_duration_is_reported_beside_the_payback():
    """A payback of fifteen months means nothing if the programme takes
    sixteen: savings do not begin until a site is cut over."""
    out = _net()
    assert out["programme_months"] == 16          # 1842 sites at 120 a month
    assert "not a schedule" in out["note"]


def test_dual_running_scales_with_duration_not_only_size():
    """A programme migrating 120 sites a month has 120 sites paying twice at
    any moment, for as long as it runs. Doubling the estate at the same rate
    doubles the duration, not the sites in flight."""
    slow = types.SimpleNamespace(**{**POLICY.__dict__,
                                    "sites_migrated_per_month": "30"})
    fast = _net(policy=POLICY)["dual_running_cost"]["base"]
    slower = _net(policy=slow)["dual_running_cost"]["base"]
    assert D(slower) < D(fast), (
        "fewer sites in flight at once is less duplicated billing per month")
    assert _net(policy=slow)["programme_months"] > _net()["programme_months"]


def test_the_one_time_cost_is_a_band_not_a_point():
    """A single number for a cost nobody has quoted implies a precision that
    does not exist, and the low and high decide whether a payback sits inside a
    contract term."""
    out = _net()
    otc = out["one_time_cost"]
    assert D(otc["low"]) < D(otc["base"]) < D(otc["high"])


def test_the_payback_says_it_is_modelled_and_what_it_omits():
    """A payback computed from grade E assumptions is a modelled payback. An
    omission that is stated is a limitation; one that is not is an error."""
    out = _net()
    assert "evidence grade E" in out["payback_basis"]
    assert "not a business case" in out["payback_basis"]
    for omitted in ("CPE purchase or refresh",
                    "early-termination liability on the existing contracts",
                    "internal programme and project cost"):
        assert omitted in out["not_modelled"], omitted


def test_a_single_site_estate_does_not_divide_by_zero():
    out = _net(sites=1, monthly="500")
    assert out["programme_months"] == 1


def test_an_empty_estate_is_not_charged_a_transition():
    out = _net(sites=0, monthly="0")
    assert D(out["one_time_cost"]["base"]) == 0
    assert D(out["dual_running_cost"]["base"]) == 0


@pytest.mark.parametrize("field", [
    "one_time_cost", "dual_running_cost", "total_transition_cost",
    "gross_run_rate_savings"])
def test_every_money_figure_is_a_band(field):
    """A point estimate for anything here would be false precision."""
    out = _net()
    assert set(out[field]) == {"low", "base", "high"}

# ----------------------------------------------- what the estimate feeds it
# The transition model was complete, tested and unreachable: TransitionPolicy
# could not be constructed, and no call site built one. These pin the two
# numbers the estimate has to supply, because getting either wrong is silent -
# a wrong site count produces a plausible payback rather than an error.

def _component(key, layer, driver, quantity, base):
    from app.domain.estimate import Component
    return Component(
        key=key, layer=layer, driver=driver, quantity=quantity,
        quantity_origin="ANALYST_ENTERED_SCOPE",
        unit_cost_origin="BENCHMARK_PRIOR", product="X", role="PRIMARY",
        service_class="IPVPN", access_technology="ETHERNET_FIBRE",
        value=Range(D(base) * D("0.8"), D(base), D(base) * D("1.3")))


def test_the_site_count_is_read_back_from_the_components():
    """Rather than passed alongside them, where it could disagree."""
    from app.domain import estimate
    assert estimate.site_count([
        _component("L0_circuits", "L0", "circuits", 9999, "1000"),
        _component("OPS_operations", "OPS", "sites", 4000, "2000")]) == 4000


def test_a_split_site_line_is_summed_not_counted_twice():
    """_split() divides a site-driven line across origins, so the OPS layer
    arrives as several components that together describe one estate."""
    from app.domain import estimate
    assert estimate.site_count([
        _component("OPS_a", "OPS", "sites", 2400, "1200"),
        _component("OPS_b", "OPS", "sites", 1600, "800")]) == 4000


def test_two_site_driven_layers_describe_one_estate_not_two():
    """Both the OPS line and the L2 overlay are driven by the site count. A
    flat sum over driver=="sites" would report 8,000 sites for a 4,000-site
    estate, double every one-time cost and halve every payback."""
    from app.domain import estimate
    assert estimate.site_count([
        _component("OPS_a", "OPS", "sites", 2400, "1200"),
        _component("OPS_b", "OPS", "sites", 1600, "800"),
        _component("L2_overlay", "L2", "sites", 4000, "500")]) == 4000


def test_an_estate_with_no_site_line_reports_no_sites():
    """And so gets no transition block, which is the honest outcome rather
    than a payback computed from a site count nobody has."""
    from app.domain import estimate
    assert estimate.site_count([
        _component("L0_circuits", "L0", "circuits", 120, "1000")]) == 0


def test_the_run_rate_handed_over_is_monthly():
    """Component values are annual - every rate is scaled by MONTHS where it
    is built - and dual_running works in months, because a month is how long
    a site spends paying for two circuits. Handing it the annual figure would
    overstate dual running twelvefold."""
    from app.domain import estimate
    comps = [_component("OPS_operations", "OPS", "sites", 10, "1200")]
    assert estimate.monthly_run_rate(comps) == D("100")
    assert estimate.total(comps).base == D("1200")
