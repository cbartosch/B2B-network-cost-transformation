"""What a site needs, against what can be delivered where it is.

The archetype says a branch wants DIA at 100 Mbps. It does not say whether
anyone can deliver that at the address, and for a large retail estate that is
the single biggest cost differentiator: a discounter in Munich has fibre or
DOCSIS, the same format in the Eifel may have only DSL or fixed wireless.
Domain 18 researched exactly this and its result reached nothing, so a
4,000-store estate was priced as though every store could take the same
product.
"""
import types

import pytest

from app.domain import serviceability
from app.seed import DENSITY_BANDS, SERVICEABILITY


@pytest.fixture()
def table():
    return {(c, b, p): types.SimpleNamespace(available=a, max_bandwidth_mbps=m)
            for c, b, p, a, m in SERVICEABILITY}


def _resolve(table, density, product="DIA", mbps=100, country="DE"):
    return serviceability.resolve(table=table, country=country,
                                  density=density, product=product,
                                  wanted_mbps=mbps)


# ------------------------------------------------- silence is not a constraint
def test_a_row_with_no_density_prices_exactly_as_before(table):
    """Without a band nothing is known about what can be delivered there, so
    the site gets what it asked for - which is how the model behaved before
    serviceability existed. Treating absence as a constraint would change every
    existing case."""
    out = _resolve(table, None)
    assert out["outcome"] == serviceability.DELIVERED
    assert out["product"] == "DIA" and out["bandwidth_mbps"] == 100


# ------------------------------------------------------- the retail case
def test_an_urban_store_gets_what_it_asks_for(table):
    assert _resolve(table, "URBAN")["outcome"] == serviceability.DELIVERED


def test_a_rural_store_takes_a_different_circuit(table):
    """The finding for a large chain: same country, same format, a different
    product - so a rural store is not a cheaper urban one."""
    out = _resolve(table, "RURAL")
    assert out["outcome"] == serviceability.SUBSTITUTED
    assert out["asked_for"] == "DIA"
    assert out["product"] == "BROADBAND_HFC"
    assert "cannot be delivered in RURAL" in out["note"]


def test_a_tier_that_cannot_be_delivered_is_capped_not_ignored(table):
    """Available but not at the bandwidth asked for. Pricing it at the tier
    nobody can deliver is the same error as pricing an unavailable product."""
    out = _resolve(table, "SUBURBAN", product="ETHERNET", mbps=10_000)
    assert out["outcome"] == serviceability.SUBSTITUTED
    assert out["product"] == "ETHERNET"
    assert out["bandwidth_mbps"] == 500
    assert "only to 500 Mbps" in out["note"]


def test_nothing_deliverable_is_reported_rather_than_priced(table):
    """An estimate that prices a circuit nobody can deliver reads as a number;
    this reads as a question."""
    empty = {("DE", "RURAL", p): types.SimpleNamespace(
        available=False, max_bandwidth_mbps=None)
        for p in serviceability.FALLBACK_ORDER}
    out = serviceability.resolve(table=empty, country="DE", density="RURAL",
                                 product="DIA", wanted_mbps=100)
    assert out["outcome"] == serviceability.UNSERVICEABLE
    assert out["product"] is None and out["bandwidth_mbps"] is None
    assert "reported rather than priced" in out["note"]


def test_the_substitute_is_chosen_for_reliability_not_price(table):
    """A cheaper substitute that cannot carry the traffic is not a substitute,
    so the fallback order is dedicated, then shared, then mobile."""
    order = serviceability.FALLBACK_ORDER
    assert order.index("DIA") < order.index("BROADBAND_HFC")
    assert order.index("BROADBAND_HFC") < order.index("MOBILE_5G")


# ----------------------------------------------------------- the read-out
def test_a_four_thousand_store_estate_reports_what_its_density_did(table):
    """"600 sites take a different product from the one their type asks for"
    is the finding. A percentage is not."""
    outcomes = []
    for band, count in (("DENSE_URBAN", 400), ("URBAN", 1600),
                        ("SUBURBAN", 1400), ("RURAL", 600)):
        outcomes.extend([_resolve(table, band)] * count)

    summary = serviceability.summarise(outcomes)
    assert summary["counts"][serviceability.DELIVERED] == 3400
    assert summary["counts"][serviceability.SUBSTITUTED] == 600
    swap = summary["substitutions"][0]
    assert swap["asked_for"] == "DIA" and swap["delivered"] == "BROADBAND_HFC"
    assert swap["sites"] == 600


def test_the_summary_of_an_empty_estate_says_so():
    assert "No sites" in serviceability.summarise([])["note"]


# ------------------------------------------------------------- the seed data
def test_every_density_band_is_seeded_for_every_country():
    countries = {c for c, *_ in SERVICEABILITY}
    for country in countries:
        for band in DENSITY_BANDS:
            assert any(c == country and b == band
                       for c, b, *_ in SERVICEABILITY), f"{country} {band}"


def test_dedicated_access_thins_out_with_density():
    """The pattern that makes clustering worth doing at all. If every band
    delivered the same products, the dimension would buy nothing and cost a
    join."""
    def deliverable(band):
        return {p for c, b, p, a, _m in SERVICEABILITY
                if c == "DE" and b == band and a}

    # Keyed on the bearer since 4.175. "DIA" is a service class and never
    # appeared in this table again; dedicated fibre is what thins out, and the
    # services that need it become unserviceable as a consequence.
    assert "ETHERNET_FIBRE" in deliverable("URBAN")
    assert "ETHERNET_FIBRE" not in deliverable("RURAL")
    # Rural gains satellite and fixed wireless, so it is not a strict subset -
    # it is a different set, which is the point. What matters is that the
    # bearers a dedicated service needs are gone.
    from app.domain import access
    assert not (set(access.carriers_for(access.ETHERNET))
                & deliverable("RURAL"))


def test_every_deliverable_product_is_one_the_model_prices():
    """A serviceability row naming a product no prior quotes would substitute
    a circuit into the estate that nothing can price - trading a reported
    constraint for silent unpriced scope."""
    # The two sides speak different vocabularies since 4.175: the table names
    # bearers, the rate card names services. Comparing them directly reported
    # nine "unpriced" technologies that are priced perfectly well - through the
    # service class that rides them.
    #
    # The invariant that survives the re-key: every bearer the table declares
    # deliverable must be one that some service class can actually use.
    # A bearer no service can ride is dead reference data, and it would
    # substitute a circuit into the estate that nothing can price.
    from app.domain import access

    usable = {t for c in access.SERVICE_CLASSES
              for t in access.carriers_for(c)}
    named = {t for _c, _b, t, a, _m in SERVICEABILITY if a}
    assert named <= usable, (
        f"deliverable but no service class can ride it: "
        f"{sorted(named - usable)}")


# --------------------------- absence of data is not evidence of absence
def test_an_empty_table_prices_as_asked_rather_than_refusing_everything():
    """The live failure: "10 site(s) in URBAN DE cannot be served at all",
    which is impossible - every product is deliverable there in the seed.

    The table arrived empty, every lookup missed, and the fallback loop found
    nothing available. Absence of data was read as evidence of absence, which
    is the error this module exists to avoid making in the other direction."""
    out = serviceability.resolve(table={}, country="DE", density="URBAN",
                                 product="DIA", wanted_mbps=100)
    assert out["outcome"] == serviceability.DELIVERED
    assert out["product"] == "DIA" and out["bandwidth_mbps"] == 100
    assert "nothing is known" in out["note"]


def test_a_band_missing_from_a_populated_table_is_also_nothing_known():
    """A table with rows for RURAL says nothing about URBAN."""
    table = {("DE", "RURAL", "DIA"): types.SimpleNamespace(
        available=True, max_bandwidth_mbps=100)}
    out = serviceability.resolve(table=table, country="DE", density="URBAN",
                                 product="DIA", wanted_mbps=100)
    assert out["outcome"] == serviceability.DELIVERED


def test_only_a_recorded_band_with_nothing_available_is_unserviceable():
    """The distinction that makes the constraint meaningful: a band somebody
    surveyed and found nothing in, versus a band nobody has looked at."""
    table = {("DE", "URBAN", p): types.SimpleNamespace(
        available=False, max_bandwidth_mbps=None)
        for p in serviceability.FALLBACK_ORDER}
    out = serviceability.resolve(table=table, country="DE", density="URBAN",
                                 product="DIA", wanted_mbps=100)
    assert out["outcome"] == serviceability.UNSERVICEABLE


def test_the_seeded_table_serves_an_urban_german_store(table):
    """A regression guard on the exact case that failed."""
    out = serviceability.resolve(table=table, country="DE", density="URBAN",
                                 product="BROADBAND_HFC", wanted_mbps=200)
    assert out["outcome"] == serviceability.DELIVERED


# ------------------- the backup path, which was never serviceability-checked
def _backup(table, density, product, primary, mbps=100, country="DE"):
    return serviceability.resolve_backup(
        table=table, country=country, density=density, product=product,
        wanted_mbps=mbps, primary_product=primary)


def test_a_backup_that_cannot_be_delivered_is_not_counted_as_resilience(table):
    """Audit finding. The backup went straight from the archetype prior into
    the circuit count, the edge list and dual_sites without being resolved - so
    a rural LARGE_OFFICE was counted dual-access on a DIA backup that the same
    table says cannot be delivered there.

    That is a resilience claim, not a cost error, and the more serious of the
    two: a cost is a number someone will challenge, and a resilience count is
    one they will rely on."""
    empty = {("DE", "RURAL", p): types.SimpleNamespace(
        available=False, max_bandwidth_mbps=None)
        for p in serviceability.FALLBACK_ORDER}
    out = _backup(empty, "RURAL", "BROADBAND_PON", "DIA")
    assert out["resilient"] is False
    assert out["outcome"] == serviceability.UNSERVICEABLE
    assert "one path" in out["note"]


def test_two_circuits_of_the_same_product_are_not_a_second_path(table):
    """Two DIA circuits from the same carrier over the same duct fail
    together. The simulation cannot know the duct; it can know the product, and
    calling two identical services diverse is the assumption that makes a
    resilience number worthless."""
    out = _backup(table, "URBAN", "ETHERNET", "ETHERNET", mbps=1000)
    assert out["resilient"] is False
    assert out["product"] is None
    assert "not a second path" in out["note"]


def test_a_substitution_onto_a_genuinely_different_product_is_resilient(table):
    """The rule must not block a real second path. A rural DC asking for an
    ETHERNET backup gets broadband, which is a different failure domain."""
    out = _backup(table, "RURAL", "ETHERNET", "ETHERNET", mbps=10_000)
    assert out["resilient"] is True
    assert out["product"] != "ETHERNET"


def test_an_ordinary_urban_backup_is_unaffected(table):
    """A constraint that blocks the common case is a bug, not a control."""
    out = _backup(table, "URBAN", "BROADBAND_PON", "DIA")
    assert out["resilient"] is True
    assert out["product"] == "BROADBAND_PON"


def test_a_row_with_no_density_still_gets_its_backup(table):
    """Silence is not a constraint, on the backup path as on the primary."""
    out = _backup(table, None, "BROADBAND_PON", "DIA")
    assert out["resilient"] is True


def test_the_simulation_reports_sites_with_no_deliverable_second_path():
    """A dual_sites count that silently shrinks reads as a weaker architecture
    rather than as a constraint on what can be delivered there."""
    import inspect

    from app.domain import simulation

    src = inspect.getsource(simulation.one_pass)
    assert "resolve_backup" in src, "the backup must be resolved"
    assert "single_by_necessity" in src
    # and the count must not be incremented when there is no second path
    guarded = src.index("resolve_backup")
    assert src.index("dual_sites += 1") > guarded


# --------------------- serviceability keyed on the bearer, not the product
def _bearer_table():
    import types

    from app.seed import SERVICEABILITY

    class _Row:
        def __init__(self, available, mbps):
            self.available, self.max_bandwidth_mbps = available, mbps

    return {(c, b, t): _Row(a, m) for c, b, t, a, m in SERVICEABILITY}


def _resolve(service_class, wanted=100, density="RURAL", country="DE"):
    return serviceability._by_access(
        table=_bearer_table(), country=country, density=density,
        service_class=service_class, wanted_mbps=wanted, asked_for="X")


def test_a_committed_vpn_is_deliverable_where_a_dedicated_service_is_not():
    """The distinction the product-keyed table could not make. It asked "is
    MPLS available in rural Germany", which a carrier answers by whether it
    will sell there - and selling is not the constraint. Reaching is.

    An IPVPN in a rural town is deliverable if a bearer reaches it. Ethernet
    transport is not, because Ethernet transport is fibre and no fibre
    reaches."""
    from app.domain import access

    assert _resolve(access.IPVPN)["outcome"] == serviceability.DELIVERED
    assert _resolve(access.ETHERNET)["outcome"] == serviceability.UNSERVICEABLE


def test_the_outcome_names_the_bearer_that_carries_it():
    """"Deliverable" without saying over what is not an answer a survey would
    accept."""
    from app.domain import access

    out = _resolve(access.BEST_EFFORT)
    assert out["access_technology"] in access.ACCESS_TECHNOLOGIES


def test_a_bearer_that_reaches_but_cannot_carry_the_size_substitutes():
    """A smaller circuit is a real option; a silent downgrade is not."""
    from app.domain import access

    out = _resolve(access.BEST_EFFORT, wanted=500)
    assert out["outcome"] == serviceability.SUBSTITUTED
    assert out["bandwidth_mbps"] < 500
    assert "below the 500 Mbps" in out["note"]


def test_an_unrecorded_bearer_is_unknown_not_unavailable():
    """The rule the product-keyed resolver had, preserved: an empty table must
    not read as an estate nobody can serve."""
    from app.domain import access

    out = serviceability._by_access(
        table={}, country="ZZ", density="RURAL",
        service_class=access.DIA, wanted_mbps=100, asked_for="X")
    assert out["outcome"] == serviceability.DELIVERED
    assert "nothing is known" in out["note"]


def test_every_service_class_has_a_carrier_list_in_the_vocabulary():
    """A service with no bearers would be unserviceable everywhere, which
    would look like a finding about the estate rather than a gap in the
    reference data."""
    from app.domain import access

    for service_class in access.SERVICE_CLASSES:
        carriers = access.carriers_for(service_class)
        assert carriers, service_class
        for technology in carriers:
            assert technology in access.ACCESS_TECHNOLOGIES, technology


def test_the_seeded_table_is_keyed_on_technologies_the_vocabulary_declares():
    """A row naming a technology the vocabulary does not know can never be
    matched, and would be invisible rather than loud."""
    from app.domain import access
    from app.seed import SERVICEABILITY

    for _country, _band, technology, _available, _mbps in SERVICEABILITY:
        assert technology in access.ACCESS_TECHNOLOGIES, technology


def test_dense_urban_delivers_what_rural_cannot():
    """The band has to matter, or the table is decoration."""
    from app.domain import access

    assert _resolve(access.ETHERNET, density="DENSE_URBAN")["outcome"] == (
        serviceability.DELIVERED)
    assert _resolve(access.ETHERNET, density="RURAL")["outcome"] == (
        serviceability.UNSERVICEABLE)
