"""Some site types do not scale with the size of the estate.

A data centre count is the clearest case. A retailer with 3,000 stores and one
with 300 both run two to four data centres: the number follows the company's
compute strategy, its regulatory geography and how far it has moved to cloud -
not how many outlets it has.

The estate shape expressed DC as a percentage share, so it scaled with site
count and produced counts nobody has:

    POSTAL_AND_PARCEL_NETWORK   0.2%  of 38,000 =    76
    RETAIL_BANKING              3.0%  of 38,000 =  1140
    CLOUD_PROVIDER             25.0%  of 38,000 =  9500

Most large enterprises run five to ten data centres, and many now run two.
Even a hyperscaler runs tens, not thousands.

So the count is capped in absolute terms, and the cap is chosen in this order:

  1. what research found, if domain 6 produced a count with a source
  2. the peer average for the industry, from the table below
  3. the generic enterprise range

The distinction between 1 and 2 matters for the evidence grade: a researched
count carries whatever grade its source had, and a peer average is this
repository's judgement. A number capped at the peer average is reported as
having been capped, because "we could not find it so we used the sector norm"
is the finding, not a detail.
"""
from decimal import Decimal


# Data centres a company in this industry plausibly runs, worldwide.
#
# The low figure is a company that has moved to cloud and kept a pair for
# what cannot leave; the base is the common case; the high is a company with
# regulatory geography to satisfy or a genuine compute business.
#
# Sourced from nothing. These are this repository's judgement and the
# `PEER_AVERAGE` grade says so - which is the point of separating them from a
# researched count rather than blending the two.
DC_BY_INDUSTRY = {
    # A genuine compute business. Tens of sites, not thousands.
    "CLOUD_PROVIDER": (12, 30, 60),
    "DATA_CENTER_REIT": (20, 45, 90),
    # Carriers run core sites as part of the network, counted separately as
    # CORE_SITE where the estate names them.
    "FIXED_OPERATOR": (6, 14, 30),
    "MOBILE_OPERATOR": (6, 14, 30),
    "CABLE_OPERATOR": (5, 12, 25),
    # Regulated finance: dual-site by obligation, and often per jurisdiction.
    "UNIVERSAL_BANKING": (4, 8, 16),
    "RETAIL_BANKING": (3, 6, 12),
    "INVESTMENT_BANKING": (4, 8, 14),
    "INSURANCE": (3, 5, 10),
    "PAYMENT_NETWORKS": (4, 8, 14),
    # Operationally critical, and usually a pair plus regional.
    "AIRLINES": (2, 4, 8),
    "RAILWAYS": (2, 4, 8),
    "UTILITIES": (2, 5, 10),
    "AIRPORT": (2, 3, 6),
    "PORT": (2, 3, 5),
    # Logistics and postal: a pair of core sites and some regional compute.
    "LOGISTICS": (2, 4, 8),
    "WAREHOUSING": (2, 3, 6),
    "POSTAL_AND_PARCEL_NETWORK": (2, 4, 8),
    # Retail: heavily consolidated, and among the furthest into cloud.
    "SUPERMARKETS": (2, 3, 6),
    "DEPARTMENT_STORES": (2, 3, 5),
    "DRUG_RETAIL": (2, 3, 5),
    # Industrials: a pair, plus whatever a plant needs on site, which is a
    # PLANT and not a data centre.
    "CHEMICALS": (2, 3, 6),
    "PHARMACEUTICALS": (2, 4, 8),
    "SEMICONDUCTORS": (2, 4, 8),
    "AUTOMOTIVE_OEM": (2, 4, 8),
    "AEROSPACE_DEFENSE": (2, 4, 8),
    "INDUSTRIAL_CONGLOMERATE": (3, 6, 12),
    # Software: the product runs in someone else's cloud.
    "SOFTWARE": (1, 2, 5),
    "SAAS": (1, 2, 4),
    "FINTECH": (1, 3, 6),
}

# When the industry is unknown or unlisted. Deliberately narrow: the whole
# point is that this number does not run to hundreds.
DC_GENERIC = (2, 4, 10)

# The hard ceiling, whatever the industry and whatever was researched.
#
# A company reporting more than this is either a hyperscaler, in which case
# the industry entry covers it, or has counted network sites and equipment
# rooms as data centres - which are CORE_SITE and NETWORK_SITE here.
DC_ABSOLUTE_MAX = 120

# The other site types whose count follows organisational structure rather
# than estate size, per country.
#
# A data centre was the clearest case and not the only one. On a 38,000-site
# German estate the same percentage model produced:
#
#     LARGE_OFFICE   0.40%  =   152     a parcel network runs tens
#     TERMINAL       1.00%  =   380     DHL Germany has ~36 parcel centres
#
# All of these are individually significant buildings: a company decides to
# open one. A collection point, a depot or a cabinet is rolled out in bulk,
# and those are the types that genuinely scale.
#
# Per country, because that is the unit a footprint row is entered in. A
# multinational has one of each per major market, not one worldwide.
NON_SCALING_PER_COUNTRY = {
    # A head office and its regional offices. Tens for a large national
    # operation, not hundreds.
    "LARGE_OFFICE": (2, 12, 40),
    # Airports, ports, sortation hubs, major hospitals. Capital projects,
    # counted in dozens at most.
    "TERMINAL": (1, 12, 60),
    # A research or engineering campus with thousands of staff.
    "CAMPUS": (1, 3, 12),
    # An operations, dispatch or trading room.
    "CONTROL_CENTER": (1, 3, 12),
}

# Where the sites removed by a cap should go instead.
#
# "A parcel services company should not have so many large offices, rather
# they should be warehouses" - and that is right in general, not only for
# parcel: the buildings a capped estate actually has are its operating sites.
# Handing the surplus to the single largest row would have made 148 German
# offices into collection points, which is wrong in a different way.
ABSORBS_SURPLUS = {
    "parcel-network": "WAREHOUSE",
    "distribution-led": "WAREHOUSE",
    "plant-centric": "PLANT",
    "many-small": "STORE",
    "branch-network": "BRANCH",
    "network-centric": "NETWORK_SITE",
    "campus-centric": "LARGE_OFFICE",
    "few-large": "WAREHOUSE",
    "office-centric": "BRANCH",
}


RESEARCHED = "RESEARCHED"
PEER_AVERAGE = "PEER_AVERAGE"
GENERIC = "GENERIC_ENTERPRISE"


def dc_count(*, industry=None, researched=None, estate_derived=None) -> dict:
    """How many data centres this estate has, and on what basis.

    `researched` is a count domain 6 established, or None. `estate_derived` is
    whatever the shape's percentage produced, which is only ever used as a
    floor - never as the answer, because it scales with site count and the
    real number does not.

    Returns the basis as well as the count. A number capped at the peer
    average is a finding: "we could not establish this, so the sector norm was
    used" belongs in the output, not in a comment.
    """
    code = str(industry or "").strip().upper()
    low, base, high = DC_BY_INDUSTRY.get(code, DC_GENERIC)
    peer_source = PEER_AVERAGE if code in DC_BY_INDUSTRY else GENERIC

    if researched is not None:
        try:
            found = int(researched)
        except (TypeError, ValueError):
            found = None
        if found is not None and found >= 0:
            capped = min(found, DC_ABSOLUTE_MAX)
            return {
                "count": capped,
                "basis": RESEARCHED,
                "researched": found,
                "capped_at": DC_ABSOLUTE_MAX if capped != found else None,
                "peer_range": [low, base, high],
                "note": (
                    f"{found} data centre(s) established by research"
                    + (f", capped at {DC_ABSOLUTE_MAX} - a count above that "
                       f"usually means network sites and equipment rooms were "
                       f"counted as data centres"
                       if capped != found else "")),
            }

    # Nothing researched. The peer average, and the estate-derived figure only
    # if it is SMALLER - a shape that implies fewer than the sector norm is
    # telling us something; one that implies more is just arithmetic on site
    # count.
    count = base
    if estate_derived is not None:
        try:
            derived = int(estate_derived)
        except (TypeError, ValueError):
            derived = None
        if derived is not None and 0 <= derived < base:
            count = derived

    return {
        "count": count,
        "basis": peer_source,
        "researched": None,
        "capped_at": None,
        "peer_range": [low, base, high],
        "note": (
            f"No data-centre count was established, so the "
            f"{'sector' if peer_source == PEER_AVERAGE else 'generic '
               'enterprise'} norm of {count} is used"
            + (f" - the estate shape implied {estate_derived}, which scales "
               f"with site count and a data centre count does not"
               if estate_derived not in (None, count) else "")
            + ". Research domain 6 to replace it: a filing, a sustainability "
              "report or the company's own engineering job postings usually "
              "name the sites."),
    }


def share_would_imply(total_sites, share) -> int:
    """What the shape's percentage produces, for the record."""
    try:
        return int(Decimal(str(total_sites)) * Decimal(str(share)))
    except Exception:
        return 0


def cap_for(archetype, *, industry=None) -> tuple:
    """(low, base, high) for a site type that does not scale, or None.

    `DC` keeps its own per-industry table, because the spread between a
    software company and a hyperscaler is two orders of magnitude and no
    single range covers both. The rest use one range per site type: an office
    is an office.
    """
    code = str(archetype or "").strip().upper()
    if code == "DC":
        return DC_BY_INDUSTRY.get(
            str(industry or "").strip().upper(), DC_GENERIC)
    return NON_SCALING_PER_COUNTRY.get(code)


def absorber_for(shape) -> str | None:
    """The site type that takes sites removed by a cap.

    Its operating sites, not its largest row. A parcel network's capped
    offices are depots; handing them to the largest row would make them
    collection points.
    """
    return ABSORBS_SURPLUS.get(str(shape or "").strip().lower())


# Site types that may only ever be ADDED, never derived from a share.
#
# Simmons Bank registered 233 BRANCHES and the branch-network shape turned
# them into 60 branches and 153 cash machines, because ATMs had 66% of the
# estate. Two errors in one:
#
#   * a registered count is evidence and a share is a guess, so a guess must
#     never reinterpret what was counted
#   * most cash machines are INSIDE a branch. They are equipment in a site
#     already counted, not sites. Only a standalone unit - a petrol station,
#     a station concourse, a shopping centre - is a site of its own, and that
#     number depends on the bank's off-premise strategy rather than on how
#     many branches it has. No ratio recovers it.
#
# The same holds for a vending estate and for parcel lockers sited inside a
# host's premises: they exist only where somebody counted them.
#
# These types appear in an estate when the analyst enters a row or research
# establishes a count. They are never proposed, and a shape naming one is a
# defect - see the guard in tests/test_additive_only.py.
ADDITIVE_ONLY = frozenset({"ATM"})


def may_be_proposed(archetype) -> bool:
    """Whether a shape may allocate sites of this type.

    False for a type that only exists where somebody counted it. The
    proposer drops such a row rather than guessing a share of the register.
    """
    return str(archetype or "").strip().upper() not in ADDITIVE_ONLY


def additive_note(archetype) -> str:
    """Why this type is absent from a proposal, for the analyst."""
    code = str(archetype or "").strip().upper()
    if code == "ATM":
        return (
            "Standalone cash machines are not proposed. Most ATMs sit inside "
            "a branch and are equipment in a site already counted; only an "
            "off-premise unit is a site of its own, and that number depends "
            "on the bank's off-premise strategy rather than on its branch "
            "count. Add a row with the number, or research it - a bank's own "
            "locator usually distinguishes branch ATMs from standalone ones.")
    return (f"{code} is only ever entered, never derived from a share.")
