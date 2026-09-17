"""What counts as a site.

The case declares which countries, which cost layers, which service families
and which legal entities are in scope, and nothing about what a *site* is. So a
footprint of 5,230 is unanswerable: hypermarkets only, all banners, franchise
convenience stores, every connected location including collection points? Those
are four different numbers and four different estates, and the model accepted
any of them without recording which was meant.

That ambiguity surfaced when a thirty-company run was checked against public
store counts. One figure was a store count and the other was closer to
connected retail locations in a single country - both defensible, neither
stated, and the disagreement unresolvable because nobody had written the rule
down.

**A footprint without its rule is an assertion.** The model refuses assertions
everywhere else: a rate needs a source, a fact needs a basis, an
acknowledgement needs a person. A site count is the largest single driver of
the baseline and was the one number with no such requirement.

The rule is declared before the footprint and pinned into the run, on the same
terms as the geography: it is part of what the estimate means, not a note about
how it was made.
"""
from decimal import Decimal

# What a site is, for counting purposes. Ordered widest to narrowest, because
# each one is a subset of the one before it - which is what makes two counts
# on different rules comparable in a stated direction rather than merely
# different.
CONNECTED_LOCATION = "CONNECTED_LOCATION"   # anything with a network drop
OPERATED_FACILITY = "OPERATED_FACILITY"     # a place the company runs
OWNED_PREMISES = "OWNED_PREMISES"           # a place the company owns
MAJOR_SITE = "MAJOR_SITE"                   # above a stated size threshold

# SITE_BASES, not BASES: known_facts.py has a BASES and reconciliation.py has
# a SOURCES, and two constant tables of one name in two modules is how
# ORIGIN_RANK came to mean different things in different files. The same
# collision as case_rates.RATE_BASES, made twice.
SITE_BASES = (CONNECTED_LOCATION, OPERATED_FACILITY, OWNED_PREMISES,
              MAJOR_SITE)

# Widest first. A count on a narrower basis is a lower bound on a count on a
# wider one, and that is the only comparison this module will assert.
BREADTH = {CONNECTED_LOCATION: 4, OPERATED_FACILITY: 3,
           OWNED_PREMISES: 2, MAJOR_SITE: 1}

# What a rule may include or exclude. Each of these moved a real number in a
# real disagreement, which is why they are named rather than left to prose.
INCLUSIONS = (
    "FRANCHISE",             # franchised stores on the company's network
    "PARTNER_OPERATED",      # a partner runs it, the company's traffic crosses it
    "UNMANNED",              # lockers, collection points, ATMs, cell sites
    "SEASONAL",              # open part of the year
    "SHARED_TENANCY",        # a concession inside somebody else's site
    "UNDER_CONSTRUCTION",    # committed and not yet live
)

# Where the number came from. Not the same question as what it counts: a store
# locator and an annual report can disagree about the same rule, and a
# footprint row should say which it used.
FILING = "FILING"                    # annual report, regulatory submission
STORE_LOCATOR = "STORE_LOCATOR"      # the company's own site finder
CLIENT_STATED = "CLIENT_STATED"      # the client told us
ANALYST_ESTIMATE = "ANALYST_ESTIMATE"  # somebody's judgement
COUNT_SOURCES = (FILING, STORE_LOCATOR, CLIENT_STATED,
                 ANALYST_ESTIMATE)

# The evidence grade a count can carry, from where it came. A store locator is
# the company's own published data and beats an estimate; it is not a filing,
# because a locator changes daily and nobody signs it.
GRADE_OF_SOURCE = {FILING: "B", STORE_LOCATOR: "C",
                   CLIENT_STATED: "C", ANALYST_ESTIMATE: "E"}


class RuleInvalid(ValueError):
    """A rule that would not make a count checkable."""


def rule(*, basis: str, includes=(), excludes=(),
         minimum_headcount=None, minimum_area_sqm=None,
         note: str | None = None) -> dict:
    """A site-inclusion rule.

    Every named inclusion must be decided - in or out - and anything left
    undecided is reported rather than defaulted. A rule silent on franchise
    locations is the rule that produced the disagreement this module exists to
    prevent: one reader assumed they were in, the other assumed out, and both
    were reading the same number.
    """
    if basis not in SITE_BASES:
        raise RuleInvalid(
            f"{basis!r} is not one of {list(SITE_BASES)}. Without a basis a count "
            f"has no unit - 5,230 of what?")

    included, excluded = set(includes or ()), set(excludes or ())
    unknown = sorted((included | excluded) - set(INCLUSIONS))
    if unknown:
        raise RuleInvalid(
            f"{unknown} are not things this rule can include or exclude. "
            f"Known: {list(INCLUSIONS)}. A category nobody named is one "
            f"nobody can check.")

    both = sorted(included & excluded)
    if both:
        raise RuleInvalid(
            f"{both} are listed as both included and excluded, so the rule "
            f"does not say what it counts")

    undecided = sorted(set(INCLUSIONS) - included - excluded)
    if basis == MAJOR_SITE and minimum_headcount is None \
            and minimum_area_sqm is None:
        raise RuleInvalid(
            "a MAJOR_SITE basis needs the threshold that makes a site major - "
            "otherwise it means whatever the person counting thought it meant")

    return {
        "basis": basis,
        "breadth": BREADTH[basis],
        "includes": sorted(included),
        "excludes": sorted(excluded),
        # Reported, not defaulted. A rule may legitimately not have decided
        # about seasonal sites; what it may not do is leave that invisible.
        "undecided": undecided,
        "minimum_headcount": (None if minimum_headcount is None
                              else int(minimum_headcount)),
        "minimum_area_sqm": (None if minimum_area_sqm is None
                             else int(minimum_area_sqm)),
        "note": note,
        "complete": not undecided,
        "summary": describe({"basis": basis, "includes": sorted(included),
                             "excludes": sorted(excluded),
                             "minimum_headcount": minimum_headcount,
                             "minimum_area_sqm": minimum_area_sqm}),
    }


def describe(rule_dict: dict) -> str:
    """The rule in a sentence, for a footnote under a site count.

    A count shown without its rule is the thing this prevents, so the rule has
    to be short enough to print beside the number.
    """
    parts = [str(rule_dict.get("basis") or "no basis").replace("_", " ").lower()]
    if rule_dict.get("includes"):
        parts.append("including "
                     + ", ".join(i.replace("_", " ").lower()
                                 for i in rule_dict["includes"]))
    if rule_dict.get("excludes"):
        parts.append("excluding "
                     + ", ".join(e.replace("_", " ").lower()
                                 for e in rule_dict["excludes"]))
    if rule_dict.get("minimum_headcount"):
        parts.append(f"at least {rule_dict['minimum_headcount']} staff")
    if rule_dict.get("minimum_area_sqm"):
        parts.append(f"at least {rule_dict['minimum_area_sqm']} sqm")
    return "; ".join(parts)


def grade_of(source: str) -> str:
    """The evidence grade a count from this source can carry."""
    if source not in COUNT_SOURCES:
        raise RuleInvalid(
            f"{source!r} is not one of {list(COUNT_SOURCES)}. The grade follows from "
            f"the source, so an unknown source is an ungradeable count.")
    return GRADE_OF_SOURCE[source]


def compare(*, left_count, left_rule: dict, right_count,
            right_rule: dict, left_scope=None, right_scope=None) -> dict:
    """Two site counts on two rules, and what can honestly be said.

    The case this exists for: a published store count against a footprint row.
    If the rules differ, the numbers are not in disagreement - they are
    answering different questions, and the only statement available is a
    direction.

    Geography is checked before the rule and refuses outright when it differs,
    because a France-only footprint and a global store count are not a
    disagreement about anything.

    Never asserts that one is wrong. A count on a narrower basis *should* be
    lower, and reporting that as an error is how a correct footprint gets
    "fixed" into a wrong one.
    """
    # Geography first, because it dominates everything the rule says.
    #
    # The first version of this compared a France-only footprint of 5,230
    # against a global store count of 14,000 and reported a contradiction on
    # breadth: the wider *rule* returned the smaller count. That was an
    # artefact. The rule was wider and the geography was a fraction, and a
    # comparison that ignores the second will call a correct footprint wrong -
    # which is how a right number gets "fixed" into a wrong one.
    if left_scope is not None and right_scope is not None:
        left_set = {str(c).upper() for c in left_scope}
        right_set = {str(c).upper() for c in right_scope}
        if left_set != right_set:
            missing = sorted(right_set - left_set)
            extra = sorted(left_set - right_set)
            return {
                "comparable": False,
                "reason": "different geography",
                "only_on_the_right": missing,
                "only_on_the_left": extra,
                "note": (
                    f"these cover different geographies, so the counts are not "
                    f"comparable on any rule: "
                    + (f"{missing} are counted on the right and not the left"
                       if missing else "")
                    + ("; " if missing and extra else "")
                    + (f"{extra} on the left and not the right"
                       if extra else "")
                    + ". Narrow one to the other before comparing."),
            }

    left, right = Decimal(str(left_count)), Decimal(str(right_count))
    left_breadth = BREADTH.get(left_rule.get("basis"), 0)
    right_breadth = BREADTH.get(right_rule.get("basis"), 0)
    same_basis = left_rule.get("basis") == right_rule.get("basis")
    same_inclusions = (sorted(left_rule.get("includes") or ())
                       == sorted(right_rule.get("includes") or ())
                       and sorted(left_rule.get("excludes") or ())
                       == sorted(right_rule.get("excludes") or ()))

    if same_basis and same_inclusions:
        gap = right - left
        return {
            "comparable": True,
            "difference": str(gap),
            "note": ("the same rule, so these are the same question and the "
                     "difference is a real disagreement about the estate"
                     if gap else "the same rule and the same count"),
        }

    # Basis and inclusions are separate axes, and the first version of this
    # compared only the basis. That produced a false contradiction: a
    # CONNECTED_LOCATION rule excluding franchise is *narrower* than an
    # OPERATED_FACILITY rule including it, and reporting the first as "the
    # wider rule returning the smaller count" accused a correct pair of
    # counts of being impossible.
    #
    # One rule is wider only if it is at least as wide on both axes and
    # strictly wider on one. Anything else is two rules that overlap, and
    # overlapping rules support no directional claim at all.
    left_included = set(left_rule.get("includes") or ())
    right_included = set(right_rule.get("includes") or ())

    def _wider_than(a_breadth, a_inc, b_breadth, b_inc):
        return (a_breadth >= b_breadth and a_inc >= b_inc
                and (a_breadth > b_breadth or a_inc > b_inc))

    if _wider_than(right_breadth, right_included, left_breadth, left_included):
        wider = "right"
    elif _wider_than(left_breadth, left_included, right_breadth, right_included):
        wider = "left"
    else:
        wider = None

    expectation = None
    if wider == "right" and right < left:
        expectation = ("the wider rule returns the smaller count, which cannot "
                       "both be true - one of the counts is wrong or one of "
                       "the rules is mislabelled")
    elif wider == "left" and left < right:
        expectation = ("the wider rule returns the smaller count, which cannot "
                       "both be true - one of the counts is wrong or one of "
                       "the rules is mislabelled")

    return {
        "comparable": False,
        "wider": wider,
        "difference": str(right - left),
        "contradiction": expectation,
        "note": (
            expectation or
            f"different rules, so these answer different questions: "
            f"{describe(left_rule)} against {describe(right_rule)}. The "
            f"difference is not an error in either."),
    }


def as_assumption(rule_dict: dict, *, case_id: str, raised_by: str) -> dict:
    """An incomplete rule as an entry for the assumption register.

    An undecided inclusion is an assumption with a known direction: if nobody
    has said whether franchise locations are in, the count is either too high
    or too low by their number, and which one is knowable.
    """
    undecided = rule_dict.get("undecided") or []
    if not undecided:
        return {}
    return {
        "case_id": case_id,
        "gap": "site-inclusion rule incomplete",
        "detail": (f"the rule does not say whether "
                   f"{', '.join(u.replace('_', ' ').lower() for u in undecided)} "
                   f"are counted. Each is a set of sites the footprint either "
                   f"contains or does not, and the baseline moves by their "
                   f"connectivity cost either way."),
        "costs": ("the site count, which is the largest single driver of the "
                  "baseline"),
        "closes_it": ("ask the client which of these they count as a site, or "
                      "state the assumption and its direction"),
        "raised_by": raised_by,
    }
