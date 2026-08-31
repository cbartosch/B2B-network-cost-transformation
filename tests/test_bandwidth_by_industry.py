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


def test_every_industry_covers_every_archetype():
    """A gap falls through to DEFAULT silently, which is the behaviour that
    made one bandwidth per archetype look adequate in the first place."""
    archetypes = {a for a, *_ in ARCHETYPES}
    industries = {i for i, *_ in ARCHETYPE_BANDWIDTH}
    missing = [(i, a) for i in industries for a in archetypes
               if (i, a) not in BY_KEY]
    assert not missing, f"industry/archetype pairs with no bandwidth: {missing}"


def test_a_default_row_exists_for_every_archetype():
    """An unrecognised sector must be priced at the generic tier, not refused."""
    archetypes = {a for a, *_ in ARCHETYPES}
    missing = [a for a in archetypes if ("DEFAULT", a) not in BY_KEY]
    assert not missing, f"archetypes with no DEFAULT bandwidth: {missing}"


def test_the_industries_actually_differ_from_the_default():
    """A table where every sector matches DEFAULT buys nothing and costs a
    join. Each industry has to disagree somewhere or it should not be there."""
    industries = {i for i, *_ in ARCHETYPE_BANDWIDTH} - {"DEFAULT"}
    for industry in industries:
        differs = [a for (i, a), b in BY_KEY.items()
                   if i == industry and b != BY_KEY[("DEFAULT", a)]]
        assert differs, (
            f"{industry} is identical to DEFAULT at every site type - either "
            f"it differs somewhere or it does not belong in the table")


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
