"""What an industry's estate looks like, as distinct from what it is called.

Six industries with five site archetypes. The dimension earned its place by
changing two things - how a site total splits across density bands, and what
bandwidth a site type gets - so adding a name without changing those would make
the taxonomy a label rather than a model.
"""
from decimal import Decimal as D

import pytest

from app.domain import industries


def test_every_density_mix_sums_to_exactly_one():
    """The resolver apportions a site total through the mix. One summing to
    less than one silently loses sites, and 187 rows is 187 chances to
    fat-finger a share - which is why they are generated rather than typed."""
    totals = {}
    for industry, _archetype, _band, share in industries.density_mix_rows():
        totals.setdefault(industry, D(0))
        totals[industry] += D(share)
    assert totals, "no mixes generated"
    for industry, total in sorted(totals.items()):
        assert total == D("1.0000"), f"{industry} sums to {total}"


def test_every_industry_has_a_bandwidth_for_every_archetype():
    """A missing row makes a site type unsizable, which the coverage gate
    reports as unpriced scope rather than as a gap in the seed."""
    by_industry = {}
    for industry, archetype, _mbps in industries.bandwidth_rows():
        by_industry.setdefault(industry, set()).add(archetype)
    expected = {"STORE", "BRANCH", "WAREHOUSE", "LARGE_OFFICE", "DC"}
    for industry, archetypes in sorted(by_industry.items()):
        assert archetypes == expected, f"{industry} is missing {expected - archetypes}"


def test_the_ten_new_sectors_are_present():
    names = {row[0] for row in industries.INDUSTRIES}
    for sector in ("NATURAL_RESOURCES", "TRAVEL_TOURISM", "IT_SERVICES",
                   "TELECOM", "DEFENSE", "PUBLIC_SAFETY", "GOVERNMENT",
                   "AIRPORTS", "PORTS", "WHOLESALE_DISTRIBUTION"):
        assert sector in names, sector


def test_a_coarse_industry_survives_its_own_split():
    """An engagement that only knows 'retail' should not have to guess which
    kind, so RETAIL stays usable rather than being replaced by its splits."""
    names = {row[0] for row in industries.INDUSTRIES}
    for coarse in ("RETAIL", "FINANCIAL_SERVICES", "MANUFACTURING",
                   "LOGISTICS", "DISTRIBUTION"):
        assert coarse in names
    splits = {row[0]: row[1] for row in industries.INDUSTRIES}
    assert splits["GROCERY_RETAIL"] == "RETAIL"
    assert splits["CAPITAL_MARKETS"] == "FINANCIAL_SERVICES"


def test_the_shapes_produce_genuinely_different_estates():
    """The point of the dimension. If every shape split a total the same way
    it would buy nothing and cost a join."""
    def rural(shape):
        return sum(D(s) for _a, b, s in industries.SHAPES[shape]
                   if b == "RURAL")

    # An airport estate has no rural sites; a mine estate is mostly rural.
    assert rural("few-large") == 0
    assert rural("plant-centric") > D("0.30")


def test_a_terminal_is_not_sized_like_a_shop():
    """Both are "a site" and one needs two orders of magnitude more circuit."""
    few = industries.SHAPE_BANDWIDTH["few-large"]["LARGE_OFFICE"]
    many = industries.SHAPE_BANDWIDTH["many-small"]["STORE"]
    assert few >= many * 100


def test_a_poor_archetype_fit_is_reported_rather_than_hidden():
    """An airport terminal is not a LARGE_OFFICE: it is a hundred thousand
    square metres with tens of thousands of transient users, and calling it an
    office makes its bandwidth prior a fiction."""
    assert industries.fit_of("AIRPORTS") == industries.POOR
    assert industries.fit_of("TELECOM") == industries.POOR
    assert industries.fit_of("NATURAL_RESOURCES") == industries.POOR
    caveat = industries.caveat("AIRPORTS")
    assert caveat and "POOR" in caveat


def test_a_good_fit_carries_no_caveat():
    """A caveat on every case would be noise; one on the cases that need it is
    a finding."""
    assert industries.fit_of("IT_SERVICES") == industries.GOOD
    assert industries.caveat("IT_SERVICES") is None


def test_an_unlisted_sector_is_unknown_not_good():
    """An unlisted sector resolves to the DEFAULT shape, and reporting that as
    a good fit would claim the estate had been considered when it had only
    been defaulted - the same defect as an empty serviceability table reading
    as an unserviceable estate."""
    assert industries.fit_of("CIRCUS_OPERATOR") == industries.UNKNOWN
    caveat = industries.caveat("CIRCUS_OPERATOR")
    assert caveat and "not a profiled sector" in caveat


def test_an_absent_industry_resolves_to_a_real_profile():
    """None is not an unlisted sector: DEFAULT is a profile somebody wrote."""
    assert industries.fit_of(None) == industries.GOOD
    assert industries.caveat(None) is None


@pytest.mark.parametrize("industry,shape", [
    ("QSR_RESTAURANTS", "many-small"),
    ("AIRPORTS", "few-large"),
    ("PORTS", "few-large"),
    ("CAPITAL_MARKETS", "few-large"),
    ("TELECOM", "network-centric"),
    ("PROCESS_MANUFACTURING", "plant-centric"),
    ("GOVERNMENT", "office-centric"),
])
def test_each_sector_resolves_to_the_shape_its_estate_actually_has(
        industry, shape):
    assert industries.shape_of(industry) == shape


def test_the_seed_generates_both_tables_from_one_source():
    """Two tables keyed (industry, archetype) that must stay in sync. Hand
    writing both is how one gains an industry the other does not have."""
    from app import seed

    # Two sources now, not one: the workbench taxonomy and the BICS benchmark,
    # with BICS superseding where they overlap. So the seeded tables are larger
    # than either source alone, and what must hold is that every row comes
    # from one of them and no key appears twice.
    own_mix = {(r[0], r[1], r[2]) for r in industries.density_mix_rows()}
    seeded_mix = {(r[0], r[1], r[2]) for r in seed.DENSITY_MIX}
    assert len(seeded_mix) == len(seed.DENSITY_MIX), "a mix key appears twice"
    assert len(seeded_mix) >= len(own_mix) - 3 * 7, (
        "BICS supersedes the three overlapping codes; anything more missing "
        "means a workbench industry lost its mix")
    assert ({r[0] for r in seed.DENSITY_MIX}
            == {r[0] for r in seed.ARCHETYPE_BANDWIDTH})


def test_v0_reports_the_industry_and_its_fit():
    """A V0 that does not say so presents a placeholder mix as a model of the
    client."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert '"archetype_fit": industries.fit_of' in api
    assert '"industry_caveat": industries.caveat' in api
    page = next(p for p in (root / "analyst_ui").rglob("*.py")
                if "Run_V0" in p.name).read_text()
    assert "industry_caveat" in page
