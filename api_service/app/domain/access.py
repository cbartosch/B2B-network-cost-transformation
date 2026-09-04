"""What a circuit is, in the two dimensions it actually has.

The vocabulary was six values in one field - DIA, MPLS, ETHERNET,
BROADBAND_HFC, BROADBAND_PON, MOBILE_5G - which conflated two orthogonal
things. `DIA` and `MPLS` are service classes; `BROADBAND_PON` is an access
technology. A client's own invoice data settles it: the same service rides four
different access technologies, 1,357 circuits of it over VDSL, 190 over VDSL
and ADSL, 52 over PON and VDSL.

So: what you buy, and how it is delivered.

**The speed pair carries its own basis.** `Access/Port = 100/30` on an IPVPN is
a 100 Mbps bearer carrying a 30 Mbps committed rate. Collapsed to a single
figure it becomes either a claim to 100 Mbps of committed capacity the client
is not buying, or a 30 Mbps bearer that was never installed. Both are wrong and
in opposite directions, which is why the pair is a structured value rather than
two loose columns: a value that carries its convention cannot be misread, and
two integers can.

**The basis follows from the service class.** Four classes, four bases,
one-to-one - so the convention is never guessed, and a pair whose basis
contradicts its class is a validation error rather than a silent
misinterpretation.
"""
from decimal import Decimal

# ------------------------------------------------------------ service classes
# What is bought, logically. Independent of how it is delivered.
DIA = "DIA"                     # dedicated internet access
IPVPN = "IPVPN"                 # managed VPN, MPLS or otherwise
ETHERNET = "ETHERNET"           # point-to-point or E-LAN transport
BEST_EFFORT = "BEST_EFFORT"     # internet access with no committed rate

SERVICE_CLASSES = (DIA, IPVPN, ETHERNET, BEST_EFFORT)

# ------------------------------------------------------- access technologies
# How it is delivered. Wired and wireless are listed separately because the
# wireless ones carry a data cap and a contention profile that the wired ones
# do not, and treating a capped 5G service as a fixed circuit is the mistake
# the resilience model was making until 4.157.
WIRED = ("ADSL", "VDSL", "HFC", "PON", "ETHERNET_FIBRE", "DARK_FIBRE")
WIRELESS = ("MOBILE_4G", "MOBILE_5G", "FWA", "MICROWAVE", "SATELLITE")
ACCESS_TECHNOLOGIES = WIRED + WIRELESS

# ------------------------------------------------------------- speed bases
# D/U  downstream / upstream                 - a raw access service
# B/S  access bearer / logical service port  - Ethernet
# B/C  access bearer / committed rate        - IPVPN
# P/C  physical port / committed capacity    - DIA
DOWN_UP = "D/U"
BEARER_SERVICE = "B/S"
BEARER_CIR = "B/C"
PORT_COMMITTED = "P/C"

SPEED_BASES = (DOWN_UP, BEARER_SERVICE, BEARER_CIR, PORT_COMMITTED)

# One basis per class, so nothing is inferred from the numbers.
BASIS_FOR_CLASS = {
    DIA: PORT_COMMITTED,
    IPVPN: BEARER_CIR,
    ETHERNET: BEARER_SERVICE,
    BEST_EFFORT: DOWN_UP,
}

# What each basis calls its two numbers. Used in every message a reader sees,
# because "100/30" means nothing without them.
BASIS_LABELS = {
    DOWN_UP: ("downstream", "upstream"),
    BEARER_SERVICE: ("access bearer", "logical service port"),
    BEARER_CIR: ("access bearer", "committed information rate"),
    PORT_COMMITTED: ("physical port", "committed capacity"),
}


class VocabularyError(ValueError):
    """A classification that cannot be true, rather than one that is unusual."""


def speed(primary, secondary=None, *, service_class: str) -> dict:
    """A structured speed pair, with the basis its class implies.

    `secondary` may be None where a service is genuinely single-rated - dark
    fibre has a bearer and no service layer - and that is recorded as None
    rather than copied from the primary, because "symmetric" and "unstated" are
    different facts.
    """
    if service_class not in BASIS_FOR_CLASS:
        raise VocabularyError(
            f"{service_class!r} is not one of {list(SERVICE_CLASSES)}, so the "
            f"speed basis cannot be determined - and guessing it is how a "
            f"bearer gets read as a committed rate")
    basis = BASIS_FOR_CLASS[service_class]
    primary = int(primary) if primary is not None else None
    secondary = int(secondary) if secondary is not None else None

    if primary is None:
        raise VocabularyError(
            f"a {basis} pair with no {BASIS_LABELS[basis][0]} is not a speed")
    if secondary is not None and secondary > primary:
        # A service rate above its own bearer is impossible on every basis
        # here: you cannot commit 200 Mbps across a 100 Mbps port, and an
        # upstream above downstream is not a service anyone sells.
        raise VocabularyError(
            f"{BASIS_LABELS[basis][1]} {secondary} exceeds "
            f"{BASIS_LABELS[basis][0]} {primary} on a {basis} pair, which "
            f"cannot be delivered")
    return {"basis": basis, "primary_mbps": primary,
            "secondary_mbps": secondary}


def describe(pair: dict) -> str:
    """`100/30 (access bearer / committed information rate)`.

    Every figure a reader sees carries what it means, because the whole defect
    was a number whose convention lived somewhere else.
    """
    basis = pair.get("basis")
    if basis not in BASIS_LABELS:
        return "unclassified speed"
    first, second = BASIS_LABELS[basis]
    if pair.get("secondary_mbps") is None:
        return f"{pair['primary_mbps']} Mbps {first}"
    return (f"{pair['primary_mbps']}/{pair['secondary_mbps']} "
            f"({first} / {second})")


# Which of the two figures a rate card is keyed on, per basis.
#
# Not simply "the secondary": a VDSL 80/20 is sold and priced as an 80 Mbps
# service, so on a D/U pair the headline is the *downstream*. On the three
# committed bases it is the secondary, because that is what is bought - an
# IPVPN at 100/30 is a 30 Mbps service on a 100 Mbps bearer.
#
# Getting this backwards priced 2,022 best-effort circuits on their upstream,
# which is the same class of error as reading a bearer as a committed rate -
# and it survived one pass of this module.
PRICED_ON_PRIMARY = (DOWN_UP,)


def priced_rate(pair: dict) -> int:
    """The figure a rate card is keyed on.

    D/U prices on the downstream. B/S, B/C and P/C price on the committed or
    service figure, falling back to the bearer where none is stated - dark
    fibre, or a service whose committed rate is unrecorded.
    """
    if pair.get("basis") in PRICED_ON_PRIMARY:
        return pair["primary_mbps"]
    return (pair["secondary_mbps"] if pair.get("secondary_mbps") is not None
            else pair["primary_mbps"])


def sizing_rate(pair: dict) -> int:
    """The figure serviceability is judged against.

    The primary, always: whether an access technology can be delivered at a
    site is a question about the bearer, not about what was committed on it.
    Judging deliverability by the committed rate would call a 100 Mbps bearer
    with a 10 Mbps CIR serviceable wherever 10 Mbps is available, which is not
    what has to be installed.
    """
    return pair["primary_mbps"]


def validate(*, service_class: str, access_technology: str | None,
             pair: dict | None) -> list:
    """Reasons this combination cannot be true. Empty means plausible.

    Returns reasons rather than raising, because an imported circuit with an
    implausible classification should be reported and held, not lose the whole
    import.
    """
    problems = []
    if service_class not in SERVICE_CLASSES:
        problems.append(f"{service_class!r} is not a service class")
    if access_technology is not None and access_technology not in ACCESS_TECHNOLOGIES:
        problems.append(f"{access_technology!r} is not an access technology")

    if pair is not None and service_class in BASIS_FOR_CLASS:
        expected = BASIS_FOR_CLASS[service_class]
        if pair.get("basis") != expected:
            problems.append(
                f"a {service_class} carries a {expected} pair, not "
                f"{pair.get('basis')!r} - the basis follows from the class and "
                f"disagreeing means one of them is wrong")

    # A committed service over an uncommitted access technology is the
    # combination worth questioning: an IPVPN over ADSL exists, and an IPVPN
    # claiming a CIR over a contended access technology is a claim the access
    # cannot support.
    if (service_class in (IPVPN, ETHERNET, DIA)
            and access_technology in ("ADSL", "VDSL", "HFC")
            and pair is not None and pair.get("secondary_mbps")):
        problems.append(
            f"a {service_class} with a committed rate over {access_technology} "
            f"is contended access carrying an uncontended promise - deliverable "
            f"in practice, and the committed figure is not guaranteed by the "
            f"access")
    return problems


# ------------------------------------------------------- geographic scope
# How local a price is, most specific first. `scope_kind` held COUNTRY and
# REGION only, which is too coarse for the market where the tariff is actually
# published: Openreach prices by regulated area (National, Area 2, Area 3,
# HNR), and Ethernet access is distance-banded from the serving exchange.
#
# A client's own invoice data makes the case - IPVPN spans 308 to 2,180 within
# one country, seven times - and a country-level prior cannot express that.
SCOPE_LADDER = ("METRO", "DISTANCE_BAND", "AREA", "COUNTRY", "REGION", "GLOBAL")


def more_specific(left: str, right: str) -> bool:
    """Is `left` a tighter scope than `right`?"""
    order = {name: i for i, name in enumerate(SCOPE_LADDER)}
    if left not in order or right not in order:
        raise VocabularyError(
            f"{left!r} or {right!r} is not one of {list(SCOPE_LADDER)}")
    return order[left] < order[right]


def resolution_order(available: list) -> list:
    """The scopes to try, tightest first.

    Resolution walks the ladder rather than taking the first match in whatever
    order the database returned - the same precedence discipline the footprint
    resolver uses, and for the same reason: a global average must never win
    over a local price that exists.
    """
    order = {name: i for i, name in enumerate(SCOPE_LADDER)}
    return sorted((s for s in available if s in order), key=lambda s: order[s])
