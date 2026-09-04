"""What an access circuit is, expressed so it cannot be misread.

The model held one `bandwidth_mbps`, and the reference estate's own invoice
descriptions show why that is two facts in one field:

    IPCUK MPLS Ethernet Access/Port = 100/30      100 Mbps bearer, 30 committed
    ICR FTTP ( was originally ICR FTTC 80/20)     80 down, 20 up

Pricing the first on its bearer looks up a tier the client never bought. On
that estate the mean port-to-committed ratio is 3.29x across 307 circuits worth
GBP 100,392 a month.
"""
import pytest

from app.domain import circuits


# ------------------------------------------------ the pair carries its meaning
@pytest.mark.parametrize("text,family,basis,primary,secondary", [
    ("IPCUK MPLS Ethernet Access/Port = 100/30", "MPLS",
     circuits.PORT_SERVICE, 100, 30),
    ("ICR FTTP ( was originally ICR FTTC 80/20)", "FTTP",
     circuits.DOWN_UP, 80, 20),
    ("GEA-FTTP 1000/115", "FTTP", circuits.DOWN_UP, 1000, 115),
    ("Wireless Broadband 30/5", "FWA", circuits.DOWN_UP, 30, 5),
    ("BT Direct Internet 100Mb", "DIA", circuits.SYMMETRIC, 100, 100),
])
def test_a_real_description_parses_to_a_pair(text, family, basis, primary,
                                             secondary):
    speed = circuits.parse(text, family=family)
    assert speed["basis"] == basis
    assert speed["primary_mbps"] == primary
    assert speed["secondary_mbps"] == secondary


def test_mpls_is_priced_on_the_committed_rate_not_the_bearer():
    """The finding, and the reason the pair exists. A rate card keyed on the
    100 Mbps port looks up a tier the client never bought - 3.3x too high on
    the reference estate's 307 MPLS circuits."""
    speed = circuits.parse("Access/Port = 100/30", family="MPLS")
    assert circuits.priced_speed(speed, family="MPLS") == 30


def test_gea_is_priced_on_the_downstream_headline():
    """Openreach prices GEA on the downstream and MPLS on the committed rate.
    A model that used the first number for both would be wrong for one."""
    speed = circuits.parse("1000/115", family="FTTP")
    assert circuits.priced_speed(speed, family="FTTP") == 1000


def test_an_unstated_committed_rate_is_not_assumed_to_equal_the_bearer():
    """`EAD 100 Mbps` states a bearer and no service rate. Falling back to the
    bearer would overprice; the caller must report it unpriced instead."""
    speed = circuits.parse("EAD 100 Mbps", family="MPLS")
    assert speed["primary_mbps"] == 100
    assert speed["secondary_mbps"] is None
    assert circuits.priced_speed(speed, family="MPLS") is None


def test_a_description_with_no_speed_is_refused_not_defaulted():
    """`ICR ADSL ( was on WBA decisions)` carries no rate. A default would put
    a figure in the model that no source stated."""
    with pytest.raises(circuits.SpeedUnreadable, match="no speed"):
        circuits.parse("ICR ADSL ( was on WBA decisions)", family="ADSL")


def test_a_symmetric_family_quoting_two_figures_yields_to_the_description():
    """The description is better evidence than the family default."""
    speed = circuits.parse("DIA 100/50", family="DIA")
    assert speed["basis"] == circuits.PORT_SERVICE


def test_every_family_declares_how_its_pair_reads():
    """A family without a basis would have its pair interpreted by guesswork,
    which is the defect the basis exists to remove."""
    for family, spec in circuits.FAMILIES.items():
        assert spec["basis"] in circuits.BASES, family
        assert "priced_on" in spec, family


def test_a_metered_family_is_marked_as_such():
    """A 5G backup with a 50 GB allowance is not a failover path for a store,
    and speed alone does not say so - which compounds the resilience
    overstatement fixed in 4.157."""
    for family in ("MOBILE", "FWA", "SATELLITE"):
        assert circuits.FAMILIES[family].get("caps_matter") is True, family
    assert not circuits.FAMILIES["DIA"].get("caps_matter")


def test_the_description_names_which_number_is_which():
    """A reader seeing "100/30" cannot tell a bearer from a downstream."""
    port = circuits.parse("100/30", family="MPLS")
    down = circuits.parse("80/20", family="FTTP")
    assert "committed" in circuits.describe(port, family="MPLS")
    assert "down" in circuits.describe(down, family="FTTP")


def test_every_family_maps_to_a_product_the_rate_card_prices():
    """A family is what a circuit is; a product is what it is priced as. A
    family with no product would parse and never price."""
    priced = {"DIA", "MPLS", "ETHERNET", "BROADBAND_HFC", "BROADBAND_PON",
              "MOBILE_5G"}
    for family in circuits.FAMILIES:
        product = circuits.LEGACY_PRODUCT[family]
        assert product is None or product in priced, family


# ------------------------------------------------------- geographic specificity
def test_scope_is_ranked_most_specific_first():
    """A national tariff is a fallback, not the answer: the reference estate's
    MPLS spans seven times within one country."""
    ranks = [circuits.scope_rank(s) for s in
             ("CASE", "DISTANCE_BAND", "AREA", "METRO", "COUNTRY", "REGION")]
    assert ranks == sorted(ranks)
    assert circuits.scope_rank("CASE") < circuits.scope_rank("COUNTRY")


def test_an_unknown_scope_sorts_last_rather_than_first():
    """An unrecognised scope must not silently outrank a national tariff."""
    assert circuits.scope_rank("NONSENSE") > circuits.scope_rank("REGION")


def test_the_uk_areas_are_the_published_zones():
    """Area 2 is competitive and Area 3 is not, so the charge control differs.
    This is regulation, not a modelling convenience."""
    assert "Area 2" in circuits.UK_AREAS and "Area 3" in circuits.UK_AREAS
