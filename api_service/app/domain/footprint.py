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

    # 2 - the known-facts register.
    #
    # The register outranks the footprint table, which is the reverse of how
    # this was first written and the reverse of what the ordering implied. A
    # registered fact is a deliberate, attributed, dated statement by a named
    # person; the footprint table is a working surface. Ranking the working
    # surface above the register meant a scratch edit silently overrode what
    # the team had recorded that it knows - and a register that anything can
    # override is not a register.
    #
    # So a Location footprint fact fixes the TOTAL, and a saved footprint is
    # read as the breakdown of that total across countries and site types. It
    # is not a competing number. Where the two totals disagree the saved split
    # is still used - overwriting an analyst's breakdown would be its own kind
    # of discarding - but the disagreement is named rather than absorbed.
    saved = list(case_row.analyst_footprint or [])
    if saved and _is_placeholder(saved, case_row):
        # Running a simulation persists the footprint so an edit is not lost on
        # the rerun that follows, which meant running the placeholder saved the
        # placeholder. A saved placeholder records nothing anybody decided.
        _skip("ANALYST_SAVED",
              f"the {len(saved)} saved row(s) are exactly the runnable "
              f"placeholder (one site per in-scope country), so they record "
              f"nothing anybody decided")
        saved = []

    fact, why_not = _best_footprint_fact(session, case_row)

    if fact is not None:
        total = int(float(fact.value_base))
        detail = (f"{total:g} {fact.unit or 'sites'} registered for "
                  f"{fact.subject or 'the subject'}, "
                  f"{fact.corroboration_state or 'PENDING'}, asserted by "
                  f"{fact.asserted_by or 'unattributed'}.")

        if saved:
            saved_total = sum(int(r.get("sites") or 0) for r in saved)
            diverges = saved_total != total
            _use("KNOWN_FACT", detail + f" Total fixed by the register.")
            _use("ANALYST_SAVED",
                 f"{len(saved)} row(s) used as the breakdown of that total"
                 + (f", but they sum to {saved_total:,} rather than "
                    f"{total:,}" if diverges else ""))
            return {
                "origin": "KNOWN_FACT_SPLIT",
                "footprint": saved,
                "detail": detail + (
                    f" Your saved breakdown is used for the split across "
                    f"countries and site types."),
                "needs_split": False,
                "register_total": total,
                "split_total": saved_total,
                "diverges": diverges,
                "split_note": (
                    f"**Your breakdown sums to {saved_total:,} sites; the "
                    f"register says {total:,}.** The register is not changed "
                    f"by this page - correct the breakdown here, or change the "
                    f"fact on page 2 if the registered total is the thing that "
                    f"is wrong." if diverges else ""),
                "known_fact_id": fact.known_fact_id,
                "provenance": [], "considered": considered,
            }

        _skip("ANALYST_SAVED", "no breakdown is saved, so the registered "
                               "total is unallocated")
        country = (case_row.country_of_domicile
                   or (list(case_row.in_scope_countries or []) or [None])[0])
        if country:
            _use("KNOWN_FACT", detail)
            # Deliberately NOT one row of `total` sites. A row asserts that
            # every site in it is identical - one bandwidth, one primary and
            # backup product, one dual-access probability, one users-per-site
            # figure - and several hundred sites are never identical. Emitting
            # the bulk total as a single row priced an entire estate at a tier
            # nobody chose, and it looked like a footprint rather than like the
            # unallocated number it was.
            #
            # So the total is reported as unallocated and the footprint comes
            # back empty. Inventing a split would be worse: a plausible mix is
            # still a mix nobody decided.
            return {
                "origin": "KNOWN_FACT_UNALLOCATED",
                "footprint": [],
                "detail": detail,
                "needs_split": True,
                "unallocated_sites": total,
                "register_total": total, "split_total": 0,
                "diverges": False,
                "split_note": (
                    f"{total:,} sites are registered and none are allocated. A "
                    f"footprint row states that every site in it is identical - "
                    f"same bandwidth, same primary and backup product, same "
                    f"dual-access probability - so {total:,} sites cannot sit "
                    f"in one row. Allocate them across countries and site "
                    f"types below: a trade counter or bank branch is a STORE, "
                    f"a depot or plant is a WAREHOUSE, a regional office is a "
                    f"LARGE_OFFICE."),
                "suggested_country": country,
                "known_fact_id": fact.known_fact_id,
                "provenance": [], "considered": considered,
            }
        _skip("KNOWN_FACT",
              "a usable Location footprint fact exists but the case has "
              "neither a country of domicile nor any in-scope country, so "
              "there is nowhere to put the sites")
    else:
        _skip("KNOWN_FACT", why_not)

    # 3 - a saved footprint with no register entry behind it
    if saved:
        _use("ANALYST_SAVED", f"{len(saved)} saved row(s), no registered "
                              f"Location footprint fact to reconcile against")
        return {
            "origin": "ANALYST_SAVED",
            "footprint": saved,
            "detail": f"{len(saved)} row(s) saved on this case. "
                      f"Analyst-entered, discounted accordingly.",
            "needs_split": False, "diverges": False,
            "provenance": [], "considered": considered,
        }
    if not case_row.analyst_footprint:
        _skip("ANALYST_SAVED", "no footprint is saved on this case")

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


def _best_footprint_fact(session, case_row) -> tuple:
    """The registered Location footprint fact to trust, and why not if none.

    Returns (row, why_not). The reason matters as much as the row: a fact that
    is present but unusable looked identical to no fact at all, which is what
    made "the register is ignored" undiagnosable from the interface.

    Where several compete, corroboration standing decides and the losers are
    named. Nothing here edits the register - a fact is immutable until a user
    changes it on page 2, and this module only reads.
    """
    all_rows = session.execute(select(db.known_fact).where(
        db.known_fact.c.case_id == case_row.case_id)).all()
    rows = [r for r in all_rows if r.fact_class == "Location footprint"]
    if not rows:
        classes = sorted({r.fact_class for r in all_rows if r.fact_class})
        return None, (
            "no known fact of class 'Location footprint' on this case"
            + (f"; the register holds {classes}" if classes
               else "; the register is empty"))

    # Defence at the consumer as well as the producer. register() now refuses
    # a unit that plainly belongs to another dimension, but rows written before
    # that check exists already carry whatever was typed - and a disclosed cost
    # line read as a site count is the failure this whole chain is worst at
    # noticing, because every stage after it behaves correctly.
    from .known_facts import (unit_conflicts_with_class,
                              value_implausible_for_class)

    # Both checks, because they catch different mistakes. The unit check finds
    # a cost line whose unit gives it away; the magnitude check finds one whose
    # unit says "sites" - which the entry form used to default to for every
    # class, so a disclosed spend arrived unit-consistent and value-absurd.
    def _rejected(row):
        return (unit_conflicts_with_class("Location footprint", row.unit)
                or value_implausible_for_class("Location footprint",
                                               row.value_base))

    mismatched = [r for r in rows if _rejected(r)]
    rows = [r for r in rows if r not in mismatched]
    if mismatched and not rows:
        # Reported with the actual reason per fact rather than a generic one:
        # "the unit is wrong" and "the number is impossible" need different
        # corrections, and an analyst told only that something was ignored has
        # to guess which.
        detail = "; ".join(
            f"{r.value_base} {r.unit or 'no unit'}: {_rejected(r)}"
            for r in mismatched[:3])
        return None, (
            f"{len(mismatched)} fact(s) filed as 'Location footprint' cannot "
            f"be a count of sites and are ignored rather than read as one. "
            f"{detail} Correct the class or the value on page 2.")

    usable = [r for r in rows if r.value_base is not None]
    if not usable:
        return None, (
            f"{len(rows)} Location footprint fact(s) exist but none carries a "
            f"value, so there is no number to use")

    usable.sort(key=lambda r: (_STANDING.get(r.corroboration_state, 2),
                               float(r.value_base)), reverse=True)
    return usable[0], ""
