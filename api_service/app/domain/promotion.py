"""Promotion: getting a research finding into the numbers the estimate uses.

Until this module existed, research was evidentially rigorous and analytically
inert. `quantities` was written into domain_disposition.evidence and read by
nothing; the footprint the simulation runs on came from what an analyst typed
on page 4, and circuit prices came from the seeded benchmark table. A perfect
answer on domain 2 moved the `evidenced` share of the confidence score and not
one number in the estimate.

Two rules shape what follows.

**Promotion is a person's act, not a consequence of researching.** A finding
appears here as a candidate; an analyst selects it and is named on the row.
That mirrors 0.1A, where the system proposes an entity and a named user
disposes, and it exists for the same reason: an automatic path from "a model
said so" to "the estimate now assumes so" is exactly the shape a bad number
takes on its way into a client deliverable.

**A promoted price is proposed, not approved.** Circuit prices are governed
reference data under 18.1: they carry an `approved` flag a steward sets.
Research writes them with approved=False, so they are visible, attributable
and inert until a steward accepts them. Site counts are case-scoped rather
than governed - they describe this client's estate, not a market rate - so
they land directly on the case with their provenance attached.

Every promoted row carries the agent_run_id that produced it, so the chain
from a number in the estimate back through the disposition, the provider call,
its liveness proof and the fetched source fragment stays unbroken.
"""
import re
import uuid
from datetime import datetime, timezone

from decimal import Decimal
from sqlalchemy import delete, insert, select, update

from .. import db
from . import access, triangulate

# The archetypes the simulation understands. A quantity naming anything else
# cannot be promoted to a footprint row - it may be a perfectly good finding,
# but it is not one this model can consume, and silently coercing it would be
# worse than declining.
def _archetype_names() -> frozenset:
    """The archetype names, derived from the seeded priors.

    This was a hardcoded set of five, while seed.ARCHETYPES holds the actual
    priors. Adding a sixth archetype to the seed would leave the classifier
    rejecting it - a promoted finding about a real site type refused because
    two lists disagreed.

    Imported lazily: seed imports db and the domain modules, so a module-level
    import here would be circular.
    """
    from ..seed import ARCHETYPES as SEEDED
    return frozenset(row[0] for row in SEEDED)


class _ArchetypeNames:
    """Late-bound so the seed stays the single source.

    `label not in ARCHETYPES` reads the same as before and now asks the seed.

    Not a frozenset subclass, which is what this was. It inherited the set
    API, was constructed empty, and the C-level fast paths behind `set(x)`,
    `list(x)`, `sorted(x)` and the set operators read the empty underlying
    storage directly - a Python-level `__iter__` override does not reach
    them. So `"LARGE_OFFICE" in ARCHETYPES` was True while
    `set(ARCHETYPES)` was empty, at the same moment, for the same object.

    Product code only ever asks `in`, so nothing here was wrong. A caller
    outside it reasonably did `known = set(ARCHETYPES)`, got an empty set,
    concluded every archetype was unknown and deleted 75 rows of promoted
    footprint evidence. A type that answers one question correctly and the
    neighbouring one silently wrongly should not be offering the second.

    A plain class offers only what it implements, and `set()` on it goes
    through `__iter__` like anything else.
    """

    def __contains__(self, item):
        return item in _archetype_names()

    def __iter__(self):
        return iter(_archetype_names())

    def __len__(self):
        return len(_archetype_names())

    def __repr__(self):
        return f"ARCHETYPES({sorted(_archetype_names())!r})"


ARCHETYPES = _ArchetypeNames()
# HFC and PON are separate products, not variants of one: a shared coaxial
# segment and fibre to the premises price differently and are quoted
# separately in real tenders. The single BROADBAND band blended two
# distributions and described neither.
PRODUCTS = {"DIA", "MPLS", "ETHERNET", "BROADBAND_HFC", "BROADBAND_PON",
            "MOBILE_5G"}


class NotPromotable(ValueError):
    """The quantity does not carry what a promotion needs."""


def _as_int(value):
    """A band bound as a whole number, or None. Tolerates "341", "341.0" and
    a Decimal, because the band is serialised as a string for JSON storage."""
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _sites_from(q: dict) -> int:
    """A site count from a quantity the classifier already accepted.

    Via triangulate.parse_value, so the number the writer stores is the
    number the matcher saw. Rounded, because these columns hold site counts
    and a source saying "about 10" means ten sites.
    """
    parsed = triangulate.parse_value(q.get("value"))
    if parsed is None:
        # Unreachable through _classify, which refuses a quantity this
        # cannot read. Raised rather than defaulted: a site count nobody
        # could parse must not become a zero or a one.
        raise ValueError(
            f"quantity {q.get('label')!r} has no readable value: "
            f"{q.get('value')!r}")
    return int(round(float(parsed)))


def _triangulated_index(evidence: dict) -> dict:
    """Bands by (label, country), so a promotion can carry the range and the
    conflict state rather than only the point the agent happened to state."""
    out = {}
    for t in (evidence or {}).get("triangulated") or []:
        key = ((t.get("label") or "").upper(),
               (t.get("country") or "").upper() or None)
        out[key] = t
    return out


def _quantity_sources(q: dict) -> list[str]:
    """The URLs behind THIS quantity, in the order the agent ranked them.

    Every promoted row used to carry the whole research domain's source
    pool - `evidence.sources`, which is what the agent read across all of
    its findings - so a site count and a revenue figure from the same
    domain cited the same seven or eight documents. Nestle's French office
    row cited a swissinfo piece about a German factory closing. The list
    was not wrong, it just did not answer the question anyone asks of it:
    which document says this number?

    A candidate does answer it. Across the published set the pool averages
    7.7 URLs and a quantity's own candidates average 1.8.

    A finding with no candidate URL cites nothing, and that is recorded
    rather than papered over with the pool - those findings are structural
    ("DE, FR and IT are all eurozone, so EUR/EUR is 1.0"), derived ("3% of
    FY2024 net sales"), or an explicit negative ("no public evidence of an
    Inditex DC in France"). None of them has a document behind it, and
    lending them the pool's would make them look sourced.
    """
    out = []
    for c in (q.get("candidates") or []):
        if not isinstance(c, dict):
            continue
        url = str(c.get("source_url") or "").strip()
        if url and url not in out:
            out.append(url)
    return out


def _quantities_for_case(session, case_id: str) -> list[dict]:
    """Every researched quantity on this case, with the disposition and agent
    run that produced it."""
    rows = session.execute(
        select(db.domain_disposition).where(
            db.domain_disposition.c.case_id == case_id)).all()
    out = []
    for r in rows:
        evidence = r.evidence or {}
        for i, q in enumerate(evidence.get("quantities") or []):
            if not isinstance(q, dict):
                continue
            band = _triangulated_index(evidence).get(
                ((q.get("label") or "").upper(),
                 (q.get("country") or "").upper() or None))
            out.append({
                "candidate_id": f"{r.domain_no}:{i}",
                "band": band,
                # Carried so the analyst sees what a finding is worth before
                # promoting it, and so UNRELIABLE can be refused.
                "reliability": (evidence or {}).get("reliability"),
                "domain_no": r.domain_no, "domain_name": r.domain_name,
                "disposition": r.disposition, "agent_run_id": r.agent_run_id,
                # This quantity's own citation, not the domain's pool. See
                # _quantity_sources for what the pool cost a reader.
                "sources": _quantity_sources(q),
                "quantity": q,
            })
    return out


# Archetype dimensions a finding can establish, and the unit wording that
# declares which one it carries. The unit is the discriminator because it is
# the field an agent naturally fills with "sites", "Mbps", "users per site" -
# a separate type tag would be one more field to get wrong.
ARCHETYPE_FIELDS = {
    "bandwidth_mbps_base": ("mbps", "mbit", "megabit"),
    "users_base": ("users", "headcount/site", "staff/site"),
    "dual_access_probability": ("share", "percent", "%", "proportion"),
    "primary_product": ("primary access", "primary product", "primary"),
    "backup_product": ("backup access", "backup product", "backup"),
}


def archetype_field(q: dict) -> str | None:
    """Which archetype dimension this quantity carries, if any."""
    label = str(q.get("label") or "").strip().upper()
    if label not in ARCHETYPES:
        return None
    unit = str(q.get("unit") or "").strip().lower()
    value = str(q.get("value") or "").strip().upper()
    # A product override carries a product name rather than a number.
    if value in PRODUCTS:
        for field in ("primary_product", "backup_product"):
            if any(h in unit for h in ARCHETYPE_FIELDS[field]):
                return field
        return None
    for field in ("bandwidth_mbps_base", "users_base",
                  "dual_access_probability"):
        if any(h in unit for h in ARCHETYPE_FIELDS[field]):
            # A bare share means nothing on its own; it has to say what of.
            if field == "dual_access_probability" and not any(
                    w in unit for w in ("dual", "backup", "diverse")):
                continue
            return field
    return None


# A disclosed annual spend line: what the ANCHOR estimation method is anchored
# on. Domains 9 and 10 exist to find exactly this and it reached nothing - the
# figure was researched, graded and stored, and an analyst still typed it into
# page 6 by hand.
SPEND_LABEL_HINTS = ("SPEND", "COST", "OPEX", "EXPENSE", "CHARGES")
ANNUAL_UNIT_HINTS = ("/year", "per year", "annual", "p.a.", "pa", "/yr")


def anchor_candidate(q: dict) -> bool:
    """Is this an annual money figure the anchor method could rest on?"""
    label = str(q.get("label") or "").upper()
    unit = str(q.get("unit") or "").lower()
    if not any(hint in label for hint in SPEND_LABEL_HINTS):
        return False
    if not any(hint in unit for hint in ANNUAL_UNIT_HINTS):
        return False
    # A per-site or per-user figure is a rate, not an anchor.
    if any(per in unit for per in ("/site", "per site", "/user", "per user",
                                   "/circuit", "per circuit")):
        return False
    return triangulate.parse_value(q.get("value")) is not None


# Units that denote countable PREMISES, so a quantity in them is an estate
# count rather than something else about the estate.
#
# The test was `"site" in unit`, and research almost never says "site" - it
# says what the thing is. 35 findings across the twenty-company sample carried
# an archetype-led label and a two-letter country and were declined on the
# unit alone: "stores", "hotels", "offices", "restaurants", "substations",
# "distribution centres", "bank branches", "agencies (points de vente)".
#
# An allowlist rather than a blocklist, because the failure modes are not
# symmetric. A premises noun this does not know is declined and visible; a
# non-premises unit let through is promoted silently into a site count. Two
# of those 35 were "employees" - a headcount against an archetype-led label,
# which under a blocklist would have become that many sites.
PREMISES_UNITS = frozenset({
    "site", "store", "shop", "outlet", "hotel", "restaurant", "office",
    "branch", "agency", "location", "depot", "warehouse", "plant",
    "factory", "clinic", "hospital", "centre", "center", "terminal",
    "premise", "property", "building", "facility", "campus",
    "mill", "refinery", "quarry", "lab", "laboratory", "showroom",
    "dealership", "kiosk", "forecourt", "station",
})

# Deliberately NOT premises, though each is a countable thing in a place.
#
# A distribution substation, a network node, a tower, a cabinet: grid and
# network assets, not an estate of offices and shops. Iberdrola's research
# returns 30,000 GB substations, and promoting that would replace a 2,769-site
# estate with a grid inventory priced as if every one took an enterprise
# circuit. test_promotion.test_a_count_whose_unit_is_not_sites_is_still_declined
# makes exactly this call and it is the right one - the unit gate is what
# keeps that judgement with a person.
#
# Listed rather than merely omitted, because "substation" ends in a premises
# noun's shape and the next person widening this list will reach for it.
# An AREA is not a count of premises, and this is the same judgement the
# grid assets above get. Bayer's row is the case: value 90, unit "acres (14
# buildings, 838,000 sq ft)" - ninety ACRES of the Creve Coeur campus, which
# Bayer is selling, promoted as ninety US campuses. The premises noun sat in
# a parenthetical and the word test found it there.
#
# Two separate faults, both fixed here: the area words are listed so an area
# can never read as an estate, and _unparenthesised() below stops a
# parenthetical qualifying a unit it does not govern.
NOT_PREMISES = frozenset({
    "substation", "node", "tower", "cabinet", "mast", "pole", "cell",
    "meter", "circuit", "connection", "customer", "subscriber",
    "acre", "hectare", "ha", "sqm", "sqft", "km", "mile", "square",
})

# Locative prepositions. A thing counted AT or IN a place is a part of that
# place unless the thing itself is premises.
#
# Royal Mail is the case: 1,200 "Customer Service Points", unit "parcel
# drop-off desks at delivery offices". A counter inside a building is not a
# building, and the arithmetic settles it - 1,200 CSPs, 1,200 delivery
# offices, 1,200 declared SERVICE_POINTs, one estate counted three ways.
# "office" is a premises noun and the word test found it after the
# preposition, where it names the CONTAINER rather than the thing counted.
_LOCATIVE = re.compile(r"\b(within|inside|at|in)\b")


def _unparenthesised(text: str) -> str:
    """The unit with its parentheticals removed.

    A parenthetical annotates a unit; it does not change what the value
    counts. "acres (14 buildings, 838,000 sq ft)" counts acres.
    """
    return re.sub(r"\([^)]*\)", " ", str(text or ""))

# A count that is not of an estate that exists today.
#
# "hotels in pipeline" and "hotels opened" both pass the unit test and only
# one of them is an estate. A planned or targeted count promoted as current
# overstates the footprint, and the overstatement is invisible once it is a
# row. "opened" is kept deliberately - it is a count of things that exist.
NOT_YET_BUILT = ("pipeline", "planned", "under construction", "target",
                 "forecast", "expected", "by 20", "commitment", "ambition",
                 "to open", "proposed")


def _singular(word: str) -> str:
    """Enough stemming to match a plural unit, and no more."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("ches"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


# An ATM count is a site count only when it says it is OFF-PREMISE.
#
# absolute_counts.ADDITIVE_ONLY exists because most cash machines are inside
# a branch: they are equipment in a site already counted, and promoting a
# bank's total ATM estate as sites counts those branches twice. That is the
# Simmons Bank failure in the other direction - the shape model once turned
# 233 registered branches into 60 branches and 153 cash machines.
#
# But a standalone ATM in a supermarket, a forecourt or a station concourse
# IS a site, it needs its own connectivity, and the comment that forbids
# deriving one says plainly how it should arrive: "as an explicit count from
# the analyst or from research". No such count could ever arrive, because
# the unit gate rejects every ATM unit there is.
#
# So the label has to carry the distinction the unit cannot. A finding that
# says standalone, off-premise, remote or non-branch is a site count; a bare
# "ATMs: 300" stays out, which is the conservative half and the common one.
STANDALONE_HINTS = ("standalone", "stand-alone", "off-premise", "off premise",
                    "offsite", "off-site", "remote", "non-branch",
                    "outside branch", "free-standing", "freestanding")

ATM_UNITS = frozenset({"atm", "cashpoint", "cashmachine"})


def names_standalone_atms(label, unit) -> bool:
    """Is this an explicit count of ATMs that are their own site?"""
    text = f"{label or ''} {unit or ''}".lower()
    words = [w for w in "".join(
        ch if ch.isalnum() else " " for ch in text).split()]
    if not any(_singular(w) in ATM_UNITS for w in words):
        return False
    return any(hint in text for hint in STANDALONE_HINTS)


def is_premises_unit(unit) -> bool:
    """Does this unit count premises?

    Word by word, so "employees" cannot match "premise" by substring and
    "distribution centres" can match on "centre". Punctuation is split on
    because the real data says "agencies (points de vente)".
    """
    text = str(unit or "").lower()
    if any(hint in text for hint in NOT_YET_BUILT):
        return False
    words = [_singular(w) for w in "".join(
        ch if ch.isalpha() else " " for ch in text).split() if w]
    # An excluded asset anywhere in the unit decides it, so "substations"
    # cannot be rescued by a premises noun sitting beside it.
    if any(w in NOT_PREMISES for w in words):
        return False
    # A thing counted WITHIN something else is a part, not a place.
    #
    # BASF's Antwerp row is the case: 50 sites on a unit reading
    # "production facilities within Antwerp site", from a source saying
    # "auf ueber 6 km2 Flaeche sind dort rund 50 Produktionsbetriebe
    # angesiedelt" - about fifty production plants on ONE six-square-
    # kilometre site. Promoted as fifty Belgian premises, each priced at
    # the PLANT profile with its own access circuit and backup.
    #
    # Both premises nouns in that unit are real - "facilities" and "site" -
    # which is why the word test passes it. The disqualifying word is
    # "within", and it is in the unit rather than the label, so the label
    # rules cannot see it either. Ludwigshafen carries the same shape at
    # 200.
    if re.search(r"\b(within|inside)\b", text):
        return False
    # "X per Y" and "X/Y" are ratios, and a premises noun in the
    # DENOMINATOR makes it a measure per site rather than a count of
    # sites. BNP's "internet access lines per branch" is 1, and reading
    # the branch as the thing being counted put a single French branch
    # into the estate beside the 1,600 declared.
    numerator = re.split(r"\s+per\s+|/", text, maxsplit=1)[0]
    # The parenthetical cannot carry the unit, and what the value counts is
    # what stands before the first locative preposition. "desks at delivery
    # offices" counts desks; "stores in France" counts stores, because the
    # head noun is premises either way and only one of them is.
    head = _LOCATIVE.split(_unparenthesised(numerator), maxsplit=1)[0]
    words = [_singular(w) for w in "".join(
        ch if ch.isalpha() else " " for ch in head).split() if w]
    return any(w in PREMISES_UNITS for w in words)


# A monthly RATE, as opposed to a duration counted in months.
#
# The test was `"month" in unit`, which "36 months" satisfies. Domain 20 asks
# for customary contract lengths and returns exactly that - 24 of them in the
# sample - and they were kept out of the price bucket only by the product
# test sitting beside it. Widening that test without this one turns "standard
# leased-line contract term, 36 months" into a circuit costing 36 a month.
#
# A rate is per month: "usd/month", "eur per month", "MRC". A duration is a
# count of them.
_RATE_PER_MONTH = ("/month", "/mo", "per month", "a month", "monthly", "mrc",
                   "p/m", "pcm")


def is_monthly_rate_unit(unit) -> bool:
    text = str(unit or "").strip().lower()
    if not any(hint in text for hint in _RATE_PER_MONTH):
        return False
    # "36 months" has no per-unit sense at all; "eur/month/site" does.
    bare_duration = text.replace(".", "").strip() in (
        "month", "months", "mth", "mths")
    return not bare_duration


# An ANNUAL rate, as opposed to a duration counted in years. Same distinction
# _RATE_PER_MONTH draws, one period up.
_RATE_PER_YEAR = ("/year", "/yr", "per year", "per annum", "a year",
                  "annual rental", "annually", "p.a.", "/annum")


def rate_period(unit) -> str | None:
    """"MONTH", "YEAR", or None - the period this unit prices.

    The rate card is monthly, and a published price is not always. Three
    findings were discarded on this alone, two of them the best price
    evidence in the entire set:

        GB ETHERNET 1 Gbps EAD wholesale annual rental (Openreach)
            2,358 GBP/year
        GB ETHERNET 100 Mbps EAD Sensitive LA wholesale annual rental
            1,764 GBP/year

    Those are REGULATED WHOLESALE REFERENCE OFFERS - published, auditable,
    and exactly the kind of enterprise price that is otherwise locked inside
    NDAs. 2,358/12 is 196.50 against the 203 GBP already sourced for that
    cell independently, which is the closest corroboration this rate card
    has. They were thrown away because the unit said year.

    Year is reported rather than silently accepted: the caller divides, and
    does so where the value is written, so the conversion is visible at the
    point it changes a number.
    """
    text = str(unit or "").strip().lower()
    if is_monthly_rate_unit(unit):
        return "MONTH"
    if any(hint in text for hint in _RATE_PER_YEAR):
        # "36 months" has a sibling here: "3 years" is a term, not a rate.
        if text.replace(".", "").strip() in ("year", "years", "yr", "yrs"):
            return None
        return "YEAR"
    return None


#: What an annual rate is divided by to reach the monthly rate card.
MONTHS_PER_YEAR = 12


# A consumer line is not an enterprise circuit, and the brief says so.
#
# Domain 19's own reject clause opens "Consumer broadband pricing is not an
# enterprise circuit price. Say which market a price describes." The agent
# COMPLIES - it says which market, in the label - and the classifier never
# read the answer. Seven findings reached the rate card naming their own
# market as consumer or residential:
#
#   FR BROADBAND_PON  100 Mbps   EUR 26/month  "(consumer residential Ft...)"
#   ES BROADBAND_PON  500 Mbps   EUR 10/month  "(residential, Digi)"
#   SG BROADBAND_PON 1000 Mbps   SGD 49.90     "(StarHub 24-m residential)"
#
# EUR 10 a month is a household line. Priced against an enterprise estate it
# understates by an order of magnitude, and it did real damage beyond the
# estimate: the first measurement of how far seeded priors sit above sourced
# ones put the two most extreme ratios in the set - 0.20x and 0.26x - on two
# of these rows.
_CONSUMER_MARKET = re.compile(
    r"\bconsumer\b|\bresidential\b|\bdomestic\b|\bhousehold\b", re.I)


def names_a_consumer_market(label) -> str:
    """The word by which this label declares itself a consumer price."""
    m = _CONSUMER_MARKET.search(str(label or ""))
    return m.group(0) if m else ""


def product_in(label) -> str | None:
    """The connectivity product a finding's label names, if exactly one.

    WORD BOUNDARIES, and the reason is the data: "US BROADBAND 100 MBPS MRC -
    LIGHTYEAR DATASET MEDIAN" contains "DIA" inside "MEDIAN". A substring scan
    prices every median broadband figure in the sample as dedicated internet
    access.

    Anywhere in the label rather than the leading token, because research
    leads with the market: the agent returned "US DIA 100 Mbps MRC" and
    "US DIA 1 Gbps MRC" against a brief whose own example is "DIA 100Mbps
    MRC". Four real market medians were declined on word order.

    Exactly one, or None. "DIA/MPLS blended rate" names two products and a
    blended rate is neither of them.
    """
    words = set("".join(
        ch if (ch.isalnum() or ch == "_") else " "
        for ch in str(label or "").upper()).split())
    found = {p for p in PRODUCTS if p in words}
    return next(iter(found)) if len(found) == 1 else None


#: Label wording that marks a finding as a CHANGE rather than a COUNT.
#:
#: The gate that lets archetype_of read past the leading token. Research
#: writes both "FR production sites (PLANT-type)" and "DE net PLANT site
#: closures announced 2025", and only the first is an estate. Without this,
#: reading an archetype from anywhere in the label admits 45 findings across
#: the sample set of which most are movements: "Net store change - Spain
#: (ES) FY2025" at MINUS 62, "Total branch closings since January 2020" at
#: 91, a planned DC at London Gateway, and "Kelsterbach DC building -
#: sold/exited, lease expiry" at 2025 - a year read as a site count.
#:
#: Matched on the label because that is where research says what it counted.
#: The unit gate cannot help: these say "sites", "sites opening", "branches
#: closed", and NOT_YET_BUILT keeps "opened" deliberately as a count of
#: things that exist, which is right for a unit and wrong for these labels.
#: Not "consolidation": Iberdrola's Glasgow DC is labelled
#: "post-consolidation" and is the site that survived one, while its
#: Cathcart DC is "pre-consolidation, decommissioned 2017" and is not a
#: site at all. The word marks the event, and only the qualifier says
#: which side of it the row sits on - so the end states are matched
#: instead.
NOT_A_COUNT = re.compile(
    r"\b(net|new|closur\w*|closing\w*|closed|open(?:ing\w*|ed)|planned"
    r"|proposed|at[-\s]risk|relocat\w*|exit\w*|expiry|decommission\w*"
    r"|cessation|ceased|completed|reduction|movement|transferred|proxy"
    r"|divest\w*|pipeline"
    # A vendor's contract scope is not an estate. BNP's "retail branch
    # sites covered by OBS SD-WAN deployment" is 1,800 from a 2021 Orange
    # press release; BNP's own registration document says 1,474 French
    # branches and it is closing about 500 more by 2030. Promoting the
    # deployment count raised the estate above both the declaration and
    # the company's own figure.
    r"|covered|deployment|rollout|contract)\b",
    re.IGNORECASE)

#: A mention that denies the archetype rather than counting it.
#:
#: Shell's "R&D centre - Germany (smaller specialised centre, no DC
#: co-location)" names DC only to say there is not one. Reading an archetype
#: from anywhere in a label makes a negated mention look like a finding.
_NEGATED = ("NO", "NOT", "WITHOUT", "NEITHER", "ZERO")


#: Multi-country scopes a price label can name while its country field
#: carries a single country code.
#:
#: Matched as whole words so "EU" does not fire on "EUR/month" and "APAC"
#: does not fire inside a vendor name. "Benelux" and "Nordics" are here for
#: the same reason as the continents: a Benelux average is three markets.
_REGION_RE = re.compile(
    r"\b(western|eastern|southern|northern|central)\s+europe\b"
    r"|\b(europe|emea|apac|latam|benelux|nordics?|iberia|dach|anz|mena)\b"
    r"|\bnorth\s+america\b|\blatin\s+america\b|\bmiddle\s+east\b"
    r"|\bsouth[\- ]east\s+asia\b|\basia[\- ]pacific\b"
    r"|\beuropean\s+(average|union)\b|\bworldwide\b|\bglobal\s+average\b",
    re.IGNORECASE)


def names_a_region(label) -> bool:
    """Does this label state a multi-country scope?"""
    return bool(_REGION_RE.search(str(label or "")))


# Premises nouns that are bound to one archetype, so a label naming one
# while the row is routed elsewhere is stating two different things.
#
# Deliberately TINY. A general noun-to-archetype map would be wrong more
# often than right - Fraport's "CAMPUS - Frankfurt Airport site" names an
# airport and is correctly a campus, and Toyota's R&D sites are correctly
# LARGE_OFFICE. Only nouns that cannot reasonably be another archetype
# belong here, and each earned its place from a row that was promoted wrong:
#
#   fraport DE/CAMPUS   "two data centers with a third as a back-up"
#                       promoted as 3 campuses, beside a declared DE/DC 3
#   nhs-england GB/LARGE_OFFICE  "Hospital sites (LARGE_OFFICE archetype)"
#                       1,140 hospitals belonging to 207 separate trusts,
#                       promoted into an office archetype whose own estate
#                       is one building in Leeds
_BOUND_NOUNS = (
    (re.compile(r"\bdata\s*cent(er|re)s?\b", re.I), {"DC"}),
    (re.compile(r"\bhospitals?\b", re.I), {"CAMPUS", "REMOTE_SITE"}),
)


def contradicts_archetype(label, archetype: str) -> str:
    """The premises noun this label names, when it cannot be that archetype.

    Returns the offending noun, or "" when the label and the archetype agree
    - which is the common case and the only one that promotes.
    """
    for pattern, allowed in _BOUND_NOUNS:
        m = pattern.search(str(label or ""))
        if m and archetype not in allowed:
            return m.group(0)
    return ""


# Two or more places joined into one figure.
#
# Woolworths is the case: "total store network comprised 1,729 retail stores
# across Australia and New Zealand", promoted as 1,729 Australian stores.
# BASF carried the same shape with a North American total read as a US one.
# A footprint row is keyed on ONE country, so a figure spanning two cannot
# be that row's count whichever country it is filed under.
#
# The region vocabulary is already written for prices - names_a_region - and
# this adds the conjoined form a region name does not cover.
_COUNTRY_WORD = (
    r"australia|new\s+zealand|germany|france|spain|italy|belgium|netherlands"
    r"|portugal|poland|austria|switzerland|sweden|norway|denmark|finland"
    r"|ireland|canada|mexico|brazil|china|japan|india|singapore|turkey"
    r"|greece|romania|bulgaria|czechia|hungary|peru|chile|argentina"
    r"|united\s+states|usa|uk|united\s+kingdom|britain|luxembourg")
_TWO_COUNTRIES = re.compile(
    rf"\b({_COUNTRY_WORD})\b\s*(?:,|and|&|\+|/)\s*\b({_COUNTRY_WORD})\b",
    re.IGNORECASE)


def spans_two_countries(label) -> bool:
    """Does this label state a figure covering more than one country?"""
    return bool(_TWO_COUNTRIES.search(str(label or "")))


# Premises somebody else operates, or holds without control.
#
# The test for a footprint row is not who owns the asset, it is who buys the
# access circuit. Three labels state the answer themselves:
#
#   bayer US/WAREHOUSE  "GXO-operated Crop Science warehouse sites (US, 3PL)"
#                       a 3PL warehouse is the provider's building on the
#                       provider's network
#   aena  MX/TERMINAL   "airports in Mexico (MX) via GAP minority stake"
#                       6.55% of GAP - "minority financial stake only, not
#                       operator", as Aena's own note says
#   ups   US/STORE      franchised UPS Store locations, 5,603 of them
#
# Deliberately NOT including "operated by" on its own. "airports operated by
# Fraport Greece" is the subject's own estate and the classifier has no way
# to know whose name follows, so that phrase would decline good rows. Each
# term here is one that cannot describe premises the subject operates.
_NOT_THEIR_PREMISES = re.compile(
    r"\b3pl\b|\bthird[\s-]party\b"
    r"|\bminority\s+(stake|shareholding|interest|holding)"
    r"|\bfranchis(e|ed|ee|es|ing)\b",
    re.IGNORECASE)


def not_their_premises(label) -> str:
    """The phrase saying these premises are somebody else's, if it is there."""
    m = _NOT_THEIR_PREMISES.search(str(label or ""))
    return m.group(0) if m else ""


def archetypes_named(label) -> list:
    """Every archetype this label names, in order, without repeats."""
    out = []
    for word in re.split(r"[^A-Za-z_]+", str(label or "").upper()):
        if word in ARCHETYPES and word not in out:
            out.append(word)
    return out


def names_a_change(label) -> bool:
    """Does this label describe a movement rather than an estate?

    A NEGATED movement is not one. Volkswagen's "ES active PLANT count
    (SEAT/CUPRA Martorell + Pamplona) - no closures imminent" is a count
    of two plants that says nothing is closing, and reading the word
    "closures" alone threw away the figure for the reassurance attached
    to it.
    """
    text = str(label or "")
    for m in NOT_A_COUNT.finditer(text):
        before = re.split(r"[^A-Za-z_]+", text[:m.start()].upper())
        before = [w for w in before if w]
        if before and before[-1] in _NEGATED:
            continue
        return True
    return False


def _negated(label, archetype: str) -> bool:
    """Is the archetype named only to deny it?"""
    words = [w for w in re.split(r"[^A-Za-z_]+", str(label or "").upper()) if w]
    return any(words[i - 1] in _NEGATED
               for i, w in enumerate(words) if w == archetype and i)


def archetype_of(label) -> str:
    """The archetype a finding's label names.

    Its leading token, unless the label names exactly one archetype
    somewhere else - "FR production sites (PLANT-type)" is PLANT, and
    reading only the leading token made it "FR" and lost Nestle's French
    plant count entirely.

    Falls back to the leading token when the label names SEVERAL, which
    keeps the existing refusal of "WAREHOUSE/BRANCH - ..." and
    "LARGE_OFFICE+PLANT+BRANCH - ...": those name two or three archetypes
    and there is nothing to key a single row on. The fallback is not in
    ARCHETYPES for such a label, so _classify declines it as before.

    The one place that decides this, because _classify matching on one thing
    and promote() storing another is how a 56-character description ended up
    being written into archetype varchar(48).
    """
    head = (str(label or "").strip().upper().split() or [""])[0]
    if head in ARCHETYPES:
        return head
    named = archetypes_named(label)
    return named[0] if len(named) == 1 else head


def _classify(q: dict) -> str:
    """footprint | price | unclassified.

    Deliberately conservative: a quantity is only routed somewhere if it
    plainly carries what that destination needs. Everything else is reported
    as unclassified rather than guessed at, because a wrong promotion is
    silent and a declined one is visible.
    """
    label = str(q.get("label") or "").strip().upper()
    unit = str(q.get("unit") or "").strip().lower()
    country = str(q.get("country") or "").strip().upper()
    # Parsed, not type-checked. `value` became a string in 4.104.0 so that a
    # source stating "2 halls, 2.75 MW" could be kept as a qualitative finding
    # instead of failing the schema - and this isinstance check then classified
    # every quantity as unclassified, so nothing at all could be promoted. The
    # two changes were three releases apart and nothing connected them.
    # A product override carries a product name, so a value that is not a
    # number is not automatically unusable here.
    if triangulate.parse_value(q.get("value")) is None and \
            str(q.get("value") or "").strip().upper() not in PRODUCTS:
        return "unclassified"
    # The leading token, the way the price branch below already reads a
    # product name - not the whole label.
    #
    # `label in ARCHETYPES` demanded the label be nothing but the archetype,
    # and the research prompt asks for the opposite: the archetype block
    # tells the agent to "say in `finding` which mapping you chose and why",
    # so a well-behaved agent returns "SERVICE_POINT - Iberdrola customer
    # service and sales points". That is the convention, and it fell through
    # to unclassified every time.
    #
    # The sample set is the evidence. Iberdrola's agent described its
    # mappings and produced 103 findings, 0 of them classified; Unilever's
    # happened to emit bare labels - PLANT, WAREHOUSE, LARGE_OFFICE - and
    # promoted 7 rows. The classifier was working only when the agent
    # omitted what it had been asked for.
    #
    # Still conservative, and deliberately: "WAREHOUSE/BRANCH - ..." names
    # two archetypes and stays unclassified, and a finding with no country or
    # a multi-country one - "FR+BE" - stays unclassified too, because a
    # footprint row is keyed on a country and there is nothing to key it on.
    # ("NETWORK_SITE - ... substations" was the example here and it now
    # classifies: see PREMISES_UNITS.) And classification only
    # decides what is *offered*; promotion.candidates proposes and a named
    # person disposes, so widening this cannot put a number into an estimate
    # on its own.
    head = archetype_of(label)
    # A movement is not an estate, and a denial is not a finding. Both are
    # read off the label, which is the only place that distinguishes "FR
    # production sites (PLANT-type)" from "DE net PLANT site closures
    # announced 2025" - the units are "sites" either way.
    if head in ARCHETYPES and (names_a_change(label) or _negated(label, head)):
        return "unclassified"
    # A figure that spans two countries, or a region, cannot be a count for
    # the one country this row is keyed on. names_a_region already guards
    # prices this way; the same scope statement disqualifies a count.
    if head in ARCHETYPES and (spans_two_countries(label)
                               or names_a_region(label)):
        return "unclassified"
    # The label names a premises type the routed archetype cannot be. Left
    # unclassified rather than re-routed: which archetype it belongs to is a
    # judgement, and the label saying "data centres" while the row says
    # CAMPUS is enough to know this row is not it.
    if head in ARCHETYPES and contradicts_archetype(label, head):
        return "unclassified"
    # Premises the label itself says belong to somebody else.
    if head in ARCHETYPES and not_their_premises(label):
        return "unclassified"
    if head in ARCHETYPES and len(country) == 2 and (
            is_premises_unit(unit)
            or (head == "ATM" and names_standalone_atms(label, unit))):
        return "footprint"
    # How a site type is built rather than how many there are. Country-
    # independent, because an architecture standard usually is.
    if archetype_field(q):
        return "archetype"
    # The disclosed cost line the ANCHOR method multiplies by an addressable
    # share. Checked before the price branch, because "TELECOM_SPEND ...
    # EUR/year" is a total and not a unit rate.
    if anchor_candidate(q):
        return "anchor"
    # A monthly rate for a named product in a named country.
    #
    # Both halves were too narrow and failed on real findings. The product had
    # to be the leading token, so "US DIA 1 Gbps MRC" was declined while "DIA
    # 1 Gbps MRC" passed - word order. And the unit test accepted any string
    # containing "month", which a contract term of "36 months" does.
    priced = product_in(label)
    # A regional average is not a country price, whatever the country says.
    #
    # The research brief forbids `country: "EMEA"` - "a region such as
    # 'North America' or 'EMEA' cannot be priced" - and the country field is
    # the only thing it checks. Asking domain 19 for European prices returned
    # two findings tagged DE: "MPLS 100 Mbps MRC - Western Europe / Benelux"
    # at EUR 1,000, and "100 Mbps MRC - Western Europe business (avg)" at USD
    # 148 PPP. Both passed rule (3) by putting a country code on a regional
    # average, which is the rule's own failure mode: it polices the field and
    # the label is where the scope is actually stated.
    #
    # Declined rather than dropped - the label still reaches a reader through
    # unclassified, and a regional benchmark is worth seeing. It is just not
    # a German price.
    # The brief rejects consumer pricing and the label says which market it
    # is. Declined rather than dropped: a consumer tariff is real evidence
    # about a market, it is just not a price for an enterprise circuit.
    if priced and names_a_consumer_market(label):
        return "unclassified"
    if priced and len(country) == 2 and rate_period(unit):
        if names_a_region(label):
            return "unclassified"
        return "price"
    return "unclassified"


def candidates(session, case_id: str) -> dict:
    """What research has produced that the estimate could consume."""
    found = _quantities_for_case(session, case_id)
    # Every target _classify can return needs a bucket. It gained "archetype"
    # and "anchor" and this dict did not, so buckets[target] raised KeyError
    # the moment research produced one - the classification and the promote
    # branch both existed and nothing could reach them, because the list an
    # analyst selects from was never built.
    buckets: dict[str, list] = {t: [] for t in
                                ("footprint", "price", "archetype", "anchor",
                                 "unclassified")}
    for entry in found:
        entry["target"] = _classify(entry["quantity"])
        buckets.setdefault(entry["target"], []).append(entry)

    promoted = session.execute(
        select(db.evidenced_footprint).where(
            db.evidenced_footprint.c.case_id == case_id)).all()
    promoted_arch = session.execute(
        select(db.evidenced_archetype).where(
            db.evidenced_archetype.c.case_id == case_id)).all()
    promoted_anchor = session.execute(
        select(db.evidenced_anchor).where(
            db.evidenced_anchor.c.case_id == case_id)).all()
    return {
        "case_id": case_id,
        "footprint_candidates": buckets["footprint"],
        "price_candidates": buckets["price"],
        # How a site type is built: product pair, dual-access rate, bandwidth,
        # users per site. These reach the simulation's topology rather than its
        # counts.
        "archetype_candidates": buckets["archetype"],
        # A disclosed annual cost line, for the ANCHOR estimation method.
        "anchor_candidates": buckets["anchor"],
        "unclassified": buckets["unclassified"],
        "already_promoted_footprint": [dict(r._mapping) for r in promoted],
        "already_promoted_archetype": [dict(r._mapping) for r in promoted_arch],
        "already_promoted_anchor": [dict(r._mapping) for r in promoted_anchor],
        "note": (
            "A candidate is a researched number the estimate could use. "
            "Nothing here is in the estimate until a named person promotes it. "
            "Unclassified findings are not rejected - they are simply not in a "
            "shape this model consumes, and stay as evidence on the domain."),
    }



def compare_to_benchmark(session, *, country: str, product: str, value: float,
                         bandwidth_mbps: int | None = None,
                         policy=None) -> dict:
    """How far a researched price sits from the approved benchmark it would
    displace.

    Inside the approved low/high band is agreement - a benchmark is a range,
    and a figure within it corroborates rather than contradicts. Outside, the
    divergence is measured against the nearest edge rather than the midpoint,
    because the question a steward is answering is "how far outside the range
    we approved is this", not "how far from its centre".

    Returns a verdict either way. NO_BENCHMARK is not silence: a researched
    price for a country the model cannot currently price at all is the most
    valuable kind, and saying so is different from saying nothing was found.
    """
    # Matched on the tier, not on country and product alone. Since 4.53.0 a
    # product has several bandwidth bands - US DIA is 480/920/1340 base at
    # 100/500/1000 Mbps - and this used to take .first() with no ordering, so
    # a 100 Mbps price could be judged against the 1 Gbps band, and which
    # band it got was not even stable between runs. A corroborating price
    # then read as materially divergent, or the reverse.
    rows = session.execute(
        select(db.unit_cost_prior).where(
            db.unit_cost_prior.c.country == country,
            db.unit_cost_prior.c.product == product,
            db.unit_cost_prior.c.approved.is_(True))).all()
    if not rows:
        return {"verdict": "NO_BENCHMARK", "material": False,
                "note": (f"no approved benchmark for {country} {product} at any "
                         f"bandwidth, so this is new coverage rather than a "
                         f"correction - nothing to contradict")}

    row = next((r for r in rows if r.bandwidth_mbps == bandwidth_mbps), None)
    if row is None:
        tiers = sorted(r.bandwidth_mbps for r in rows if r.bandwidth_mbps)
        return {
            "verdict": "NO_BENCHMARK_AT_BANDWIDTH", "material": False,
            "observed_bandwidth_mbps": bandwidth_mbps,
            "benchmarked_bandwidths": tiers,
            "note": (f"{country} {product} is benchmarked at "
                     f"{tiers or 'no stated'} Mbps but not at "
                     f"{bandwidth_mbps or 'an unstated bandwidth'}. Comparing "
                     f"across tiers would be a comparison of different "
                     f"products, so this is reported rather than judged - a "
                     f"price at a tier the model cannot currently price is "
                     f"new coverage.")}

    low, base, high = float(row.low), float(row.base), float(row.high)
    if low <= value <= high:
        return {"verdict": "WITHIN_BAND", "material": False,
                "benchmark": {"low": low, "base": base, "high": high},
                "note": (f"{value} falls inside the approved band "
                         f"{low}-{high}; the research corroborates the "
                         f"benchmark")}

    edge = low if value < low else high
    # Guard a zero edge rather than dividing by it: a benchmark of 0 is a data
    # error, and reporting it as such beats a ZeroDivisionError inside a
    # promotion the analyst thought had succeeded.
    if edge == 0:
        return {"verdict": "BENCHMARK_UNUSABLE", "material": True,
                "benchmark": {"low": low, "base": base, "high": high},
                "note": (f"the approved band for {country} {product} has a "
                         f"zero edge, so divergence cannot be computed - the "
                         f"benchmark itself needs attention")}

    share = abs(value - edge) / abs(edge)
    threshold = float(policy.material_divergence_share) if policy else 0.25
    direction = "below" if value < low else "above"
    return {
        "verdict": "OUTSIDE_BAND",
        "material": share >= threshold,
        "benchmark": {"low": low, "base": base, "high": high},
        "divergence_share": round(share, 4),
        "direction": direction,
        "threshold": threshold,
        "note": (f"{value} is {share:.0%} {direction} the approved band "
                 f"{low}-{high}"
                 + (f", beyond the {threshold:.0%} materiality threshold - "
                    f"public research and the governed benchmark disagree "
                    f"materially and a steward should adjudicate before "
                    f"approving either"
                    if share >= threshold else
                    f", within the {threshold:.0%} materiality threshold")),
    }


def _one_row_per_pair(entries: list, *, accept_conflicts: bool = False) -> tuple:
    """One footprint row per (country, archetype): the largest PROMOTABLE one.

    evidenced_footprint holds one row per pair - promote deletes and
    reinserts - so when several candidates share a pair, write order decided
    which survived. Simmons Bank's locations domain returned a 222-branch
    national total AND a six-state breakdown of the same network, all typed
    STORE, and the estate kept KANSAS'S 4.

    THE LARGEST, NOT THE SUM, and the sample set is why. Of 25 pairs with
    several rows across 26 companies, the largest is the right answer in
    every one:

        simmons-bank  US/STORE   [4,19,45,47,57,65,222]  222, not 459
        dhl           DE/WHSE    [38,46,81]               81, not 165
        lufthansa     DE/OFFICE  [3,6,10]                 10, not 19
        tesco         GB/STORE   [45,806,3829]          3829, not 4680
        basf          DE/PLANT   [1,54]                   54, not 55

    Research returns a total alongside illustrative subsets - a regional
    breakdown, a named example, a partial measure like Tesco's "store Wi-Fi
    site count at the time of the BT deal". It does not return a disjoint
    partition with no total, and summing one of these double-counts the same
    sites under two descriptions.

    LARGEST AMONG THOSE THE CONFLICT GATE WILL ACCEPT, because this used to
    run before that gate and the two together could lose a usable row.
    Nestle's French plants: research returned a conflicted 13-18 band and a
    clean single-source 12. The 18 won the pair, the gate below then refused
    it on a 38% spread, and the 12 had already been discarded as superseded
    - so the pair ended up empty and the declared 28 stood unchallenged, an
    apportionment of a group total that every source which looked came in
    below.

    Falling back to the largest overall when nothing is promotable, so a
    wholly conflicted pair still reaches the gate and is still refused out
    loud rather than vanishing here without a record.

    What is displaced is returned, not dropped: the alternatives research
    found are part of what it found.
    """
    import collections

    def promotable(e) -> bool:
        return accept_conflicts or not (e.get("band") or {}).get(
            "review_required")

    by_pair, out, superseded = collections.defaultdict(list), [], []
    for e in entries:
        q = e["quantity"]
        if _classify(q) != "footprint":
            out.append(e)
            continue
        by_pair[(str(q.get("country")).upper(),
                 archetype_of(q.get("label")))].append(e)

    for (country, archetype), group in sorted(by_pair.items()):
        group.sort(key=lambda e: _sites_from(e["quantity"]) or 0)
        usable = [e for e in group if promotable(e)]
        winner = (usable or group)[-1]
        out.append(winner)
        if len(group) == 1:
            continue
        kept = _sites_from(winner["quantity"]) or 0
        rest = [(_sites_from(e["quantity"]) or 0)
                for e in group if e is not winner]
        superseded.append({
            "country": country, "archetype": archetype,
            "kept": kept, "also_found": sorted(rest),
            # Larger figures passed over because the gate would refuse them.
            # Worth naming: the pair is carrying a smaller number than
            # research's highest, and the reason is a conflict rather than
            # a judgement that the bigger figure was wrong.
            "larger_but_conflicted": sorted(
                v for v, e in ((_sites_from(e["quantity"]) or 0, e)
                               for e in group)
                if e is not winner and not promotable(e) and v > kept),
            # A genuine disjoint partition - several regions and no total -
            # is the one shape where the largest undercounts. Nothing in the
            # sample looks like it (the closest is 1.07x), so it is reported
            # rather than handled: a rule invented for a case that has not
            # happened would be guessing twice.
            "parts_exceed_kept": sum(rest) > kept * 1.5,
        })
    return out, superseded


def promote(session, *, case_id: str, candidate_ids: list[str],
            promoted_by: str, divergence_policy=None,
            accept_conflicts: bool = False) -> dict:
    """Move selected candidates into the numbers the estimate reads.

    Idempotent per (case, country, archetype) for footprint and per
    (country, product, price_year) for prices: promoting the same finding
    twice replaces rather than duplicates, so a corrected re-run does not
    leave the old figure sitting alongside the new one.
    """
    if not promoted_by:
        raise NotPromotable("promotion must be attributed to a named person")

    wanted = set(candidate_ids)
    entries = [e for e in _quantities_for_case(session, case_id)
               if e["candidate_id"] in wanted]
    missing = wanted - {e["candidate_id"] for e in entries}
    if missing:
        raise NotPromotable(f"no such candidate(s): {sorted(missing)}")

    now = datetime.now(timezone.utc)
    promoted_footprint, proposed_prices, declined = [], [], []
    promoted_archetype, promoted_anchor = [], []
    entries, superseded = _one_row_per_pair(
        entries, accept_conflicts=accept_conflicts)

    for e in entries:
        q, target = e["quantity"], _classify(e["quantity"])
        band = e.get("band") or {}
        if band.get("review_required") and not accept_conflicts:
            # A quantity whose sources materially disagree is not ready to be
            # a number in an estimate. Promoting the midpoint would resolve
            # the disagreement by arithmetic and record no trace of it, which
            # is the outcome conflict retention exists to prevent. The
            # promotion is refused with the spread named; an analyst who has
            # looked and decided can pass accept_conflicts.
            # Name the finding and the reason it actually failed.
            #
            # This said "sources disagree by {spread}" whatever the flag
            # was, and review_required fires on three of them. Nestle's
            # German plant count is a UNIT_MISMATCH between two sources
            # both stating 12, so the refusal read "sources disagree by 0%
            # (12 to 12)" - a sentence that invites an analyst to dismiss
            # it as noise. It also named no label and no country, so a
            # reader could not tell which of eleven findings was refused.
            why = {
                "MATERIAL_SPREAD": (
                    f"sources disagree by {band.get('spread_share', 0):.0%} "
                    f"({band.get('low')} to {band.get('high')})"),
                "UNIT_MISMATCH": "sources state this in units that disagree",
                "NEWEST_DIVERGES": ("the newest source diverges from the "
                                    "others"),
            }
            fired = [f for f in (band.get("flags") or []) if f in why]
            declined.append({
                "candidate_id": e["candidate_id"],
                "label": q.get("label"), "country": q.get("country"),
                "flags": fired,
                "reason": (f"{'; '.join(why[f] for f in fired) or 'the band is marked for review'}"
                           f", and this has not been reviewed. Look at it and "
                           f"promote with accept_conflicts, or research the "
                           f"domain again.")})
            continue
        if target == "anchor":
            # A disclosed cost line, for the ANCHOR method. Promoted as
            # evidence rather than retyped as an assertion, which is the
            # difference between an anchor that reports EVIDENCED_PUBLIC and
            # one that caps the whole estimate under 0.6A.
            label = str(q["label"]).upper()
            row_id = f"{case_id}-{label}"
            session.execute(delete(db.evidenced_anchor).where(
                db.evidenced_anchor.c.id == row_id))
            session.execute(insert(db.evidenced_anchor).values(
                id=row_id, case_id=case_id, label=label,
                value=str(triangulate.parse_value(q["value"])),
                currency=(q.get("currency")
                          or str(q.get("unit") or "").split("/")[0].strip()
                          or None),
                as_of=str(q.get("as_of") or ""), domain_no=e["domain_no"],
                agent_run_id=e["agent_run_id"], source_urls=e["sources"],
                reliability_grade=(e.get("reliability") or {}).get("grade"),
                promoted_by=promoted_by, promoted_at=now))
            promoted_anchor.append({"label": label, "value": q["value"],
                                    "domain_no": e["domain_no"]})
            continue

        if target == "archetype":
            # How a site type is built, for this case only. Never written to
            # reference.archetype_prior: one client's estate is not a
            # benchmark, and establishing this for one case must not retune
            # every other.
            arch_name = str(q["label"]).upper()
            field = archetype_field(q)
            raw = str(q["value"]).strip()
            if field in ("primary_product", "backup_product"):
                raw = raw.upper()
            row_id = f"{case_id}-{arch_name}-{field}"
            session.execute(delete(db.evidenced_archetype).where(
                db.evidenced_archetype.c.id == row_id))
            session.execute(insert(db.evidenced_archetype).values(
                id=row_id, case_id=case_id, archetype=arch_name, field=field,
                value=raw, origin="PROMOTED_RESEARCH",
                domain_no=e["domain_no"], agent_run_id=e["agent_run_id"],
                source_urls=e["sources"],
                reliability_grade=(e.get("reliability") or {}).get("grade"),
                recorded_by=promoted_by, recorded_at=now))
            promoted_archetype.append({"archetype": arch_name, "field": field,
                                       "value": raw,
                                       "domain_no": e["domain_no"]})
            continue

        if target == "footprint":
            country = str(q["country"]).upper()
            # The leading token, the same one _classify matched on - not the
            # whole label.
            #
            # These were the same string for as long as the classifier only
            # accepted a bare archetype name. Widening it to accept the
            # described form the research prompt asks for - "SERVICE_POINT -
            # Iberdrola customer service and sales points" - made them
            # different, and this wrote 56 characters into archetype
            # varchar(48): every promotion 500'd with
            # StringDataRightTruncation.
            #
            # Length is the lesser half. The simulation keys archetypes by
            # name, so storing the description would have produced a
            # footprint row for an archetype that does not exist - priced at
            # the DEFAULT prior, silently, with the estate looking enumerated.
            # A column being too short is the only reason that was ever
            # visible.
            archetype = archetype_of(q["label"])
            session.execute(delete(db.evidenced_footprint).where(
                db.evidenced_footprint.c.case_id == case_id,
                db.evidenced_footprint.c.country == country,
                db.evidenced_footprint.c.archetype == archetype))
            session.execute(insert(db.evidenced_footprint).values(
                id=str(uuid.uuid4()), case_id=case_id, country=country,
                # Parsed the way _classify parsed it, not int().
                #
                # The classifier admits a quantity when
                # triangulate.parse_value() can read it, and that function
                # deliberately reads a source's wording - "1,250", "2.75",
                # "3 million", "~10". int() reads none of those. So a
                # candidate this module offered, and a named person chose to
                # promote, took the whole request down with
                #
                #   ValueError: invalid literal for int() with base 10: '~10'
                #
                # and the caller saw a 500 with no indication which finding
                # caused it. Lufthansa lost all seven of its footprint rows
                # that way and was priced from public disclosure alone.
                #
                # The fix for exactly this already existed two lines below,
                # on the band columns, with a comment saying "crashing on a
                # decimal string is not [right]". The site count never got
                # it. A matcher and a writer disagreeing about what a field
                # means is the same defect P-15 was, one field across.
                archetype=archetype, sites=_sites_from(q),
                as_of=str(q.get("as_of") or ""), domain_no=e["domain_no"],
                # The band is stored as strings, and a price band's low is
                # "477.5" - int() on that raises rather than truncating. These
                # columns hold site counts, so rounding is right and crashing
                # on a decimal string is not.
                band_low=_as_int(band.get("low")),
                band_high=_as_int(band.get("high")),
                source_count=band.get("candidate_count"),
                agent_run_id=e["agent_run_id"],
                source_urls=e["sources"], promoted_by=promoted_by,
                promoted_at=now))
            promoted_footprint.append(
                {"country": country, "archetype": archetype,
                 # Same reading as the row that was just written, so the
                 # receipt cannot disagree with the record it describes.
                 "sites": _sites_from(q), "as_of": q.get("as_of")})
        elif target == "price":
            country = str(q["country"]).upper()
            # The SAME resolver the classifier used, not the leading token.
            #
            # _classify matching one thing and promote() storing another is a
            # defect this module has already had once, with the archetype:
            # the classifier was widened to the leading token while promote()
            # stored the whole label, and 56 characters went into a
            # varchar(48). Widening the classifier to find a product anywhere
            # in the label while this still took `split()[0]` would write
            # "US" as the product of "US DIA 1 Gbps MRC" - a rate card row for
            # a product that does not exist, which no circuit would ever
            # match and nothing would report.
            product = product_in(q["label"])
            _parsed = triangulate.parse_value(q["value"])
            if _parsed is None:
                declined.append({
                    "candidate_id": e["candidate_id"],
                    # One unbroken phrase per idea. Wrapping split "stated in
                    # words" across two literals, so a test asserting on it
                    # failed even though the message was correct - and the
                    # failure named the assertion rather than the line break.
                    "reason": (f"{q.get('value')!r} is a finding "
                               f"stated in words, not a number, "
                               f"so it cannot be promoted to a priced "
                               f"input.")})
                continue
            value = float(_parsed)
            # An annual rate becomes a monthly one here, where it changes a
            # number, rather than in the classifier where it would only
            # change a label. See rate_period.
            period = rate_period(q.get("unit"))
            if period == "YEAR":
                value = value / MONTHS_PER_YEAR
            # A single observed price is a point, not a band. Recorded as the
            # base with the band left equal to it and approved=False, so a
            # steward has to widen it deliberately rather than the system
            # inventing a spread it has no evidence for.
            # Compare against the benchmark this would displace, before
            # writing. A researched price that contradicts a governed value is
            # the most informative outcome here and used to be the least
            # visible one: the row landed unapproved with no comparison
            # recorded, so a steward saw a number rather than a disagreement.
            # A price with no bandwidth is a valid observation and not a
            # usable prior: match_prior requires a tier, so a null-bandwidth
            # row would sit in unit_cost_prior pricing nothing while counting
            # as coverage. That is the exact condition migration v17 deletes
            # pre-split rows for, and writing it here anyway - which the first
            # version of this code did, with a comment calling the null
            # "visible" - reintroduced it two releases later. The observation
            # keeps its home in the benchmark vault; only a priceable row
            # reaches the reference table.
            mbps = q.get("bandwidth_mbps")
            if not mbps:
                declined.append({
                    "candidate_id": e["candidate_id"],
                    "reason": (f"{country} {product} price of {value} carries no "
                               f"bandwidth. A circuit rate without a tier cannot "
                               f"be matched to any circuit, so it is not "
                               f"promotable to a prior - re-run the domain, or "
                               f"set the tier on the observation first.")})
                continue
            cmp = compare_to_benchmark(session, country=country,
                                       product=product, value=value,
                                       bandwidth_mbps=int(mbps),
                                       policy=divergence_policy)
            row_id = f"{country}-{product}-{int(mbps)}-researched"
            session.execute(delete(db.unit_cost_prior).where(
                db.unit_cost_prior.c.id == row_id))
            session.execute(insert(db.unit_cost_prior).values(
                id=row_id, country=country, product=product, cost_layer="L0",
                bandwidth_mbps=int(mbps),
                # The two dimensions the rate card is keyed on. Without them a
                # promoted price is reachable only through the legacy fallback
                # - the same defect the benchmark path had until 4.177, in the
                # other writer of this table.
                service_class=access.LEGACY_PRODUCT.get(
                    product, (None, None))[0],
                access_technology=access.LEGACY_PRODUCT.get(
                    product, (None, None))[1],
                # Grade C: a credible market benchmark requiring adjustment.
                # An agent found a published figure and the claim was checked
                # against the page it came from, which is worth more than an
                # assumption and less than a transaction. Without this it
                # inherited the column default of E and a researched price
                # looked exactly like a seeded guess.
                evidence_grade="C", price_basis="PROMOTED",
                low=value, base=value, high=value,
                # The currency the source quoted, not USD. Every promoted price
                # was stamped USD regardless of the country researched, so a
                # EUR tariff found in France entered the rate card as dollars -
                # a 7-8% error before anything else happened, and invisible
                # because the column agreed with every other row.
                currency=(q.get("currency") or "USD"),
                price_year=2026, approved=False,
                source_agent_run_id=e["agent_run_id"],
                source_note=(f"researched from domain {e['domain_no']} by "
                             f"{promoted_by}; as_of {q.get('as_of') or 'unstated'}; "
                             f"single observation, band not yet set. "
                             + (f"source quoted {_parsed} per YEAR in "
                                f"{q.get('unit')!r}, divided by "
                                f"{MONTHS_PER_YEAR} to reach this monthly "
                                f"rate. " if period == "YEAR" else "")
                             + f"vs benchmark: {cmp['verdict']} - {cmp['note']}")))
            proposed_prices.append(
                {"country": country, "product": product, "base": value,
                 "approved": False, "benchmark_comparison": cmp})
        else:
            declined.append({"candidate_id": e["candidate_id"],
                             "reason": "not in a shape the estimate consumes"})
    session.commit()

    material = [p for p in proposed_prices
                if (p.get("benchmark_comparison") or {}).get("material")]
    return {
        "promoted_anchor": promoted_anchor,
        "promoted_archetype": promoted_archetype,
        "promoted_footprint": promoted_footprint,
        "proposed_prices": proposed_prices,
        # Lifted out of the list rather than left to be noticed inside it. A
        # disagreement between public research and a governed benchmark is the
        # thing a steward most needs to see and the thing most easily missed
        # in a row of successful-looking promotions.
        "material_divergences": material,
        # Several candidates described the same (country, archetype) and the
        # largest was kept. Reported because the alternatives research found
        # are part of what it found, and because write order used to decide
        # this silently.
        "superseded_within_pair": superseded,
        "declined": declined,
        "promoted_by": promoted_by,
        "note": (
            "Footprint rows are now available to the simulation page as the "
            "evidenced starting point. Prices are written unapproved and take "
            "no part in any estimate until a steward approves them - research "
            "proposes a governed value, it does not set one."),
    }


#: The relative band the rate card asserts on every DIA, MPLS, Ethernet and
#: broadband row it holds. Not a judgement introduced here - measured off
#: the card: 280 DIA rows, 89 MPLS, 356 Ethernet, all at exactly this.
CARD_BAND_SHARE = Decimal("0.25")


def approve_price(session, *, row_id: str, approved_by: str,
                  low=None, high=None) -> dict:
    """Admit a promoted price into the rate card, under a name.

    WHY A BAND IS REQUIRED. `promote` writes low = base = high, because a
    single observed price is a point and the system must not invent a
    spread it has no evidence for. That is right while the row is
    unapproved and wrong the moment it prices anything: `estimate.widen`
    spreads a band about its base by scaling the gap, so a zero-width range
    stays zero-width through every widening. An approved point price is
    therefore immune to CR-06 evidence widening - a grade C single
    observation presented as exact, in an estimate whose whole method is
    outside-in. That is worse than the grade E seed it replaces, which at
    least carries the card's own uncertainty.

    So approval is where the band is set, deliberately, by the person whose
    name goes on it. Pass low and high to state it. Omit them and the row
    inherits CARD_BAND_SHARE - the width the card already asserts on every
    comparable row - which is not a new claim about this price, only a
    refusal to claim it is exact.

    A zero-width band is still reachable by passing low == high == base. It
    has to be asked for.
    """
    if not approved_by:
        raise NotPromotable("approval must be attributed to a named person")
    row = session.execute(select(db.unit_cost_prior).where(
        db.unit_cost_prior.c.id == row_id)).first()
    if row is None:
        raise NotPromotable(f"no such price row: {row_id}")

    base = Decimal(str(row.base))
    if low is None and high is None:
        low = base * (Decimal("1") - CARD_BAND_SHARE)
        high = base * (Decimal("1") + CARD_BAND_SHARE)
        band_origin = "CARD_DEFAULT_WIDTH"
    else:
        low = Decimal(str(base if low is None else low))
        high = Decimal(str(base if high is None else high))
        band_origin = "STATED_ON_APPROVAL"
    if not low <= base <= high:
        raise NotPromotable(
            f"the band {low}-{high} does not contain the observed "
            f"{base}. Approving would move the number, and a band is a "
            f"statement about uncertainty rather than about the price.")

    session.execute(update(db.unit_cost_prior)
                    .where(db.unit_cost_prior.c.id == row_id)
                    .values(approved=True, approved_by=approved_by,
                            approved_at=datetime.now(timezone.utc),
                            low=low, high=high))
    session.commit()
    return {"id": row_id, "country": row.country, "product": row.product,
            "bandwidth_mbps": row.bandwidth_mbps,
            "base": str(base), "low": str(low), "high": str(high),
            "band_origin": band_origin, "approved_by": approved_by,
            "evidence_grade": row.evidence_grade,
            "note": ("this price now prices every circuit at this country, "
                     "product and tier in every case")}


def revoke_price(session, *, row_id: str, revoked_by: str,
                 reason: str) -> dict:
    """Take an approved price back out of the rate card.

    Approval is reversible because its consequences are not always visible
    at the moment it is made. Approving two EUR-denominated rows left the
    card holding EUR and USD together, and the estimate refused to price 11
    of 26 companies: "these figures are in ['EUR', 'USD'] and no conversion
    has been applied." The guard was right and the approval was wrong, and
    there was no way back out.

    The row keeps its observed value and its grade - revoking is a
    statement about whether it may price, not about whether it is true -
    and the band stays where approval set it, so re-approving does not
    silently re-derive it.
    """
    if not revoked_by or not reason:
        raise NotPromotable(
            "revocation needs a named person and a reason: a price leaving "
            "the rate card changes every estimate that used it")
    row = session.execute(select(db.unit_cost_prior).where(
        db.unit_cost_prior.c.id == row_id)).first()
    if row is None:
        raise NotPromotable(f"no such price row: {row_id}")
    session.execute(update(db.unit_cost_prior)
                    .where(db.unit_cost_prior.c.id == row_id)
                    .values(approved=False,
                            source_note=f"{row.source_note or ''} "
                                        f"| revoked by {revoked_by}: "
                                        f"{reason}".strip(" |")))
    session.commit()
    return {"id": row_id, "country": row.country, "product": row.product,
            "bandwidth_mbps": row.bandwidth_mbps, "approved": False,
            "revoked_by": revoked_by, "reason": reason}


def evidenced_footprint(session, case_id: str) -> list[dict]:
    """The promoted footprint, with the provenance behind each count.

    Returns the band and source count as well as the figure. Those columns
    were added in v22 and this function did not select them, so the interface
    could only ever show a bare number - and a bare number cannot say whether
    three sources agreed on it or one source stated it, which is the
    difference between a count worth building an estimate on and one worth
    checking first.
    """
    rows = session.execute(
        select(db.evidenced_footprint)
        .where(db.evidenced_footprint.c.case_id == case_id)
        .order_by(db.evidenced_footprint.c.country,
                  db.evidenced_footprint.c.archetype)).all()
    return [{"country": r.country, "archetype": r.archetype, "sites": r.sites,
             "as_of": r.as_of, "agent_run_id": r.agent_run_id,
             "promoted_by": r.promoted_by, "domain_no": r.domain_no,
             "band_low": r.band_low, "band_high": r.band_high,
             "source_count": r.source_count,
             "source_urls": r.source_urls or []} for r in rows]
