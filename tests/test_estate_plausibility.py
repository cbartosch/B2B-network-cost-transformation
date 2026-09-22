"""Is this estate one a company could actually have?

A German footprint arrived with 3,800 data centres, 19,000 large offices and no
service points, priced at USD 1.21 billion - and every control passed. Coverage
read 1.000 and the page said "V0 COMPLETE - all coverage tests passed."

Coverage asks whether the estate can be PRICED. Nothing asked whether it is
POSSIBLE. The green light is what made it dangerous: a number nobody believes
is harmless, and a number with every gate satisfied is not.
"""
from pathlib import Path

import pytest

from app.domain import estate_plausibility as plausibility


BROKEN = [
    {"country": "DE", "archetype": "BRANCH", "sites": 2660},
    {"country": "DE", "archetype": "BRANCH", "sites": 5320},
    {"country": "DE", "archetype": "DC", "sites": 2280},
    {"country": "DE", "archetype": "DC", "sites": 1520},
    {"country": "DE", "archetype": "LARGE_OFFICE", "sites": 7600},
    {"country": "DE", "archetype": "LARGE_OFFICE", "sites": 11400},
    {"country": "DE", "archetype": "WAREHOUSE", "sites": 3040},
    {"country": "DE", "archetype": "WAREHOUSE", "sites": 3800},
    {"country": "DE", "archetype": "WAREHOUSE", "sites": 5700},
]


def test_the_footprint_that_priced_at_a_billion_is_refused():
    result = plausibility.assess(BROKEN, registered_total=38000)
    assert not result["plausible"]
    kinds = {f["kind"] for f in result["findings"]}
    assert "IMPOSSIBLE_COUNT" in kinds
    assert "IMPLAUSIBLE_COMPOSITION" in kinds
    assert "OVER_ALLOCATED" in kinds


def test_thousands_of_data_centres_in_one_country_is_impossible():
    """A very large enterprise runs single-digit data centres per country.
    3,800 is four orders of magnitude out and nothing objected."""
    result = plausibility.assess(BROKEN)
    dc = [f for f in result["findings"]
          if f.get("archetype") == "DC" and f["kind"] == "IMPOSSIBLE_COUNT"]
    assert dc, "3,800 data centres in one country must be refused"
    assert "WAREHOUSE" in dc[0]["likely_cause"] or \
        "STORE" in dc[0]["likely_cause"], "it must say what they probably are"


def test_a_large_estate_of_offices_is_implausible():
    """An estate of 38,000 sites is not 44% large offices. At that scale the
    sites are outlets, depots or cabinets, whatever the industry."""
    result = plausibility.assess(BROKEN)
    composition = [f for f in result["findings"]
                   if f["kind"] == "IMPLAUSIBLE_COMPOSITION"]
    assert composition
    assert "shape is wrong" in composition[0]["likely_cause"]


def test_over_allocation_against_the_register_is_caught():
    """43,320 allocated against a registered 38,000 - two proposals in the
    table at once."""
    result = plausibility.assess(BROKEN, registered_total=38000)
    over = [f for f in result["findings"] if f["kind"] == "OVER_ALLOCATED"]
    assert over and over[0]["sites"] == 43320


@pytest.mark.parametrize("name,footprint", [
    ("postal network", [
        {"country": "DE", "archetype": "STORE", "sites": 34700},
        {"country": "DE", "archetype": "WAREHOUSE", "sites": 2660},
        {"country": "DE", "archetype": "TERMINAL", "sites": 38},
        {"country": "DE", "archetype": "DC", "sites": 8}]),
    ("tower company", [
        {"country": "ES", "archetype": "NETWORK_SITE", "sites": 40000},
        {"country": "ES", "archetype": "LARGE_OFFICE", "sites": 12},
        {"country": "ES", "archetype": "DC", "sites": 4}]),
    ("retail bank", [
        {"country": "FR", "archetype": "BRANCH", "sites": 1800},
        {"country": "FR", "archetype": "LARGE_OFFICE", "sites": 60},
        {"country": "FR", "archetype": "DC", "sites": 6}]),
    ("pharma", [
        {"country": "GB", "archetype": "CAMPUS", "sites": 9},
        {"country": "GB", "archetype": "LARGE_OFFICE", "sites": 22}]),
    ("chemicals", [
        {"country": "DE", "archetype": "PLANT", "sites": 140},
        {"country": "DE", "archetype": "LARGE_OFFICE", "sites": 30}]),
    ("grocery chain", [
        {"country": "GB", "archetype": "STORE", "sites": 2800},
        {"country": "GB", "archetype": "WAREHOUSE", "sites": 28}]),
    ("contract logistics", [
        {"country": "DE", "archetype": "WAREHOUSE", "sites": 420},
        {"country": "DE", "archetype": "BRANCH", "sites": 130}]),
    ("large utility", [
        {"country": "DE", "archetype": "NETWORK_SITE", "sites": 12000},
        {"country": "DE", "archetype": "CONTROL_CENTER", "sites": 11},
        {"country": "DE", "archetype": "REMOTE_SITE", "sites": 300}]),
])
def test_it_is_silent_on_estates_that_are_real(name, footprint):
    """A ceiling that fires on a real estate is worse than no ceiling. A
    postal network really does have 30,000 service points and a tower company
    40,000 cabinets."""
    result = plausibility.assess(
        footprint, registered_total=sum(r["sites"] for r in footprint))
    assert result["plausible"], (name, result["findings"])


def test_only_the_mass_deployed_site_types_are_unbounded():
    """The first version exempted five and let 25,840 warehouses in Germany
    through - the same error it was written to catch, one site type over.

    A postal network really does have 30,000 collection points and a tower
    company 40,000 cabinets. A depot is a building with loading bays: DHL runs
    a few hundred in Germany, Amazon around a hundred fulfilment centres."""
    # Five since the unmanned site types were added. A packstation, a vending
    # machine and a cash machine run to tens of thousands in one country for
    # one company, the same as a store or a tower cabinet.
    assert set(plausibility.UNBOUNDED) == {
        "STORE", "NETWORK_SITE", "SERVICE_POINT", "SELF_SERVICE_TERMINAL",
        "ATM"}
    for archetype in plausibility.UNBOUNDED:
        assert archetype not in plausibility.PER_COUNTRY_CEILING
    for archetype in ("WAREHOUSE", "BRANCH", "REMOTE_SITE"):
        assert archetype in plausibility.PER_COUNTRY_CEILING


def test_a_parcel_network_typed_as_depots_is_caught():
    """What DHL's footprint became once the shape drift was repaired: the
    right total, spread over the wrong site type."""
    result = plausibility.assess([
        {"country": "DE", "archetype": "BRANCH", "sites": 7980},
        {"country": "DE", "archetype": "DC", "sites": 1140},
        {"country": "DE", "archetype": "LARGE_OFFICE", "sites": 3040},
        {"country": "DE", "archetype": "WAREHOUSE", "sites": 25840},
    ], registered_total=38000)
    assert not result["plausible"]
    flagged = {f["archetype"] for f in result["findings"]
               if f["kind"] == "IMPOSSIBLE_COUNT"}
    assert {"WAREHOUSE", "BRANCH", "DC"} <= flagged
    warehouse = next(f for f in result["findings"]
                     if f.get("archetype") == "WAREHOUSE")
    assert "STORE" in warehouse["likely_cause"]


def test_it_reports_rather_than_refuses():
    """An implausible estate is an analyst error, not a missing input.
    Refusing would strand a case mid-edit."""
    result = plausibility.assess(BROKEN)
    assert isinstance(result["findings"], list)
    assert "plausible" in result


def test_the_finding_reaches_the_estimate_and_the_page():
    """A check nobody reads is the defect this session keeps finding."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "estate_plausibility.assess(" in api
    assert '"estate_plausibility": _plausibility' in api

    page = next(root.glob(
        "analyst_ui/streamlit_app/pages/6_Run_V0*.py")).read_text()
    assert "estate_plausibility" in page
    assert "could be PRICED, not that it" in page


# ------------------- a saved footprint that predates a shape change
def test_the_page_warns_when_the_saved_footprint_disagrees_with_the_industry():
    """"Whatever is in the table below is what runs" - and the table is
    whatever was last saved, possibly under a different industry or before an
    estate shape changed.

    A DHL case kept a 44% LARGE_OFFICE mix long after LOGISTICS had been
    changed to 68% WAREHOUSE, and nothing said the two disagreed. The analyst
    re-proposed, saw the same table, and reasonably concluded the fix had not
    worked."""
    root = Path(__file__).resolve().parents[1]
    page = next(root.glob(
        "analyst_ui/streamlit_app/pages/5_Simulation*.py")).read_text()
    assert "_STALE_SHAPE_TOLERANCE" in page
    assert "does not match what" in page
    assert "re-proposing and re-applying will change it" in page


def test_the_implied_mix_is_published_by_the_api():
    """Derived in the page it would be a second copy of the shape, and a
    second thing to leave stale."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert 'resolved["industry_mix"]' in api
    assert "db.density_mix.c.industry" in api


def test_the_comparison_tolerates_hand_editing():
    """The analyst is expected to edit rows. Flagging every correction as
    stale would make the warning noise, so only a whole site type being out
    by more than a fifth counts."""
    root = Path(__file__).resolve().parents[1]
    page = next(root.glob(
        "analyst_ui/streamlit_app/pages/5_Simulation*.py")).read_text()
    line = next(x for x in page.splitlines()
                if x.startswith("_STALE_SHAPE_TOLERANCE"))
    assert float(line.split("=")[1]) >= 0.15
