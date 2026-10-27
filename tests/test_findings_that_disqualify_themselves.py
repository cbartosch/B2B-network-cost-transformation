"""A finding whose own text disqualifies it must not be offered as a row.

Every case below was promoted into a real estate and had to be caught by a
person reading the evidence afterwards. The disqualifying words were present
in the finding the whole time - in the unit, or in the label - and promotion
read the value and discarded the text that qualified it.

These are decline conditions, not corrections. Classification decides what is
OFFERED; a named person still disposes. Declining costs a reader nothing,
because an unclassified finding still reaches them.
"""
import pytest

from app.domain import promotion


# --------------------------------------------------- an area is not an estate
def test_ninety_acres_is_not_ninety_campuses():
    """bayer US/CAMPUS. Value 90, unit 'acres (14 buildings, 838,000 sq ft)'.

    Bayer is SELLING around 90 acres of its Creve Coeur campus. The premises
    word sat in a parenthetical, where the word test found it.
    """
    assert not promotion.is_premises_unit("acres (14 buildings, 838,000 sq ft)")


def test_an_area_unit_is_never_premises():
    for unit in ("acres", "hectares", "square metres", "sq ft", "km2"):
        assert not promotion.is_premises_unit(unit), unit


def test_a_parenthetical_cannot_rescue_a_non_premises_unit():
    assert not promotion.is_premises_unit("employees (across 12 offices)")


def test_a_parenthetical_does_not_break_a_real_unit():
    """The gate must not start declining findings that were always right."""
    assert promotion.is_premises_unit("stores (all formats)")
    assert promotion.is_premises_unit("sites")
    assert promotion.is_premises_unit("distribution centres")


# ------------------------------------------------ a part is not the whole
def test_a_desk_at_an_office_is_not_an_office():
    """royal-mail GB/STORE. 1,200 Customer Service Points, unit 'parcel
    drop-off desks at delivery offices'. 1,200 CSPs, 1,200 delivery offices,
    1,200 declared SERVICE_POINTs - one estate counted three ways."""
    assert not promotion.is_premises_unit(
        "parcel drop-off desks at delivery offices")


def test_a_premises_noun_before_the_preposition_still_counts():
    """'stores in France' counts stores. The head noun decides."""
    assert promotion.is_premises_unit("stores in France")
    assert promotion.is_premises_unit("retail outlets in operation")


def test_the_within_rule_is_unchanged():
    """basf BE/PLANT: 'production facilities within Antwerp site' - fifty
    plants on one six-square-kilometre site."""
    assert not promotion.is_premises_unit(
        "production facilities within Antwerp site")


# --------------------------------------- one row is keyed on one country
@pytest.mark.parametrize("label", [
    "STORE - total store network across Australia and New Zealand",
    "PLANT - production sites, Germany and France",
    "WAREHOUSE - distribution centres (Belgium/Netherlands)",
])
def test_a_two_country_total_is_not_a_country_count(label):
    """woolworths AU/STORE. The source says '1,729 retail stores across
    Australia and New Zealand'; it was promoted into Australia alone. BASF
    carried the same shape with a North American total read as a US one."""
    assert promotion.spans_two_countries(label), label


def test_one_country_is_not_two():
    assert not promotion.spans_two_countries("STORE - stores in France")
    assert not promotion.spans_two_countries("PLANT - German plants")


def test_a_region_disqualifies_a_count_as_well_as_a_price():
    assert promotion._classify({
        "label": "STORE - retail stores across Western Europe",
        "country": "DE", "unit": "stores", "value": 400}) == "unclassified"


# ------------------------- the label names something the archetype is not
def test_data_centres_are_not_campuses():
    """fraport DE/CAMPUS. 'two data centers with a third as a back-up'
    promoted as 3 campuses, beside a declared DE/DC of 3."""
    assert promotion.contradicts_archetype(
        "Owned/operated data centres at Frankfurt Airport campus", "CAMPUS")
    assert not promotion.contradicts_archetype(
        "Owned/operated data centres at Frankfurt Airport campus", "DC")


def test_hospitals_are_not_offices():
    """nhs-england GB/LARGE_OFFICE. The label named its own fault:
    'Hospital sites (LARGE_OFFICE archetype)'. NHS England's own office
    estate is one building in Leeds; the 1,140 hospitals belong to 207
    separate trusts."""
    assert promotion.contradicts_archetype(
        "Hospital sites (LARGE_OFFICE archetype)", "LARGE_OFFICE")
    assert not promotion.contradicts_archetype(
        "Hospital sites", "CAMPUS")


def test_the_bound_noun_map_stays_small():
    """A general noun-to-archetype map would decline more good rows than bad.

    Fraport's 'CAMPUS - Frankfurt Airport site' names an airport and is
    correctly a campus; Toyota's R&D sites are correctly LARGE_OFFICE.
    Neither may be declined.
    """
    assert not promotion.contradicts_archetype(
        "CAMPUS - Frankfurt Airport site (DE)", "CAMPUS")
    assert not promotion.contradicts_archetype(
        "LARGE_OFFICE - research and development sites", "LARGE_OFFICE")
    assert not promotion.contradicts_archetype(
        "TERMINAL - Greece regional airports", "TERMINAL")


# ------------------------------------------------------- end to end
@pytest.mark.parametrize("q", [
    {"label": "CAMPUS - Creve Coeur campus land (US)", "country": "US",
     "unit": "acres (14 buildings, 838,000 sq ft)", "value": 90},
    {"label": "SERVICE_POINT - Customer Service Points (GB)", "country": "GB",
     "unit": "parcel drop-off desks at delivery offices", "value": 1200},
    {"label": "STORE - network across Australia and New Zealand",
     "country": "AU", "unit": "stores", "value": 1729},
    {"label": "CAMPUS - owned data centres at Frankfurt Airport campus",
     "country": "DE", "unit": "sites", "value": 3},
    {"label": "LARGE_OFFICE - Hospital sites (LARGE_OFFICE archetype)",
     "country": "GB", "unit": "sites", "value": 1140},
])
def test_none_of_these_are_offered_as_footprint(q):
    assert promotion._classify(q) == "unclassified", q["label"]


def test_a_good_row_is_still_offered():
    """The point of all of this is to decline the five, not the sixth."""
    assert promotion._classify({
        "label": "STORE - Carrefour stores in Spain", "country": "ES",
        "unit": "stores", "value": 1595}) == "footprint"


# ------------------------------- premises that belong to somebody else
def test_a_3pl_warehouse_is_not_their_warehouse():
    """bayer US/WAREHOUSE. 'GXO-operated Crop Science warehouse sites
    (US, 3PL)' - the provider's building on the provider's network.

    Note the checker's DISQUALIFYING list held 'third-party' and did not
    fire, because this label says 3PL."""
    assert promotion.not_their_premises(
        "GXO-operated Crop Science warehouse sites (US, 3PL)")


def test_a_minority_stake_is_not_an_estate():
    """aena MX/TERMINAL. 'airports in Mexico (MX) via GAP minority stake' -
    6.55% of GAP, 'minority financial stake only, not operator'."""
    assert promotion.not_their_premises(
        "TERMINAL - airports in Mexico (MX) via GAP minority stake")


def test_a_franchise_is_not_an_estate():
    assert promotion.not_their_premises("franchised UPS Store locations")


def test_operated_by_alone_does_not_decline():
    """'airports operated by Fraport Greece' is the subject's OWN estate.

    The classifier cannot know whose name follows, so the phrase is
    deliberately absent from the pattern. Declining it would cost real rows.
    """
    assert not promotion.not_their_premises(
        "TERMINAL - Greek regional airports operated by Fraport Greece")


@pytest.mark.parametrize("q", [
    {"label": "WAREHOUSE - GXO-operated Crop Science sites (US, 3PL)",
     "country": "US", "unit": "sites", "value": 7},
    {"label": "TERMINAL - airports in Mexico (MX) via GAP minority stake",
     "country": "MX", "unit": "sites", "value": 12},
])
def test_somebody_elses_premises_are_not_offered(q):
    assert promotion._classify(q) == "unclassified", q["label"]


# ------------------------------------------------------- a mixed count
def test_a_count_not_all_managed_by_the_subject_is_mixed():
    """network-rail GB/TERMINAL. 'total stations in GB rail network (owned,
    not all managed by NR)' - 2,593 stations promoted over the 20 Network
    Rail manages, the rest run by train operators."""
    label = ("TERMINAL - total stations in GB rail network "
             "(owned, not all managed by NR)")
    assert promotion.not_their_premises(label)
    assert promotion._classify({"label": label, "country": "GB",
                                "unit": "stations", "value": 2593}) \
        == "unclassified"


def test_a_count_not_all_operated_by_a_third_party_is_mixed_too():
    """The same grammar naming a third party is still a mixed count -
    franchised plus company-run - so it declines either way."""
    assert promotion.not_their_premises(
        "STORE - network (not all operated by franchisees)")


def test_a_bare_negation_is_not_caught():
    """'not operated by franchisees' means the company DOES operate them.
    Without 'all' the verdict depends on whose name follows, which the
    classifier cannot know - so it must not decline."""
    assert not promotion.not_their_premises(
        "STORE - stores not operated by franchisees")
    assert not promotion.not_their_premises(
        "TERMINAL - stations not managed by NR")


def test_the_managed_subset_still_promotes():
    """The 20 stations Network Rail does manage are its estate."""
    assert promotion._classify({
        "label": "TERMINAL - Network Rail directly managed stations",
        "country": "GB", "unit": "sites", "value": 20}) == "footprint"


# ------------------------------------------ an estate that does not exist yet
def test_a_site_that_exists_only_from_a_later_year_is_not_offered():
    """totalenergies BE/WAREHOUSE. Value 1, unit 'sites converting to
    logistics', as_of 'from 2029'.

    TotalEnergies' Antwerp cracker site is to become a logistics hub from
    2029. It was promoted from research as a Belgian warehouse, and only an
    exclusion somebody wrote into the spec by hand kept it out of the estate:
    the date that said it did not exist yet was in as_of, which nothing
    read."""
    q = {"label": "WAREHOUSE – Antwerp cracker site conversion to logistics "
                  "hub (Belgium)",
         "value": "1", "unit": "sites converting to logistics",
         "country": "BE", "as_of": "from 2029"}
    assert promotion.dated_in_the_future(q, this_year=2026)
    assert promotion._classify(q) == "unclassified"


@pytest.mark.parametrize("as_of,future", [
    ("from 2029", True), ("opening in 2028", True), ("2030 onwards", True),
    ("by FY2027", True), ("FY2025", False), ("2026", False),
    ("from 2023", False), ("31 Dec 2025", False), ("unstated", False)])
def test_a_later_year_is_read_wherever_the_date_is_stated(as_of, future):
    q = {"label": "STORE count", "unit": "stores", "as_of": as_of}
    assert promotion.dated_in_the_future(q, this_year=2026) is future
