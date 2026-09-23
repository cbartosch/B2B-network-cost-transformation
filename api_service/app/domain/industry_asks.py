"""What to ask about, for the estate this industry actually has.

A research brief was one text per domain, the same for every client. So an
agent researching a bank was asked for "site counts" in general and never for
the number of standalone cash machines, and an agent researching a parcel
network was never asked how many packstations there are - while those two
numbers are the largest rows in their respective estates.

The asks are DERIVED from the industry's estate shape rather than written per
industry. A shape that gains a site type gains its ask automatically, and one
that loses a type loses it: a hand-maintained list of 49 industries would be
stale the week after it was written, which is the defect this repository has
found in a hardcoded list four times now.

Two site types are always asked for, whatever the shape says:

  * data centres, because the count drives cost more than any other single
    site and is the one figure a percentage of the estate cannot produce
  * standalone cash machines, because they are additive-only - the estate
    shape deliberately proposes none, so if nobody researches the number,
    there are none
"""

# What to look for, per site type, and where it is usually published.
#
# Phrased as the thing a person would search for rather than as the
# archetype's internal name: nobody publishes a "SELF_SERVICE_TERMINAL" count.
SITE_TYPE_ASKS = {
    "DC": {
        "ask": "How many data centres does it own or occupy, and where?",
        "why": ("The count drives cost more than any other single site, and "
                "it does not scale with the rest of the estate - a company "
                "with 300 sites and one with 38,000 both run a handful."),
        "look_for": [
            "annual report IT or infrastructure section",
            "sustainability report, which usually counts facilities",
            "colocation provider customer announcements",
            "engineering job postings naming a site by city",
            "cloud migration press releases stating what was exited",
        ],
        "unit": "sites",
    },
    "ATM": {
        "ask": ("How many STANDALONE cash machines does it operate - "
                "off-premise units, not those inside a branch?"),
        "why": ("An ATM inside a branch is equipment in a site already "
                "counted. Only an off-premise unit is a site of its own, and "
                "the number follows the bank's off-premise strategy rather "
                "than its branch count - no ratio recovers it."),
        "look_for": [
            "the bank's own ATM locator, which usually flags branch vs "
            "standalone",
            "annual report retail distribution section",
            "regulatory filings listing points of presence",
            "ATM network or interchange scheme membership data",
        ],
        "unit": "sites",
    },
    "SELF_SERVICE_TERMINAL": {
        "ask": ("How many parcel lockers, packstations or self-service "
                "kiosks does it operate?"),
        "why": ("Usually the largest row in a parcel estate by count, and "
                "each is one cellular device rather than a connected "
                "building."),
        "look_for": [
            "the operator's own locker or packstation locator",
            "annual report network or last-mile section",
            "press releases announcing locker rollout targets",
        ],
        "unit": "sites",
    },
    "SERVICE_POINT": {
        "ask": ("How many service points, parcel shops or hosted counters "
                "does it operate inside third-party premises?"),
        "why": ("These often ride the host's connection rather than a "
                "corporate circuit, so whether they are in scope at all is "
                "part of the answer."),
        "look_for": [
            "the operator's own location finder",
            "annual report retail network section",
            "partner announcements with retail chains",
        ],
        "unit": "sites",
    },
    "NETWORK_SITE": {
        "ask": "How many towers, masts or street cabinets does it operate?",
        "why": ("Unmanned and enormous in count, and the cost driver is "
                "count rather than capacity."),
        "look_for": [
            "annual report network section",
            "regulatory infrastructure registers",
            "tower company transaction announcements",
        ],
        "unit": "sites",
    },
    "TERMINAL": {
        "ask": ("How many sortation hubs, terminals or major facilities does "
                "it operate?"),
        "why": ("Few in number and large in cost, so an error here moves the "
                "baseline more than an error across thousands of small "
                "sites."),
        "look_for": [
            "annual report operations section",
            "capital expenditure announcements",
            "facility opening press releases",
        ],
        "unit": "sites",
    },
    "PLANT": {
        "ask": "How many production sites, plants or refineries does it run?",
        "why": "Each carries far more bandwidth than an office of the size.",
        "look_for": [
            "annual report operations or manufacturing footprint",
            "sustainability report, which counts sites for emissions",
        ],
        "unit": "sites",
    },
    "REMOTE_SITE": {
        "ask": "How many mines, wells or generation sites does it operate?",
        "why": ("A fixed line often does not exist at these, so whether they "
                "are served at all is part of the answer."),
        "look_for": [
            "annual report asset list",
            "regulatory production filings",
        ],
        "unit": "sites",
    },
    "CAMPUS": {
        "ask": "How many research or engineering campuses does it operate?",
        "why": "The highest bandwidth per site in most estates.",
        "look_for": [
            "annual report R&D section",
            "site opening announcements",
            "engineering job postings by location",
        ],
        "unit": "sites",
    },
    "CONTROL_CENTER": {
        "ask": ("How many operations, dispatch or control centres does it "
                "run?"),
        "why": "Tier 1 sites, dual-fed, and few in number.",
        "look_for": [
            "annual report operations section",
            "regulatory resilience filings",
        ],
        "unit": "sites",
    },
    "BRANCH": {
        "ask": "How many branches does it operate, and in which countries?",
        "why": "Usually the counted number a bank publishes.",
        "look_for": [
            "annual report distribution section",
            "the bank's own branch locator",
            "regulatory points-of-presence filings",
        ],
        "unit": "sites",
    },
    "STORE": {
        "ask": "How many stores or outlets does it operate, by country?",
        "why": "Usually published, and usually the largest row by count.",
        "look_for": [
            "annual report store count table",
            "the retailer's own store locator",
        ],
        "unit": "sites",
    },
    "LARGE_OFFICE": {
        "ask": ("How many head offices and regional offices does it occupy, "
                "and in which cities?"),
        "why": ("A company decides to open an office, so the count follows "
                "its organisation rather than the size of its estate - a "
                "share of the site total produced 152 for a German parcel "
                "network that runs tens."),
        "look_for": [
            "annual report property or premises section",
            "the company's own contact or offices page",
            "commercial property lettings and lease announcements",
            "job postings by location, which name the offices that hire",
        ],
        "unit": "sites",
    },
    "WAREHOUSE": {
        "ask": ("How many depots, distribution centres or warehouses does it "
                "operate?"),
        "why": "The operating buildings of a logistics estate.",
        "look_for": [
            "annual report logistics or supply chain section",
            "property portfolio disclosures",
            "industrial REIT tenant announcements",
        ],
        "unit": "sites",
    },
}

# Asked whatever the estate shape says.
#
# Only the data centre. Its count drives cost more than any other single site
# and cannot be derived from a share, so it is worth asking about for any
# company at all.
#
# ATM is NOT here. It is additive-only, so the shape proposes none and an
# unresearched count stays zero - but asking a chemicals company how many
# cash machines it runs is noise, and a brief full of irrelevant questions is
# one an agent learns to skim. It is asked where the estate could plausibly
# have them: see CONDITIONAL_ASK.
ALWAYS_ASK = ("DC",)

# Asked when the estate contains a type that implies them.
#
# A standalone cash machine belongs to a business with a retail counter, so a
# BRANCH or STORE layer is what makes the question worth asking. A chemicals
# company has neither.
# Keyed on the ESTATE SHAPE, not on an archetype.
#
# BRANCH is ambiguous: a bank branch in a branch-network estate and a small
# non-customer-facing site everywhere else. Keying on the archetype asked a
# chemicals company how many cash machines it runs, and failed to require the
# count from a bank - whose shape no longer allocates any ATM at all, by
# design.
#
# The shape is the thing that knows what kind of business this is.
CONDITIONAL_ASK = {
    "ATM": ("branch-network", "many-small", "parcel-network"),
}


def asks_for(archetypes, *, industry=None, shape=None) -> list:
    """The site-count questions worth asking for this estate.

    `archetypes` is whatever the industry's shape actually contains. The two
    in ALWAYS_ASK are added regardless, and the list is ordered so the ones
    that move the number most come first.
    """
    present = {str(a).strip().upper() for a in (archetypes or [])}
    shape_name = str(shape or "").strip().lower()
    wanted = list(ALWAYS_ASK)
    for archetype, shapes in CONDITIONAL_ASK.items():
        if shape_name in shapes:
            wanted.append(archetype)
    wanted += sorted(present - set(wanted))

    out = []
    for archetype in wanted:
        entry = SITE_TYPE_ASKS.get(archetype)
        if not entry:
            continue
        out.append({
            "archetype": archetype,
            "always_asked": archetype in ALWAYS_ASK,
            "in_this_estate": archetype in present,
            # Asked because something else in the estate implies it, not
            # because the shape allocates any. A standalone cash machine is
            # the case: the shape proposes none by design.
            "conditional": (archetype in CONDITIONAL_ASK
                            and shape_name in CONDITIONAL_ASK[archetype]),
            **entry,
        })
    # DC first, then the types this estate actually has, then the rest.
    out.sort(key=lambda e: (not e["always_asked"],
                            not (e["in_this_estate"] or e["conditional"]),
                            e["archetype"]))
    return out


def required_counts(archetypes, *, shape=None) -> list:
    """The counts a V0 should not be published without.

    Only the two that cannot be recovered any other way. Everything else has
    a defensible fallback in the estate shape; these do not - a data centre
    count derived from a share is wrong by an order of magnitude, and an
    unresearched standalone ATM count is silently zero because the shape
    proposes none.
    """
    present = {str(a).strip().upper() for a in (archetypes or [])}
    shape_name = str(shape or "").strip().lower()
    needed = ["DC"]
    if shape_name in CONDITIONAL_ASK["ATM"] or "ATM" in present:
        needed.append("ATM")
    return needed
