"""In-scope country resolution (supports 0.1A intake, extends 0.1C).

`in_scope_countries` on `engagement_case` is consumed literally downstream -
estimates:run filters `unit_cost_prior` on exact ISO codes (routers/api.py,
`run_estimate`). Nothing reads a region name or a "GLOBAL" sentinel from that
column, and nothing should have to: the pricing filter needs concrete codes
whichever way the analyst expressed scope.

So a region or "global" selection is resolved to a literal country list at
save time, same as before, and the *descriptor* the analyst actually chose is
kept alongside it in `in_scope_region` purely for audit and re-editing - so
"why is Singapore priced?" has an answer that isn't "someone typed SG once".

REGION and GLOBAL resolve against what the rate card can price, evaluated at
save time rather than fixed, so they track the card rather than drifting stale
as PRIORS grows. A country prices at its own rate or, failing that, at its
sub-region's and then that sub-region's parent's - `price_ladder` below - so it
is in scope if any rung of its ladder holds an approved price. A selection
that reaches no priced country still resolves - to an empty list - because an
empty list is a legitimate answer for the mandatory-intake gate, and a
fabricated non-empty one is worse than a plain "no priced countries in this
region yet".
"""
from sqlalchemy import select

from .. import db

# A sub-region's parent, for the second rung of the fallback.
#
# A country with no card falls to its sub-region; a sub-region with no priced
# member falls to its parent. Ethiopia reaches AFRICA_SSA, which has no rates,
# and then EMEA, which does - so the estate prices instead of refusing, and the
# scope recorded on the price says which rung answered.
#
# AMER and APAC are their own parents: there is nothing above them, and mapping
# them to a global average across markets differing by a factor of three would
# be a worse answer than the region itself.
REGION_PARENT = {
    "AFRICA_NORTH": "EMEA",
    "AFRICA_SSA": "EMEA",
    "EUROPE_CENTRAL": "EMEA",
    "EUROPE_EAST": "EMEA",
    "EUROPE_NORTH": "EMEA",
    "EUROPE_SOUTH": "EMEA",
    "EUROPE_WEST": "EMEA",
    "MIDDLE_EAST": "EMEA",
}


def price_ladder(country: str, region: str | None) -> list[str]:
    """The scopes one country's circuits may be priced at, most specific first.

    The country, then its sub-region, then that sub-region's parent. The route
    has loaded both regional rungs into `priors` since EMEA split, and nothing
    told `match_prior` to look at them: both callers passed the country alone,
    so Hungary's 5G backups were unpriced while the Central European rate that
    would have priced them sat in the dict. The tests spelled the chain out by
    hand whenever they called `match_prior`, so they passed throughout - the
    rung was wired in every test and in no route.

    A country in no region gets only itself, and so does a scope that is
    already a region - a backbone leg priced against EMEA has nothing above it
    to fall to.
    """
    ladder = [country]
    if region and region != country:
        ladder.append(region)
        parent = REGION_PARENT.get(region)
        if parent:
            ladder.append(parent)
    return ladder


SCOPE_MODES = ("COUNTRIES", "REGION", "GLOBAL")

# The regions an analyst can choose, as the atlas regions each one covers.
#
# This was a hand list - EMEA as GB, DE, FR, NL and AE, APAC as Singapore,
# the Americas as the US - written when there was no atlas anywhere in the
# system. `reference.country_region` is that atlas now, and the ladder prices
# a country without a card of its own at its region's median, so choosing
# EMEA scoped a case to five of the 125 EMEA countries the card can price.
#
# Still not derived from priors: "EMEA" is a grouping of countries, not
# "wherever we happen to have a prior". The atlas says which countries are in
# it; the card only decides which of them can be priced.
REGION_SCOPES = {
    "EMEA": tuple(sorted(sub for sub, parent in REGION_PARENT.items()
                         if parent == "EMEA")),
    "APAC": ("APAC",),
    "AMERICAS": ("AMER",),
}


def region_choices() -> list[str]:
    return sorted(REGION_SCOPES)


def pricing_scopes(session, countries) -> dict:
    """{country: the scope that would price it, or None}.

    The first rung of each country's ladder holding an approved price - the
    country, its sub-region or that sub-region's parent. Counting a country's
    own rows instead called Ethiopia unpriced while the estimate priced every
    Ethiopian circuit at AFRICA_SSA's median.
    """
    countries = list(countries or [])
    if not countries:
        return {}
    region_of = dict(session.execute(
        select(db.country_region.c.country, db.country_region.c.region)
        .where(db.country_region.c.country.in_(countries))).all())
    ladders = {c: price_ladder(c, region_of.get(c)) for c in countries}
    rungs = {rung for ladder in ladders.values() for rung in ladder}
    priced = {r.country for r in session.execute(
        select(db.unit_cost_prior.c.country)
        .where(db.unit_cost_prior.c.country.in_(rungs),
               db.unit_cost_prior.c.approved.is_(True)).distinct()).all()}
    return {c: next((rung for rung in ladder if rung in priced), None)
            for c, ladder in ladders.items()}


def region_members(session, region: str) -> list[str]:
    """Every country the atlas places in `region` that the card can price."""
    atlas = [r.country for r in session.execute(
        select(db.country_region.c.country)
        .where(db.country_region.c.region.in_(REGION_SCOPES[region]))).all()]
    return sorted(c for c, rung in pricing_scopes(session, atlas).items()
                  if rung)


def resolve(session, *, scope_mode: str, region: str | None,
            explicit_countries: list[str] | None) -> tuple[list[str], str | None]:
    """Return (in_scope_countries, in_scope_region) for the case row.

    in_scope_region is None for an explicit COUNTRIES selection, so the
    mandatory-intake gate and every existing consumer of in_scope_countries
    keep working exactly as they did - REGION and GLOBAL are additive, not a
    parallel scope system.
    """
    if scope_mode not in SCOPE_MODES:
        raise ValueError(f"unknown scope_mode {scope_mode!r}; expected one of {SCOPE_MODES}")

    if scope_mode == "COUNTRIES":
        return (explicit_countries or []), None

    if scope_mode == "REGION":
        if region not in REGION_SCOPES:
            raise ValueError(f"unknown region {region!r}; expected one of {region_choices()}")
        return region_members(session, region), region

    # GLOBAL: every *country* the card can price today - with an approved
    # prior of its own, or one on its ladder. Own priors alone left GLOBAL at
    # 78 countries while EMEA alone now reaches 125.
    #
    # scope_kind is filtered because a price may now be scoped to a region -
    # a backbone circuit belongs to EMEA - and offering "EMEA" as an in-scope
    # country would put a region into a country list, where every downstream
    # consumer would treat it as an ISO code.
    own = {r.country for r in session.execute(
        select(db.unit_cost_prior.c.country)
        .where(db.unit_cost_prior.c.approved.is_(True),
               db.unit_cost_prior.c.scope_kind != "REGION")
        .distinct()).all()}
    atlas = [r.country for r in session.execute(
        select(db.country_region.c.country)).all()]
    reached = {c for c, rung in pricing_scopes(session, atlas).items() if rung}
    return sorted(own | reached), "GLOBAL"
