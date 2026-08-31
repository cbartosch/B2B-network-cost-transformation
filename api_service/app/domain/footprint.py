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
    """The best available footprint, its origin, and why the others were not used.

    The `considered` trace is not decoration. Five separate rounds went on
    "the footprint is wrong" and each one was answered by inferring which
    branch had fired, because the answer was not observable. Every source is
    now listed with whether it was used and, if not, the reason - so the next
    question is answered by reading rather than by guessing.
    """
    case_row = session.execute(select(db.case).where(
        db.case.c.case_id == case_id)).first()
    if case_row is None:
        raise LookupError(f"case {case_id} not found")

    considered = []

    def _skip(source, reason):
        considered.append({"source": source, "used": False, "reason": reason})

    def _use(source, reason=""):
        considered.append({"source": source, "used": True, "reason": reason})

    # 1 - promoted research
    promoted = promotion.evidenced_footprint(session, case_id)
    if promoted:
        _use("PROMOTED_RESEARCH", f"{len(promoted)} promoted row(s)")
        return {
            "origin": "PROMOTED_RESEARCH",
            "footprint": [{"country": r["country"], "archetype": r["archetype"],
                           "sites": r["sites"]} for r in promoted],
            "detail": f"{len(promoted)} row(s) promoted from research, with "
                      f"sources and as-of dates.",
            "needs_split": False, "provenance": promoted,
            "considered": considered,
        }
    _skip("PROMOTED_RESEARCH", "nothing has been promoted from research on "
                               "this case")

    # 2 - a footprint someone saved
    saved = list(case_row.analyst_footprint or [])
    if not saved:
        _skip("ANALYST_SAVED", "no footprint is saved on this case")
    elif _is_placeholder(saved, case_row):
        # A saved placeholder carries no information and must not outrank a
        # registered fact. Running a simulation persists the footprint so an
        # edit is not lost on the rerun that follows - which meant running the
        # placeholder saved the placeholder, and that then took precedence
        # over a known fact. The convenience of one change blocked another.
        _skip("ANALYST_SAVED",
              f"the {len(saved)} saved row(s) are exactly the runnable "
              f"placeholder (one site per in-scope country), so they record "
              f"nothing anybody decided")
        saved = []
    else:
        _use("ANALYST_SAVED", f"{len(saved)} saved row(s)")
        return {
            "origin": "ANALYST_SAVED",
            "footprint": saved,
            "detail": f"{len(saved)} row(s) saved on this case. "
                      f"Analyst-entered, discounted accordingly.",
            "needs_split": False, "provenance": [],
            "considered": considered,
        }

    # 3 - the known-facts register
    derived, why_not = _from_known_facts(session, case_row)
    if derived:
        _use("KNOWN_FACT", derived["detail"])
        derived["considered"] = considered
        return derived
    _skip("KNOWN_FACT", why_not)

    # 4 - the case's own scope
    countries = list(case_row.in_scope_countries or [])
    if countries:
        _use("SCOPE_PLACEHOLDER", f"{len(countries)} in-scope country(ies)")
        return {
            "origin": "SCOPE_PLACEHOLDER",
            "footprint": [{"country": c, "archetype": DEFAULT_ARCHETYPE,
                           "sites": 1} for c in countries],
            "detail": "One site per in-scope country, so the page is "
                      "runnable. Not an estimate of anything.",
            "needs_split": False, "provenance": [],
            "considered": considered,
        }
    _skip("SCOPE_PLACEHOLDER", "the case declares no in-scope countries")

    _use("ILLUSTRATIVE", "nothing else was available")
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
        "considered": considered,
    }


def _is_placeholder(saved: list, case_row) -> bool:
    """Is this saved footprint just the runnable default?

    Exactly one row per in-scope country, the default archetype, one site each
    - which is what SCOPE_PLACEHOLDER produces. Matching that shape means the
    save recorded nothing an analyst decided, so it is treated as absent
    rather than as a statement.

    Deliberately narrow. A footprint with one row of one site that an analyst
    genuinely meant survives, because it will not match the country set.
    """
    countries = list(case_row.in_scope_countries or [])
    if not countries or len(saved) != len(countries):
        return False
    expected = {(c.upper(), DEFAULT_ARCHETYPE, 1) for c in countries}
    actual = {((r.get("country") or "").upper(),
               (r.get("archetype") or "").upper(),
               int(r.get("sites") or 0)) for r in saved}
    return actual == expected


def _from_known_facts(session, case_row) -> tuple:
    """Derive a footprint from a registered Location footprint fact.

    Returns (result, why_not). The reason matters as much as the result: a
    fact that is present but unusable looked identical to no fact at all, and
    that ambiguity is what made "the register is ignored" unanswerable without
    reading the database by hand.
    """
    all_rows = session.execute(select(db.known_fact).where(
        db.known_fact.c.case_id == case_row.case_id)).all()
    rows = [r for r in all_rows if r.fact_class == "Location footprint"]
    if not rows:
        classes = sorted({r.fact_class for r in all_rows})
        return None, (
            f"no known fact of class 'Location footprint' on this case"
            + (f"; the register holds {classes}" if classes
               else "; the register is empty"))
    usable = [r for r in rows if r.value_base is not None]
    if not usable:
        return None, (
            f"{len(rows)} Location footprint fact(s) exist but none carries a "
            f"value_base, so there is no number to use")

    usable.sort(key=lambda r: (_STANDING.get(r.corroboration_state, 2),
                               float(r.value_base)), reverse=True)
    best = usable[0]
    others = usable[1:]

    country = (case_row.country_of_domicile
               or (list(case_row.in_scope_countries or []) or [None])[0])
    if not country:
        return None, (
            "a usable Location footprint fact exists but the case has neither "
            "a country of domicile nor any in-scope country, so there is "
            "nowhere to put the sites")

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
    }, ""
