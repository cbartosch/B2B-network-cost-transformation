"""Tiers filled in between two priced anchors on the rate card.

The card jumped 1,000 Mbps straight to 10,000. match_prior takes the cheapest
tier at or above the requirement - correctly, because substituting downward
understates - so a 1,650 Mbps circuit was priced at the 10 Gbps rate. 161
circuits in the twenty-company sample sit in that gap, and once the rural
multiplier arrived the overshoot was doubled on top of itself.
"""
import math
from decimal import Decimal as D

import pytest

from app import seed


#: The tiers under test, read from the configuration rather than restated.
#: A hardcoded list breaks on every legitimate change to the tier set and
#: says nothing about why a tier is there - which is how the EMEA assertion
#: in test_regional_fallback failed the moment this gap was filled.
TARGETS = {target for target, _lo, _hi in seed._INTERPOLATED_TIERS}
ANCHORS = {target: (lo, hi) for target, lo, hi in seed._INTERPOLATED_TIERS}


def _by_key(rows):
    return {(c, p, int(bw)): (float(lo), float(ba), float(hi))
            for c, p, _l, bw, lo, ba, hi in rows}


@pytest.fixture(scope="module")
def priced():
    return _by_key(seed.PRIORS)


# ------------------------------------------------- the method, checked

@pytest.mark.parametrize("target,low_t,high_t,tolerance", [
    (250, 100, 500, 3.0),
    (500, 250, 1000, 5.0),
])
def test_the_interpolation_reproduces_tiers_the_card_already_holds(
        priced, target, low_t, high_t, tolerance):
    """The claim that makes these rows a derivation rather than an invention.

    Predict a tier the card already has from its two neighbours and compare.
    If the method could not reproduce what is there, it would have no
    standing to produce what is not.
    """
    errors = []
    for (country, product, bw), value in priced.items():
        if bw != target:
            continue
        lo = priced.get((country, product, low_t))
        hi = priced.get((country, product, high_t))
        if not lo or not hi:
            continue
        f = math.log(target / low_t) / math.log(high_t / low_t)
        predicted = lo[1] * ((hi[1] / lo[1]) ** f)
        errors.append(abs(predicted - value[1]) / value[1] * 100)
    assert errors, f"no rows to validate {target} against"
    errors.sort()
    median = errors[len(errors) // 2]
    assert median < tolerance, f"median error {median:.1f}% predicting {target}"


# ------------------------------------------------------- what was added

def test_every_configured_tier_is_present(priced):
    added = {bw for (_c, _p, bw) in priced if bw in TARGETS}
    assert added == TARGETS, f"configured {TARGETS}, found {added}"


def test_a_derived_tier_sits_between_its_anchors(priced):
    """Sublinear pricing, so a 2 Gbps rate is above 1 Gbps and well below 10 -
    an interpolation landing outside its anchors is not an interpolation."""
    checked = 0
    for (country, product, bw), value in priced.items():
        if bw not in TARGETS:
            continue
        low_t, high_t = ANCHORS[bw]
        lo = priced[(country, product, low_t)]
        hi = priced[(country, product, high_t)]
        for i in range(3):
            assert lo[i] <= value[i] <= hi[i], (country, product, bw)
        checked += 1
    assert checked, "no derived tiers found"


def test_every_derived_tier_is_cheaper_than_the_one_it_replaces(priced):
    """The whole point. A 1,650 Mbps circuit used to pay the 10 Gbps rate."""
    for (country, product, bw), value in priced.items():
        if bw not in TARGETS:
            continue
        assert value[1] < priced[(country, product, ANCHORS[bw][1])][1]


def test_the_tiers_stay_monotonic_in_bandwidth(priced):
    """More bandwidth never costs less, or match_prior's "cheapest tier at or
    above" would pick a higher tier than needed and be right to."""
    by_pair = {}
    for (country, product, bw), value in priced.items():
        by_pair.setdefault((country, product), {})[bw] = value[1]
    for pair, tiers in by_pair.items():
        ordered = [tiers[b] for b in sorted(tiers)]
        assert ordered == sorted(ordered), f"{pair} is not monotonic: {tiers}"


def test_nothing_is_extrapolated_past_the_top_of_a_card(priced):
    """A tier past the last anchor has nothing holding it down - a much
    weaker claim than sitting between two. DIA and the broadband products
    stop at 1 Gbps and must gain nothing here."""
    for (country, product, bw) in priced:
        if bw in TARGETS:
            assert (country, product, ANCHORS[bw][1]) in priced, (
                f"{country} {product} {bw} has no upper anchor")


def test_an_existing_tier_is_never_overwritten():
    """Interpolation fills gaps. A row somebody set, or a sourced rate that
    superseded one, must survive untouched."""
    seen = {}
    for c, p, _l, bw, _lo, ba, _hi in seed.PRIORS:
        key = (c, p, int(bw))
        if key in seen:
            assert seen[key] == ba, f"duplicate row for {key}"
        seen[key] = ba


# --------------------------------------------------------- provenance

def test_a_derived_tier_is_not_presented_as_a_seeded_position():
    """`price_basis` separates them so a reader retunes the right thing: an
    assumption is replaced with a quote, an interpolation disappears when
    its anchors are quoted."""
    assert seed._DERIVED_TIER_KEYS, "no derived tiers"
    for country, product, bw in seed._DERIVED_TIER_KEYS:
        assert bw in TARGETS
        assert product == "ETHERNET", (
            "only ETHERNET spans 1-10 Gbps on this card; a tier elsewhere "
            "would be an extrapolation wearing an interpolation's label")


def test_every_row_at_a_new_tier_is_labelled_interpolated():
    """The key set is settled against the FINISHED pipeline, not against
    PRIORS at the moment of interpolation.

    Computed mid-pipeline first, and that was wrong by 22 rows: _regional_tiers
    runs later and derives EMEA, APAC and the rest from the country rows, so
    the regions inherited the new tiers correctly and were then labelled SEED
    - rows derived twice over, presenting as positions somebody set.
    """
    at_new_tier = {(c, p, int(bw)) for c, p, _l, bw, _lo, _ba, _hi
                   in seed.PRIORS if int(bw) in TARGETS}
    assert at_new_tier == seed._DERIVED_TIER_KEYS, (
        "unlabelled: " + str(sorted(at_new_tier - seed._DERIVED_TIER_KEYS)[:5]))


def test_regions_inherit_the_new_tiers(priced):
    """A region prices what its member countries price. Having filled the
    gap for countries, leaving regions with a 1-to-10 Gbps cliff would put
    the overshoot back for every country that falls through to one."""
    for region in ("EMEA", "APAC", "AMER"):
        tiers = {bw for (c, p, bw) in priced
                 if c == region and p == "ETHERNET"}
        assert TARGETS <= tiers, f"{region} missing {TARGETS - tiers}"


def test_a_tier_priced_before_the_fill_is_never_relabelled():
    """The guard on the second half of the rule. A sourced rate supersedes by
    key, and must keep its own basis rather than inherit this one."""
    for key in seed._DERIVED_TIER_KEYS:
        assert key not in seed._PRE_INTERPOLATION_KEYS
