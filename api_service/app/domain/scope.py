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

GLOBAL is resolved dynamically against approved priors rather than a fixed
list, so it tracks whatever countries are actually priceable rather than
drifting stale as PRIORS grows. A region with no approved priors in any
member country still resolves - to an empty list - because an empty list is
a legitimate answer for the mandatory-intake gate, and a fabricated non-empty
one is worse than a plain "no priced countries in this region yet".
"""
from sqlalchemy import select

from .. import db

SCOPE_MODES = ("COUNTRIES", "REGION", "GLOBAL")

# Maintained by hand: there is no atlas anywhere else in this system, and a
# derived-from-priors set would silently misrepresent a purely political
# grouping (e.g. "EMEA" is not "wherever we happen to have a prior").
REGION_COUNTRIES = {
    "EMEA": ["GB", "DE", "FR", "NL", "AE"],
    "APAC": ["SG"],
    "AMERICAS": ["US"],
}


def region_choices() -> list[str]:
    return sorted(REGION_COUNTRIES)


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
        if region not in REGION_COUNTRIES:
            raise ValueError(f"unknown region {region!r}; expected one of {region_choices()}")
        return list(REGION_COUNTRIES[region]), region

    # GLOBAL: every *country* with at least one approved prior, today.
    #
    # scope_kind is filtered because a price may now be scoped to a region -
    # a backbone circuit belongs to EMEA - and offering "EMEA" as an in-scope
    # country would put a region into a country list, where every downstream
    # consumer would treat it as an ISO code.
    rows = session.execute(
        select(db.unit_cost_prior.c.country)
        .where(db.unit_cost_prior.c.approved.is_(True),
               db.unit_cost_prior.c.scope_kind != "REGION")
        .distinct()).all()
    return sorted({r.country for r in rows}), "GLOBAL"
