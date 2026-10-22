"""A rural plant gets a fibre build. A rural shop does not.

The seed marked rural Ethernet fibre undeliverable on retail reasoning - "rural
is where a retail estate's assumptions break" - and applied it to every site
type, because the serviceability table has no site-type dimension. Every rural
PLANT asks for Ethernet with no substitute in its product pair, so all of them
were removed from their estates: 312 sites, 59% of michelin's plants.

A factory funds a fibre build as a matter of course. The cost of that build
was always meant to be carried by the ETHERNET RURAL density multiplier, which
had nothing to apply to.
"""
from decimal import Decimal as D

from app import seed

RURAL = {(c, tech): (available, mbps)
         for c, band, tech, available, mbps in seed.SERVICEABILITY
         if band == "RURAL"}
MULT = {(product, band): (D(low), D(base), D(high))
        for product, band, low, base, high in seed.DENSITY_COST_MULTIPLIER}


def test_rural_ethernet_fibre_is_deliverable_everywhere_it_is_seeded():
    for country in ("DE", "GB", "FR", "NL", "US"):
        available, mbps = RURAL[(country, "ETHERNET_FIBRE")]
        assert available, country
        # The PLANT archetype asks for 1000 Mbps; a lower tier would just
        # move the failure from availability to bandwidth.
        assert mbps >= 1000, country


def test_rural_dark_fibre_stays_undeliverable():
    """A distinct product, and nothing in this change argues for it."""
    for country in ("DE", "GB", "FR", "NL", "US"):
        available, _ = RURAL[(country, "DARK_FIBRE")]
        assert not available, country


def test_the_build_premium_is_priced_rather_than_assumed_away():
    """Making the bearer available is only honest if the rural build costs
    more. The multiplier is what carries that, and it must stay a premium."""
    low, base, high = MULT[("ETHERNET", "RURAL")]
    assert base > D("1.5"), "a rural build must cost materially more than urban"
    assert low >= D("1.0") and high > base


def test_retail_never_asks_for_a_fibre_bearer():
    """The reason this change cannot inflate a retail estate: STORE's product
    pair holds no fibre product, so rural shops keep buying broadband."""
    # seed.ARCHETYPES rows are (archetype, users, bandwidth, dual_access,
    # primary_product, backup_product, committed_fraction).
    store = next(r for r in seed.ARCHETYPES if r[0] == "STORE")
    products = {store[4], store[5]}
    fibre = {"ETHERNET", "DIA", "MPLS"}
    assert not (products & fibre), products


def test_the_plant_is_what_asks_for_ethernet():
    """The archetype this change exists for. If PLANT ever stopped asking for
    Ethernet the premise here would be gone and this test says so."""
    plant = next(r for r in seed.ARCHETYPES if r[0] == "PLANT")
    assert plant[4] == "ETHERNET"
