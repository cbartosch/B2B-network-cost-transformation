"""What an industry's estate looks like, as distinct from what it is called.

Six industries with five site archetypes, and the dimension earned its place by
changing two things: how a site total splits across density bands, and what
bandwidth a site type gets. Adding a name without changing those would make the
taxonomy a label rather than a model.

So each industry here declares a **shape**, and the shapes genuinely differ:

  many-small     hundreds of near-identical sites, rural-weighted, low
                 bandwidth each - grocery, pharmacy, quick service, public
                 safety stations
  few-large      a handful of enormous, urban, extremely high-bandwidth sites -
                 airports, ports, capital markets
  plant-centric  a small number of heavy industrial sites plus an office -
                 process manufacturing, natural resources
  office-centric an estate that is mostly people in buildings - IT services,
                 insurance, government administration
  network-centric the estate *is* the network - telecom exchanges and points of
                 presence, where a "site" is a piece of infrastructure

**Where the archetype taxonomy does not fit, that is recorded rather than
hidden.** An airport terminal is not a LARGE_OFFICE: it is a hundred thousand
square metres with tens of thousands of transient users, and calling it an
office makes its bandwidth prior a fiction. The five archetypes are an
office-and-retail vocabulary, and the industries flagged
`archetype_fit="POOR"` are the ones where a proper model needs site types this
one does not have. Naming that is more useful than a mix that pretends
otherwise.
"""

# How well the five existing archetypes describe an industry's estate.
#
# GOOD  the estate really is offices, branches, stores, warehouses and data
#       centres
# FAIR  the mapping is defensible with a caveat - a hotel priced as a large
#       office is wrong about why it needs bandwidth, and right about how much
# POOR  the estate is made of things this vocabulary has no word for, and the
#       mix is a placeholder until it does
GOOD, FAIR, POOR = "GOOD", "FAIR", "POOR"
# An industry nobody has profiled. Not GOOD: an unlisted sector resolves to the
# DEFAULT shape, and reporting that as a good fit would claim the estate had
# been considered when it had only been defaulted - the same defect as an empty
# serviceability table reading as an unserviceable estate.
UNKNOWN = "UNKNOWN"

# (industry, parent, shape, archetype_fit, note)
#
# `parent` records what an industry was split out of, so a case tagged with the
# old coarse value still resolves and a reader can see the lineage. RETAIL
# stays as a usable value rather than being replaced: an engagement that only
# knows "retail" should not be forced to guess which kind.
INDUSTRIES = [
    # ---- retail, split by site size and density -------------------------
    ("RETAIL", None, "many-small", GOOD,
     "kept as a usable value: an engagement that only knows 'retail' should "
     "not have to guess which kind"),
    ("GROCERY_RETAIL", "RETAIL", "many-small", GOOD,
     "large stores, deep rural reach, in-store systems and payment"),
    ("SPECIALTY_RETAIL", "RETAIL", "many-small", GOOD,
     "smaller footprint, mall and high-street weighted, so less rural"),
    ("QSR_RESTAURANTS", "RETAIL", "many-small", GOOD,
     "the most sites and the least bandwidth each; drive-through and payment"),
    ("PHARMACY_RETAIL", "RETAIL", "many-small", GOOD,
     "dense small sites with a regulated data path to dispensing systems"),

    # ---- financial services, split by what the estate is for ------------
    ("FINANCIAL_SERVICES", None, "office-centric", GOOD,
     "kept as a usable value"),
    ("RETAIL_BANKING", "FINANCIAL_SERVICES", "many-small", GOOD,
     "a branch network plus a small number of very large offices"),
    ("INSURANCE", "FINANCIAL_SERVICES", "office-centric", GOOD,
     "few sites, mostly large offices, little rural presence"),
    ("CAPITAL_MARKETS", "FINANCIAL_SERVICES", "few-large", GOOD,
     "very few sites, extreme bandwidth and latency sensitivity, and the "
     "data centre is the business rather than a support function"),

    # ---- manufacturing and distribution ---------------------------------
    ("MANUFACTURING", None, "plant-centric", FAIR, "kept as a usable value"),
    ("DISCRETE_MANUFACTURING", "MANUFACTURING", "plant-centric", FAIR,
     "assembly plants, which this model prices as warehouses - right about "
     "the building and wrong about the machine network inside it"),
    ("PROCESS_MANUFACTURING", "MANUFACTURING", "plant-centric", POOR,
     "continuous-process plants: a refinery or a chemical works is not a "
     "warehouse, and its control network is a site type this model lacks"),
    ("AUTOMOTIVE", "MANUFACTURING", "plant-centric", FAIR,
     "plants plus a dealer network, which behaves like specialty retail"),
    ("DISTRIBUTION", None, "plant-centric", GOOD, "kept as a usable value"),
    ("WHOLESALE_DISTRIBUTION", "DISTRIBUTION", "plant-centric", GOOD,
     "large depots with a thin office layer"),

    # ---- logistics ------------------------------------------------------
    ("LOGISTICS", None, "plant-centric", GOOD, "kept as a usable value"),
    ("PARCEL_LOGISTICS", "LOGISTICS", "many-small", GOOD,
     "sortation hubs plus a wide network of small depots, rural-weighted"),
    ("FREIGHT_FORWARDING", "LOGISTICS", "office-centric", GOOD,
     "an office business with warehouse space attached, not the reverse"),

    # ---- the ten new sectors --------------------------------------------
    ("NATURAL_RESOURCES", None, "plant-centric", POOR,
     "mines, wells and processing plants, overwhelmingly rural and often "
     "beyond any fixed bearer - the estate this model serves worst, and the "
     "one where serviceability matters most"),
    ("TRAVEL_TOURISM", None, "office-centric", FAIR,
     "hotels and resorts, priced as large offices: right about the bandwidth, "
     "wrong about why - guest wifi is the load, not staff"),
    ("IT_SERVICES", None, "office-centric", GOOD,
     "offices and data centres, the estate this model describes best"),
    ("TELECOM", None, "network-centric", POOR,
     "the estate is the network. Exchanges, points of presence and head ends "
     "are infrastructure rather than premises, and pricing them as data "
     "centres understates how many there are and overstates each one"),
    ("DEFENSE", None, "plant-centric", POOR,
     "bases and depots, with resilience and separation requirements that are "
     "the point rather than a feature - and a site type this model lacks"),
    ("PUBLIC_SAFETY", None, "many-small", FAIR,
     "many small stations plus a small number of dispatch centres where "
     "availability, not bandwidth, is the binding constraint"),
    ("GOVERNMENT", None, "office-centric", GOOD,
     "administrative offices and citizen service centres, which behave like "
     "branches"),
    ("AIRPORTS", None, "few-large", POOR,
     "very few, very large sites. A terminal is a hundred thousand square "
     "metres with tens of thousands of transient users; calling it a large "
     "office makes its bandwidth prior a fiction"),
    ("PORTS", None, "few-large", POOR,
     "terminals, yards and cranes. The same shape as airports and the same "
     "mismatch: a container yard is not a warehouse"),

    ("DEFAULT", None, "office-centric", GOOD,
     "the fallback every resolver uses when an industry is unknown or "
     "unseeded"),
]

# The shapes, as density mixes over (archetype, density_band). Each must sum to
# 1.0 across the whole industry - the resolver apportions a site total through
# it, and a mix summing to less than one would silently lose sites.
#
# One mix per shape rather than per industry: twenty-seven hand-written mixes
# would be twenty-seven chances to fat-finger a share, and the shapes are the
# thing that actually differs. An industry needing its own can be given one.
SHAPES = {
    "many-small": [
        ("STORE", "DENSE_URBAN", "0.1000"), ("STORE", "URBAN", "0.4000"),
        ("STORE", "SUBURBAN", "0.3200"), ("STORE", "RURAL", "0.1400"),
        ("WAREHOUSE", "SUBURBAN", "0.0250"),
        ("LARGE_OFFICE", "URBAN", "0.0100"), ("DC", "URBAN", "0.0050"),
    ],
    "campus-centric": [
        # A handful of very large research, engineering or manufacturing
        # campuses, the offices around them, and a data centre.
        #
        # No BRANCH at all, which is the point. office-centric puts 53% of its
        # sites in branches, so AstraZeneca was modelled with a branch network
        # it does not have - and its own benchmark row names R_D_CAMPUS as the
        # representative site, so the shape contradicted the benchmark beside
        # it.
        #
        # Six BICS codes name a campus in their benchmark row: pharmaceuticals,
        # biotechnology, aerospace and defence, software, SaaS and fintech.
        # Insurance and commercial real estate name an office and keep
        # office-centric; investment banking names a trading floor and
        # integrated oil a refinery, which are their own shapes.
        #
        # Half campus, 40% office, 10% data centre: a campus estate is a small
        # number of very large sites, which is what makes it expensive per site
        # and cheap per user.
        ("CAMPUS", "DENSE_URBAN", "0.1500"),
        ("CAMPUS", "URBAN", "0.2000"),
        # Suburban because a research or manufacturing campus is usually out of
        # town - land, and in pharma distance from anything it might harm.
        ("CAMPUS", "SUBURBAN", "0.1500"),
        ("LARGE_OFFICE", "DENSE_URBAN", "0.1500"),
        ("LARGE_OFFICE", "URBAN", "0.2500"),
        ("DC", "DENSE_URBAN", "0.0600"), ("DC", "URBAN", "0.0400"),
    ],
    "few-large": [
        # A handful of enormous sites. The office is the terminal or the
        # operations centre; there is no store layer at all.
        ("LARGE_OFFICE", "DENSE_URBAN", "0.2000"),
        ("LARGE_OFFICE", "URBAN", "0.3000"),
        ("LARGE_OFFICE", "SUBURBAN", "0.1500"),
        ("WAREHOUSE", "URBAN", "0.1500"),
        ("WAREHOUSE", "SUBURBAN", "0.1000"),
        ("DC", "DENSE_URBAN", "0.0600"), ("DC", "URBAN", "0.0400"),
    ],
    "plant-centric": [
        ("WAREHOUSE", "SUBURBAN", "0.3000"), ("WAREHOUSE", "RURAL", "0.3500"),
        ("WAREHOUSE", "URBAN", "0.1500"),
        ("LARGE_OFFICE", "URBAN", "0.1000"),
        ("BRANCH", "RURAL", "0.0700"),
        ("DC", "URBAN", "0.0300"),
    ],
    "office-centric": [
        ("LARGE_OFFICE", "DENSE_URBAN", "0.1500"),
        ("LARGE_OFFICE", "URBAN", "0.2500"),
        ("BRANCH", "URBAN", "0.2500"), ("BRANCH", "SUBURBAN", "0.2000"),
        ("BRANCH", "RURAL", "0.0800"),
        ("DC", "DENSE_URBAN", "0.0400"), ("DC", "URBAN", "0.0300"),
    ],
    "network-centric": [
        # The estate is infrastructure. Many small unstaffed sites and a few
        # very large ones - priced here as DC and BRANCH because those are the
        # only words available, which is why TELECOM is flagged POOR.
        ("DC", "DENSE_URBAN", "0.0800"), ("DC", "URBAN", "0.1200"),
        ("DC", "SUBURBAN", "0.0500"),
        ("BRANCH", "URBAN", "0.3000"), ("BRANCH", "SUBURBAN", "0.2500"),
        ("BRANCH", "RURAL", "0.1500"),
        ("LARGE_OFFICE", "DENSE_URBAN", "0.0500"),
    ],
}

# Bandwidth per archetype, by shape. The figure is the bearer that has to be
# installed; what a site commits on it is the committed fraction set per
# archetype.
#
# These differ by shape because that is the point of the dimension: a
# quick-service restaurant and an airport terminal are both "a site" and one
# needs two orders of magnitude more circuit than the other.
# Only tiers the rate card prices: 50, 100, 500, 1000, 10000.
#
# The first version declared 40000 for an airport data centre and 100000 for a
# telecom core site. Both are real circuits and neither is priceable - the top
# seeded tier is 10000 - so declaring them turned the largest sites in the
# estate into unpriced scope and dragged coverage down. Asserting a bearer the
# model cannot price does not make the model more right about that site; it
# makes it wrong and silent instead of wrong and visible.
#
# The sectors that genuinely need more are exactly the ones flagged POOR, and
# their caveat already says the archetype is wrong for them. A 100G figure
# would add a second error rather than fix the first.
# Every archetype has a figure in every shape.
#
# The five site types added with the archetype vocabulary need one too, or an
# industry whose estate contains them has unpriceable scope - which is what
# four guards reported the moment the vocabulary grew.
#
# These are the fallbacks. A per-industry figure from the benchmark overrides
# them wherever one exists, and for the representative site of an industry one
# always does.
#
# PLANT 1 Gbps, TERMINAL 10, CONTROL_CENTER 1, REMOTE_SITE and NETWORK_SITE
# 100 Mbps - a remote extraction site and an unmanned tower carry telemetry
# and backhaul, not user traffic.
#
# CAMPUS sits at 10 Gbps in every shape.
#
# The benchmark's own campus rows - R_D_CAMPUS, RESEARCH_CAMPUS,
# ENGINEERING_CAMPUS - are all 10.5 Gbps, capped at the top tier the rate card
# quotes. It is the same figure in every shape because a research campus is a
# research campus whether the company also runs stores or refineries.
SHAPE_BANDWIDTH = {
    "many-small":     {"STORE": 50, "BRANCH": 100, "WAREHOUSE": 100,
                       "LARGE_OFFICE": 500, "CAMPUS": 10000, "DC": 10000,
                       "PLANT": 1000, "REMOTE_SITE": 100,
                       "CONTROL_CENTER": 1000,
                       "NETWORK_SITE": 100, "TERMINAL": 10000},
    "few-large":      {"STORE": 100, "BRANCH": 500, "WAREHOUSE": 1000,
                       "LARGE_OFFICE": 10000, "CAMPUS": 10000, "DC": 10000,
                       "PLANT": 1000, "REMOTE_SITE": 100,
                       "CONTROL_CENTER": 1000,
                       "NETWORK_SITE": 100, "TERMINAL": 10000},
    "plant-centric":  {"STORE": 50, "BRANCH": 100, "WAREHOUSE": 500,
                       "LARGE_OFFICE": 1000, "CAMPUS": 10000, "DC": 10000,
                       "PLANT": 1000, "REMOTE_SITE": 100,
                       "CONTROL_CENTER": 1000,
                       "NETWORK_SITE": 100, "TERMINAL": 10000},
    "office-centric": {"STORE": 50, "BRANCH": 100, "WAREHOUSE": 100,
                       "LARGE_OFFICE": 1000, "CAMPUS": 10000, "DC": 10000,
                       "PLANT": 1000, "REMOTE_SITE": 100,
                       "CONTROL_CENTER": 1000,
                       "NETWORK_SITE": 100, "TERMINAL": 10000},
    "network-centric": {"STORE": 100, "BRANCH": 1000, "WAREHOUSE": 500,
                        "LARGE_OFFICE": 10000, "CAMPUS": 10000, "DC": 10000,
                       "PLANT": 1000, "REMOTE_SITE": 100,
                       "CONTROL_CENTER": 1000,
                       "NETWORK_SITE": 100, "TERMINAL": 10000},
}

# The highest tier the seeded rate card prices. A bandwidth above this is
# unpriceable, and the test that caught it is worth more than the ambition.
MAX_PRICEABLE_MBPS = 10000

# Where a sector genuinely differs from its shape, with the reason.
#
# A shape is an economy, not a claim that every sector sharing it is the same
# estate. Six industries came out identical to DEFAULT at every site type,
# which buys nothing and costs a join - so each one that stays in the table
# says where it disagrees and why.
#
# Only real differences. An override invented to satisfy a test would be worse
# than the collapse it fixes.
BANDWIDTH_OVERRIDES = {
    # A bank branch is not a small shop: card, teller and video traffic on one
    # circuit, and a regulated path to core banking.
    "FINANCIAL_SERVICES": {"STORE": 100},
    "RETAIL_BANKING": {"STORE": 100},
    # Claims and underwriting centres are large; the agency offices that feed
    # them are not.
    "INSURANCE": {"LARGE_OFFICE": 10000},
    # A development office moves more data than a sales office of the same
    # size - builds, images, remote environments.
    "IT_SERVICES": {"LARGE_OFFICE": 10000, "BRANCH": 500},
    # A citizen service centre runs identity, video and document capture; an
    # administrative office does not.
    "GOVERNMENT": {"BRANCH": 500},
    # Guest wifi is the load in a hotel, not staff - which is why the fit is
    # FAIR: the figure is right and the reason is wrong.
    "TRAVEL_TOURISM": {"LARGE_OFFICE": 10000},
    # An office business with warehouse space attached still runs customs and
    # tracking systems through the shed.
    "FREIGHT_FORWARDING": {"WAREHOUSE": 500},
    # A grocery store carries more systems than a specialty one: pharmacy,
    # bakery, fuel, self-checkout.
    "GROCERY_RETAIL": {"STORE": 100},
    # A sortation hub is a warehouse running scanners at line rate.
    "PARCEL_LOGISTICS": {"WAREHOUSE": 1000},
    # A dispatch centre is the whole operation; a station is a handful of
    # terminals and a radio backhaul.
    "PUBLIC_SAFETY": {"LARGE_OFFICE": 10000, "STORE": 100},
    # A dealer network behaves like specialty retail on top of the plants.
    "AUTOMOTIVE": {"STORE": 100},
    # A refinery's control network is the reason the fit is POOR; the bearer
    # is still larger than a distribution shed's.
    "PROCESS_MANUFACTURING": {"WAREHOUSE": 1000},
    # Remote extraction sites are the smallest bearers in the model and the
    # hardest to deliver at all.
    "NATURAL_RESOURCES": {"BRANCH": 50},
    # A base is not a depot: separation and resilience drive more circuit per
    # site than the building would suggest.
    "DEFENSE": {"WAREHOUSE": 1000, "LARGE_OFFICE": 10000},
    # Terminals and yards are the largest single sites in the model.
    "AIRPORTS": {"WAREHOUSE": 1000},
    "PORTS": {"WAREHOUSE": 1000},
    # A depot is a shed with a scanner, not a distribution centre.
    "WHOLESALE_DISTRIBUTION": {"WAREHOUSE": 1000},
    "DISCRETE_MANUFACTURING": {"WAREHOUSE": 1000},
    # Very few sites, and the data centre is the business.
    "CAPITAL_MARKETS": {"BRANCH": 1000},
    # SPECIALTY_RETAIL and QSR_RESTAURANTS carry no override on purpose. The
    # first attempt gave them LARGE_OFFICE 1000, which is DEFAULT's figure -
    # an override written toward the default rather than away from it, which
    # collapsed them onto it precisely as the shape had. Their many-small
    # shape already puts the head office at 500, and that is the difference.
    # Dense small sites with a regulated dispensing path.
    "PHARMACY_RETAIL": {"STORE": 100},
    # An exchange is unstaffed infrastructure carrying aggregate traffic.
    "TELECOM": {"WAREHOUSE": 1000},
}


def shape_of(industry: str) -> str:
    """The site shape for an industry, falling back through its parent.

    A case tagged with a coarse value resolves to that value's own shape; one
    tagged with a split resolves to its own. Neither needs the other to exist.
    """
    wanted = (industry or "DEFAULT").strip().upper() or "DEFAULT"
    for name, _parent, shape, _fit, _note in INDUSTRIES:
        if name == wanted:
            return shape
    return "office-centric"


def fit_of(industry: str) -> str:
    """How well the five archetypes describe this industry's estate."""
    wanted = (industry or "DEFAULT").strip().upper() or "DEFAULT"
    for name, _parent, _shape, fit, _note in INDUSTRIES:
        if name == wanted:
            return fit
    return UNKNOWN


def caveat(industry: str) -> str | None:
    """What to tell a reader about an industry the archetypes serve badly.

    None where the fit is GOOD. A caveat on every case would be noise; a
    caveat on the ones that need it is a finding.
    """
    wanted = (industry or "DEFAULT").strip().upper() or "DEFAULT"
    for name, _parent, _shape, fit, note in INDUSTRIES:
        if name != wanted:
            continue
        if fit == GOOD:
            return None
        return (f"{name} is modelled with the five site archetypes this "
                f"workbench has, and the fit is {fit}: {note}. Site counts "
                f"and bandwidths for this sector carry that limitation on top "
                f"of their evidence grade.")
    return (f"{wanted} is not a profiled sector, so this estate is split and "
            f"sized on the DEFAULT office-centric shape. That is a fallback "
            f"rather than a judgement about this industry - a many-small "
            f"retail estate or a few-large airport estate modelled this way "
            f"will be wrong about where the sites are and how big they are.")


def density_mix_rows() -> list:
    """(industry, archetype, density_band, share) for every industry."""
    rows = []
    for name, _parent, shape, _fit, _note in INDUSTRIES:
        for archetype, band, share in SHAPES[shape]:
            rows.append((name, archetype, band, share))
    return rows


def bandwidth_rows() -> list:
    """(industry, archetype, mbps) for every industry."""
    rows = []
    for name, _parent, shape, _fit, _note in INDUSTRIES:
        sizes = dict(SHAPE_BANDWIDTH[shape])
        sizes.update(BANDWIDTH_OVERRIDES.get(name, {}))
        for archetype, mbps in sorted(sizes.items()):
            rows.append((name, archetype, mbps))
    return rows
