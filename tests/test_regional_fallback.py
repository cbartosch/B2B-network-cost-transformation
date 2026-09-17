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


def test_every_mapped_region_actually_exists():
    """A country pointing at a region with no rates is mapped and still
    unpriced, which is how Brazil behaved."""
    from app.seed import COUNTRY_REGION, PRIORS

    with_rates = {c for c, *_rest in PRIORS if len(c) > 2}
    pointed_at = {r for _c, r in COUNTRY_REGION}
    assert not pointed_at - with_rates, (
        f"{sorted(pointed_at - with_rates)} are mapped to and price nothing")


@pytest.mark.parametrize("country", ["PL", "TR", "ZA", "MX", "JP", "AU", "BR"])
def test_an_unlisted_country_prices_a_branch_through_its_region(country):
    """The point of the whole change: a 100 Mbps office in a country with no
    card of its own gets a regional average rather than nothing."""
    from app.domain.access import LEGACY_PRODUCT
    from app.domain.estimate import match_prior

    region = _region_of()[country]
    service_class, technology = LEGACY_PRODUCT["DIA"]
    hit, _substituted = match_prior(
        _priors(), country, "DIA", 100, service_class=service_class,
        access_technology=technology, scopes=[country, region])
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

    for region in ("EMEA", "AMER", "APAC"):
        members = [c for c, r in region_of.items()
                   if r == region and c in by_scope]
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

    service_class, technology = LEGACY_PRODUCT["ETHERNET"]
    hit, _s = match_prior(
        _priors(), "PL", "ETHERNET", 500, service_class=service_class,
        access_technology=technology, scopes=["PL", "EMEA"])
    assert hit is not None and hit["base"] == "840", (
        "a 500 Mbps Ethernet tail in Poland must take the derived regional "
        "rate, not the backbone row")


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


def test_each_region_carries_a_usable_share_of_the_world():
    """A region with three members is not a fallback. This is a sanity floor,
    not a target - the shape only matters because a region has to have enough
    members for the fallback to be worth having."""
    from collections import Counter

    from app.seed import COUNTRY_REGION

    counts = Counter(r for _c, r in COUNTRY_REGION)
    assert set(counts) == {"EMEA", "AMER", "APAC"}
    for region, n in counts.items():
        assert n >= 40, f"{region} has only {n} countries"
