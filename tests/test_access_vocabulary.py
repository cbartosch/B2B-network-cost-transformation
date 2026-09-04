"""What a circuit is, in the two dimensions it actually has.

The vocabulary was six values in one field - DIA, MPLS, ETHERNET,
BROADBAND_HFC, BROADBAND_PON, MOBILE_5G - conflating two orthogonal things:
`DIA` and `MPLS` are service classes, `BROADBAND_PON` is an access technology.

A client's own invoice data settles it. The same service rides four different
access technologies: 1,357 circuits over VDSL, 190 over VDSL and ADSL, 52 over
PON and VDSL. One field cannot hold both, and `Access/Port = 100/30` in those
same descriptions is a bearer and a committed rate that a single figure
destroys.
"""
import pytest

from app.domain import access


# ------------------------------------------- the basis follows from the class
@pytest.mark.parametrize("service_class,expected", [
    (access.DIA, access.PORT_COMMITTED),
    (access.IPVPN, access.BEARER_CIR),
    (access.ETHERNET, access.BEARER_SERVICE),
    (access.BEST_EFFORT, access.DOWN_UP),
])
def test_each_service_class_has_exactly_one_speed_basis(service_class, expected):
    """Four classes, four bases, one-to-one - so the convention is never
    inferred from the numbers. A pair whose basis contradicts its class is a
    validation error rather than a silent misinterpretation."""
    pair = access.speed(100, 30, service_class=service_class)
    assert pair["basis"] == expected


def test_every_class_and_basis_is_accounted_for():
    assert set(access.BASIS_FOR_CLASS) == set(access.SERVICE_CLASSES)
    assert set(access.BASIS_FOR_CLASS.values()) == set(access.SPEED_BASES)
    assert set(access.BASIS_LABELS) == set(access.SPEED_BASES)


# --------------------------------------- the two figures mean different things
def test_an_ipvpn_is_priced_on_its_committed_rate_and_sized_on_its_bearer():
    """`Access/Port = 100/30` is a 100 Mbps bearer carrying 30 Mbps committed.
    Priced at 100 it charges for a bearer as though it were capacity; sized at
    30 it installs a circuit that cannot carry the service."""
    pair = access.speed(100, 30, service_class=access.IPVPN)
    assert access.priced_rate(pair) == 30
    assert access.sizing_rate(pair) == 100


def test_a_best_effort_service_is_priced_on_its_downstream():
    """A VDSL 80/20 is sold and priced as an 80 Mbps service. The first version
    of priced_rate returned the secondary unconditionally, which priced 2,022
    best-effort circuits on their upstream - the same class of error as reading
    a bearer as a committed rate, and it survived one pass of the module."""
    pair = access.speed(80, 20, service_class=access.BEST_EFFORT)
    assert access.priced_rate(pair) == 80
    assert access.sizing_rate(pair) == 80


def test_a_single_rated_service_records_no_secondary():
    """Dark fibre has a bearer and no service layer. "Symmetric" and "unstated"
    are different facts, so the secondary is None rather than a copy."""
    pair = access.speed(10_000, None, service_class=access.ETHERNET)
    assert pair["secondary_mbps"] is None
    assert access.priced_rate(pair) == 10_000


# ----------------------------------------------------------- what it refuses
def test_a_committed_rate_above_its_own_bearer_is_refused():
    """You cannot commit 200 Mbps across a 100 Mbps port."""
    with pytest.raises(access.VocabularyError, match="exceeds"):
        access.speed(100, 200, service_class=access.IPVPN)


def test_the_old_vocabulary_is_no_longer_a_service_class():
    """MPLS was a value in the single field. It is a technology inside IPVPN,
    and accepting it as a class would let the two dimensions collapse again."""
    with pytest.raises(access.VocabularyError, match="not one of"):
        access.speed(100, 30, service_class="MPLS")
    for old in ("BROADBAND_PON", "BROADBAND_HFC", "MOBILE_5G"):
        assert old not in access.SERVICE_CLASSES


def test_a_pair_whose_basis_contradicts_its_class_is_reported():
    problems = access.validate(
        service_class=access.IPVPN, access_technology="ETHERNET_FIBRE",
        pair={"basis": access.DOWN_UP, "primary_mbps": 100,
              "secondary_mbps": 30})
    assert any("follows from the class" in p for p in problems)


def test_a_committed_service_over_contended_access_is_flagged_not_refused():
    """An IPVPN over VDSL exists and is sold. What it cannot do is guarantee a
    committed rate across contended access - so this is a caveat on the
    circuit, not a reason to reject the import."""
    problems = access.validate(
        service_class=access.IPVPN, access_technology="VDSL",
        pair=access.speed(80, 20, service_class=access.IPVPN))
    assert any("uncontended promise" in p for p in problems)


# ------------------------------------------------------------- description
def test_every_figure_a_reader_sees_carries_what_it_means():
    """The whole defect was a number whose convention lived somewhere else."""
    pair = access.speed(100, 30, service_class=access.IPVPN)
    assert access.describe(pair) == (
        "100/30 (access bearer / committed information rate)")
    assert "downstream / upstream" in access.describe(
        access.speed(80, 20, service_class=access.BEST_EFFORT))


# ------------------------------------------------------- geographic scope
def test_the_scope_ladder_runs_local_to_global():
    """IPVPN spans 308 to 2,180 within one country in the client's own data -
    seven times - so a country-level prior cannot express a local price."""
    assert access.more_specific("METRO", "COUNTRY")
    assert access.more_specific("AREA", "REGION")
    assert not access.more_specific("GLOBAL", "METRO")


def test_resolution_tries_the_tightest_scope_first():
    """A global average must never win over a local price that exists."""
    assert access.resolution_order(
        ["GLOBAL", "COUNTRY", "AREA", "METRO", "REGION"]) == [
        "METRO", "AREA", "COUNTRY", "REGION", "GLOBAL"]


def test_the_ladder_covers_what_openreach_actually_publishes():
    """Openreach prices by regulated area and Ethernet is distance-banded from
    the serving exchange. Both are levels, not adjustments."""
    for level in ("AREA", "DISTANCE_BAND", "METRO", "COUNTRY", "REGION"):
        assert level in access.SCOPE_LADDER


def test_wireless_is_listed_separately_from_wired():
    """A capped 5G service is not a fixed circuit, and treating one as the
    other is the mistake the resilience model made until 4.157."""
    assert "MOBILE_5G" in access.WIRELESS
    assert "PON" in access.WIRED
    assert not set(access.WIRED) & set(access.WIRELESS)


# ------------------------------------------- parsing the client's own text
@pytest.mark.parametrize("description,service_class,expected", [
    ("IPCUK MPLS Ethernet Access/Port = 100/30", access.IPVPN, (100, 30)),
    ("ICR FTTP ( was originally ICR FTTC 80/20)", access.BEST_EFFORT, (80, 20)),
    ("EAD 100 Mbps", access.ETHERNET, (100, None)),
])
def test_a_speed_pair_is_read_from_a_real_invoice_description(
        description, service_class, expected):
    """2,010 of 2,287 descriptions in one client's data carry an x/y pair."""
    pair = access.parse(description, service_class=service_class)
    assert pair is not None
    assert (pair["primary_mbps"], pair["secondary_mbps"]) == expected


def test_a_description_with_no_speed_is_refused_not_defaulted():
    """`ICR ADSL ( was on WBA decisions)` carries no speed at all. Returning a
    default would put a priced circuit in the estate on a bandwidth nobody
    stated - and 277 of those descriptions exist."""
    assert access.parse("ICR ADSL ( was on WBA decisions)",
                        service_class=access.BEST_EFFORT) is None
    assert access.parse("", service_class=access.DIA) is None


def test_a_prior_written_before_the_split_is_still_readable():
    """The six old values mapped onto the two dimensions they conflated, so a
    stored prior does not become unreadable when the vocabulary changes."""
    assert access.LEGACY_PRODUCT["BROADBAND_PON"] == (access.BEST_EFFORT, "PON")
    assert access.LEGACY_PRODUCT["MPLS"] == (access.IPVPN, None)
    for service_class, technology in access.LEGACY_PRODUCT.values():
        assert service_class in access.SERVICE_CLASSES
        assert technology is None or technology in access.ACCESS_TECHNOLOGIES


def test_the_uk_areas_are_the_ones_the_tariff_publishes():
    """Openreach's regulated zones are levels, not adjustments to a national
    figure."""
    assert "Area 2" in access.UK_AREAS and "Area 3" in access.UK_AREAS


def test_a_metered_access_technology_is_marked_as_such():
    """A 5G backup with a 50 GB allowance is not a failover path for a store,
    and a speed pair says nothing about it - which compounds the resilience
    overstatement fixed in 4.157."""
    for technology in ("MOBILE_4G", "MOBILE_5G", "SATELLITE"):
        assert access.caps_matter(technology), technology
    for technology in ("PON", "ETHERNET_FIBRE", "VDSL"):
        assert not access.caps_matter(technology), technology


def test_an_unknown_scope_sorts_last_rather_than_first():
    """An unrecognised scope must never silently outrank a national tariff that
    exists. Returning 0 for anything unfamiliar would make a typo the most
    specific price in the system."""
    assert access.scope_rank("NONSENSE") > access.scope_rank("REGION")
    assert access.scope_rank("METRO") == 0


# ------------------------------------------------- the vocabulary is wired
def test_the_vocabulary_is_used_by_the_model_and_not_only_by_its_own_tests():
    """The audit finding this test exists for.

    The four-class vocabulary shipped in 4.166 with twenty passing tests and
    nothing importing it. Every symbol read `used by: nothing`. The model still
    priced on a single bandwidth field, so an IPVPN at 100/30 was still priced
    on 100 - the exact defect the module was built to prevent.

    That is the same shape as `fx_convention` collected and never read, and
    `expires` written onto every prior and ignored by match_prior. A module
    nobody imports is a document, not a control.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "domain").exists())

    importers = set()
    for path in (app / "domain").glob("*.py"):
        if path.stem == "access":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and any(
                    a.name == "access" for a in node.names):
                importers.add(path.stem)
    assert importers, (
        "nothing imports domain/access.py - the vocabulary is inert and the "
        "model still prices on a single bandwidth field")
    # The two places that must use it: the rate card and serviceability.
    assert "estimate" in importers, "the rate card must key on the priced rate"
    assert "serviceability" in importers, (
        "deliverability must be judged on the bearer")


def test_the_rate_card_keys_on_the_priced_rate():
    """An IPVPN at 100/30 priced on its bearer charges for capacity the client
    is not buying - 2.33x per circuit on the reference estate's own rate card,
    across 319 circuits."""
    import inspect

    from app.domain import estimate

    source = inspect.getsource(estimate.match_prior)
    assert "access.priced_rate(speed)" in source


def test_deliverability_is_judged_on_the_bearer():
    """The opposite rate to the price. Asking whether 30 Mbps is available
    would call a 100/30 circuit serviceable wherever 30 is deliverable, which
    is not what has to be installed."""
    import inspect

    from app.domain import serviceability

    for fn in (serviceability.resolve, serviceability.resolve_backup):
        assert "access.sizing_rate(speed)" in inspect.getsource(fn), fn.__name__


def test_the_scope_ladder_has_one_definition():
    """match_prior carried its own ladder in a comment while access.py held
    the real one - a fourth copy of the same concept, and the copy a reader
    finds first."""
    import inspect

    from app.domain import estimate

    source = inspect.getsource(estimate.match_prior)
    assert "access.scope_rank" in source
    assert "DISTANCE_BAND" not in source, (
        "the ladder belongs in the vocabulary, not restated here")


# ------------------------------- the rate card keyed on the two dimensions
def _priors():
    return {
        "fibre": {"scope": "GB", "service_class": "IPVPN",
                  "access_technology": "ETHERNET_FIBRE",
                  "bandwidth_mbps": 30, "base": "420"},
        "vdsl": {"scope": "GB", "service_class": "IPVPN",
                 "access_technology": "VDSL",
                 "bandwidth_mbps": 30, "base": "95"},
        "agnostic": {"scope": "GB", "service_class": "IPVPN",
                     "access_technology": None,
                     "bandwidth_mbps": 30, "base": "300"},
        "legacy": {"scope": "GB", "product": "MPLS",
                   "bandwidth_mbps": 30, "base": "999"},
    }


def test_the_same_service_over_different_access_resolves_to_different_rates():
    """`product` held one value for two orthogonal facts, so an IPVPN over VDSL
    and an IPVPN over fibre - genuinely different prices - could not be told
    apart at all."""
    from app.domain.estimate import match_prior

    pair = access.speed(100, 30, service_class=access.IPVPN)
    fibre, _ = match_prior(_priors(), "GB", "MPLS", 100, speed=pair,
                           service_class=access.IPVPN,
                           access_technology="ETHERNET_FIBRE")
    vdsl, _ = match_prior(_priors(), "GB", "MPLS", 100, speed=pair,
                          service_class=access.IPVPN,
                          access_technology="VDSL")
    assert fibre["base"] == "420"
    assert vdsl["base"] == "95"


def test_an_unmatched_technology_falls_back_to_the_agnostic_rate():
    """A DIA tariff quoted per Mbps does not care how the fibre arrives. The
    fallback is by specificity - exact technology first, then agnostic, never
    the reverse."""
    from app.domain.estimate import match_prior

    pair = access.speed(100, 30, service_class=access.IPVPN)
    hit, _ = match_prior(_priors(), "GB", "MPLS", 100, speed=pair,
                         service_class=access.IPVPN,
                         access_technology="MOBILE_5G")
    assert hit["base"] == "300"
    assert hit["access_technology"] is None


def test_a_rate_card_that_has_not_been_migrated_still_prices():
    """Additive, not a flag day: a caller supplying no service class gets the
    legacy key, so a snapshot written before this change stays reproducible."""
    from app.domain.estimate import match_prior

    legacy = {("GB", "MPLS", 30): {"base": "999"}}
    hit, _ = match_prior(legacy, "GB", "MPLS", 30)
    assert hit["base"] == "999"


def test_the_dimensions_are_derived_from_one_mapping_not_restated():
    """LEGACY_PRODUCT is the single mapping from the old field to the two
    dimensions. The seed derives from it; duplicating it there would be a
    second copy to drift, which is how ORIGIN_RANK ended up in two modules."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "seed.py").exists())
    seed = (app / "seed.py").read_text()
    assert "access.LEGACY_PRODUCT[p][0]" in seed
    assert "access.LEGACY_PRODUCT[p][1]" in seed
    # and every mapped value is in the vocabulary
    for service_class, technology in access.LEGACY_PRODUCT.values():
        assert service_class in access.SERVICE_CLASSES
        assert technology is None or technology in access.ACCESS_TECHNOLOGIES


# --------------------------- the analyst chooses the class, not the technology
def test_the_analyst_choice_overrides_the_seeded_class():
    """A store may take a best-effort internet service or a managed VPN, and
    that is a decision about what the business needs."""
    import types

    from app.domain import simulation

    archetypes = {"STORE": {"dual_access_probability": 0.0,
                            "primary_product": "BROADBAND_HFC",
                            "backup_product": "MOBILE_5G", "users_base": 12,
                            "bandwidth_mbps_base": 50,
                            "primary_service_class": "BEST_EFFORT",
                            "backup_service_class": "BEST_EFFORT"}}
    footprint = [{"country": "GB", "archetype": "STORE", "sites": 100}]

    default = simulation.one_pass(42, footprint, archetypes)
    chosen = simulation.one_pass(42, footprint, archetypes,
                                 service_class_by_archetype={"STORE": "IPVPN"})
    assert {r["service_class"] for r in default["products"]} == {"BEST_EFFORT"}
    assert {r["service_class"] for r in chosen["products"]} == {"IPVPN"}


def test_choosing_a_service_class_does_not_change_the_access_technology():
    """How it arrives is whatever serviceability can deliver. A store served by
    PON rather than HFC is the same decision met a different way, not a
    substitution - which is what `primary_product` could not express."""
    from app.domain import simulation

    archetypes = {"STORE": {"dual_access_probability": 0.0,
                            "primary_product": "BROADBAND_HFC",
                            "backup_product": "MOBILE_5G", "users_base": 12,
                            "bandwidth_mbps_base": 50,
                            "primary_service_class": "BEST_EFFORT",
                            "backup_service_class": "BEST_EFFORT"}}
    footprint = [{"country": "GB", "archetype": "STORE", "sites": 100}]

    before = simulation.one_pass(42, footprint, archetypes)
    after = simulation.one_pass(42, footprint, archetypes,
                                service_class_by_archetype={"STORE": "IPVPN"})
    assert ([r["access_technology"] for r in before["products"]]
            == [r["access_technology"] for r in after["products"]])


def test_an_unmigrated_prior_still_yields_a_service_class():
    """A prior written before 4.169 has no service class. Derived from its
    product rather than left null, so an old reference row still prices."""
    from app.domain import simulation

    archetypes = {"STORE": {"dual_access_probability": 0.0,
                            "primary_product": "BROADBAND_HFC",
                            "backup_product": "MOBILE_5G", "users_base": 12,
                            "bandwidth_mbps_base": 50}}
    out = simulation.one_pass(
        42, [{"country": "GB", "archetype": "STORE", "sites": 10}], archetypes)
    assert {r["service_class"] for r in out["products"]} == {"BEST_EFFORT"}


def test_a_backbone_link_is_ethernet_transport():
    """It carries the WAN between hubs rather than a site's internet access."""
    from app.domain import simulation

    out = simulation.one_pass(
        42, [{"country": "GB", "archetype": "STORE", "sites": 10}],
        {"STORE": {"dual_access_probability": 0.0,
                   "primary_product": "BROADBAND_HFC",
                   "backup_product": "MOBILE_5G", "users_base": 12,
                   "bandwidth_mbps_base": 50,
                   "primary_service_class": "BEST_EFFORT",
                   "backup_service_class": "BEST_EFFORT"}},
        backbone={"links": [{"tier": "DC_TO_REGION", "region": "EMEA",
                             "count": 1, "product": "ETHERNET",
                             "bandwidth_mbps": 10000, "dual": True}]})
    backbone = [r for r in out["products"] if r["role"] == "BACKBONE"]
    assert backbone and all(r["service_class"] == access.ETHERNET
                            for r in backbone)


def test_an_access_technology_cannot_be_chosen_as_a_service_class():
    """The endpoint refuses PON: it is resolved, not chosen."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "not a service class" in api
    assert "resolved by serviceability" in api


def test_the_service_class_choice_is_pinned_to_the_run():
    """The serviceability table was read and not pinned in 4.135, and every
    site came back unserviceable. A choice read from the case rather than the
    run would price half an estate one way and half the other when the analyst
    changed it mid-run."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "jobs.py").exists())
    api = (app / "routers" / "api.py").read_text()
    jobs = (app / "jobs.py").read_text()
    assert '"service_class_by_archetype": (' in api, "the route must pin it"
    assert 'get("service_class_by_archetype")' in jobs, "the runner must read it"
    assert "service_class_by_archetype=service_class_by_archetype" in jobs, (
        "and must pass it to the simulation, or it is read and never used")
