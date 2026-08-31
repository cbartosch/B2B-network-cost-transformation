"""Where the footprint comes from, resolved in one place.

The precedence lived in the simulation page as four branches of Streamlit
logic, and it was wrong in a different way on four separate occasions: it
ignored the case's own scope, then it discarded typed counts on rerun, then it
persisted only what had been run, then it never read the known-facts register
at all. Each fix was correct and none of them was the last one, because the
rule was expressed in the place least able to be tested.

So the rule lives here, is returned with its origin, and has tests.

Precedence, strongest first:

1. **PROMOTED_RESEARCH** - counts promoted from domain research, with their
   sources, band and as-of date. Public evidence.
2. **ANALYST_SAVED** - a footprint someone deliberately saved on the case.
   ANALYST_ENTERED_SCOPE, discounted as such, but it is what a person meant.
3. **KNOWN_FACT** - derived from a registered Location footprint fact. This
   used to require clicking through a panel to apply, which meant a fact could
   sit in the register while the simulation ran on placeholders - the thing an
   analyst reported four times as "it is ignoring my data".
4. **SCOPE_PLACEHOLDER** - one site per in-scope country, so the page is
   runnable.
5. **ILLUSTRATIVE** - only when the case declares no scope at all.

The known-fact route is honest about its own limit. A registered fact says how
many sites there are; it does not say what type they are or how they split
across countries. So the total lands in the country of domicile as a single
row, `needs_split` is set, and the caller is told to divide it. Spreading it
evenly across seven countries would be inventing six numbers, and putting it
under a guessed archetype would price it at a bandwidth nobody chose.
"""
from sqlalchemy import select

from .. import db
from . import promotion

# Corroboration standing, best first. A corroborated fact is public evidence;
# an uncorroborated one is an assertion that caps confidence under 0.6A. Where
# two facts compete, the better-supported one is used and the other reported.
_STANDING = {"CORROBORATED": 3, "PENDING": 2, None: 2, "": 2,
             "UNCORROBORATED": 1, "CONTRADICTED": 0}

DEFAULT_ARCHETYPE = "BRANCH"


def resolve(session, case_id: str) -> dict:
    """The best available footprint, its origin, and what to do about it."""
    case_row = session.execute(select(db.case).where(
        db.case.c.case_id == case_id)).first()
    if case_row is None:
        raise LookupError(f"case {case_id} not found")

    promoted = promotion.evidenced_footprint(session, case_id)
    if promoted:
        return {
            "origin": "PROMOTED_RESEARCH",
            "footprint": [{"country": r["country"], "archetype": r["archetype"],
                           "sites": r["sites"]} for r in promoted],
            "detail": f"{len(promoted)} row(s) promoted from research, with "
                      f"sources and as-of dates.",
            "needs_split": False, "provenance": promoted,
        }

    saved = list(case_row.analyst_footprint or [])
    if saved:
        return {
            "origin": "ANALYST_SAVED",
            "footprint": saved,
            "detail": f"{len(saved)} row(s) saved on this case. "
                      f"Analyst-entered, discounted accordingly.",
            "needs_split": False, "provenance": [],
        }

    derived = _from_known_facts(session, case_row)
    if derived:
        return derived

    countries = list(case_row.in_scope_countries or [])
    if countries:
        return {
            "origin": "SCOPE_PLACEHOLDER",
            "footprint": [{"country": c, "archetype": DEFAULT_ARCHETYPE,
                           "sites": 1} for c in countries],
            "detail": f"One site per in-scope country, so the page is "
                      f"runnable. Not an estimate of anything.",
            "needs_split": False, "provenance": [],
        }

    return {
        "origin": "ILLUSTRATIVE",
        "footprint": [
            {"country": "GB", "archetype": "BRANCH", "sites": 120},
            {"country": "DE", "archetype": "BRANCH", "sites": 80},
            {"country": "US", "archetype": "LARGE_OFFICE", "sites": 12},
            {"country": "GB", "archetype": "DC", "sites": 2},
        ],
        "detail": "This case declares no in-scope countries, so these are "
                  "illustrative values. Set the scope on page 1.",
        "needs_split": False, "provenance": [],
    }


def _from_known_facts(session, case_row) -> dict | None:
    """Derive a footprint from a registered Location footprint fact."""
    rows = session.execute(select(db.known_fact).where(
        db.known_fact.c.case_id == case_row.case_id,
        db.known_fact.c.fact_class == "Location footprint")).all()
    usable = [r for r in rows if r.value_base is not None]
    if not usable:
        return None

    usable.sort(key=lambda r: (_STANDING.get(r.corroboration_state, 2),
                               float(r.value_base)), reverse=True)
    best = usable[0]
    others = usable[1:]

    country = (case_row.country_of_domicile
               or (list(case_row.in_scope_countries or []) or [None])[0])
    if not country:
        return None

    detail = (f"Derived from a registered known fact: {float(best.value_base):g} "
              f"{best.unit or 'sites'} for {best.subject or 'the subject'}, "
              f"{best.corroboration_state or 'PENDING'}, asserted by "
              f"{best.asserted_by or 'unattributed'}.")
    if others:
        detail += (f" {len(others)} other registered count(s) were not used "
                   f"({', '.join(f'{float(o.value_base):g} for {o.subject}' for o in others)}) "
                   f"- filed under a different subject they will never "
                   f"corroborate each other.")

    return {
        "origin": "KNOWN_FACT",
        "footprint": [{"country": country, "archetype": DEFAULT_ARCHETYPE,
                       "sites": int(float(best.value_base))}],
        "detail": detail,
        # The fact says how many, not what type or where. Splitting it evenly
        # across the in-scope countries would invent numbers; guessing the
        # archetype would price it at a bandwidth nobody chose.
        "needs_split": True,
        "split_note": (
            f"All {int(float(best.value_base))} sites are in one row under "
            f"{country} / {DEFAULT_ARCHETYPE}, because the register records a "
            f"total and not a breakdown. Split it across countries and site "
            f"types before running - a bank branch is a STORE, a trade counter "
            f"is a STORE, a depot is a WAREHOUSE, and each is priced "
            f"differently."),
        "known_fact_id": best.known_fact_id,
        "provenance": [],
    }
