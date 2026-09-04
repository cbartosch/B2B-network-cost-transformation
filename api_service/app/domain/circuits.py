"""What an access circuit is, expressed so it cannot be misread.

The model held one `bandwidth_mbps` per circuit. That conflates two genuinely
different facts, and the client's own invoice descriptions show both:

    IPCUK MPLS Ethernet Access/Port = 100/30      a 100 Mbps bearer, 30 CIR
    ICR FTTP ( was originally ICR FTTC 80/20)     80 down, 20 up

2,010 of 2,287 circuits in that file carry an x/y pair. Collapsing `100/30` to
`100` overstates what was bought; collapsing it to `30` understates the bearer
that was installed. Both are wrong, in opposite directions, and a single field
cannot tell you which mistake it is making.

So a speed is a **pair with a declared basis**. The basis is what stops a
bearer being read as a service rate:

    DOWN_UP        asymmetric access: 80/20 VDSL, 1000/115 FTTP, 24/1 ADSL
    PORT_SERVICE   a bearer and a committed rate: 100/30 MPLS, 1000/200 EAD
    SYMMETRIC      one figure, both directions: 100 Mbps DIA
    BEARER_ONLY    dark fibre or duct - a path, no service rate

And `priced_on` records which of the pair the tariff keys off, because that
differs: Openreach prices GEA on the downstream headline and EAD on the bearer,
and a model that guesses will guess wrong for one of them.

`bandwidth_mbps` survives as a derived view - the speed a circuit is *priced*
on - so thirty-three modules that read it keep working. The pair is
authoritative; the single figure is a projection of it.
"""
import re

# --- how to read the pair -----------------------------------------------------
DOWN_UP = "DOWN_UP"
PORT_SERVICE = "PORT_SERVICE"
SYMMETRIC = "SYMMETRIC"
BEARER_ONLY = "BEARER_ONLY"

BASES = (DOWN_UP, PORT_SERVICE, SYMMETRIC, BEARER_ONLY)

# --- the access families ------------------------------------------------------
#
# Eleven, not the six the model started with. Each declares how its pair reads
# and which figure the tariff prices, so neither is inferred from the numbers.
#
# `caps_matter` marks a family whose usable capacity is not described by speed
# alone: a 5G backup with a 50 GB allowance is not a failover path for a store,
# and treating it as one is the resilience overstatement in a second form.
FAMILIES = {
    "DIA":            {"basis": SYMMETRIC,    "priced_on": "primary"},
    "ETHERNET":       {"basis": PORT_SERVICE, "priced_on": "primary"},
    "MPLS":           {"basis": PORT_SERVICE, "priced_on": "secondary"},
    "FTTP":           {"basis": DOWN_UP,      "priced_on": "primary"},
    "SOGEA":          {"basis": DOWN_UP,      "priced_on": "primary"},
    "VDSL":           {"basis": DOWN_UP,      "priced_on": "primary"},
    "ADSL":           {"basis": DOWN_UP,      "priced_on": "primary"},
    "HFC":            {"basis": DOWN_UP,      "priced_on": "primary"},
    "FWA":            {"basis": DOWN_UP,      "priced_on": "primary",
                       "caps_matter": True},
    "MOBILE":         {"basis": DOWN_UP,      "priced_on": "primary",
                       "caps_matter": True},
    "SATELLITE":      {"basis": DOWN_UP,      "priced_on": "primary",
                       "caps_matter": True, "latency_matters": True},
    "DARK_FIBRE":     {"basis": BEARER_ONLY,  "priced_on": "primary"},
    "DUCT":           {"basis": BEARER_ONLY,  "priced_on": None},
}

# The six products the model priced before this. Kept as the pricing vocabulary
# so the seeded rate card and every existing prior still resolve - a family is
# what a circuit *is*, a product is what it is *priced as*.
LEGACY_PRODUCT = {
    "DIA": "DIA", "ETHERNET": "ETHERNET", "MPLS": "MPLS",
    "FTTP": "BROADBAND_PON", "SOGEA": "BROADBAND_HFC", "VDSL": "BROADBAND_HFC",
    "ADSL": "BROADBAND_HFC", "HFC": "BROADBAND_HFC",
    "FWA": "MOBILE_5G", "MOBILE": "MOBILE_5G", "SATELLITE": "MOBILE_5G",
    "DARK_FIBRE": "ETHERNET", "DUCT": None,
}

_PAIR = re.compile(r"(\d+(?:\.\d+)?)\s*[/xX]\s*(\d+(?:\.\d+)?)")
_SINGLE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mb|mbps|m\b)", re.I)


class SpeedUnreadable(ValueError):
    """A speed that cannot be read is not a speed of zero."""


def parse(text: str, *, family: str | None = None) -> dict:
    """A speed pair from free text, or a refusal.

    Refuses rather than guesses. `ICR ADSL ( was on WBA decisions)` carries no
    speed at all, and returning 0 or a default would put a priced circuit in
    the model on the strength of a description that never mentioned a rate.
    """
    spec = FAMILIES.get((family or "").upper(), {})
    basis = spec.get("basis")

    pair = _PAIR.search(text or "")
    if pair:
        primary, secondary = float(pair.group(1)), float(pair.group(2))
        if basis == SYMMETRIC and primary != secondary:
            # A symmetric family quoting two different numbers is not
            # symmetric - the description is better evidence than the family
            # default, so the basis yields.
            basis = PORT_SERVICE
        return {"basis": basis or DOWN_UP, "primary_mbps": primary,
                "secondary_mbps": secondary, "read_from": pair.group(0)}

    single = _SINGLE.search(text or "")
    if single:
        value = float(single.group(1))
        if basis in (None, SYMMETRIC):
            return {"basis": SYMMETRIC, "primary_mbps": value,
                    "secondary_mbps": value, "read_from": single.group(0)}
        # A pair-basis family with one figure: the figure is the bearer and the
        # service rate is unstated. Recorded as unknown, not assumed equal.
        return {"basis": basis, "primary_mbps": value,
                "secondary_mbps": None, "read_from": single.group(0),
                "note": "one figure for a two-figure basis; the second is "
                        "unstated and is not assumed to equal the first"}

    raise SpeedUnreadable(
        f"no speed in {text[:60]!r}. A circuit with no readable rate cannot be "
        f"sized or priced, and a default would put a figure in the model that "
        f"no source stated.")


def priced_speed(speed: dict, *, family: str) -> float | None:
    """The figure the tariff keys off, which is not always the headline.

    Openreach prices GEA on the downstream and MPLS on the committed rate. A
    model that used the first number for both would overprice every MPLS
    circuit by the ratio of its bearer to its CIR - on the client's own
    100/30 circuits, by more than three times.
    """
    spec = FAMILIES.get((family or "").upper(), {})
    which = spec.get("priced_on")
    if which is None:
        return None
    value = speed.get(f"{which}_mbps")
    if value is None and which == "secondary":
        # The committed rate is unstated. Falling back to the bearer would
        # overprice; refusing is correct and the caller reports it unpriced.
        return None
    return value


def describe(speed: dict, *, family: str) -> str:
    """The pair, written so a reader knows which number is which."""
    basis = speed.get("basis")
    primary, secondary = speed.get("primary_mbps"), speed.get("secondary_mbps")
    if basis == SYMMETRIC:
        return f"{primary:g} Mbps symmetric"
    if basis == BEARER_ONLY:
        return f"{primary:g} Mbps bearer, no service rate"
    if secondary is None:
        return f"{primary:g} Mbps bearer, committed rate unstated"
    if basis == PORT_SERVICE:
        return f"{primary:g} Mbps port / {secondary:g} Mbps committed"
    return f"{primary:g} down / {secondary:g} up"


# --- geographic scope ---------------------------------------------------------
#
# Most specific first. `match_prior` walks this order and takes the first hit,
# so a distance-banded EAD price beats an area price beats a national one -
# which is how Openreach actually publishes.
#
# The model had COUNTRY and REGION only, and the client's MPLS spans seven
# times within one country. Country was never a fine enough scope to price on.
SCOPE_LADDER = (
    "CASE",           # this client's own invoiced rate, never shared
    "DISTANCE_BAND",  # EAD and similar, banded from the serving exchange
    "AREA",           # Openreach Area 2 / Area 3 / HNR, a regulated zone
    "METRO",          # a city-level price zone
    "COUNTRY",
    "REGION",         # EMEA / AMER / APAC, the backbone fallback
)

# Openreach's published zones. Area 2 is competitive and Area 3 is not, so the
# charge control differs - this is regulation, not a modelling convenience.
UK_AREAS = ("National", "Area 2", "Area 3", "HNR", "Other")


def scope_rank(scope_kind: str) -> int:
    """Lower is more specific. Unknown scopes sort last rather than first: an
    unrecognised scope must not silently outrank a national tariff."""
    try:
        return SCOPE_LADDER.index((scope_kind or "").upper())
    except ValueError:
        return len(SCOPE_LADDER)
