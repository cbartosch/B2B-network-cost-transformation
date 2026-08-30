"""The ANCHOR method: estimating from a disclosed cost line.

The build-up path prices an enumerated estate. For a large group there is
usually no public site-level circuit inventory - DHL's 2025 accounts disclose
EUR 213M of telecommunication costs and no circuit mix at all - so build-up
prices nothing, coverage computes 0% and the gate refuses for a reason that
has nothing to do with the evidence available. These cover the second method
and, as importantly, what it refuses to pretend.
"""
from decimal import Decimal as D

import pytest

from app.domain import anchor_estimate as ae
from app.domain.policy import AnchorPolicy, PolicyInvalid


def _policy(low="0.45", base="0.55", high="0.65", mix=None, floor="0.25"):
    return AnchorPolicy(
        set_name="t", addressable_share_low=D(low),
        addressable_share_base=D(base), addressable_share_high=D(high),
        layer_mix=mix or {"L0": D("0.60"), "L2": D("0.10"),
                          "L4": D("0.20"), "OPS": D("0.10")},
        min_addressable_share=D(floor))


def test_the_pool_is_a_governed_share_of_the_anchor_not_the_anchor():
    """A disclosed telecom line is an upper bound - voice, mobile, non-WAN
    services, out-of-scope sites. Treating it as the addressable pool would
    overstate the prize by roughly double."""
    comps, basis = ae.build_pool_components(
        anchor_value=D("213000000"), policy=_policy(),
        anchor_origin=ae.ANCHOR_DISCLOSED)
    pool = basis["addressable_pool"]
    assert float(pool["base"]) == pytest.approx(117_150_000, rel=1e-6)
    assert float(pool["low"]) < float(pool["base"]) < float(pool["high"])
    assert float(pool["high"]) < 213_000_000


def test_the_pool_splits_across_the_layers_the_levers_act_on():
    """The seeded levers name cost layers. Splitting the pool the same way is
    what lets one savings engine serve both methods."""
    comps, _ = ae.build_pool_components(
        anchor_value=D("100000000"), policy=_policy(),
        anchor_origin=ae.ANCHOR_DISCLOSED)
    assert {c.layer for c in comps} == {"L0", "L2", "L4", "OPS"}
    total = sum(float(c.value.base) for c in comps)
    assert total == pytest.approx(55_000_000, rel=1e-6)


def test_a_layer_mix_that_does_not_sum_to_one_is_refused():
    """A pool that does not account for itself silently drops or double-counts
    spend, and the total would still look plausible."""
    with pytest.raises(PolicyInvalid, match="sum to 1"):
        _policy(mix={"L0": D("0.60"), "L2": D("0.10"),
                     "L4": D("0.10"), "OPS": D("0.10")}).validate()


def test_an_unordered_share_band_is_refused():
    with pytest.raises(PolicyInvalid, match="ordered"):
        _policy(low="0.70", base="0.55", high="0.65").validate()


def test_a_typed_anchor_reports_partial_not_complete():
    """The whole estimate rests on the anchor. If that number is an assertion
    rather than a disclosed figure, the estimate cannot present as fully
    evidenced however good the rest of it is."""
    _, basis = ae.build_pool_components(
        anchor_value=D("213000000"), policy=_policy(),
        anchor_origin=ae.ANCHOR_ASSERTED)
    cov = ae.assess_coverage(basis=basis, policy=_policy(),
                             anchor_origin=ae.ANCHOR_ASSERTED)
    assert cov["status"] == "PARTIAL"
    assert "assertion" in cov["reason"]


def test_a_disclosed_anchor_reports_complete():
    _, basis = ae.build_pool_components(
        anchor_value=D("213000000"), policy=_policy(),
        anchor_origin=ae.ANCHOR_DISCLOSED)
    cov = ae.assess_coverage(basis=basis, policy=_policy(),
                             anchor_origin=ae.ANCHOR_DISCLOSED)
    assert cov["status"] == "COMPLETE"


def test_an_addressable_share_below_the_floor_is_refused():
    """Explaining under a quarter of your own anchor is not an estimate of it."""
    pol = _policy(low="0.05", base="0.10", high="0.15", floor="0.25")
    _, basis = ae.build_pool_components(
        anchor_value=D("213000000"), policy=pol,
        anchor_origin=ae.ANCHOR_DISCLOSED)
    cov = ae.assess_coverage(basis=basis, policy=pol,
                             anchor_origin=ae.ANCHOR_DISCLOSED)
    assert cov["status"] == "REFUSED"


def test_circuit_coverage_is_zero_and_says_why():
    """Zero here means nothing was enumerated, not that pricing failed.
    Comparing it with a BUILD_UP coverage figure compares two questions."""
    _, basis = ae.build_pool_components(
        anchor_value=D("213000000"), policy=_policy(),
        anchor_origin=ae.ANCHOR_DISCLOSED)
    cov = ae.assess_coverage(basis=basis, policy=_policy(),
                             anchor_origin=ae.ANCHOR_DISCLOSED)
    assert cov["circuit_coverage_pct"] == "0.000"
    assert cov["coverage_basis"] == "ADDRESSABLE_SHARE_OF_PUBLIC_ANCHOR"
    assert "not because they could not be priced" in cov["note"]


def test_a_zero_anchor_cannot_support_an_estimate():
    with pytest.raises(ae.AnchorUnusable):
        ae.build_pool_components(anchor_value=D("0"), policy=_policy(),
                                 anchor_origin=ae.ANCHOR_DISCLOSED)
