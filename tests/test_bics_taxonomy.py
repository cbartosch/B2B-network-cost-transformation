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
    assert bics.shape_for("SAAS") == "office-centric"
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
