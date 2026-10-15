"""Market unit prices reaching the rate card.

Domain 19 exists to find them and its brief says so: "This feeds the pricing
benchmark directly". It produced 57 findings across the twenty-company sample
and 10 reached the price bucket. Four of the declines were real market
medians - "US DIA 1 Gbps MRC, 901 USD/month, bandwidth 1000" - turned away on
word order, because the classifier read the product from the leading token
and the agent led with the market.

This is the only channel that can put observed evidence under
reference.unit_cost_prior at grade C. Everything else there is grade E seed.
"""
import pytest

from app.domain.promotion import (_classify, is_monthly_rate_unit,
                                  product_in)


def _q(**kw):
    base = {"label": "DIA 100 Mbps MRC", "value": "492",
            "unit": "USD/month", "country": "US", "bandwidth_mbps": 100}
    base.update(kw)
    return base


# ------------------------------------------- finding the product named

def test_a_product_named_after_the_market_is_found():
    """The four real declines. The brief's example is "DIA 100Mbps MRC" and
    the agent returned "US DIA 100 Mbps MRC"; both name the same product."""
    assert product_in("US DIA 100 Mbps MRC - Lightyear dataset median") == "DIA"
    assert product_in("US MPLS 1 Gbps MRC - North America median") == "MPLS"


def test_median_does_not_contain_dia():
    """The trap in a substring scan, and it is in the real data: every one of
    these findings ends "LIGHTYEAR DATASET MEDIAN". Matched by substring,
    every median broadband price in the sample becomes dedicated internet
    access."""
    assert product_in("US BROADBAND 100 Mbps MRC - dataset MEDIAN") is None
    assert product_in("Immediate provisioning") is None


def test_a_label_naming_two_products_is_declined():
    """A blended rate is neither product, and picking one would be a guess
    in a bucket that writes to the rate card."""
    assert product_in("DIA/MPLS blended enterprise rate") is None
    assert product_in("DIA and ETHERNET combined MRC") is None


def test_a_bare_product_name_still_works():
    assert product_in("DIA 100Mbps MRC") == "DIA"


@pytest.mark.parametrize("label", ["BROADBAND 100 Mbps MRC",
                                   "business broadband MRC"])
def test_broadband_without_a_technology_is_not_a_product(label):
    """The card prices BROADBAND_PON and BROADBAND_HFC separately - fibre and
    cable are different builds at different costs. A finding that says only
    "broadband" cannot choose between them, and three of the sample's US
    prices are exactly this."""
    assert product_in(label) is None


# --------------------------------------- a rate per month, not a duration

@pytest.mark.parametrize("unit", ["USD/month", "usd/month", "EUR per month",
                                  "eur/month/site", "GBP/month", "MRC",
                                  "USD monthly", "usd p/m"])
def test_a_monthly_rate_is_recognised(unit):
    assert is_monthly_rate_unit(unit), unit


@pytest.mark.parametrize("unit", ["months", "month", "mths"])
def test_a_duration_in_months_is_not_a_rate(unit):
    """Domain 20 asks for customary contract lengths and returned 24 of them
    in the sample - "standard leased-line contract term, 36 months". The old
    test was `"month" in unit`, which those satisfy. They were kept out of
    the price bucket only by the product test beside it, so widening that
    without this would price a contract term as a circuit."""
    assert not is_monthly_rate_unit(unit), unit


@pytest.mark.parametrize("unit", ["sites", "operators", "percent", "years",
                                  "EUR", "Mbps"])
def test_an_unrelated_unit_is_not_a_rate(unit):
    assert not is_monthly_rate_unit(unit), unit


# ------------------------------------------------------- the branch

def test_a_well_formed_market_price_classifies():
    assert _classify(_q()) == "price"


def test_the_declined_medians_now_classify():
    """Three of the original four. A Lightyear dataset median is a US
    figure stated with the market first, which is all this was ever
    about."""
    for label, value, mbps in [
            ("US DIA 100 Mbps MRC - Lightyear dataset median", "492", 100),
            ("US DIA 1 Gbps MRC - Lightyear dataset median", "901", 1000),
            ("US DIA 10 Gbps MRC - Lightyear dataset median", "1987", 10000)]:
        assert _classify(_q(label=label, value=value,
                            bandwidth_mbps=mbps)) == "price", label


def test_the_fourth_was_a_north_america_median_and_no_longer_classifies():
    """The one that changed, and why.

    This test swept in "US MPLS 1 Gbps MRC - North America median" with
    three Lightyear medians. The fix it was written for was about word
    order - the classifier read the product from the leading token and the
    agent led with the market - and the regional scope of this one rode
    along unexamined.

    It is the same shape as the two findings that came back when domain 19
    was asked for European prices: "MPLS 100 Mbps MRC - Western Europe /
    Benelux" tagged DE, and a Western Europe business average tagged DE.
    North America is the US, Canada and Mexico; carving it out because the
    US dominates the volume would be the special pleading this codebase
    keeps finding elsewhere.

    The already-approved US/MPLS 1 Gbps row at 1,439 rests on this median.
    Declining it here governs what is promoted next, not what was approved
    before - that row is recorded and stands until somebody revisits it.
    """
    assert _classify(_q(label="US MPLS 1 Gbps MRC - North America median",
                        value="1439", bandwidth_mbps=1000)) == "unclassified"


def test_a_contract_term_is_not_a_price():
    """"STANDARD LEASED-LINE / DIA CONTRACT TERM (GB), 36, months" names a
    product and has a two-letter country. Only the unit keeps it out."""
    assert _classify({"label": "Standard leased-line / DIA contract term (GB)",
                      "value": "36", "unit": "months",
                      "country": "GB"}) == "unclassified"


@pytest.mark.parametrize("country", [None, "", "North America", "EMEA"])
def test_a_price_without_a_two_letter_country_is_declined(country):
    """A rate card row is keyed on a country. "North America DIA 1 Gbps MRC"
    is in the sample and cannot be placed."""
    assert _classify(_q(country=country)) == "unclassified"


# ----------------------------------------------- what the brief promises

def test_the_brief_example_carries_every_field_promotion_requires():
    """The brief asked for bandwidth in prose and showed an example without
    it, so the agent put the tier in the label text where nothing reads it -
    and promotion declines a price with no tier. A brief whose own example
    cannot be promoted teaches the wrong shape."""
    import json
    from app.domain.research_briefs import RESEARCH_BRIEFS

    example = json.loads(RESEARCH_BRIEFS[19]["example"])[0]
    for field in ("label", "value", "unit", "bandwidth_mbps", "country"):
        assert field in example, f"domain 19 example omits {field}"
    assert _classify(example) == "price"
    assert example["bandwidth_mbps"], "a tier of zero is no tier"
