"""BICS L3 as the one industry taxonomy.

Two existed and **three of forty-two codes overlapped**. The workbench's own
twenty-eight drove the density mix and the seeded bandwidth; the supplied BICS
benchmark had forty-two with published figures. So an analyst picking AIRPORTS
or DEFENSE from the intake list got no benchmark row at all, and 4.193's data
was unreachable for twenty-five of twenty-eight industries.

Substring bridging was the obvious shortcut and it pairs CAPITAL_MARKETS with
SUPERMARKETS, which is why the mapping is decided rather than derived from
names.
"""
from decimal import Decimal as D

import pytest

from app.domain import bics, industries, industry_benchmark as benchmark


def _codes():
    return benchmark.seeded()["industries"]


def test_every_benchmark_industry_has_an_estate_shape():
    """A benchmark row for an industry whose estate shape nobody decided is
    half a model: the published bandwidth would be right and the mix of site
    types it applies to would be a default."""
    assert bics.unclassified(_codes()) == []


def test_no_shape_is_assigned_to_an_industry_the_benchmark_lacks():
    """An assignment for a code that does not exist is a guess nobody will
    ever check."""
    assert not set(bics.SHAPE_OF_BICS) - set(_codes())


def test_the_shape_follows_the_site_archetype_not_the_industry_name():
    """A refinery, a mine and a fab are all plant-centric; a trading floor and
    an engineering campus are both office-centric; a tower site and a core DC
    are both network-centric. None of that follows from what the company
    sells."""
    assert bics.shape_for("SEMICONDUCTORS") == "plant-centric"
    assert bics.shape_for("GOLD_MINING") == "plant-centric"
    assert bics.shape_for("INVESTMENT_BANKING") == "office-centric"
    # SAAS moved to campus-centric in 4.219.0: its benchmark row names an
    # ENGINEERING_CAMPUS, and office-centric put 53% of its sites in branches.
    # Investment banking above keeps office-centric because its row names a
    # trading floor, not a campus - which is the distinction this test is for.
    assert bics.shape_for("SAAS") == "campus-centric"
    assert bics.shape_for("TOWER_COMPANY") == "network-centric"
    assert bics.shape_for("MOBILE_OPERATOR") == "network-centric"


def test_retail_banking_is_network_centric_not_office_centric():
    """Branches are the estate. An investment bank and a retail bank are both
    financials and have nothing in common structurally."""
    assert bics.shape_for("RETAIL_BANKING") == "network-centric"
    assert bics.shape_for("INVESTMENT_BANKING") == "office-centric"


def test_an_unclassified_code_gets_the_least_wrong_default():
    """Office-centric rather than something more specific: a wrong specific
    shape reads as knowledge."""
    assert bics.shape_for("NOT_AN_INDUSTRY") == bics.DEFAULT_SHAPE
    assert bics.DEFAULT_SHAPE == "office-centric"


def test_every_derived_mix_sums_to_exactly_one():
    """The mix decides how a site total splits, so a mix summing to anything
    else is a footprint that is not the footprint."""
    rows = bics.density_mix_rows(_codes(), industries.SHAPES)
    totals = {}
    for code, _archetype, _band, share in rows:
        totals[code] = totals.get(code, D(0)) + D(share)
    assert {c: str(v) for c, v in totals.items() if v != D("1.0000")} == {}


def test_bics_supersedes_the_older_taxonomy_rather_than_adding_to_it():
    """RETAIL_BANKING, INSURANCE and LOGISTICS exist in both - the three-code
    overlap - and appending gave each of them two mixes summing to 2.0000,
    which the footprint resolver would have read as twice the estate."""
    from app.seed import DENSITY_MIX

    totals = {}
    for industry, _archetype, _band, share in DENSITY_MIX:
        totals[industry] = totals.get(industry, D(0)) + D(share)
    doubled = {i: str(v) for i, v in totals.items() if v != D("1.0000")}
    assert doubled == {}, f"these industries have more than one mix: {doubled}"


def test_no_industry_and_archetype_is_priced_twice():
    """Two bandwidth rows for one (industry, archetype) means whichever the
    query returns last wins, silently."""
    from app.seed import ARCHETYPE_BANDWIDTH

    seen, duplicates = set(), []
    for industry, archetype, _mbps in ARCHETYPE_BANDWIDTH:
        if (industry, archetype) in seen:
            duplicates.append((industry, archetype))
        seen.add((industry, archetype))
    assert not duplicates, duplicates


def test_a_bics_industry_prices_the_site_type_it_actually_has():
    """A supermarket estate prices STORE at the published figure rather than
    falling back to a seeded guess for BRANCH."""
    from app.seed import ARCHETYPE_BANDWIDTH

    rows = {(i, a): m for i, a, m in ARCHETYPE_BANDWIDTH}
    assert ("SUPERMARKETS", "STORE") in rows
    assert ("TOWER_COMPANY", "TOWER_SITE") in rows
    assert ("SEMICONDUCTORS", "FAB") in rows


def test_the_supporting_archetypes_keep_a_bandwidth():
    """A BICS industry's estate shape includes archetypes its benchmark does
    not name - a supermarket has distribution centres and a head office, and
    the benchmark says only STORE. Those still need a figure."""
    from app.seed import ARCHETYPE_BANDWIDTH, DENSITY_MIX

    priced = {(i, a) for i, a, _ in ARCHETYPE_BANDWIDTH}
    in_mix = {(i, a) for i, a, _b, _s in DENSITY_MIX}
    missing = sorted(in_mix - priced)
    assert not missing, f"in a mix and unpriced: {missing[:8]}"


def test_the_intake_offers_bics_as_the_taxonomy_to_choose():
    """Both lists are returned, and which one to use has to be stated - a
    caller cannot tell from two arrays which choice gets published data."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert '"preferred_taxonomy": "bics_l3"' in api
    assert "taxonomy_note" in api


def test_the_unbenchmarked_industries_have_a_shape_and_a_priceable_estate():
    """An industry with a benchmark row and no estate shape takes the default,
    and a wrong specific shape reads as knowledge. These five were dropped
    when the shape map was first written on the grounds that the benchmark had
    no rows for them - which was the wrong call: a benchmark gap is a reason to
    seed a grade E row and say so, not a reason to leave a steelmaker with
    nowhere to go."""
    from app.domain import industry_benchmark as benchmark
    from app.seed import ARCHETYPE_BANDWIDTH, DENSITY_MIX

    unbenchmarked = benchmark.seeded()["unbenchmarked_industries"]
    assert len(unbenchmarked) == 5

    priced = {(i, a) for i, a, _m in ARCHETYPE_BANDWIDTH}
    in_mix = {(i, a) for i, a, _b, _s in DENSITY_MIX}
    for code in unbenchmarked:
        assert bics.shape_for(code) != bics.DEFAULT_SHAPE or code in (
            "AEROSPACE_DEFENSE",), f"{code} fell back to the default shape"
        mine = {(i, a) for (i, a) in in_mix if i == code}
        assert mine, f"{code} has no estate mix"
        assert not (mine - priced), f"{code} has unpriceable site types"


def test_steel_is_not_forestry():
    """The one mapping that could not be defended. The archetype was right and
    the label was not."""
    from app.domain import industry_benchmark as benchmark

    rows = {r["industry_code"]: r for r in benchmark.seeded()["rows"]}
    assert rows["STEEL"]["archetype_code"] == "MILL"
    assert rows["STEEL"]["sector"] == "Materials"
    assert rows["FORESTRY_PAPER"]["archetype_code"] == "MILL"
    # Same archetype, different industry - which is the point: a shared estate
    # shape is not a shared industry.
    assert bics.shape_for("STEEL") == bics.shape_for("FORESTRY_PAPER")


# ------------------------------------------- the campus estate
def test_a_campus_estate_has_no_branch_network():
    """AstraZeneca was modelled with a branch network it does not have.

    office-centric puts 53% of its sites in BRANCH, and the pharmaceutical
    benchmark row names R_D_CAMPUS as the representative site - so the shape
    was contradicting the benchmark beside it."""
    from app.domain import industries

    campus = industries.SHAPES["campus-centric"]
    assert not any(a == "BRANCH" for a, _b, _s in campus)
    assert any(a == "CAMPUS" for a, _b, _s in campus)


def test_only_the_codes_whose_benchmark_names_a_campus_are_campus_centric():
    """Decided from the benchmark, not the industry name. Insurance and
    commercial real estate name an office; investment banking names a trading
    floor and integrated oil a refinery. Those are different estates."""
    from app.domain import bics, industry_benchmark as benchmark

    archetype_of = {r["industry_code"]: r["archetype_code"]
                    for r in benchmark.seeded()["rows"]}
    for code, shape in bics.SHAPE_OF_BICS.items():
        names_campus = "CAMPUS" in (archetype_of.get(code) or "") \
            or "HUB" in (archetype_of.get(code) or "")
        if shape == "campus-centric":
            assert names_campus, (
                f"{code} is campus-centric and its benchmark names "
                f"{archetype_of.get(code)}")


def test_a_campus_is_priced_like_a_campus_not_an_office():
    """A campus carries a workforce and the compute it uses. Pricing it beside
    a large office would understate it by an order of magnitude."""
    from app.seed import ARCHETYPE_BANDWIDTH

    rates = {(i, a): m for i, a, m in ARCHETYPE_BANDWIDTH}
    campus = rates.get(("PHARMACEUTICALS", "CAMPUS"))
    office = rates.get(("PHARMACEUTICALS", "LARGE_OFFICE"))
    assert campus and office and campus >= office * 5


def test_the_campus_prior_is_a_dc_with_people_on_it():
    """Not a big office and not a data hall. A DC has no users and bursts; a
    campus has thousands of people AND the compute they use, so it carries a
    high committed rate and a platform layer a data hall gets none of."""
    from app.seed import ARCHETYPES

    priors = {row[0]: row for row in ARCHETYPES}
    campus, dc = priors["CAMPUS"], priors["DC"]
    assert campus[1] > 1000, "a campus has a workforce"
    assert dc[1] == 0, "a data centre does not"
    assert campus[2] == dc[2], "both sit at the top bandwidth tier"
    assert float(campus[6]) > float(dc[6]), (
        "a campus sustains load where a data hall bursts")


# --------------------------------- the screen that chooses an industry
def test_the_intake_reads_the_taxonomy_the_endpoint_prefers():
    """An analyst looking for a drug maker found only PHARMACY_RETAIL, which
    is Boots.

    The endpoint returned both lists and said which to prefer; the page read
    `industries` - the twenty-eight workbench codes - while `bics_l3` sat
    beside it with forty-seven. The whole BICS load was unreachable from the
    one screen that chooses an industry, and the call succeeded, so nothing
    looked wrong."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = next(root.glob("analyst_ui/streamlit_app/pages/1_Intake*.py"))
    source = page.read_text()

    assert "preferred_taxonomy" in source, (
        "the page must read the taxonomy the endpoint prefers, not the first "
        "list in the payload")
    assert "bics_l3" in source


def test_a_case_on_the_older_taxonomy_is_not_silently_blanked():
    """A case created before the BICS load carries one of the old codes. If
    the dropdown no longer offers it, the next save writes an empty
    industry."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = next(root.glob("analyst_ui/streamlit_app/pages/1_Intake*.py"))
    source = page.read_text()

    assert "_INDUSTRIES.append(_cur_for_list)" in source
    assert "earlier taxonomy" in source, (
        "an older code must be flagged as pricing from seeded figures")


def test_the_endpoint_offers_both_lists_and_names_the_preferred_one():
    """Two arrays and no guidance is how the page picked the wrong one."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert '"preferred_taxonomy": "bics_l3"' in api
    assert '"bics_l3"' in api
    assert '"industries"' in api
