"""A regional average is not a country price, whatever the country says.

The research brief for domain 19 forbids a region: "a region such as
'North America' or 'EMEA' cannot be priced". It polices the `country`
FIELD, and the scope is actually stated in the label.

Asking domain 19 for European prices returned exactly two findings tagged
DE, and both were Western Europe averages:

    MPLS 100 Mbps MRC - Western Europe / Benelux        EUR 1,000
    100 Mbps MRC - Western Europe business (avg)        USD 148 PPP

Each satisfied rule (3) by putting a country code on a regional figure.
"""
import pytest

from app.domain import promotion


def _price(label, country="DE"):
    return promotion._classify({
        "label": label, "value": 1000, "unit": "EUR/month",
        "country": country, "bandwidth_mbps": 100})


@pytest.mark.parametrize("label", [
    "MPLS 100 Mbps MRC - Western Europe / Benelux",
    "DIA 100 Mbps MRC - Europe average",
    "MPLS 1 Gbps - EMEA benchmark",
    "DIA 100 Mbps - North America",
    "ETHERNET 1 Gbps - APAC",
    "DIA 100 Mbps - Nordics",
    "DIA 100 Mbps - DACH region",
    "MPLS 100 Mbps - Latin America",
    "DIA 100 Mbps - global average",
])
def test_a_regional_label_is_not_a_country_price(label):
    assert _price(label) == "unclassified", label


@pytest.mark.parametrize("label", [
    "DIA 100 Mbps MRC - Germany",
    "MPLS 100 Mbps MRC - Deutsche Telekom business tariff",
    "ETHERNET 1 Gbps MRC - France (Orange published)",
])
def test_a_country_price_still_classifies(label):
    assert _price(label) == "price", label


def test_the_currency_unit_does_not_read_as_europe():
    """"EUR/month" contains "EU". Matching on substrings would have
    declined every euro-denominated price in the card."""
    assert not promotion.names_a_region("DIA 100 Mbps MRC Germany EUR/month")
    assert _price("DIA 100 Mbps MRC Germany") == "price"


def test_the_two_findings_that_prompted_this_are_both_caught():
    assert promotion.names_a_region(
        "MPLS 100 Mbps MRC - Western Europe / Benelux")
    assert promotion.names_a_region(
        "BROADBAND_PON 100 Mbps MRC - Western Europe business (avg)")
