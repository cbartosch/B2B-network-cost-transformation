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
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from .. import db
from . import promotion

# Corroboration standing, best first. A corroborated fact is public evidence;
# an uncorroborated one is an assertion that caps confidence under 0.6A. Where
# two facts compete, the better-supported one is used and the other reported.
_STANDING = {"CORROBORATED": 3, "PENDING": 2, None: 2, "": 2,
             "UNCORROBORATED": 1, "CONTRADICTED": 0}

DEFAULT_ARCHETYPE = "BRANCH"


# Every key any branch of resolve() can emit, with the value that means
# "this branch has nothing to say about it".
#
# Six branches emitted between 6 and 15 keys, so every read on the page was a
# guess about which one had run - and `_fp["register_total"]` raised KeyError
# the moment a saved footprint with no register entry behind it came back.
# Guarding each read is the same guess written out; a stable shape removes the
# question.
RESOLVED_SHAPE = {
    "origin": None, "footprint": [], "detail": "", "provenance": [],
    "considered": [], "diverges": False, "needs_split": False,
    "split_note": None, "register_total": None, "split_total": None,
    "unallocated_sites": None, "suggested_country": None,
    "known_fact_id": None, "total_from": None, "other_footprint_facts": [],
}


def _shaped(result: dict) -> dict:
    """One shape for every branch, so a reader never has to know which ran."""
    return {**RESOLVED_SHAPE, **result}


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
        return _shaped({
            "origin": "PROMOTED_RESEARCH",
            "footprint": [{"country": r["country"], "archetype": r["archetype"],
                           "sites": r["sites"]} for r in promoted],
            "detail": f"{len(promoted)} row(s) promoted from research, with "
                      f"sources and as-of dates.",
            "needs_split": False, "provenance": promoted,
            "considered": considered,
        })
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

    fact, why_not, _all_footprint_facts = _best_footprint_fact(
        session, case_row)

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
            return _shaped({
                "origin": "KNOWN_FACT_SPLIT",
                "footprint": saved,
                "detail": detail + (
                    f" Your saved breakdown is used for the split across "
                    f"countries and site types."),
                "needs_split": False,
                "register_total": total,
                # Which fact supplied it, and what else was in the running.
                # "the register says 3,912" is unanswerable without this: the
                # resolver picks one fact from several by standing then value,
                # so a reader cannot see which won - or that facts about
                # different countries competed instead of summing.
                "total_from": {
                    "known_fact_id": fact.known_fact_id,
                    "subject": fact.subject, "unit": fact.unit,
                    "value_base": str(fact.value_base),
                    "corroboration_state": fact.corroboration_state,
                    "asserted_by": fact.asserted_by},
                "other_footprint_facts": [
                    {"value_base": str(r.value_base), "unit": r.unit,
                     "subject": r.subject,
                     "corroboration_state": r.corroboration_state}
                    for r in _all_footprint_facts if r is not fact],
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
            })

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
            return _shaped({
                "origin": "KNOWN_FACT_UNALLOCATED",
                "footprint": [],
                "detail": detail,
                "needs_split": True,
                "unallocated_sites": total,
                "register_total": total, "split_total": 0,
                # Which fact supplied it, and what else was in the running.
                # "the register says 3,912" is unanswerable without this: the
                # resolver picks one fact from several by standing then value,
                # so a reader cannot see which won - or that facts about
                # different countries competed instead of summing.
                "total_from": {
                    "known_fact_id": fact.known_fact_id,
                    "subject": fact.subject, "unit": fact.unit,
                    "value_base": str(fact.value_base),
                    "corroboration_state": fact.corroboration_state,
                    "asserted_by": fact.asserted_by},
                "other_footprint_facts": [
                    {"value_base": str(r.value_base), "unit": r.unit,
                     "subject": r.subject,
                     "corroboration_state": r.corroboration_state}
                    for r in _all_footprint_facts if r is not fact],
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
            })
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
        return _shaped({
            "origin": "ANALYST_SAVED",
            "footprint": saved,
            "detail": f"{len(saved)} row(s) saved on this case. "
                      f"Analyst-entered, discounted accordingly.",
            "needs_split": False, "diverges": False,
            "provenance": [], "considered": considered,
        })
    if not case_row.analyst_footprint:
        _skip("ANALYST_SAVED", "no footprint is saved on this case")

    # 4 - the case's own scope
    countries = list(case_row.in_scope_countries or [])
    if countries:
        _use("SCOPE_PLACEHOLDER", f"{len(countries)} in-scope country(ies)")
        return _shaped({
            "origin": "SCOPE_PLACEHOLDER",
            "footprint": [{"country": c, "archetype": DEFAULT_ARCHETYPE,
                           "sites": 1} for c in countries],
            "detail": "One site per in-scope country, so the page is "
                      "runnable. Not an estimate of anything.",
            "needs_split": False, "provenance": [],
            "considered": considered,
        })
    _skip("SCOPE_PLACEHOLDER", "the case declares no in-scope countries")

    _use("ILLUSTRATIVE", "nothing else was available")
    return _shaped({
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
    })


def propose_split(session, *, total: int, country: str, industry: str | None,
                  countries: list | None = None) -> dict:
    """A starting split of one total across site types and density bands.

    A registered total arrived with an empty table and a message saying nothing
    would be guessed. That is right about silent invention and wrong about the
    remedy: the analyst has to invent the split anyway, with no help, and an
    empty table blocks the page.

    So this proposes one and says exactly what it is - a governed mix for the
    sector, not a finding about this client. It is never applied on its own:
    the rows land in the editor and become real only when the analyst saves or
    runs, which is the same accept-or-edit act the public known-fact sweep
    uses.

    Largest remainder, so the parts sum to the total. Rounding each share
    independently loses sites, and a split that does not add up is worse than
    no split - it reads as arithmetic.
    """
    sector = (industry or "DEFAULT").strip().upper() or "DEFAULT"
    rows = session.execute(select(db.density_mix).where(
        db.density_mix.c.industry.in_([sector, "DEFAULT"]))).all()
    chosen = [r for r in rows if r.industry == sector] or \
             [r for r in rows if r.industry == "DEFAULT"]
    if not chosen or total <= 0:
        return {"rows": [], "basis": None,
                "note": "no governed mix for this sector, so nothing is "
                        "proposed - split it by hand below."}

    matched = bool([r for r in rows if r.industry == sector])
    chosen.sort(key=lambda r: (r.archetype, r.density_band))
    raw = [Decimal(total) * Decimal(str(r.share)) for r in chosen]
    counts = [int(x) for x in raw]
    for index in sorted(range(len(raw)), key=lambda i: raw[i] - counts[i],
                        reverse=True)[:total - sum(counts)]:
        counts[index] += 1

    proposed = [
        {"country": country.upper(), "archetype": r.archetype,
         "density": r.density_band, "sites": n}
        for r, n in zip(chosen, counts) if n > 0]
    return {
        "rows": proposed,
        "basis": "INDUSTRY_DEFAULT" if matched else "GENERIC_DEFAULT",
        "industry": sector if matched else "DEFAULT",
        "note": (
            f"A typical shape for {sector if matched else 'an unspecified'} "
            f"sector, applied to {total:,} sites and put in the table for you "
            f"to correct. It is a governed default, not a finding about this "
            f"client - so edit it before running, and name locations or "
            f"research domain 2 to replace it with evidence. Nothing is saved "
            f"until you save or run."),
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


# Ordering used only to rank the choices offered, never to decide.
def total_candidates(session, *, case_id: str) -> dict:
    """Every registered site total, ranked, with what each one is.

    The resolver used to pick one by rule - best corroboration standing, then
    largest value - and report only the number. So "the register says 3,912"
    was unanswerable, and two complementary facts about different countries
    competed instead of summing: 1,840 UK stores beat 89 Ireland stores and
    Ireland was silently dropped.

    Every other decision in this workflow is proposed and disposed. Entity
    resolution offers candidates with differentiators and a named person
    confirms; the public sweep proposes and the analyst accepts; a promotion
    needs a promoter. A number that sets the size of the entire modelled estate
    should not be the one thing a rule decides quietly.

    So this offers the choices and explains them. The sum is offered too,
    because complementary facts are the common case for a multi-country estate
    and no rule can tell them apart from rival estimates - only a person
    reading the units can.
    """
    from .known_facts import unit_conflicts_with_class, value_implausible_for_class

    rows = [r for r in session.execute(select(db.known_fact).where(
        db.known_fact.c.case_id == case_id,
        db.known_fact.c.fact_class == "Location footprint")).all()]

    usable, rejected = [], []
    for row in rows:
        why = (unit_conflicts_with_class("Location footprint", row.unit)
               or value_implausible_for_class("Location footprint",
                                              row.value_base))
        if why or row.value_base is None:
            rejected.append({
                "known_fact_id": row.known_fact_id,
                "value_base": None if row.value_base is None
                else str(row.value_base),
                "unit": row.unit,
                "reason": why or "carries no value, so there is no number"})
            continue
        usable.append(row)

    usable.sort(key=lambda r: (_STANDING.get(r.corroboration_state, 2),
                               float(r.value_base)), reverse=True)

    choices = [{
        "known_fact_id": r.known_fact_id,
        "sites": int(float(r.value_base)),
        "unit": r.unit,
        "subject": r.subject,
        "corroboration_state": r.corroboration_state,
        "asserted_by": r.asserted_by,
        "basis": r.basis,
        # The qualification the sweep supplied - "total UK entity headcount
        # band", "Republic of Ireland" - which is usually the whole reason one
        # of these is the right one.
        "supplied_note": getattr(r, "supplied_note", None),
        "band": (None if r.value_low is None and r.value_high is None
                 else {"low": None if r.value_low is None else str(r.value_low),
                       "high": None if r.value_high is None else str(r.value_high)}),
    } for r in usable]

    total = sum(c["sites"] for c in choices)
    if len(choices) > 1:
        choices.append({
            "known_fact_id": "SUM",
            "sites": total,
            "unit": "sites",
            "subject": f"all {len(usable)} registered fact(s) added together",
            "corroboration_state": None, "asserted_by": None, "basis": None,
            "supplied_note": (
                "Choose this where the facts describe different parts of the "
                "estate rather than rival estimates of the same part - "
                "\"1,840 UK stores\" and \"89 Ireland stores\" are both true "
                "and the estate is 1,929. Choose a single fact where they are "
                "competing counts of the same thing."),
            "band": None,
        })

    # Footprint facts on other cases. "I had registered sites, where did they
    # go" has three possible answers - filtered out, never written, or on a
    # different case - and only the third is invisible from this page. The
    # register is case-scoped, and a case created for a second client while the
    # first was selected is the easiest mistake in the whole workflow to make.
    elsewhere = [
        {"case_id": r.case_id, "value_base": str(r.value_base),
         "unit": r.unit, "subject": r.subject, "asserted_by": r.asserted_by}
        for r in session.execute(select(db.known_fact).where(
            db.known_fact.c.fact_class == "Location footprint",
            db.known_fact.c.case_id != case_id,
            db.known_fact.c.value_base.isnot(None))).all()]

    return {
        "choices": choices,
        "rejected": rejected,
        "on_other_cases": elsewhere,
        # The rule-based order is a suggestion for reading, not a decision.
        "suggested": choices[0]["known_fact_id"] if choices else None,
        "note": (
            "Pick the one that describes the estate you are modelling. Nothing "
            "is chosen until you choose it, and the choice is recorded on the "
            "case so the simulation and the estimate use the same number."
            if len(choices) > 1 else
            "One registered total, so there is nothing to choose between."
            if choices else
            "No usable Location footprint fact on this case."),
    }


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
               else "; the register is empty")), []

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
                                               row.value_base)), "", []

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
            f"{detail} Correct the class or the value on page 2."), []

    usable = [r for r in rows if r.value_base is not None]
    if not usable:
        return None, (
            f"{len(rows)} Location footprint fact(s) exist but none carries a "
            f"value, so there is no number to use"), []

    # The analyst's choice, where they made one. Honoured over the rule,
    # because the rule cannot tell a rival count from a complementary one and
    # a person reading the units can.
    chosen = getattr(case_row, "footprint_total_choice", None)
    if chosen == "SUM" and len(usable) > 1:
        total = sum(float(r.value_base) for r in usable)
        # A synthetic fact carrying the sum, so everything downstream reads
        # one total as before. Attributed to the person who chose it: this is
        # their judgement that the facts are complementary, not a new source.
        summed = SimpleNamespace(
            known_fact_id="SUM", case_id=case_row.case_id,
            fact_class="Location footprint", subject=usable[0].subject,
            value_base=total, value_low=None, value_high=None, unit="sites",
            corroboration_state=min(
                (r.corroboration_state for r in usable),
                key=lambda st: _STANDING.get(st, 2)),
            asserted_by=getattr(case_row, "footprint_total_chosen_by", None)
            or "chosen on the simulation page",
            basis="INDUSTRY_KNOWLEDGE", supplied_note=(
                f"the sum of {len(usable)} registered fact(s), chosen as "
                f"complementary parts of the estate rather than rival counts"))
        return summed, "", usable
    if chosen:
        picked = next((r for r in usable if r.known_fact_id == chosen), None)
        if picked is not None:
            return picked, "", usable
        # The chosen fact is gone - deleted or superseded. Falling back
        # silently would model a different estate under the same decision, so
        # the reason travels with the result.
        return usable[0] if usable else None, (
            f"the chosen site total ({chosen[:8]}) is no longer a usable "
            f"registered fact, so it has been ignored. Choose again on the "
            f"simulation page."), usable

    usable.sort(key=lambda r: (_STANDING.get(r.corroboration_state, 2),
                               float(r.value_base)), reverse=True)
    # The runners-up too. Picking one fact and discarding the record of the
    # others makes a total unexplainable, and these may not even be competing
    # claims - "1,840 UK stores" and "89 Ireland stores" are complementary and
    # this takes the larger.
    return usable[0], "", usable
