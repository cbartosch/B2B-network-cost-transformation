"""A country with no card of its own falls back to its region.

The three regions held exactly one row each - ETHERNET at 10 Gbps, for the
backbone - so a country without its own card fell through to a region that
could not price a branch, a store or an office. And the country-region map had
nine rows: the seven countries that already had a card, plus Brazil and India.

So Poland mapped to nothing, Brazil mapped to a region with nothing, and an
estate in either was entirely unpriced scope.
"""
import pytest


def _priors():
    from app.domain.access import LEGACY_PRODUCT
    from app.seed import PRIORS

    out = {}
    for country, product, _layer, mbps, low, base, high in PRIORS:
        service_class, technology = LEGACY_PRODUCT.get(product, (None, None))
        out[(country, product, int(mbps))] = {
            "low": str(low), "base": str(base), "high": str(high),
            "scope": country, "service_class": service_class,
            "access_technology": technology, "bandwidth_mbps": int(mbps),
            "price_year": 2026}
    return out


def _region_of():
    from app.seed import COUNTRY_REGION
    return dict(COUNTRY_REGION)


def test_the_map_covers_more_than_the_countries_that_have_a_card():
    """Nine rows meant an unmapped country could not reach a fallback that
    existed. A map listing only the countries already priced is not a
    fallback."""
    from app.seed import COUNTRY_REGION, PRIORS

    mapped = {c for c, _r in COUNTRY_REGION}
    priced = {c for c, *_rest in PRIORS if len(c) == 2}
    assert len(mapped) >= 60, f"only {len(mapped)} countries mapped"
    assert mapped > priced, (
        "the map adds nothing beyond the countries that already have rates")


def test_no_country_is_mapped_twice():
    """Two regions for one country means whichever the query returns last
    wins, silently."""
    from collections import Counter

    from app.seed import COUNTRY_REGION

    duplicated = [c for c, n in Counter(
        c for c, _r in COUNTRY_REGION).items() if n > 1]
    assert not duplicated, duplicated


def test_every_mapped_region_resolves_to_rates_eventually():
    """A country pointing at a region with no rates is mapped and still
    unpriced, which is how Brazil behaved.

    Since EMEA split, a region may legitimately price nothing - five of the
    eight bands contain no country with a card - as long as its parent does.
    What must not exist is a region that prices nothing and has nowhere to
    fall."""
    from app.domain.scope import REGION_PARENT
    from app.seed import COUNTRY_REGION, PRIORS

    with_rates = {c for c, *_rest in PRIORS if len(c) > 2}
    stranded = sorted(
        r for r in {r for _c, r in COUNTRY_REGION}
        if r not in with_rates
        and REGION_PARENT.get(r) not in with_rates)
    assert not stranded, (
        f"{stranded} price nothing and their parent prices nothing either")


@pytest.mark.parametrize("country", ["PL", "TR", "ZA", "MX", "JP", "AU", "BR"])
def test_an_unlisted_country_prices_a_branch_through_its_region(country):
    """The point of the whole change: a 100 Mbps office in a country with no
    card of its own gets a regional average rather than nothing."""
    from app.domain.access import LEGACY_PRODUCT
    from app.domain.estimate import match_prior

    from app.domain.scope import REGION_PARENT

    # The whole chain. South Africa reaches AFRICA_SSA, which has no rates,
    # and passing only that rung reported a pricing gap where there was a
    # missing query.
    region = _region_of()[country]
    chain = [country, region, REGION_PARENT.get(region)]
    service_class, technology = LEGACY_PRODUCT["DIA"]
    hit, _substituted = match_prior(
        _priors(), country, "DIA", 100, service_class=service_class,
        access_technology=technology, scopes=[c for c in chain if c])
    assert hit is not None, f"{country} cannot price a 100 Mbps office"


def test_a_country_in_no_region_still_refuses():
    """An unmapped country has no fallback, and inventing one would be a
    global average across markets that differ by a factor of three."""
    from app.domain.access import LEGACY_PRODUCT
    from app.domain.estimate import match_prior

    service_class, technology = LEGACY_PRODUCT["DIA"]
    hit, _substituted = match_prior(
        _priors(), "XX", "DIA", 100, service_class=service_class,
        access_technology=technology, scopes=["XX"])
    assert hit is None


def test_a_region_only_prices_what_its_members_price():
    """APAC has no cable broadband because Singapore has none. A region that
    invented a product its members do not sell would price a market that does
    not exist."""
    from app.seed import COUNTRY_REGION, PRIORS

    region_of = dict(COUNTRY_REGION)
    by_scope = {}
    for country, product, _layer, mbps, *_rest in PRIORS:
        by_scope.setdefault(country, set()).add((product, int(mbps)))

    from app.domain.scope import REGION_PARENT

    for region in sorted({r for _c, r in COUNTRY_REGION}
                         | set(REGION_PARENT.values())):
        # A parent's members are every country beneath any of its bands, not
        # the countries mapped directly to it - nothing maps to EMEA now.
        members = [c for c, r in region_of.items()
                   if c in by_scope
                   and (r == region or REGION_PARENT.get(r) == region)]
        member_rates = set()
        for country in members:
            member_rates |= by_scope[country]
        invented = sorted(
            pair for pair in by_scope.get(region, set())
            if pair not in member_rates and pair[0] != "ETHERNET")
        assert not invented, (
            f"{region} prices {invented}, which no member country prices")


def test_the_backbone_row_is_not_reused_as_site_access():
    """`match_prior` is keyed (scope, product, bandwidth) and ignores role, so
    one row would have to serve both a backbone leg and a 10 Gbps site access
    circuit. EMEA's backbone price is 7000 against GB's 3700 for access, so
    reusing it prices a Polish data centre at 1.9x.

    The region declines to price site access at that tier instead, and the
    coverage gate reports it - which is the model's answer everywhere else it
    cannot tell two things apart."""
    from app.domain.access import LEGACY_PRODUCT
    from app.domain.estimate import match_prior
    from app.seed import PRIORS

    # the backbone row is still there, untouched
    backbone = [r for r in PRIORS
                if r[0] == "EMEA" and r[1] == "ETHERNET" and r[3] == 10000]
    assert len(backbone) == 1, "the backbone row must survive the fill"

    # and a 10 Gbps site in an unlisted EMEA country is not priced from it at
    # a lower tier's expense - the derived tiers stop below it
    derived = sorted(r[3] for r in PRIORS
                     if r[0] == "EMEA" and r[1] == "ETHERNET")
    assert derived == [500, 1000, 10000], derived

    # Albania, not Poland: Poland is in the Eastern Europe cluster and has its
    # own Ethernet rows since the workbook loaded.
    service_class, technology = LEGACY_PRODUCT["ETHERNET"]
    hit, _s = match_prior(
        _priors(), "AL", "ETHERNET", 500, service_class=service_class,
        access_technology=technology, scopes=["AL", "EUROPE_SOUTH", "EMEA"])
    assert hit is not None, "an Albanian Ethernet tail must price"
    assert hit["scope"] != "EMEA" or hit["bandwidth_mbps"] != 10000, (
        "a 500 Mbps tail must not be priced from the 10 Gbps backbone row")


# ----------------------------------- every ISO country reaches a region
# Codes with no enterprise estate: uninhabited, research stations, or
# administered territories with no commercial network. Asserting a region for
# them is noise in a governed table.
UNINHABITED = frozenset(
    "AQ BV GS HM TF IO UM".split())


def _iso_alpha_2():
    """Every ISO-3166-1 alpha-2 code, from the system's own iso-codes data.

    Read rather than hardcoded. A list typed from memory is exactly how the
    first version of this map ended up with eight African countries out of
    fifty-four - and a test that checks a hand-written list against a
    hand-written list checks nothing.
    """
    import json
    from pathlib import Path

    for candidate in (Path("/usr/share/iso-codes/json/iso_3166-1.json"),
                      Path("/usr/share/zoneinfo/iso3166.tab")):
        if not candidate.exists():
            continue
        if candidate.suffix == ".json":
            data = json.loads(candidate.read_text())
            return {c["alpha_2"] for c in data["3166-1"]}
        return {line.split("\t")[0] for line in candidate.read_text().splitlines()
                if line and not line.startswith("#")}
    return set()


def test_every_iso_country_reaches_a_region():
    """Ethiopian Airlines came back 37% covered because Ethiopia, Togo and
    Cote d'Ivoire were absent from the map - 58 of its 69 sites unpriced, and
    not because the model could not price an airline but because nobody had
    listed its country.

    A map picked by thinking about where clients are encodes whoever was
    thinking. This one is generated against the ISO list."""
    from app.seed import COUNTRY_REGION

    iso = _iso_alpha_2()
    if not iso:
        import pytest
        pytest.skip("no iso-codes data on this system to check against")

    mapped = {c for c, _r in COUNTRY_REGION}
    missing = sorted(iso - mapped - UNINHABITED)
    assert not missing, (
        f"{len(missing)} ISO countries reach no region: {missing[:12]}")


def test_the_map_invents_no_country():
    """A row for a code that is not a country is a row nobody will ever
    match, and it makes the count look complete when it is not."""
    from app.seed import COUNTRY_REGION

    iso = _iso_alpha_2()
    if not iso:
        import pytest
        pytest.skip("no iso-codes data on this system to check against")

    invented = sorted({c for c, _r in COUNTRY_REGION} - iso)
    assert not invented, invented


def test_no_uninhabited_territory_is_assigned():
    """Antarctica has no enterprise estate. Assigning it a region is noise."""
    from app.seed import COUNTRY_REGION

    mapped = {c for c, _r in COUNTRY_REGION}
    assert not (mapped & UNINHABITED), sorted(mapped & UNINHABITED)


def test_no_region_is_too_small_to_be_worth_having():
    """A region with two members is a country wearing a label. The floor is
    low - EUROPE_EAST has six - because a small band whose members share a
    market is more useful than a large one that does not, which is the whole
    argument for splitting EMEA."""
    from collections import Counter

    from app.seed import COUNTRY_REGION

    counts = Counter(r for _c, r in COUNTRY_REGION)
    assert len(counts) == 10, sorted(counts)
    for region, n in counts.items():
        assert n >= 5, f"{region} has only {n} countries"


# ------------------------- ten regions, and a chain rather than one rung
def test_emea_is_split_into_bands_that_mean_something():
    """One EMEA spanned Germany and Ethiopia: 125 countries taking a median of
    five European markets, which is a number with very little information in
    it."""
    from app.seed import COUNTRY_REGION

    regions = {r for _c, r in COUNTRY_REGION}
    for expected in ("EUROPE_WEST", "EUROPE_CENTRAL", "EUROPE_NORTH",
                     "EUROPE_SOUTH", "EUROPE_EAST", "MIDDLE_EAST",
                     "AFRICA_NORTH", "AFRICA_SSA", "AMER", "APAC"):
        assert expected in regions, expected
    assert "EMEA" not in regions, (
        "EMEA is the parent now, not a country's own region")


def test_every_sub_region_has_a_parent_to_fall_through_to():
    """Five of the eight contain no country with a rate card. Without a parent
    the split would be a coverage regression - a Nordic or African estate would
    reach a region that prices nothing and refuse."""
    from app.domain.scope import REGION_PARENT
    from app.seed import COUNTRY_REGION, PRIORS

    priced = {c for c, *_rest in PRIORS}
    for region in {r for _c, r in COUNTRY_REGION}:
        if region in priced:
            continue
        assert region in REGION_PARENT, (
            f"{region} prices nothing and has no parent, so every estate in "
            f"it is unpriced scope")
        assert REGION_PARENT[region] in priced


def test_a_priced_sub_region_beats_its_parent():
    """The point of splitting. Saudi Arabia took a pan-EMEA 550 and now takes
    the Middle East 1300 - a 2.4x correction that one region could not
    express."""
    from app.domain.estimate import match_prior
    from app.domain.scope import REGION_PARENT
    from app.seed import COUNTRY_REGION

    # Countries chosen for having no card of their own. The workbook load put
    # Saudi Arabia, Poland and Ireland on their own rates, so they no longer
    # need a fallback - which is the load working, not the ladder breaking.
    region_of = dict(COUNTRY_REGION)
    # Read from the data, not guessed. Three attempts at this picked countries
    # that turned out to be in a workbook cluster - Saudi Arabia, Bahrain and
    # Kuwait are all GCC - and a test whose fixture is a guess about the data
    # is a test of the guess.
    for country, expected_scope in (("IQ", "MIDDLE_EAST"),
                                    ("AL", "EUROPE_SOUTH"),
                                    ("MC", "EUROPE_WEST")):
        sub = region_of[country]
        chain = [country, sub, REGION_PARENT.get(sub)]
        hit, _s = match_prior(
            _priors(), country, "DIA", 100, service_class="DIA",
            access_technology="ETHERNET_FIBRE",
            scopes=[c for c in chain if c])
        assert hit is not None and hit["scope"] == expected_scope, (
            f"{country} priced by {hit and hit['scope']}, not {expected_scope}")


def test_the_parent_rung_is_still_reachable_even_though_nothing_needs_it():
    """Every band has its own rates since the workbook loaded, so no country
    falls through to EMEA any more. The rung still has to work: the five empty
    bands were the reason it exists, and a band whose cluster figures are later
    withdrawn would need it again.

    Asserted on the wiring rather than on a country, because there is no
    longer a country that exercises it - and a test that silently stops
    testing anything is worse than one that says what it is checking."""
    from app.domain.scope import REGION_PARENT
    from app.seed import PRIORS

    priced = {c for c, *_rest in PRIORS if len(c) > 2}
    for band, parent in REGION_PARENT.items():
        assert parent in priced, (
            f"{band} falls to {parent}, which prices nothing")

    # and the chain still resolves for a hypothetical unpriced band
    hypothetical = [x for x in ("XX", "EUROPE_NORTH",
                                REGION_PARENT["EUROPE_NORTH"]) if x]
    assert hypothetical[-1] == "EMEA"


def test_the_route_loads_both_rungs():
    """Loading only the sub-region would have made the split a coverage
    regression, and the failure would have looked like a pricing gap rather
    than a missing query."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    # `REGION_PARENT`, not `scope.REGION_PARENT`: run_estimate assigns a local
    # called `scope`, which makes the name local for the whole function and
    # made the earlier attribute read an unbound local. Asserting the module
    # path here pinned the very construction that broke every estimate.
    assert "from ..domain.scope import REGION_PARENT" in api
    assert "scope.REGION_PARENT" not in api
    assert "set(_sub) |" in api


def test_region_parent_does_not_live_in_the_seed():
    """The router needs it and must not import the seed: importing that module
    builds every rate list as a side effect."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "from ..seed import" not in api
    scope_src = (app / "domain" / "scope.py").read_text()
    assert "REGION_PARENT = {" in scope_src
