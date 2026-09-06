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


# ------------------------- the analyst assigns the service class per site type
def _pass(choice=None):
    from app.domain import simulation
    return simulation.one_pass(
        42, [{"country": "GB", "archetype": "STORE", "sites": 100}],
        {"STORE": {"dual_access_probability": 0.0,
                   "primary_product": "BROADBAND_HFC",
                   "backup_product": "MOBILE_5G", "users_base": 12,
                   "bandwidth_mbps_base": 50}},
        service_class_by_archetype=choice)


def test_the_analyst_choice_changes_what_a_site_type_buys():
    """A store on a best-effort broadband service and a store on a committed
    IPVPN are different estates at the same site count, and the seeded prior is
    a starting position rather than a decision."""
    default = {r.get("service_class") for r in _pass()["products"]
               if r["role"] == "PRIMARY"}
    chosen = {r.get("service_class") for r in _pass({"STORE": "IPVPN"})["products"]
              if r["role"] == "PRIMARY"}
    assert default == {access.BEST_EFFORT}
    assert chosen == {access.IPVPN}


def test_choosing_a_service_class_does_not_choose_an_access_technology():
    """The whole reason the two are separate fields. `primary_product` held
    both, so choosing BROADBAND_HFC for a store asserted a delivery technology
    as well as a service level - and a store served by PON instead came out as
    a substitution rather than as the same decision met a different way."""
    products = {r["product"] for r in _pass({"STORE": "IPVPN"})["products"]
                if r["role"] == "PRIMARY"}
    assert products == {"BROADBAND_HFC"}, (
        "the access technology must stay whatever serviceability delivers")


def test_an_unassigned_site_type_keeps_its_seeded_default():
    """Assigning one type must not blank the others."""
    out = _pass({"WAREHOUSE": "DIA"})          # STORE unassigned
    assert {r.get("service_class") for r in out["products"]
            if r["role"] == "PRIMARY"} == {access.BEST_EFFORT}


def test_the_assignment_is_reachable_from_the_interface():
    """Both endpoints existed and were complete for a release while no screen
    called them - so an analyst had no way to assign anything, and the
    reachability check did not cover a PUT under a case."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = next(p for p in (root / "analyst_ui").rglob("*.py")
                if "Simulation" in p.name).read_text()
    assert "/service-classes" in page
    assert "Assign these service classes" in page


def test_the_assignment_is_pinned_to_the_run():
    """A resumed or re-read run must price on the classes it was run with, not
    on whatever the case says now - the same rule serviceability needed in
    4.137."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    # Bounded by the params dict itself rather than by a character count. My
    # first version used [:600] and the pin sits 1,601 characters in, so a
    # correct pin failed on a window size - the same defect as the 1,600-char
    # window in test_ui_pages.
    start = api.index('params={"footprint"')
    end = api.index("\n        )", start)
    assert "service_class_by_archetype" in api[start:end], (
        "the chosen classes must be pinned to the run, or a resumed pass "
        "prices on whatever the case says now")


def _seeded_platform_products():
    """The platform products the rate card prices, from the seed's source."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "seed.py").exists())
    source = (app / "seed.py").read_text()
    start = source.index("PLATFORM = [")
    namespace = {}
    exec(source[start:source.index("\n]\n", start) + 3], namespace)
    return {row[0] for row in namespace["PLATFORM"]}


def _seeded_levers():
    """The LEVERS table, read from the seed's source.

    Importing app.seed pulls in sqlalchemy, which is absent wherever there is
    no database - so a guard that imports it does not run in the offline
    runner. That is exactly where this one was.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "seed.py").exists())
    source = (app / "seed.py").read_text()
    start = source.index("LEVERS = [")
    namespace = {}
    exec(source[start:source.index("\n]\n", start) + 3], namespace)
    return namespace["LEVERS"]


# ------------- lever eligibility on the live vocabulary
#
# These lived in test_savings_advisory.py, which imports sqlalchemy at
# module level and is therefore blocked in the offline runner - so the
# guard written to catch exactly this drift did not run, and missed that
# LEV-MPLS-001 still read ["MPLS"]. A guard in a file that cannot execute
# is a comment.
def test_every_lever_constraint_names_a_value_the_vocabulary_declares():
    """The defect this test exists for.

    `applies_to_products` was keyed on the vocabulary 4.166 replaced.
    LEV-MPLS-001 named "MPLS", which is no longer a service class - it is
    IPVPN. The moment the pipeline supplied a service class, that lever would
    have matched nothing and booked zero MPLS savings for entirely the wrong
    reason, which looks exactly like the correct behaviour.

    Whichever landed first - the pipeline switch or the re-key - would have
    silently broken the other. This is the guard that makes the next change to
    either one fail loudly instead."""
    from app.domain import access

    # Read from source rather than imported: app.seed imports sqlalchemy at
    # module level, so importing it blocks this guard in any environment
    # without a database - which is where it was, silently, while
    # LEV-MPLS-001 still read ["MPLS"].
    for row in _seeded_levers():
        lever_id, service_classes = row[0], row[7]
        access_technologies, platform = row[8], row[9]
        for value in service_classes or ():
            assert value in access.SERVICE_CLASSES, (
                f"{lever_id} is eligible on service class {value!r}, which is "
                f"not in {list(access.SERVICE_CLASSES)}")
        for value in access_technologies or ():
            assert value in access.ACCESS_TECHNOLOGIES, (
                f"{lever_id} names access technology {value!r}, which the "
                f"vocabulary does not declare")
        # Platform products are the L2/L4 vocabulary and deliberately not
        # service classes - SSE_LICENCE never was one.
        #
        # And they must be products the rate card actually prices. The first
        # version of this guard checked service classes and access
        # technologies and not this dimension, so LEV-SASE-001 named
        # "SD_WAN_OVERLAY" while the platform table seeded "SDWAN_OVERLAY" -
        # one underscore, and the lever could never match anything.
        priced = _seeded_platform_products()
        for value in platform or ():
            assert value not in access.SERVICE_CLASSES, (
                f"{lever_id} lists {value!r} as a platform product and it is "
                f"also a service class - the two dimensions have collapsed")
            assert value in priced, (
                f"{lever_id} is eligible on platform product {value!r}, which "
                f"the rate card does not price. Priced: {sorted(priced)}")


def test_the_dead_product_field_is_not_read_by_the_eligibility_test():
    """Retained for readability, deliberately not consulted: its values cannot
    match the new vocabulary, so falling back to it would silently disable a
    lever rather than fail."""
    import inspect

    from app.domain import estimate

    source = inspect.getsource(estimate.scenarios)
    assert "applies_to_service_classes" in source
    assert 'lever.get("applies_to_products")' not in source


def test_a_platform_lever_is_not_eligible_on_an_access_circuit():
    """`applies_to_products` held one list for two unrelated things: the L0
    levers named MPLS and DIA, the L2/L4 levers named SD_WAN_OVERLAY and
    SSE_LICENCE. The same conflation as `product`, one level up."""
    from app.domain import access

    sase = next(r for r in _seeded_levers() if r[0] == "LEV-SASE-001")
    assert sase[7] is None, "a platform lever constrains no service class"
    assert sase[9] == ["SDWAN_OVERLAY", "SSE_LICENCE"]
    assert not set(sase[9]) & set(access.SERVICE_CLASSES)


def test_right_sizing_excludes_best_effort():
    """Right-sizing needs a committed rate to reduce. The old list named the
    committed classes one by one - DIA, ETHERNET, MPLS - which is what "not
    BEST_EFFORT" says directly: a 100/20 broadband line is not sold at 60/12."""
    from app.domain import access

    rightsizing = next(r for r in _seeded_levers()
                       if r[0] == "LEV-BANDWIDTH-001")
    assert access.BEST_EFFORT not in rightsizing[7]
    assert set(rightsizing[7]) == {access.DIA, access.IPVPN, access.ETHERNET}


def test_a_target_component_keeps_its_dimensions():
    """Audit finding A-04, closed here. target_components was rebuilt without
    the fields, so every target row reported a null product - and a lever's
    own eligibility could not be checked against the estate it had acted on."""
    import inspect

    from app.domain import estimate

    source = inspect.getsource(estimate.scenarios)
    for field in ("product=c.product", "service_class=c.service_class",
                  "access_technology=c.access_technology"):
        assert field in source, field


# ---------------------------------------------- the live pipeline is switched
PRIORS = {
    "fibre": {"scope": "GB", "service_class": "IPVPN",
              "access_technology": "ETHERNET_FIBRE",
              "bandwidth_mbps": 100, "base": "980"},
    "vdsl": {"scope": "GB", "service_class": "IPVPN",
             "access_technology": "VDSL", "bandwidth_mbps": 100, "base": "220"},
    ("GB", "MPLS", 100): {"base": "999"},
}


def _row(**over):
    row = {"country": "GB", "product": "MPLS", "bandwidth_mbps": 100,
           "role": "PRIMARY", "count": 10}
    row.update(over)
    return row


def test_the_pricing_pipeline_discriminates_by_access_technology():
    """Both live call sites passed `row["product"]` alone, so an IPVPN over
    VDSL and an IPVPN over fibre resolved to one rate - a 4.4x difference the
    conflated field could not express, on every circuit in every estate."""
    from app.domain.estimate import match_prior

    fibre, _ = match_prior(
        PRIORS, "GB", "MPLS", 100, service_class=access.IPVPN,
        access_technology="ETHERNET_FIBRE")
    vdsl, _ = match_prior(
        PRIORS, "GB", "MPLS", 100, service_class=access.IPVPN,
        access_technology="VDSL")
    assert fibre["base"] == "980"
    assert vdsl["base"] == "220"


def test_a_row_without_the_dimensions_still_prices():
    """The switch is additive. A simulation output written before 4.169 has no
    service class, and must not become unpriced scope."""
    from app.domain.estimate import match_prior

    legacy, _ = match_prior(PRIORS, "GB", "MPLS", 100)
    assert legacy["base"] == "999"


@pytest.mark.parametrize("module,call", [
    ("coverage", "derive_scope"),
    ("estimate", "build_components"),
])
def test_both_live_call_sites_pass_the_dimensions(module, call):
    """The gate and the calculation must agree. Two different notions of
    "priced" would mean the gate was measuring something the total did not
    contain."""
    import importlib
    import inspect

    source = inspect.getsource(
        getattr(importlib.import_module(f"app.domain.{module}"), call))
    assert 'service_class=row.get("service_class")' in source, module
    assert 'access_technology=row.get("access_technology")' in source, module


def test_the_simulation_emits_what_the_pipeline_reads():
    """The producer and the consumers have to agree on the field names, or the
    switch silently reads None and falls back to the legacy key forever - which
    would look exactly like the switch working."""
    import inspect

    from app.domain import simulation

    source = inspect.getsource(simulation.one_pass)
    for field in ('"service_class"', '"access_technology"'):
        assert field in source, f"the simulation must emit {field}"


# ------------- the evidence path speaks the same vocabulary as the rate card
def test_a_cleared_observation_derives_a_prior_the_new_key_can_find():
    """Red-team finding. The rate card was re-keyed on service class and access
    technology in 4.168; `benchmark_observation` carried neither, and the
    derive step wrote a prior with only a product.

    So every prior derived from evidence was reachable only through the legacy
    fallback - the route from a cleared observation to a graded rate was broken
    by the re-key that route exists to serve, and it would have looked like the
    benchmark vault simply never improving anything."""
    import inspect

    from app.domain import benchmark_ingest

    source = inspect.getsource(benchmark_ingest.derive_bands)
    assert "service_class=service_class" in source
    assert "access_technology=technology" in source


def test_a_derived_prior_is_graded_as_a_benchmark_not_an_assumption():
    """Without a grade it inherited the column default, which is E - so a rate
    built from cleared market observations looked exactly like a seeded guess,
    and `unsourced_price_share` counted it as one."""
    import inspect

    from app.domain import benchmark_ingest

    source = inspect.getsource(benchmark_ingest.derive_bands)
    assert 'evidence_grade="C"' in source
    assert 'price_basis="BENCHMARK"' in source


def test_a_group_disagreeing_on_service_class_falls_back_rather_than_averaging():
    """Observations that disagree on what was bought are not one band. The
    derivation takes the agreed value where there is one and the product's
    mapping where there is not - it never picks a winner."""
    import inspect

    from app.domain import benchmark_ingest

    source = inspect.getsource(benchmark_ingest.derive_bands)
    assert "if len(classes) == 1" in source


def test_every_table_that_prices_speaks_one_vocabulary():
    """The guard for the class. Three tables were re-keyed and a fourth was
    not, which is how a chain breaks in the middle: each end is consistent and
    the join between them is not."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "db.py").exists())
    source = (app / "db.py").read_text()

    for table in ("unit_cost_prior", "benchmark_observation"):
        start = source.index(f"{table} = Table(")
        end = source.index("schema=", start)
        columns = {node.args[0].value
                   for node in ast.walk(ast.parse(source[start:end] + ")"))
                   if isinstance(node, ast.Call)
                   and getattr(node.func, "id", "") == "Column"
                   and node.args and isinstance(node.args[0], ast.Constant)}
        assert "service_class" in columns, table
        assert "access_technology" in columns, table


# ------------------------------- the second figure, and where it comes from
def test_a_committed_service_is_priced_on_what_it_buys():
    """The link that was missing. The model knew one figure per site type and
    could not say whether it was the pipe or the guarantee, so an IPVPN on a
    100 Mbps bearer was priced as 100 Mbps of committed capacity - 980 a month
    against 420 on the GB rate card, on every committed circuit."""
    pair = access.pair_for(service_class=access.IPVPN, bearer_mbps=100,
                           committed_fraction="0.50")
    assert access.priced_rate(pair) == 50
    assert access.sizing_rate(pair) == 100


def test_a_data_centre_buys_a_smaller_fraction_of_a_larger_bearer():
    """An analyst's judgement, recorded: a data centre's peak is bursty and
    bearer capacity is cheap at that scale, so it commits 30%. A store has no
    headroom to burst into and commits half."""
    from app.seed import ARCHETYPES

    fractions = {row[0]: row[6] for row in ARCHETYPES}
    assert fractions["DC"] == "0.30"
    assert fractions["STORE"] == "0.50"
    assert fractions["BRANCH"] == "0.50"


def test_a_best_effort_service_takes_its_upstream_from_the_technology():
    """Not from the site type. A VDSL line is 80/20 and a GPON line 1000/115
    because that is what the standard delivers, not because anyone negotiated
    it - so the second figure belongs to the bearer, not the building."""
    vdsl = access.pair_for(service_class=access.BEST_EFFORT, bearer_mbps=80,
                           access_technology="VDSL")
    pon = access.pair_for(service_class=access.BEST_EFFORT, bearer_mbps=1000,
                          access_technology="PON")
    assert (vdsl["primary_mbps"], vdsl["secondary_mbps"]) == (80, 20)
    assert (pon["primary_mbps"], pon["secondary_mbps"]) == (1000, 115)


def test_a_dedicated_service_is_symmetric():
    pair = access.pair_for(service_class=access.DIA, bearer_mbps=500)
    assert pair["primary_mbps"] == pair["secondary_mbps"] == 500


def test_an_unstated_fraction_yields_no_secondary_rather_than_a_guess():
    """`priced_rate` then falls back to the bearer, which is the old
    overstatement - so the absence has to be visible rather than silently
    priced. Reported, not invented."""
    pair = access.pair_for(service_class=access.IPVPN, bearer_mbps=100,
                           committed_fraction=None)
    assert pair["secondary_mbps"] is None
    assert access.priced_rate(pair) == 100


def test_an_unknown_technology_is_treated_as_symmetric():
    """The conservative direction: it overstates the upstream, and a site sized
    on too much upstream is priced correctly while one sized on too little
    would look deliverable when it is not."""
    assert access.upstream_share("SOMETHING_NEW") == 1
    assert access.upstream_share(None) == 1


def test_the_simulation_emits_the_priced_rate_not_the_bearer():
    """The last link. Everything upstream of this was built and nothing
    supplied a pair, so the pipeline priced on the bearer regardless."""
    import inspect

    from app.domain import simulation

    source = inspect.getsource(simulation.one_pass)
    assert "access.pair_for(" in source
    assert "access.priced_rate(pair)" in source


# ------------------------- the default is a starting position, not a decision
def test_the_case_choice_overrides_the_seeded_default():
    """A seeded fraction records a judgement. An engagement that knows what its
    sites actually commit should not need a rebuild to say so - the same
    treatment the service class already gets."""
    import inspect

    from app.domain import simulation

    source = inspect.getsource(simulation.one_pass)
    assert "committed_fraction_by_archetype" in source
    # the case's choice is tried before the seeded default
    choice = source.index("committed_fraction_by_archetype or {}")
    seeded = source.index('prior.get("committed_fraction")')
    assert choice < seeded, "the case choice must be tried first"


def test_the_ensemble_forwards_both_analyst_choices():
    """`service_class_by_archetype` was accepted by run_ensemble and never
    passed to one_pass - a defaulted positional wedged in front of the
    keyword-only marker by an automated edit - so every ensemble run silently
    used the seeded default and the assignment screen appeared to do nothing.
    """
    import inspect

    from app.domain import simulation

    source = inspect.getsource(simulation.run_ensemble)
    assert "service_class_by_archetype=service_class_by_archetype" in source
    assert "committed_fraction_by_archetype=(" in source


def test_the_job_runner_reads_the_choice_it_was_pinned_with():
    """From the run's own pinned priors rather than the case, so changing the
    choice mid-run does not price half an estate one way and half the other."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "jobs.py").exists())
    jobs = (app / "jobs.py").read_text()
    assert 'get("committed_fraction_by_archetype")' in jobs
    assert "row.pinned_priors" in jobs


def test_a_fraction_outside_the_bearer_is_refused():
    """A site cannot commit more than the circuit it has, and committing
    nothing is a best-effort service rather than a committed one with a
    fraction of zero."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "outside (0, 1]" in api


def test_the_panel_reaches_a_screen():
    """Three controls this session existed and reached no screen."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    page = next(p for p in (root / "analyst_ui").rglob("*.py")
                if "Simulation" in p.name).read_text()
    assert "/committed-fractions" in page
    assert "Set these committed shares" in page


# ------------------ a researched price is evidence, and must arrive as one
def test_a_promoted_price_carries_a_grade_and_the_dimensions():
    """The other writer of unit_cost_prior. The benchmark path was fixed in
    4.177 and this one was not, so a price an agent found - with its claim
    checked against the page it came from - inherited the column default of E
    and looked exactly like a seeded guess."""
    import inspect

    from app.domain import promotion

    source = inspect.getsource(promotion)
    block = source[source.index('-researched"'):]
    assert 'evidence_grade="C"' in block[:2000]
    assert 'price_basis="PROMOTED"' in block[:2000]
    assert "service_class=access.LEGACY_PRODUCT" in block[:2000]


def test_a_promoted_price_keeps_the_currency_the_source_quoted():
    """Every promoted price was stamped USD regardless of the country
    researched, so a EUR tariff found in France entered the rate card as
    dollars - 7 to 8% before anything else happened, and invisible because
    every other row said USD too.

    The agent has reported a currency since the schema gained one; the
    promotion discarded it."""
    import inspect

    from app.domain import promotion

    source = inspect.getsource(promotion)
    block = source[source.index('-researched"'):]
    assert 'currency=(q.get("currency") or "USD")' in block[:2500]
    assert 'currency="USD"' not in block[:2500], (
        "a hardcoded currency on a researched price is a country-sized error")


def test_the_agent_schema_can_report_a_currency():
    """It always could. The loss was downstream."""
    from app.llm import schemas

    fields = schemas.Quantity.model_fields
    assert "currency" in fields
    assert "term_months" in fields
