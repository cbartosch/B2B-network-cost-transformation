"""Which units mean "this many premises".

The footprint branch of the promotion classifier tested `"site" in unit`, and
research almost never says "site" - it says what the thing is. Across the
twenty-company sample 35 findings carried an archetype-led label and a
two-letter country and were declined on the unit alone: Inditex's 1,025
Spanish stores, McDonald's 13,706 US restaurants, Tesco's 3,829 GB stores,
Allianz's 2,601 French agencies.

The risk runs the other way too. Two of those 35 were "employees" against an
archetype-led label, which a looser test turns into that many sites, silently.
"""
import pytest

from app.domain.promotion import _classify, is_premises_unit


# ------------------------------------------- units that count premises

@pytest.mark.parametrize("unit", [
    "site", "sites",
    "stores", "hotels", "offices", "restaurants",
    "distribution centres", "distribution centers", "bank branches",
    "agencies (points de vente)", "branch office (Allianz SE holding)",
    "locations (global, all types)", "office locations",
    "outpatient centers", "manufacturing plants", "hospitals",
    "offices or depots", "hotels opened",
])
def test_a_premises_unit_is_recognised(unit):
    assert is_premises_unit(unit), unit


@pytest.mark.parametrize("unit", [
    # People. The one that matters most: an archetype-led label with a
    # headcount becomes that many sites under a blocklist.
    "employees", "employees (lower bound)", "staff", "users",
    # Money, time, share, capacity.
    "EUR/month", "million EUR", "percent of households", "year of award",
    "operators", "principal operators", "Mbps", "percent fibre subscriptions",
])
def test_a_unit_that_is_not_premises_is_declined(unit):
    assert not is_premises_unit(unit), unit


# ------------------------------------- counts of things not yet built

@pytest.mark.parametrize("unit", [
    "hotels in pipeline", "stores planned", "sites under construction",
    "restaurants target", "hotels expected", "stores to open",
    "branches proposed",
])
def test_a_count_of_what_does_not_exist_yet_is_declined(unit):
    """"hotels in pipeline" and "hotels opened" both name premises and only
    one of them is an estate. A planned count promoted as current overstates
    the footprint, and the overstatement is invisible once it is a row."""
    assert not is_premises_unit(unit), unit


def test_opened_is_kept_because_those_exist():
    assert is_premises_unit("hotels opened")


# --------------------------------------------- substring accidents

def test_a_longer_word_containing_a_premises_noun_does_not_match():
    """Word by word, not substring. "employees" must not match "premise",
    and this is the specific way a blocklist would have failed."""
    assert not is_premises_unit("employees")
    assert not is_premises_unit("stationery")
    assert not is_premises_unit("officers")


def test_a_premises_noun_inside_punctuation_still_matches():
    """The real data says "agencies (points de vente)"."""
    assert is_premises_unit("agencies (points de vente)")
    assert is_premises_unit("centres/depots")


# ------------------------------------------- end to end on the branch

def _q(**kw):
    base = {"label": "STORE - GB estate", "value": "120",
            "unit": "stores", "country": "GB"}
    base.update(kw)
    return base


def test_an_archetype_with_a_premises_unit_and_a_country_classifies():
    assert _classify(_q()) == "footprint"


def test_an_archetype_with_a_headcount_does_not():
    assert _classify(_q(unit="employees")) == "unclassified"


@pytest.mark.parametrize("country", [None, "", "FR+BE", "Global", "EMEA"])
def test_no_usable_country_still_declines(country):
    """Unchanged and deliberate. A footprint row is keyed on a country, so
    one without is not a near-miss to be rescued - promoting it would mean
    inventing where the sites are, and "FR+BE" would mean inventing the
    split between them. 37 of the sample's declines are this, correctly."""
    assert _classify(_q(country=country)) == "unclassified"


# ------------------------------- countable things that are not an estate

@pytest.mark.parametrize("unit", [
    "substations", "network nodes", "towers", "street cabinets",
    "smart meters", "circuits", "connections", "customers",
])
def test_a_grid_or_network_asset_is_not_a_premises_count(unit):
    """Iberdrola's research returns 30,000 GB substations. Promoting that
    replaces a 2,769-site estate with a grid inventory priced as if every
    one took an enterprise circuit.

    test_promotion.test_a_count_whose_unit_is_not_sites_is_still_declined
    makes this call already and it is the right one. Asserted again here
    because widening the unit gate is exactly what would quietly undo it -
    it did, on the first attempt.
    """
    assert not is_premises_unit(unit), unit


def test_an_excluded_asset_beside_a_premises_noun_still_declines():
    """"substations and depots" names one of each. The asset decides, so a
    premises noun sitting beside it cannot rescue the count."""
    assert not is_premises_unit("substations and depots")
