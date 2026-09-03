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
