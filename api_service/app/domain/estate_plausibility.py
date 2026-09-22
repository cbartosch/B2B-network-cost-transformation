"""Is this estate one a company could actually have?

A German footprint arrived with 3,800 data centres, 19,000 large offices and no
service points at all, priced at USD 1.21 billion - and every control passed.
Coverage read 1.000 and the page said "V0 COMPLETE - all coverage tests
passed."

That is the gap this module closes. Coverage asks whether the estate can be
PRICED. Nothing asked whether the estate is POSSIBLE. A fictional footprint
that happens to price completely gets a green light, and the green light is
what makes it dangerous: a number nobody believes is harmless, and a number
with every gate satisfied is not.

The checks are deliberately crude. They are not trying to validate a footprint
- only to catch the ones that cannot be true of any company. A ceiling that
fires on a real estate is worse than no ceiling, so each is set where a
plausible enterprise is nowhere near it.

Two kinds of impossibility:

  * a count no company reaches for that site type, anywhere. Nobody has
    thousands of data centres in one country.
  * a composition no company has. An estate of 38,000 sites is not 44% large
    offices; at that scale the sites are outlets, depots or cabinets.

Both are reported per country, because that is where a footprint is entered
and where the error is made.
"""
from decimal import Decimal


# The most of each site type a single company plausibly operates in ONE
# country. Generous on purpose - these are impossibility bounds, not norms.
#
# A very large enterprise runs single-digit data centres per country and a few
# dozen worldwide; 3,800 in Germany is four orders of magnitude out. A campus,
# a terminal and a control centre are similarly rare and similarly large. An
# office estate can genuinely run to low thousands for a bank or an insurer,
# so that ceiling is high and only catches the absurd.
#
# STORE, BRANCH, WAREHOUSE, NETWORK_SITE and REMOTE_SITE have no ceiling. A
# postal network has 30,000 service points, a tower company 40,000 cabinets,
# and a retailer 5,000 stores in one country. Those are real.
PER_COUNTRY_CEILING = {
    "DC": 60,
    "TERMINAL": 120,
    "CAMPUS": 150,
    "CONTROL_CENTER": 150,
    "PLANT": 800,
    # A depot or distribution centre is a building with loading bays. DHL
    # runs a few hundred in Germany and Amazon around a hundred fulfilment
    # centres; 25,840 is not an estate, it is a parcel network typed as
    # depots. This was left unbounded in the first version and let exactly
    # that through.
    "WAREHOUSE": 3000,
    # A bank's branch network. Deutsche Bank ran roughly a thousand; the
    # largest national networks reach a few thousand under one operator.
    "BRANCH": 5000,
    # Extraction and generation sites. A large utility runs thousands of
    # substations, but those are NETWORK_SITE - a mine or a wind farm is
    # counted in dozens to low hundreds.
    "REMOTE_SITE": 4000,
    "LARGE_OFFICE": 4000,
}

# Genuinely unbounded, and only these two.
#
# A postal network really does have 30,000 collection points and a tower
# company 40,000 cabinets: both are mass-deployed to one specification and
# the count is the business. Everything else has a ceiling, because the first
# version exempted five types and let 25,840 warehouses through - the same
# error as the one it was written to catch, one site type over.
UNBOUNDED = ("STORE", "NETWORK_SITE", "SERVICE_POINT",
             "SELF_SERVICE_TERMINAL", "ATM")

# Above this many sites in one country, the estate is a network of small
# things. A 38,000-site estate is not 44% large offices - at that scale the
# sites are outlets, depots or cabinets, whatever the industry.
LARGE_ESTATE_SITES = 5000
LARGE_ESTATE_SMALL_SITE_SHARE = Decimal("0.60")
SMALL_SITE_TYPES = frozenset({"STORE", "BRANCH", "NETWORK_SITE",
                              "REMOTE_SITE", "WAREHOUSE",
                              "SERVICE_POINT", "SELF_SERVICE_TERMINAL",
                              "ATM"})


def assess(footprint: list, *, registered_total: int | None = None) -> dict:
    """Findings about the estate, and whether any is disqualifying.

    Returns findings rather than raising: the caller decides whether an
    implausible estate blocks a run or is reported alongside it. A footprint
    that cannot be true should not be silently priced either way.
    """
    findings = []
    by_country = {}
    for row in footprint or []:
        country = str(row.get("country") or "").upper()
        archetype = str(row.get("archetype") or "").upper()
        try:
            sites = int(row.get("sites") or 0)
        except (TypeError, ValueError):
            continue
        if sites <= 0:
            continue
        by_country.setdefault(country, {})
        by_country[country][archetype] = \
            by_country[country].get(archetype, 0) + sites

    for country, counts in sorted(by_country.items()):
        total = sum(counts.values())

        # 1. counts no company reaches for that site type
        for archetype, sites in sorted(counts.items()):
            ceiling = PER_COUNTRY_CEILING.get(archetype)
            if ceiling is None or sites <= ceiling:
                continue
            findings.append({
                "kind": "IMPOSSIBLE_COUNT",
                "country": country,
                "archetype": archetype,
                "sites": sites,
                "ceiling": ceiling,
                "detail": (
                    f"{sites:,} {archetype} sites in {country}. No company "
                    f"operates more than about {ceiling:,} of these in one "
                    f"country - this is not a footprint, it is a site type "
                    f"applied to the wrong rows."),
                "likely_cause": _likely_cause(archetype),
            })

        # 2. a composition no company has at this scale
        if total >= LARGE_ESTATE_SITES:
            small = sum(n for a, n in counts.items() if a in SMALL_SITE_TYPES)
            share = Decimal(small) / Decimal(total)
            if share < LARGE_ESTATE_SMALL_SITE_SHARE:
                findings.append({
                    "kind": "IMPLAUSIBLE_COMPOSITION",
                    "country": country,
                    "sites": total,
                    "small_site_share": f"{share:.3f}",
                    "detail": (
                        f"{total:,} sites in {country} and only "
                        f"{share:.0%} of them are small-site types. An "
                        f"estate this large is a network of outlets, depots "
                        f"or cabinets - whatever the industry, it is not "
                        f"mostly offices, plants and data centres."),
                    "likely_cause": (
                        "the industry's estate shape is wrong for this "
                        "company, so the site total was spread over the "
                        "wrong archetypes"),
                })

    # 3. allocated against registered
    if registered_total:
        allocated = sum(sum(c.values()) for c in by_country.values())
        if allocated > registered_total:
            findings.append({
                "kind": "OVER_ALLOCATED",
                "sites": allocated,
                "registered": int(registered_total),
                "detail": (
                    f"{allocated:,} sites allocated against a registered "
                    f"{int(registered_total):,} - {allocated - int(registered_total):,} "
                    f"more than the register holds. A proposal applied twice "
                    f"does this."),
                "likely_cause": ("rows from two proposals in the table at "
                                 "once, or a total that changed after the "
                                 "split was made"),
            })

    return {
        "findings": findings,
        "plausible": not findings,
        # Named so a reader can see what was checked and not only what failed.
        "checked": {
            "per_country_ceilings": sorted(PER_COUNTRY_CEILING),
            "unbounded_types": list(UNBOUNDED),
            "large_estate_threshold": LARGE_ESTATE_SITES,
        },
    }


def _likely_cause(archetype: str) -> str:
    """What the rows probably are, when there are far too many of them."""
    return {
        "DC": ("these are almost certainly not computing facilities - a "
               "depot is a WAREHOUSE, an outlet or service point is a STORE"),
        "LARGE_OFFICE": ("an estate with thousands of sites is outlets or "
                         "depots, not head offices - a parcel shop or "
                         "packstation is a STORE"),
        "TERMINAL": ("a terminal is an airport, port or major hospital - a "
                     "depot is a WAREHOUSE"),
        "CAMPUS": ("a campus is a research or engineering site with thousands "
                   "of staff - an office is a LARGE_OFFICE"),
        "CONTROL_CENTER": ("a control centre is an operations or dispatch "
                           "room, of which a company has a handful"),
        "PLANT": "a production site, not a depot or an outlet",
        "WAREHOUSE": ("a depot or distribution centre is a building with "
                      "loading bays - a parcel shop, packstation or "
                      "collection point is a STORE, and there can be tens of "
                      "thousands of those"),
        "BRANCH": ("if these are customer-facing they are STOREs, which have "
                   "no ceiling"),
        "REMOTE_SITE": ("an extraction or generation site - passive "
                        "infrastructure like a cabinet or mast is a "
                        "NETWORK_SITE, which has no ceiling"),
    }.get(archetype, "the site type is applied to the wrong rows")
