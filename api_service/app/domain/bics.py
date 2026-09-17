"""BICS level 3 as the one industry taxonomy.

Two taxonomies existed and **three of forty-two codes overlapped**. The
workbench's own twenty-eight drove the density mix and the seeded bandwidth;
the supplied BICS benchmark had forty-two with published bandwidth, committed
share and criticality. An analyst picking AIRPORTS or DEFENSE from the intake
list therefore got no benchmark row at all, and the published data was
unreachable for twenty-five of twenty-eight industries.

Substring bridging was the obvious shortcut and it pairs CAPITAL_MARKETS with
SUPERMARKETS, so it is worse than none.

**What the benchmark supplies and what it does not.** Forty of its forty-two
codes name exactly one site archetype - a representative site, not an estate.
A supermarket chain has stores, distribution centres and a head office, and the
benchmark says only "STORE". So:

    BICS code -> benchmark   bandwidth, committed share, criticality, density
                             band, for the archetype it names
    BICS code -> shape       which archetypes an estate of this kind has, in
                             what proportion and in which density bands

The shape is this repository's judgement and says so. The benchmark is
published and says so. Keeping them apart is the point: one is evidence and the
other is not, and a reader should be able to tell which figure came from where.
"""

# The estate shape each BICS industry has. The five shapes were already defined
# for the workbench taxonomy and are reused unchanged - an estate of many small
# customer-facing sites is the same shape whether it sells groceries or
# prescriptions.
#
# Assigned by what the estate looks like, not by what the company sells. A
# tower company and a telecom operator are both network-centric; a refinery
# and a mine are both plant-centric; an investment bank and a software firm are
# both office-centric even though nothing else about them matches.
# Derived from the site archetype the benchmark names for each industry, not
# from the industry's name. A refinery, a mine and a fab are all plant-centric;
# a trading floor and an engineering campus are both office-centric; a tower
# site and a core DC are both network-centric - and none of that follows from
# what the company sells.
#
# 41 of 42 were derived mechanically from the archetype. The exception is
# noted where it sits, because an assignment made by reading should look
# different from one made by matching.
SHAPE_OF_BICS = {
    # Industrials: OPERATIONS_CENTER
    "AIRLINES": "network-centric",
    # Industrials: MAJOR_HUB_AIRPORT, REGIONAL_AIRPORT
    "AIRPORT": "few-large",
    # Consumer Discretionary: MANUFACTURING_PLANT
    "AUTOMOTIVE_OEM": "plant-centric",
    # Healthcare: RESEARCH_CAMPUS
    "BIOTECHNOLOGY": "office-centric",
    # Communication Services: HEADEND
    "CABLE_OPERATOR": "network-centric",
    # Information Technology: DATA_CENTER
    "CLOUD_PROVIDER": "network-centric",
    # Real Estate: OFFICE_BUILDING
    "COMMERCIAL_REIT": "office-centric",
    # Materials: MINE
    "COPPER_MINING": "plant-centric",
    # Real Estate: DATA_CENTER
    "DATA_CENTER_REIT": "network-centric",
    # Consumer Discretionary: STORE
    "DEPARTMENT_STORES": "many-small",
    # Materials: AUTONOMOUS_MINE
    "DIVERSIFIED_MINING": "plant-centric",
    # Consumer Staples: STORE
    "DRUG_RETAIL": "many-small",
    # Consumer Discretionary: FULFILLMENT_CENTER
    "E_COMMERCE": "few-large",
    # Financials: ENGINEERING_HUB
    "FINTECH": "office-centric",
    # Communication Services: CORE_SITE
    "FIXED_OPERATOR": "network-centric",
    # Consumer Staples: PLANT
    "FOOD_MANUFACTURING": "plant-centric",
    # Materials: MILL
    "FORESTRY_PAPER": "plant-centric",
    # Materials: MINE
    "GOLD_MINING": "plant-centric",
    # Healthcare: MAJOR_HOSPITAL
    "HOSPITAL": "few-large",
    # Consumer Discretionary: RESORT
    "HOTELS": "many-small",
    # Financials: REGIONAL_OFFICE
    "INSURANCE": "office-centric",
    # Energy: HQ, REFINERY
    "INTEGRATED_OIL_GAS": "office-centric",
    # Financials: TRADING_FLOOR
    "INVESTMENT_BANKING": "office-centric",
    # Energy: EXPORT_TERMINAL
    "LNG": "few-large",
    # Industrials: DISTRIBUTION_CENTER
    "LOGISTICS": "few-large",
    # Communication Services: CORE_DC
    "MOBILE_OPERATOR": "network-centric",
    # Financials: PROCESSING_CENTER
    "PAYMENT_NETWORKS": "network-centric",
    # Healthcare: R_D_CAMPUS
    "PHARMACEUTICALS": "office-centric",
    # Industrials: MEGA_CONTAINER_PORT
    "PORT": "few-large",
    # Industrials: OPERATIONS_CENTER
    "RAILWAYS": "network-centric",
    # Energy: WIND_SOLAR_FARM
    "RENEWABLE_ENERGY": "plant-centric",
    # Financials: BRANCH
    # network-centric, not many-small. A branch network is many small sites
    # and many-small is a STORE shape - the proportions fit and the archetype
    # does not, and BRANCH dominates network-centric. The generator that
    # produced this map had BRANCH in the wrong set.
    "RETAIL_BANKING": "network-centric",
    # Information Technology: ENGINEERING_CAMPUS
    "SAAS": "office-centric",
    # Information Technology: FAB
    "SEMICONDUCTORS": "plant-centric",
    # Information Technology: ENGINEERING_CAMPUS
    "SOFTWARE": "office-centric",
    # Consumer Staples: STORE
    "SUPERMARKETS": "many-small",
    # Communication Services: TOWER_SITE
    "TOWER_COMPANY": "network-centric",
    # Financials: CORE_BANKING_DC
    "UNIVERSAL_BANKING": "network-centric",
    # Energy: PRODUCTION_SITE
    "UPSTREAM_E_P": "plant-centric",
    # Energy: CONTROL_CENTER
    "UTILITIES": "network-centric",
    # Industrials: FULFILLMENT_CENTER
    "WAREHOUSING": "few-large",
    # Materials: PRODUCTION_PLANT. Not derived - the archetype table names
    # PLANT and MANUFACTURING_PLANT and this row says PRODUCTION_PLANT, so it
    # is assigned by reading rather than by matching. A near-miss like that is
    # exactly what a substring bridge would have got wrong.
    "CHEMICALS": "plant-centric",

    # ---- industries the supplied benchmark does not cover -----------------
    # Their rows are this repository's own (see industry_benchmark.
    # UNBENCHMARKED_BICS_ROWS) and so are these shapes. Derived the same way as
    # the rest: from the archetype the row names, not from the industry's
    # name.
    #
    # Industrials: MANUFACTURING_PLANT. Siemens, Schneider, ABB, Caterpillar
    # and Philips were all being mapped to AUTOMOTIVE_OEM, which has the right
    # shape and the wrong label.
    "INDUSTRIAL_CONGLOMERATE": "plant-centric",
    # Materials: PRODUCTION_PLANT. Cement, aggregates and glass - hundreds of
    # small fixed sites, many genuinely rural because a quarry is where the
    # rock is. Saint-Gobain, Holcim, Heidelberg, CRH and CEMEX.
    "BUILDING_MATERIALS": "plant-centric",
    # Materials: MILL. ArcelorMittal was mapped to FORESTRY_PAPER - the
    # archetype was right and the label was indefensible.
    "STEEL": "plant-centric",
    # Industrials: ENGINEERING_CAMPUS. Design data rather than plant
    # telemetry, so office-centric despite the assembly sites. Airbus.
    "AEROSPACE_DEFENSE": "office-centric",
    # Consumer Staples: PLANT. Closer to food manufacturing than to speciality
    # chemicals. Unilever and L'Oreal.
    "HOUSEHOLD_PERSONAL_CARE": "plant-centric",
}

# The shape used when a BICS code has no assignment. Office-centric rather than
# something more specific: it is the least wrong default for an enterprise
# nobody has classified, and a wrong specific shape reads as knowledge.
DEFAULT_SHAPE = "office-centric"


def shape_for(industry_code: str) -> str:
    """The estate shape for a BICS code, or the default.

    A code the benchmark carries but this does not classify gets the default
    and is reported by `unclassified()` rather than silently defaulted - an
    industry with the wrong estate shape produces a plausible estate that is
    wrong in a way nobody can see.
    """
    return SHAPE_OF_BICS.get((industry_code or "").upper(), DEFAULT_SHAPE)


def unclassified(industry_codes) -> list:
    """BICS codes with no shape assignment.

    Checked in the build, because a benchmark row for an industry whose estate
    shape nobody decided is half a model.
    """
    return sorted(code for code in industry_codes
                  if (code or "").upper() not in SHAPE_OF_BICS)


def density_mix_rows(industry_codes, shapes: dict) -> list:
    """(industry, archetype, density_band, share) for every BICS code.

    Derived from the shape, not from the benchmark: the benchmark names one
    representative archetype and an estate has several. Every mix sums to
    exactly 1.0000 because the shapes it copies do, and a test asserts it.
    """
    rows = []
    for code in sorted(industry_codes):
        for archetype, band, share in shapes[shape_for(code)]:
            rows.append((code, archetype, band, share))
    return rows
