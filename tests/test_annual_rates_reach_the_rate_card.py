"""A published price is not always monthly, and the rate card is.

Three price findings were discarded on their unit alone, two of them the
best price evidence in the whole set:

    GB ETHERNET 1 Gbps EAD wholesale annual rental (Openreach)  2,358 GBP/year
    GB ETHERNET 100 Mbps EAD Sensitive LA wholesale annual rental 1,764 GBP/year

Those are REGULATED WHOLESALE REFERENCE OFFERS - published, auditable, and
exactly the enterprise pricing that is otherwise locked inside NDAs. The
first divides to 196.50 a month against the 203 GBP independently sourced
for that same cell, which is the closest corroboration this rate card has.

They were thrown away because the unit said year.
"""
import pytest

from app.domain import promotion


@pytest.mark.parametrize("unit", [
    "GBP/year", "EUR per year", "USD/yr", "GBP annual rental",
    "EUR per annum", "USD p.a.",
])
def test_an_annual_rate_is_recognised(unit):
    assert promotion.rate_period(unit) == "YEAR", unit


@pytest.mark.parametrize("unit", [
    "EUR/month", "USD per month", "GBP MRC", "EUR/month/site",
])
def test_a_monthly_rate_is_still_monthly(unit):
    assert promotion.rate_period(unit) == "MONTH", unit


@pytest.mark.parametrize("unit", ["36 months", "months", "years", "3 years"])
def test_a_term_is_not_a_rate(unit):
    """'36 months' is a contract length. The sibling trap one period up is
    '3 years', and it must not become a yearly rate either."""
    assert promotion.rate_period(unit) is None, unit


def test_an_annual_price_is_offered_as_a_price():
    assert promotion._classify({
        "label": "GB ETHERNET 1 Gbps EAD wholesale annual rental (Openreach)",
        "country": "GB", "unit": "GBP/year", "value": 2358,
        "bandwidth_mbps": 1000}) == "price"


def test_the_monthly_gate_itself_is_unchanged():
    """is_monthly_rate_unit keeps its old meaning - other callers and the
    existing tests rely on it answering only about months."""
    assert promotion.is_monthly_rate_unit("EUR/month")
    assert not promotion.is_monthly_rate_unit("GBP/year")
    assert not promotion.is_monthly_rate_unit("36 months")


# ------------------------------------ a household line is not an estate price
@pytest.mark.parametrize("label", [
    "BROADBAND_PON 100 Mbps MRC France (consumer residential Fttx)",
    "BROADBAND_PON 500 Mbps MRC Spain (residential, Digi)",
    "BROADBAND_PON 1000 Mbps MRC - SG residential (StarHub 24-month)",
])
def test_a_consumer_price_is_not_an_enterprise_circuit_price(label):
    """Domain 19's reject clause opens 'Consumer broadband pricing is not an
    enterprise circuit price. Say which market a price describes.' The agent
    complies - in the label - and the classifier never read the answer.

    EUR 10 a month is a household line. Seven reached the rate card, and two
    of them produced the most extreme seed-versus-sourced ratios in the set.
    """
    assert promotion.names_a_consumer_market(label), label
    assert promotion._classify({
        "label": label, "country": "FR", "unit": "EUR/month",
        "value": 26, "bandwidth_mbps": 100}) == "unclassified"


def test_an_enterprise_price_is_still_offered():
    assert promotion._classify({
        "label": "ETHERNET EAD 1 Gbps annual rental wholesale (Openreach)",
        "country": "GB", "unit": "GBP/year", "value": 2358,
        "bandwidth_mbps": 1000}) == "price"
    assert promotion._classify({
        "label": "DIA 100 Mbps MRC - US market benchmark", "country": "US",
        "unit": "USD/month", "value": 492, "bandwidth_mbps": 100}) == "price"
