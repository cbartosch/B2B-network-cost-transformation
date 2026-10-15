"""A thing counted WITHIN something else is a part, not a place.

BASF's Antwerp row: 50 sites on a unit reading "production facilities
within Antwerp site", from a source saying about 50 Produktionsbetriebe
on one six-square-kilometre site. Promoted as fifty Belgian premises,
each priced at the PLANT profile with its own access circuit and backup.

Both premises nouns in that unit are real - "facilities" and "site" -
which is why the word test passed it. The disqualifying word is "within",
and it sits in the unit, where the label rules cannot see it.
"""
import pytest

from app.domain.promotion import is_premises_unit


@pytest.mark.parametrize("unit", [
    "production facilities within Antwerp site",
    "production units closed within Ludwigshafen PLANT",
    "new production plant (within existing site)",
    "halls inside the data centre",
])
def test_a_count_within_a_site_is_not_a_count_of_sites(unit):
    assert not is_premises_unit(unit), unit


@pytest.mark.parametrize("unit", [
    "sites",
    "distribution centres",
    "agencies (points de vente)",
    "production sites",
    "branches",
])
def test_an_ordinary_premises_unit_still_passes(unit):
    assert is_premises_unit(unit), unit


def test_the_three_real_cases_are_all_caught():
    """Every within/inside unit in the sample set and in the fresh BASF
    research is a sub-unit count. There are no false positives to trade
    against - which is why this is a unit rule rather than a report."""
    for unit, value in [("production facilities within Antwerp site", 50),
                        ("production units closed within Ludwigshafen PLANT", 3),
                        ("new production plant (within existing site)", 1)]:
        assert not is_premises_unit(unit), f"{unit} ({value})"


def test_it_is_the_unit_that_carries_the_word_not_the_label():
    """The label reads "PLANT (Belgium - Antwerp Verbund site production
    facilities)" and names no disqualifying word at all. Reading only
    labels would have missed every one of these."""
    label = "PLANT (Belgium - Antwerp Verbund site production facilities)"
    assert "within" not in label.lower()
    assert not is_premises_unit("production facilities within Antwerp site")
