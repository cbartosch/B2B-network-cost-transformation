"""Bandwidth by site type and industry.

archetype_prior carried one bandwidth per archetype, which asserts that a
200-site retail bank branch and a 200-site parts depot need the same circuit.
They do not: a branch runs card, teller and video traffic back to a data
centre; a depot runs scanning and a warehouse session. The archetype describes
the shape of a site, the industry describes what happens inside it, and the
bandwidth follows from both.
"""
import pytest

from app.seed import ARCHETYPE_BANDWIDTH, ARCHETYPES, PRIORS

BY_KEY = {(i, a): b for i, a, b in ARCHETYPE_BANDWIDTH}


def test_every_archetype_in_an_estate_mix_has_a_bandwidth():
    """Every archetype an industry's estate actually contains, not every
    archetype that exists.

    The old rule required all five for all industries, which was true while
    every industry shared the same five site types. Since BICS became the
    taxonomy an estate contains what its shape says: a semiconductor estate
    has a fab, an office and a DC and no STORE, and a bandwidth row for
    (SEMICONDUCTORS, STORE) would be data about a site that does not exist.

    What must hold is narrower and stronger: nothing in a mix may be
    unpriceable, because a site in the footprint with no rate is unpriced
    scope."""
    from app.seed import ARCHETYPE_BANDWIDTH, DENSITY_MIX

    priced = {(i, a) for i, a, _m in ARCHETYPE_BANDWIDTH}
    in_mix = {(i, a) for i, a, _b, _s in DENSITY_MIX}
    missing = sorted(in_mix - priced)
    assert not missing, f"in an estate mix and unpriced: {missing[:8]}"


def test_a_default_row_exists_for_every_archetype():
    """An unrecognised sector must be priced at the generic tier, not refused."""
    archetypes = {a for a, *_ in ARCHETYPES}
    missing = [a for a in archetypes if ("DEFAULT", a) not in BY_KEY]
    assert not missing, f"archetypes with no DEFAULT bandwidth: {missing}"


def test_the_industries_actually_differ_from_the_default():
    """A table where every sector matches DEFAULT buys nothing and costs a
    join. Each industry has to disagree somewhere or it should not be there."""
    # Compared only on archetypes DEFAULT also has. Since BICS became the
    # taxonomy an industry can name a site type DEFAULT has never heard of -
    # TOWER_SITE, FAB, MEGA_CONTAINER_PORT - and there is nothing to compare
    # those against. An industry whose only site type is one of those differs
    # from DEFAULT by definition.
    industries = {i for i, *_ in ARCHETYPE_BANDWIDTH} - {"DEFAULT"}
    default_archetypes = {a for (i, a) in BY_KEY if i == "DEFAULT"}
    for industry in industries:
        mine = {a for (i, a) in BY_KEY if i == industry}
        if not (mine & default_archetypes):
            continue                    # every site type is its own
        # An industry differs if it disagrees on a shared site type OR if it
        # names one of its own. SEMICONDUCTORS shares only supporting
        # archetypes with DEFAULT - an office and a DC - and those take
        # DEFAULT's figures deliberately, because the benchmark said nothing
        # about them. Its FAB is where it differs, and the FAB is the point.
        differs = [a for a in mine & default_archetypes
                   if BY_KEY[(industry, a)] != BY_KEY[("DEFAULT", a)]]
        own = sorted(mine - default_archetypes)
        assert differs or own, (
            f"{industry} matches DEFAULT at every shared site type and names "
            f"none of its own - either it differs somewhere or it does not "
            f"belong in the table")


def test_a_bank_branch_needs_more_than_a_generic_store():
    """The motivating case. A retail bank branch carries card, teller and
    video traffic; the generic STORE tier is a small shop."""
    assert BY_KEY[("FINANCIAL_SERVICES", "STORE")] > BY_KEY[("DEFAULT", "STORE")]


def test_a_logistics_depot_needs_more_than_a_generic_warehouse():
    assert BY_KEY[("LOGISTICS", "WAREHOUSE")] > BY_KEY[("DEFAULT", "WAREHOUSE")]


@pytest.mark.parametrize("industry,archetype,mbps", ARCHETYPE_BANDWIDTH)
def test_every_bandwidth_is_priceable(industry, archetype, mbps):
    """A tier no prior quotes prices nothing: match_prior takes the cheapest
    tier at or above the requirement and returns nothing if there is none, so
    an invented bandwidth silently drops circuits out of the estimate."""
    tiers = {bw for _c, _p, _l, bw, *_ in PRIORS}
    assert any(t >= mbps for t in tiers), (
        f"{industry}/{archetype} needs {mbps} Mbps and no prior quotes that "
        f"tier or above")


def test_the_simulation_puts_bandwidth_on_the_edge():
    """A sample that shows the product without the bandwidth shows half the
    circuit - the two together are what it costs."""
    import inspect
    from app.domain import simulation
    src = inspect.getsource(simulation.one_pass)
    assert src.count('"bandwidth_mbps": bw_base') == 2, (
        "both the primary and the backup edge must carry their bandwidth")


def test_every_seeded_bandwidth_has_a_tier_that_can_price_it():
    """The BICS benchmark put a supermarket store at 275 Mbps while the card
    quoted consumer access at 50 and 100 only, so every store in every retail
    estate was unpriced scope - 2% coverage for a French grocer and 15% for a
    German discounter, with the gate correctly refusing to price the rest.

    `match_prior` takes the cheapest tier at or above the requirement and never
    substitutes downward, so a bandwidth above every tier is unpriceable rather
    than approximated. Nothing caught it because the other pricing tests use
    industries whose figures happen to land on a quoted tier."""
    from app.seed import ARCHETYPES, ARCHETYPE_BANDWIDTH, PRIORS

    product_of = {row[0]: row[4] for row in ARCHETYPES}
    tiers = {}
    for _country, product, _layer, mbps, *_rest in PRIORS:
        tiers.setdefault(product, set()).add(int(mbps))

    unpriceable = []
    for industry, archetype, mbps in ARCHETYPE_BANDWIDTH:
        product = product_of.get(archetype)
        if product is None:
            continue
        quoted = tiers.get(product, set())
        if not quoted or not any(t >= int(mbps) for t in quoted):
            unpriceable.append(f"{industry}/{archetype} needs {mbps} Mbps of "
                               f"{product}, highest tier "
                               f"{max(quoted) if quoted else 'none'}")
    assert not unpriceable, unpriceable


def test_the_consumer_tiers_extend_a_market_rather_than_inventing_one():
    """A country with no HFC row has no HFC market recorded, and adding three
    tiers for it would assert a market rather than extend one."""
    from app.seed import PRIORS

    by_country = {}
    for country, product, _layer, mbps, *_rest in PRIORS:
        if product in ("BROADBAND_HFC", "BROADBAND_PON"):
            by_country.setdefault((country, product), set()).add(int(mbps))

    # Anchored on each country's own lowest recorded tier, not on a 100 Mbps
    # row: France and the Netherlands price HFC at 50 only, and requiring 100
    # skipped them - leaving a French supermarket estate unpriceable, which is
    # the defect this change exists to fix.
    for (country, product), tiers in by_country.items():
        assert min(tiers) <= 100, (
            f"{country}/{product} starts at {min(tiers)} Mbps with no lower "
            f"anchor - these tiers were not extended from a recorded market")


def test_a_higher_tier_costs_more_than_the_one_below_it():
    """A 250 Mbps service cheaper than a 100 Mbps one would make right-sizing
    recommend an upgrade."""
    from app.seed import PRIORS

    by_key = {}
    for country, product, _layer, mbps, low, base, high in PRIORS:
        by_key.setdefault((country, product), {})[int(mbps)] = int(base)

    for (country, product), tiers in by_key.items():
        ordered = sorted(tiers)
        for lower, upper in zip(ordered, ordered[1:]):
            assert tiers[upper] > tiers[lower], (
                f"{country}/{product}: {upper} Mbps costs {tiers[upper]} and "
                f"{lower} Mbps costs {tiers[lower]}")


def test_every_country_prices_the_primary_circuits_its_estates_need():
    """A Dutch and French estate came back 67% covered while the same estate in
    the US covered 100%. France and the Netherlands quoted no Ethernet at all
    and no DIA above 500 Mbps, while GB, DE and US quoted both.

    Nothing caught it because the priceability check above asks "does *any*
    country quote this tier" - and ETHERNET 250 exists in the US, so it passed
    while France could not price it. A global check hiding a per-country gap is
    the same shape as the defect it was written to catch."""
    from app.domain.access import LEGACY_PRODUCT
    from app.seed import ARCHETYPES, ARCHETYPE_BANDWIDTH, PRIORS, SERVICEABILITY

    product_of = {row[0]: row[4] for row in ARCHETYPES}
    tiers, countries = {}, set()
    for country, product, _layer, mbps, *_rest in PRIORS:
        tiers.setdefault((country, product), set()).add(int(mbps))
        if len(country) == 2:
            countries.add(country)

    # Primary circuits only: a 5G backup at 50 Mbps behind a 275 Mbps primary
    # is a deliberate degraded path, not a missing rate.
    wanted = {(product_of[a], int(m)) for _i, a, m in ARCHETYPE_BANDWIDTH
              if a in product_of}
    # And only where the bearer can be delivered. Singapore quotes no cable
    # broadband because Singapore has no cable network.
    deliverable = {(c, t) for c, _b, t, available, _m in SERVICEABILITY
                   if available}
    bearer = {p: pair[1] for p, pair in LEGACY_PRODUCT.items()}

    gaps = {}
    for country in sorted(countries):
        missing = [(p, m) for p, m in sorted(wanted)
                   if not (bearer.get(p)
                           and (country, bearer[p]) not in deliverable)
                   and not any(t >= m
                               for t in tiers.get((country, p), set()))]
        if missing:
            gaps[country] = missing
    assert not gaps, gaps


def test_a_filled_tier_leaves_no_hole_beneath_it():
    """match_prior takes the cheapest tier at or above the requirement, so a
    hole between 100 and 1000 prices a 500 Mbps circuit at the gigabit rate.
    The UAE had exactly that until the 500 row was emitted alongside."""
    from app.seed import PRIORS

    by_key = {}
    for country, product, _layer, mbps, *_rest in PRIORS:
        by_key.setdefault((country, product), set()).add(int(mbps))

    for (country, product), tiers in by_key.items():
        if product != "DIA" or len(country) != 2:
            continue
        if 100 in tiers and 1000 in tiers:
            assert 500 in tiers, (
                f"{country}/DIA jumps 100 to 1000 with no 500 - a 500 Mbps "
                f"circuit there is priced at the gigabit rate")


def test_a_country_with_no_rate_curve_is_left_alone():
    """A country quoting no DIA at all has no curve to extend, and inventing
    one would assert a market rather than extend a known one."""
    from app.seed import PRIORS

    dia = {c for c, p, *_ in PRIORS if p == "DIA"}
    ethernet = {c for c, p, *_ in PRIORS if p == "ETHERNET"}
    invented = sorted(c for c in ethernet if c not in dia and len(c) == 2)
    assert not invented, (
        f"{invented} have Ethernet tiers without a DIA row to scale from")
