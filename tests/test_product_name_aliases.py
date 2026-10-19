"""Research names a product the way the market does, not the way the schema
does. An Openreach "EAD" is an Ethernet leased line; an "FTTP" rental is fibre.

Two regulated wholesale reference offers - the strongest enterprise price
evidence there is, and exactly what domain 19's brief asks for - were declined
because product_in did not know the carrier's word for the product:

    Openreach wholesale EAD1000 (1 Gbps leased line) annual rental - GB  2,262 GBP/year
    Openreach wholesale FTTP 1 Gbps broadband annual rental - GB         1,173.36 GBP/year

Tesco and Shell both carried the EAD1000 rental and both lost it.
"""
import pytest

from app.domain import promotion


@pytest.mark.parametrize("label,product", [
    ("Openreach wholesale EAD1000 (1 Gbps leased line) annual rental - GB", "ETHERNET"),
    ("Openreach EAD100 annual rental", "ETHERNET"),
    ("EAD10 wholesale reference offer", "ETHERNET"),
    ("Openreach wholesale FTTP 1 Gbps broadband annual rental - GB", "BROADBAND_PON"),
])
def test_a_carrier_alias_resolves_to_its_product(label, product):
    assert promotion.product_in(label) == product, label


def test_canonical_tokens_are_unchanged():
    assert promotion.product_in("ETHERNET 1 Gbps MRC") == "ETHERNET"
    assert promotion.product_in("US DIA 100 Mbps MRC") == "DIA"
    assert promotion.product_in("BROADBAND_PON 500 Mbps MRC") == "BROADBAND_PON"


def test_an_alias_that_names_an_already_named_product_is_not_two_products():
    # "ETHERNET" and the "EAD" alias both mean Ethernet - one product, not two.
    assert promotion.product_in("ETHERNET EAD1000 1 Gbps annual rental") == "ETHERNET"


@pytest.mark.parametrize("label", [
    "DIA / EAD blended 1 Gbps rate",          # two products once EAD resolves
    "DIA/MPLS blended rate",                   # the original two-product case
    "EAD1000 and FTTP bundle price",          # Ethernet + fibre
])
def test_two_products_stay_ambiguous(label):
    assert promotion.product_in(label) is None, label


@pytest.mark.parametrize("label", [
    "US BROADBAND 100 Mbps MRC - Lightyear dataset median",   # bare broadband
    "UK 1 Gbps leased line price forecast - metro areas",      # leased line: ambiguous, not mapped
    "Proximus enterprise fibre (FiberMax) monthly list price", # fibre: medium or PON, not mapped
    "market LEAD time for a new circuit",                      # LEAD must not match EAD
    "roll-out AHEAD of plan",                                  # AHEAD must not match EAD
])
def test_ambiguous_or_homograph_labels_are_not_promoted(label):
    assert promotion.product_in(label) is None, label


def test_the_behavioural_win_an_openreach_rental_is_now_a_price():
    """The whole point: the EAD and FTTP annual rentals now classify as price."""
    assert promotion._classify({
        "label": "Openreach wholesale EAD1000 (1 Gbps leased line) annual rental - GB",
        "country": "GB", "unit": "GBP/year", "value": 2262,
        "bandwidth_mbps": 1000}) == "price"
    assert promotion._classify({
        "label": "Openreach wholesale FTTP 1 Gbps broadband annual rental - GB",
        "country": "GB", "unit": "GBP/year", "value": 1173.36,
        "bandwidth_mbps": 1000}) == "price"


def test_the_banking_homograph_is_not_priced():
    """"EAD" is also Exposure At Default. It is a stock in currency, not a rate,
    so even though product_in resolves the word, the rate_period gate keeps it
    out of the price branch - it stays unclassified, as it did before."""
    assert promotion.product_in("Credit risk EAD exposure") == "ETHERNET"  # word resolves
    assert promotion._classify({
        "label": "Credit risk EAD exposure (DE book)", "country": "DE",
        "unit": "EUR", "value": 1200000000}) == "unclassified"
