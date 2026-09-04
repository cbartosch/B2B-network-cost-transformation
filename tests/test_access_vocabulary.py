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
