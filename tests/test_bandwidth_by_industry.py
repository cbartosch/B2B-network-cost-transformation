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
