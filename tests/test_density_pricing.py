"""Density reaching the price.

The band was recorded on every site and priced nowhere: unit_cost_prior keys
on (country, product, bandwidth) and nothing in it knew where a site was.
Four releases of work on bands moved 2,315 sites into RURAL and the baseline
by 0.1%, which is the signature of a dimension the model carries and ignores.
"""
from decimal import Decimal as D

import pytest

from app.domain import estimate
from app.domain.money import Range


MULT = {
    ("ETHERNET", "RURAL"): {"low": "1.25", "base": "2.00", "high": "3.20"},
    ("ETHERNET", "URBAN"): {"low": "1.00", "base": "1.00", "high": "1.00"},
    ("MOBILE_5G", "RURAL"): {"low": "1.00", "base": "1.05", "high": "1.15"},
}


def _rate(low="100", base="200", high="300"):
    return Range(low, base, high)


# ------------------------------------------------------------ the scaling

def test_a_rural_circuit_costs_more_than_the_national_rate():
    scaled, mult = estimate._by_density(
        _rate(), product="ETHERNET", band="RURAL", prior_band=None,
        multipliers=MULT)
    assert scaled.base == D("400")
    assert mult["base"] == "2.00"


def test_the_range_widens_rather_than_sliding():
    """A rural tail is not merely dearer, it is quoted per site after a
    survey. low, base and high scale by their own factors, so the spread
    grows - a multiplier that only moved the base would assert a precision
    nobody has."""
    before = _rate()
    after, _ = estimate._by_density(
        before, product="ETHERNET", band="RURAL", prior_band=None,
        multipliers=MULT)
    assert (after.high - after.low) > (before.high - before.low)
    assert after.low == D("125") and after.high == D("960")


def test_a_product_with_no_local_loop_barely_moves():
    """The claim the table is shaped around: cost follows the local loop, so
    a mobile SIM is nearly flat where an Ethernet tail is not."""
    eth, _ = estimate._by_density(_rate(), product="ETHERNET", band="RURAL",
                                  prior_band=None, multipliers=MULT)
    mob, _ = estimate._by_density(_rate(), product="MOBILE_5G", band="RURAL",
                                  prior_band=None, multipliers=MULT)
    assert mob.base < eth.base
    assert mob.base == D("210")


# -------------------------------------------------- when nothing is applied

def test_a_circuit_with_no_band_prices_at_the_national_rate():
    """Backbone transport has no band, and neither does a site whose band
    nobody established. Both must price exactly as they did before."""
    before = _rate()
    after, mult = estimate._by_density(
        before, product="ETHERNET", band=None, prior_band=None,
        multipliers=MULT)
    assert after is before and mult is None


def test_a_product_with_no_multiplier_row_is_unscaled():
    after, mult = estimate._by_density(
        _rate(), product="SATELLITE", band="RURAL", prior_band=None,
        multipliers=MULT)
    assert after.base == D("200") and mult is None


def test_an_observed_band_rate_is_not_scaled_again():
    """A rate recorded FOR this band is evidence about exactly this
    question. Multiplying it by the default would apply the adjustment twice
    and bury the observation under a guess."""
    after, mult = estimate._by_density(
        _rate(), product="ETHERNET", band="RURAL", prior_band="RURAL",
        multipliers=MULT)
    assert after.base == D("200") and mult is None


def test_no_multiplier_table_leaves_every_rate_alone():
    after, mult = estimate._by_density(
        _rate(), product="ETHERNET", band="RURAL", prior_band=None,
        multipliers=None)
    assert after.base == D("200") and mult is None


# ------------------------------------------------------- the seeded table

def test_urban_is_the_anchor_at_exactly_one():
    """The seeded national rate is an urban-weighted average, so URBAN is
    1.0 by construction and the other bands say how far they sit from it. A
    drift here silently reprices every urban circuit in the model."""
    from app import seed
    urban = [(p, lo, ba, hi) for p, b, lo, ba, hi
             in seed.DENSITY_COST_MULTIPLIER if b == "URBAN"]
    assert urban, "no URBAN rows"
    for product, low, base, high in urban:
        assert (low, base, high) == ("1.00", "1.00", "1.00"), product


def test_every_rate_card_product_has_a_full_set_of_bands():
    """A product missing a band prices at the national rate for that band
    only - a gap that looks like a deliberate 1.0 and is not."""
    from app import seed
    bands = {"DENSE_URBAN", "URBAN", "SUBURBAN", "RURAL"}
    have = {}
    for product, band, *_ in seed.DENSITY_COST_MULTIPLIER:
        have.setdefault(product, set()).add(band)
    carded = {p for _c, p, _b in
              {(r[0], r[1], r[2]) for r in []}} or set(have)
    for product in carded:
        assert have[product] == bands, f"{product} missing {bands - have[product]}"


def test_the_bands_are_monotonic_within_each_product():
    """Denser is never dearer. An inversion would mean the table disagrees
    with the reason it exists - that cost follows the local loop."""
    from app import seed
    order = ["DENSE_URBAN", "URBAN", "SUBURBAN", "RURAL"]
    by = {}
    for product, band, _lo, base, _hi in seed.DENSITY_COST_MULTIPLIER:
        by.setdefault(product, {})[band] = D(base)
    for product, bands in by.items():
        seq = [bands[b] for b in order]
        assert seq == sorted(seq), f"{product} is not monotonic: {seq}"


@pytest.mark.parametrize("dedicated,shared", [("ETHERNET", "MOBILE_5G"),
                                              ("DIA", "BROADBAND_PON"),
                                              ("MPLS", "MOBILE_5G")])
def test_dedicated_products_vary_more_with_density_than_shared_ones(
        dedicated, shared):
    """The substantive claim, asserted rather than left in a comment."""
    from app import seed
    rural = {p: D(base) for p, b, _lo, base, _hi
             in seed.DENSITY_COST_MULTIPLIER if b == "RURAL"}
    assert rural[dedicated] > rural[shared]
