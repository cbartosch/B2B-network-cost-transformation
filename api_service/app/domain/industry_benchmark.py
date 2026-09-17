"""What a site of a given kind, in a given industry, actually buys.

Supplied as a benchmark workbook: 44 rows across 10 sectors, 42 BICS level-3
industries and 37 site archetypes, each carrying typical bandwidth, committed
rate as a share of it, location context and a criticality tier.

This is the first reference data in the model that was not invented here. The
five site archetypes and their bandwidths were the workbench's own judgement,
and nine industries were carrying an honest "POOR fit" caveat because a
terminal, a mine and a tower site are not branches. This replaces the judgement
where the benchmark covers it and leaves the caveat where it does not.

Three things it supplies that were previously assumed:

**A committed share per site kind, not per archetype.** 4.181 set one fraction
per archetype from an analyst's judgement - 30% for a data centre, 50% for
everything else. The benchmark is finer and sometimes disagrees: a supermarket
store is 25-75% and a trading floor is 100%, and treating both as 50% was
wrong in opposite directions.

**A bandwidth range rather than a point.** The workbench held one figure per
(industry, archetype). A range is what the market actually looks like, and
carrying low and high lets the simulation express a spread it was previously
inventing from a single number.

**Criticality, which is what dual access is for.** `dual_access_probability`
was a seeded guess per archetype. A Tier 1 site has a second path because
losing it stops the business; a Tier 3 store does not. That is a property of
the site's role, which is exactly what the tier states.

The bandwidth ranges are wide - "1-20 Gbps" is a factor of twenty - and that
width is information rather than noise. A range that wide says the archetype
covers genuinely different sites, and narrowing it by picking a midpoint would
assert a precision the source does not have.
"""
from decimal import Decimal

# Location context onto the density bands the serviceability table is keyed on.
#
# Industrial is its own thing in the source and has no band here: an industrial
# estate is usually suburban in access terms - served, but not by the dense
# urban fibre a city centre has - and mapping it to RURAL would make a refinery
# unserviceable when refineries have fibre.
CONTEXT_TO_DENSITY = {
    "Developed Urban": "DENSE_URBAN",
    "Developed": "DENSE_URBAN",
    "Urban": "URBAN",
    "Industrial": "SUBURBAN",
    "Regional": "SUBURBAN",
    "Remote": "RURAL",
}

# Criticality onto the probability that a site has a second access path.
#
# Tier 1 is 1.00 rather than 0.95: a tier 1 site without a second path is a
# finding about that site, not a rounding. The model already reports
# `single_by_necessity` when serviceability cannot deliver one, so asserting
# the requirement and letting serviceability refuse it is more honest than
# assuming some tier 1 sites chose not to.
TIER_TO_DUAL_ACCESS = {
    "Tier 1": Decimal("1.00"),
    "Tier 2": Decimal("0.70"),
    "Tier 3": Decimal("0.35"),
}

# Cloud requirement onto whether the estate needs a direct cloud on-ramp, which
# is a priced component rather than a property of the access circuit. Carried
# so a later release can price it; nothing reads it yet and that is recorded
# rather than hidden.
CLOUD_REQUIREMENT_ORDER = ("Medium", "Medium-High", "High", "Very High",
                           "Extreme")

# What the source says about direct cloud connectivity. "Required" is a
# commitment; "Optional" is not.
CLOUD_DIRECT = ("No", "Optional", "Recommended", "Strategic Sites", "Required")


# The supplied BICS L3 industry WAN benchmark, verbatim.
#
# (sector, industry_l3, site_archetype, location_context,
#  typical_bandwidth, cir_pct, cloud_requirement, cloud_direct, criticality)
#
# Kept as the source stated it, in the source's own words and units, and parsed
# by domain/industry_benchmark at seed time. Storing the parsed figures here
# instead would put a transformation between the source and the repository with
# no way to check it - and the parse refusing a row is how a bad row gets
# noticed rather than silently defaulted.
INDUSTRY_WAN_BENCHMARK = [
    ("Energy", "Integrated Oil & Gas", "HQ", "Developed Urban", "5-40 Gbps", "100%", "High", "Recommended", "Tier 1"),
    ("Energy", "Integrated Oil & Gas", "Refinery", "Industrial", "1-20 Gbps", "80-100%", "Medium", "Strategic Sites", "Tier 1"),
    ("Energy", "Upstream E&P", "Production Site", "Remote", "100 Mbps-2 Gbps", "50-100%", "Medium-High", "Optional", "Tier 2"),
    ("Energy", "LNG", "Export Terminal", "Industrial", "1-10 Gbps", "80-100%", "Medium", "Strategic Sites", "Tier 1"),
    ("Energy", "Utilities", "Control Center", "Urban", "1-10 Gbps", "100%", "Medium", "Optional", "Tier 1"),
    ("Energy", "Renewable Energy", "Wind/Solar Farm", "Remote", "20-500 Mbps", "50-100%", "High", "Recommended", "Tier 2"),
    ("Materials", "Diversified Mining", "Autonomous Mine", "Remote", "1-20 Gbps", "100%", "High", "Recommended", "Tier 1"),
    ("Materials", "Copper Mining", "Mine", "Remote", "200 Mbps-5 Gbps", "80-100%", "High", "Recommended", "Tier 2"),
    ("Materials", "Gold Mining", "Mine", "Remote", "100 Mbps-2 Gbps", "80-100%", "High", "Recommended", "Tier 2"),
    ("Materials", "Chemicals", "Production Plant", "Industrial", "500 Mbps-10 Gbps", "80-100%", "Medium", "Optional", "Tier 1"),
    ("Materials", "Forestry & Paper", "Mill", "Regional", "100 Mbps-2 Gbps", "50-100%", "Medium", "Optional", "Tier 2"),
    ("Industrials", "Airport", "Major Hub Airport", "Developed Urban", "10-100 Gbps", "80-100%", "High", "Required", "Tier 1"),
    ("Industrials", "Airport", "Regional Airport", "Regional", "1-10 Gbps", "80-100%", "High", "Recommended", "Tier 2"),
    ("Industrials", "Airlines", "Operations Center", "Urban", "1-20 Gbps", "100%", "Very High", "Required", "Tier 1"),
    ("Industrials", "Port", "Mega Container Port", "Developed", "5-40 Gbps", "80-100%", "High", "Recommended", "Tier 1"),
    ("Industrials", "Railways", "Operations Center", "Urban", "1-10 Gbps", "100%", "Medium-High", "Recommended", "Tier 1"),
    ("Industrials", "Logistics", "Distribution Center", "Regional", "500 Mbps-10 Gbps", "80-100%", "Very High", "Required", "Tier 1"),
    ("Industrials", "Warehousing", "Fulfillment Center", "Regional", "500 Mbps-10 Gbps", "80-100%", "Very High", "Required", "Tier 1"),
    ("Consumer Discretionary", "Automotive OEM", "Manufacturing Plant", "Industrial", "1-20 Gbps", "80-100%", "High", "Recommended", "Tier 1"),
    ("Consumer Discretionary", "Hotels", "Resort", "Urban", "200 Mbps-2 Gbps", "50-100%", "High", "Recommended", "Tier 2"),
    ("Consumer Discretionary", "Department Stores", "Store", "Urban", "50-500 Mbps", "25-75%", "High", "Optional", "Tier 3"),
    ("Consumer Discretionary", "E-Commerce", "Fulfillment Center", "Regional", "1-20 Gbps", "100%", "Extreme", "Required", "Tier 1"),
    ("Consumer Staples", "Food Manufacturing", "Plant", "Industrial", "500 Mbps-5 Gbps", "80-100%", "High", "Recommended", "Tier 2"),
    ("Consumer Staples", "Supermarkets", "Store", "Urban", "20-200 Mbps", "25-75%", "High", "Optional", "Tier 3"),
    ("Consumer Staples", "Drug Retail", "Store", "Urban", "20-200 Mbps", "25-75%", "High", "Optional", "Tier 3"),
    ("Healthcare", "Hospital", "Major Hospital", "Urban", "500 Mbps-10 Gbps", "80-100%", "High", "Required", "Tier 1"),
    ("Healthcare", "Pharmaceuticals", "R&D Campus", "Developed Urban", "1-20 Gbps", "100%", "Very High", "Required", "Tier 1"),
    ("Healthcare", "Biotechnology", "Research Campus", "Developed Urban", "1-20 Gbps", "100%", "Very High", "Required", "Tier 1"),
    ("Financials", "Universal Banking", "Core Banking DC", "Developed", "10-100 Gbps", "100%", "High", "Required", "Tier 1"),
    ("Financials", "Retail Banking", "Branch", "Urban", "20-200 Mbps", "25-75%", "High", "Optional", "Tier 3"),
    ("Financials", "Investment Banking", "Trading Floor", "Urban", "10-40 Gbps", "100%", "Very High", "Required", "Tier 1"),
    ("Financials", "Insurance", "Regional Office", "Urban", "100 Mbps-2 Gbps", "50-100%", "High", "Recommended", "Tier 2"),
    ("Financials", "Payment Networks", "Processing Center", "Developed", "20-100 Gbps", "100%", "Extreme", "Required", "Tier 1"),
    ("Financials", "Fintech", "Engineering Hub", "Urban", "1-20 Gbps", "100%", "Extreme", "Required", "Tier 1"),
    ("Information Technology", "Software", "Engineering Campus", "Urban", "10-100 Gbps", "100%", "Extreme", "Required", "Tier 1"),
    ("Information Technology", "SaaS", "Engineering Campus", "Urban", "20-200 Gbps", "100%", "Extreme", "Required", "Tier 1"),
    ("Information Technology", "Cloud Provider", "Data Center", "Developed", "100-400+ Gbps", "100%", "Extreme", "Required", "Tier 1"),
    ("Information Technology", "Semiconductors", "Fab", "Industrial", "1-20 Gbps", "100%", "High", "Required", "Tier 1"),
    ("Communication Services", "Mobile Operator", "Core DC", "Urban", "10-100 Gbps", "100%", "High", "Required", "Tier 1"),
    ("Communication Services", "Fixed Operator", "Core Site", "Urban", "10-100 Gbps", "100%", "High", "Required", "Tier 1"),
    ("Communication Services", "Cable Operator", "Headend", "Regional", "1-20 Gbps", "100%", "High", "Recommended", "Tier 1"),
    ("Communication Services", "Tower Company", "Tower Site", "Remote", "10-200 Mbps", "50-100%", "Medium", "No", "Tier 3"),
    ("Real Estate", "Data Center REIT", "Data Center", "Developed", "20-200 Gbps", "100%", "Extreme", "Required", "Tier 1"),
    ("Real Estate", "Commercial REIT", "Office Building", "Urban", "100 Mbps-2 Gbps", "50-100%", "Medium", "Optional", "Tier 2"),
]


# Industries the supplied benchmark does not cover, added here because the
# taxonomy has to cover the industries the firm actually works with.
#
# A thirty-company run mapped fourteen of them to a nearest neighbour:
# Siemens, Schneider, ABB, Caterpillar and Philips to AUTOMOTIVE_OEM;
# Saint-Gobain, Holcim, Heidelberg, CRH and CEMEX to CHEMICALS; Airbus to
# AUTOMOTIVE_OEM; Unilever and L'Oreal to FOOD_MANUFACTURING; and
# ArcelorMittal to FORESTRY_PAPER - which is the one that cannot be defended.
# A mill is a mill and the estate shape was sound, but an output telling a
# client their steelworks was modelled as forestry and paper is finished
# before it starts.
#
# **These are this repository's figures, not the supplied benchmark's.** They
# are kept in their own list and carry `source` = LOCAL so a reader can tell
# which of the two produced any given row. Every one is an expert assumption
# about a typical site of that kind, which is what evidence grade E means, and
# they should be replaced the first time a real engagement in one of these
# sectors produces better.
#
# I dropped these five when the shape map was first written, on the grounds
# that the benchmark had no rows for them. That was the wrong call: a benchmark
# gap is a reason to seed a grade E row and say so, not a reason to leave a
# steelmaker with nowhere to go.
LOCAL_INDUSTRY_ROWS = [
    # Diversified industrials. Many mid-sized plants plus large engineering
    # campuses; bandwidth driven by design data and plant telemetry rather
    # than by either alone.
    ("Industrials", "Industrial Conglomerate", "Manufacturing Plant",
     "Industrial", "200 Mbps-2 Gbps", "50-80%", "High", "Recommended",
     "Tier 2"),
    # Cement, aggregates, glass, plasterboard. Hundreds of small fixed sites,
    # many genuinely rural - a quarry is where the rock is - and low per-site
    # bandwidth with high availability requirements because a kiln does not stop.
    ("Materials", "Building Materials", "Production Plant",
     "Regional", "50-500 Mbps", "50-100%", "Medium", "No", "Tier 2"),
    # Steel and metals processing. A works is a continuous process with heavy
    # sensor traffic and a small number of very large sites.
    ("Materials", "Steel", "Mill",
     "Industrial", "500 Mbps-5 Gbps", "80-100%", "Medium-High", "Optional",
     "Tier 1"),
    # Aerospace and defence. Engineering campuses carrying very large design
    # datasets, and assembly sites with tight availability requirements.
    ("Industrials", "Aerospace & Defense", "Engineering Campus",
     "Developed Urban", "1-20 Gbps", "80-100%", "Very High", "Required",
     "Tier 1"),
    # Household and personal care. Consumer-goods plants and distribution,
    # closer to food manufacturing than to speciality chemicals.
    ("Consumer Staples", "Household & Personal Care", "Plant",
     "Regional", "100 Mbps-1 Gbps", "50-80%", "Medium-High", "Optional",
     "Tier 2"),
]


class BenchmarkRowInvalid(ValueError):
    """A row that cannot be read into the model's units."""


def parse_bandwidth(text) -> tuple:
    """"5-40 Gbps" into (5000, 40000) Mbps.

    Refuses rather than guesses. A value this cannot read is a row the analyst
    must look at, and a default would put a bandwidth in the model that the
    source does not state.
    """
    import re

    raw = str(text or "").replace("+", "").strip()
    match = re.match(
        r"([\d.]+)\s*(Mbps|Gbps)?\s*-\s*([\d.]+)\s*(Mbps|Gbps)", raw, re.I)
    if not match:
        raise BenchmarkRowInvalid(
            f"{text!r} is not a bandwidth range this can read. Expected "
            f"something like '500 Mbps-10 Gbps' or '1-20 Gbps'.")

    low_value, low_unit, high_value, high_unit = match.groups()
    # "1-20 Gbps" states the unit once, at the end, and it governs both.
    low_unit = low_unit or high_unit

    def to_mbps(value, unit):
        factor = 1000 if str(unit).lower() == "gbps" else 1
        return int(Decimal(value) * factor)

    low, high = to_mbps(low_value, low_unit), to_mbps(high_value, high_unit)
    if low > high:
        raise BenchmarkRowInvalid(
            f"{text!r} reads as {low}-{high} Mbps, which is backwards")
    return low, high


def parse_cir(text) -> tuple:
    """"80-100%" into (Decimal("0.80"), Decimal("1.00")).

    A single figure like "100%" is both bounds: the source is stating a
    certainty rather than a range, and widening it would invent a spread.
    """
    import re

    raw = str(text or "").strip()
    if match := re.match(r"(\d+)\s*-\s*(\d+)\s*%", raw):
        low, high = int(match.group(1)), int(match.group(2))
    elif match := re.match(r"(\d+)\s*%", raw):
        low = high = int(match.group(1))
    else:
        raise BenchmarkRowInvalid(
            f"{text!r} is not a committed share this can read. Expected "
            f"'100%' or '80-100%'.")
    if not (0 < low <= high <= 100):
        raise BenchmarkRowInvalid(
            f"{text!r} reads as {low}-{high}%, which is not a share of a "
            f"bearer. A committed rate above the circuit carrying it cannot be "
            f"delivered, and one of zero is a best-effort service rather than "
            f"a committed one.")
    return Decimal(low) / 100, Decimal(high) / 100


def archetype_code(site_archetype: str) -> str:
    """"Mega Container Port" into MEGA_CONTAINER_PORT.

    Derived from the source's own wording rather than mapped onto the five
    archetypes the workbench already had. Mapping a refinery to WAREHOUSE would
    lose the thing that makes it a refinery, and the whole reason nine
    industries carried a POOR-fit caveat was that the five did not cover them.
    """
    import re

    code = re.sub(r"[^A-Za-z0-9]+", "_", str(site_archetype or "").strip())
    return code.strip("_").upper() or "UNKNOWN"


def industry_code(industry_l3: str) -> str:
    """"Integrated Oil & Gas" into INTEGRATED_OIL_GAS."""
    import re

    code = re.sub(r"[^A-Za-z0-9]+", "_", str(industry_l3 or "").strip())
    return code.strip("_").upper() or "UNKNOWN"


def read_row(row: dict) -> dict:
    """One benchmark row in the model's own units.

    Everything derived, nothing defaulted. A row missing a field this needs is
    refused with the field named, because a benchmark silently completed from
    assumptions is worse than one an analyst has to fix.
    """
    low_mbps, high_mbps = parse_bandwidth(row.get("Typical Bandwidth"))
    cir_low, cir_high = parse_cir(row.get("CIR %"))

    context = str(row.get("Location Context") or "").strip()
    density = CONTEXT_TO_DENSITY.get(context)
    if density is None:
        raise BenchmarkRowInvalid(
            f"{context!r} is not a location context this maps to a density "
            f"band. Known: {sorted(CONTEXT_TO_DENSITY)}.")

    tier = str(row.get("Criticality") or "").strip()
    dual = TIER_TO_DUAL_ACCESS.get(tier)
    if dual is None:
        raise BenchmarkRowInvalid(
            f"{tier!r} is not a criticality tier. Known: "
            f"{sorted(TIER_TO_DUAL_ACCESS)}.")

    return {
        "sector": str(row.get("Sector") or "").strip(),
        "industry_l3": str(row.get("Industry L3") or "").strip(),
        "industry_code": industry_code(row.get("Industry L3")),
        "site_archetype": str(row.get("Site Archetype") or "").strip(),
        "archetype_code": archetype_code(row.get("Site Archetype")),
        "location_context": context,
        "density_band": density,
        "bandwidth_low_mbps": low_mbps,
        "bandwidth_high_mbps": high_mbps,
        # The midpoint, for a caller that needs one figure. Reported beside the
        # range and never instead of it: "1-20 Gbps" is a factor of twenty, and
        # a midpoint of 10.5 Gbps asserts a precision the source does not have.
        "bandwidth_base_mbps": int((low_mbps + high_mbps) / 2),
        "committed_share_low": str(cir_low),
        "committed_share_high": str(cir_high),
        "committed_share_base": str(((cir_low + cir_high) / 2).quantize(
            Decimal("0.001"))),
        "criticality_tier": tier,
        "dual_access_probability": str(dual),
        "cloud_requirement": str(row.get("Cloud Requirement") or "").strip()
                             or None,
        "cloud_direct": str(row.get("Direct Cloud Connectivity") or "").strip()
                        or None,
    }


def read_all(rows: list) -> dict:
    """Every row, with the ones that could not be read named rather than lost.

    A load that silently drops a row it cannot parse leaves an industry with no
    benchmark and no explanation - and the analyst discovers it as a missing
    figure three screens later.
    """
    kept, refused = [], []
    for index, row in enumerate(rows):
        try:
            kept.append(read_row(row))
        except BenchmarkRowInvalid as exc:
            refused.append({"row": index + 1,
                            "industry": row.get("Industry L3"),
                            "site_archetype": row.get("Site Archetype"),
                            "reason": str(exc)})
    return {
        "rows": kept,
        "refused": refused,
        "sectors": sorted({r["sector"] for r in kept}),
        "industries": sorted({r["industry_code"] for r in kept}),
        "archetypes": sorted({r["archetype_code"] for r in kept}),
        "note": (f"{len(kept)} benchmark row(s) across "
                 f"{len({r['sector'] for r in kept})} sector(s), "
                 f"{len({r['industry_code'] for r in kept})} BICS L3 "
                 f"industry/industries and "
                 f"{len({r['archetype_code'] for r in kept})} site "
                 f"archetype(s)"
                 + (f"; {len(refused)} row(s) refused and named"
                    if refused else "; none refused")),
    }


COLUMNS = ("Sector", "Industry L3", "Site Archetype", "Location Context",
           "Typical Bandwidth", "CIR %", "Cloud Requirement",
           "Direct Cloud Connectivity", "Criticality")


def seeded() -> dict:
    """The benchmark as shipped plus this repository's own rows, parsed.

    Both, because the taxonomy has to cover the industries the firm works
    with - and marked, because a reader has to be able to tell a published
    figure from one we wrote. `source` says which.
    """
    out = read_all([dict(zip(COLUMNS, row))
                    for row in INDUSTRY_WAN_BENCHMARK + LOCAL_INDUSTRY_ROWS])
    local = {industry_code(row[1]) for row in LOCAL_INDUSTRY_ROWS}
    for entry in out["rows"]:
        entry["source"] = ("LOCAL" if entry["industry_code"] in local
                           else "BICS_L3_BENCHMARK")
    out["local_industries"] = sorted(local)
    out["note"] += (f"; {len(local)} of these are this repository's own rows "
                    f"for industries the supplied benchmark does not cover, "
                    f"marked source=LOCAL and graded as assumptions")
    return out


def for_industry(industry_code: str, *, rows: list | None = None) -> list:
    """Every benchmark row for one BICS L3 industry, best match first.

    Exact code first, then a sector sibling, then nothing. A sibling is a
    weaker answer and is returned flagged rather than silently: a supermarket
    benchmark applied to a drug retailer is defensible and is not the same as
    having one.
    """
    catalogue = rows if rows is not None else seeded()["rows"]
    wanted = (industry_code or "").upper()
    exact = [r for r in catalogue if r["industry_code"] == wanted]
    if exact:
        return [{**r, "match": "EXACT"} for r in exact]

    sectors = {r["sector"] for r in catalogue if r["industry_code"] == wanted}
    if not sectors:
        return []
    return [{**r, "match": "SECTOR_SIBLING"} for r in catalogue
            if r["sector"] in sectors]


def archetypes_for(industry_code: str, *, rows: list | None = None) -> list:
    """The site archetypes this industry's benchmark actually names.

    A refinery, a mine and a tower site rather than the five this workbench
    invented - which is the whole reason nine industries carried a POOR-fit
    caveat.
    """
    return sorted({r["archetype_code"]
                   for r in for_industry(industry_code, rows=rows)})
