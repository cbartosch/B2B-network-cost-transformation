"""What a site needs, against what can be delivered where it is.

The archetype says a branch wants DIA at 100 Mbps. It does not say whether
anyone can deliver that at the address, and for a large retail estate that is
the single biggest cost differentiator: a discounter in Munich has fibre or
DOCSIS, the same format in the Eifel may have only DSL or fixed wireless.
Domain 18 researched exactly this and its result reached nothing, so a
4,000-store estate was priced as though every store could take the same
product.
"""
import types

import pytest

from app.domain import serviceability
from app.seed import DENSITY_BANDS, SERVICEABILITY


@pytest.fixture()
def table():
    return {(c, b, p): types.SimpleNamespace(available=a, max_bandwidth_mbps=m)
            for c, b, p, a, m in SERVICEABILITY}


def _resolve(table, density, product="DIA", mbps=100, country="DE"):
    return serviceability.resolve(table=table, country=country,
                                  density=density, product=product,
                                  wanted_mbps=mbps)


# ------------------------------------------------- silence is not a constraint
def test_a_row_with_no_density_prices_exactly_as_before(table):
    """Without a band nothing is known about what can be delivered there, so
    the site gets what it asked for - which is how the model behaved before
    serviceability existed. Treating absence as a constraint would change every
    existing case."""
    out = _resolve(table, None)
    assert out["outcome"] == serviceability.DELIVERED
    assert out["product"] == "DIA" and out["bandwidth_mbps"] == 100


# ------------------------------------------------------- the retail case
def test_an_urban_store_gets_what_it_asks_for(table):
    assert _resolve(table, "URBAN")["outcome"] == serviceability.DELIVERED


def test_a_rural_store_takes_a_different_circuit(table):
    """The finding for a large chain: same country, same format, a different
    product - so a rural store is not a cheaper urban one."""
    out = _resolve(table, "RURAL")
    assert out["outcome"] == serviceability.SUBSTITUTED
    assert out["asked_for"] == "DIA"
    assert out["product"] == "BROADBAND_HFC"
    assert "cannot be delivered in RURAL" in out["note"]


def test_a_tier_that_cannot_be_delivered_is_capped_not_ignored(table):
    """Available but not at the bandwidth asked for. Pricing it at the tier
    nobody can deliver is the same error as pricing an unavailable product."""
    out = _resolve(table, "SUBURBAN", product="ETHERNET", mbps=10_000)
    assert out["outcome"] == serviceability.SUBSTITUTED
    assert out["product"] == "ETHERNET"
    assert out["bandwidth_mbps"] == 500
    assert "only to 500 Mbps" in out["note"]


def test_nothing_deliverable_is_reported_rather_than_priced(table):
    """An estimate that prices a circuit nobody can deliver reads as a number;
    this reads as a question."""
    empty = {("DE", "RURAL", p): types.SimpleNamespace(
        available=False, max_bandwidth_mbps=None)
        for p in serviceability.FALLBACK_ORDER}
    out = serviceability.resolve(table=empty, country="DE", density="RURAL",
                                 product="DIA", wanted_mbps=100)
    assert out["outcome"] == serviceability.UNSERVICEABLE
    assert out["product"] is None and out["bandwidth_mbps"] is None
    assert "reported rather than priced" in out["note"]


def test_the_substitute_is_chosen_for_reliability_not_price(table):
    """A cheaper substitute that cannot carry the traffic is not a substitute,
    so the fallback order is dedicated, then shared, then mobile."""
    order = serviceability.FALLBACK_ORDER
    assert order.index("DIA") < order.index("BROADBAND_HFC")
    assert order.index("BROADBAND_HFC") < order.index("MOBILE_5G")


# ----------------------------------------------------------- the read-out
def test_a_four_thousand_store_estate_reports_what_its_density_did(table):
    """"600 sites take a different product from the one their type asks for"
    is the finding. A percentage is not."""
    outcomes = []
    for band, count in (("DENSE_URBAN", 400), ("URBAN", 1600),
                        ("SUBURBAN", 1400), ("RURAL", 600)):
        outcomes.extend([_resolve(table, band)] * count)

    summary = serviceability.summarise(outcomes)
    assert summary["counts"][serviceability.DELIVERED] == 3400
    assert summary["counts"][serviceability.SUBSTITUTED] == 600
    swap = summary["substitutions"][0]
    assert swap["asked_for"] == "DIA" and swap["delivered"] == "BROADBAND_HFC"
    assert swap["sites"] == 600


def test_the_summary_of_an_empty_estate_says_so():
    assert "No sites" in serviceability.summarise([])["note"]


# ------------------------------------------------------------- the seed data
def test_every_density_band_is_seeded_for_every_country():
    countries = {c for c, *_ in SERVICEABILITY}
    for country in countries:
        for band in DENSITY_BANDS:
            assert any(c == country and b == band
                       for c, b, *_ in SERVICEABILITY), f"{country} {band}"


def test_dedicated_access_thins_out_with_density():
    """The pattern that makes clustering worth doing at all. If every band
    delivered the same products, the dimension would buy nothing and cost a
    join."""
    def deliverable(band):
        return {p for c, b, p, a, _m in SERVICEABILITY
                if c == "DE" and b == band and a}

    assert "DIA" in deliverable("URBAN")
    assert "DIA" not in deliverable("RURAL")
    assert deliverable("RURAL") < deliverable("URBAN")


def test_every_deliverable_product_is_one_the_model_prices():
    """A serviceability row naming a product no prior quotes would substitute
    a circuit into the estate that nothing can price - trading a reported
    constraint for silent unpriced scope."""
    from app.seed import PRIORS
    priced = {p for _c, p, _l, _bw, *_ in PRIORS}
    named = {p for _c, _b, p, a, _m in SERVICEABILITY if a}
    assert named <= priced, f"deliverable but unpriced: {sorted(named - priced)}"


# --------------------------- absence of data is not evidence of absence
def test_an_empty_table_prices_as_asked_rather_than_refusing_everything():
    """The live failure: "10 site(s) in URBAN DE cannot be served at all",
    which is impossible - every product is deliverable there in the seed.

    The table arrived empty, every lookup missed, and the fallback loop found
    nothing available. Absence of data was read as evidence of absence, which
    is the error this module exists to avoid making in the other direction."""
    out = serviceability.resolve(table={}, country="DE", density="URBAN",
                                 product="DIA", wanted_mbps=100)
    assert out["outcome"] == serviceability.DELIVERED
    assert out["product"] == "DIA" and out["bandwidth_mbps"] == 100
    assert "nothing is known" in out["note"]


def test_a_band_missing_from_a_populated_table_is_also_nothing_known():
    """A table with rows for RURAL says nothing about URBAN."""
    table = {("DE", "RURAL", "DIA"): types.SimpleNamespace(
        available=True, max_bandwidth_mbps=100)}
    out = serviceability.resolve(table=table, country="DE", density="URBAN",
                                 product="DIA", wanted_mbps=100)
    assert out["outcome"] == serviceability.DELIVERED


def test_only_a_recorded_band_with_nothing_available_is_unserviceable():
    """The distinction that makes the constraint meaningful: a band somebody
    surveyed and found nothing in, versus a band nobody has looked at."""
    table = {("DE", "URBAN", p): types.SimpleNamespace(
        available=False, max_bandwidth_mbps=None)
        for p in serviceability.FALLBACK_ORDER}
    out = serviceability.resolve(table=table, country="DE", density="URBAN",
                                 product="DIA", wanted_mbps=100)
    assert out["outcome"] == serviceability.UNSERVICEABLE


def test_the_seeded_table_serves_an_urban_german_store(table):
    """A regression guard on the exact case that failed."""
    out = serviceability.resolve(table=table, country="DE", density="URBAN",
                                 product="BROADBAND_HFC", wanted_mbps=200)
    assert out["outcome"] == serviceability.DELIVERED
