"""How reliable a finding is, graded rather than gated.

The previous model was binary: a finding that cleared the source minimum
became evidence, and everything else was thrown away. That reduces an agent to
a deterministic search with extra latency and cost - the whole reason to use
one is that it can read a hedged annual-report footnote, a regulator table and
a trade-press figure and tell you what each is worth. Binning the two that
fall short discards exactly the judgement being paid for.

So nothing found is discarded. Every finding is returned with a grade:

  VERY_RELIABLE  several independent sources, each re-fetched and confirmed to
                 contain the claim, from source classes that publish figures
                 they are accountable for, agreeing closely and recently.
  RELIABLE       real support that falls short on one axis - one source fewer
                 than the bar, an older vintage, a wider spread, a
                 secondary publisher. Usable with judgement; the shortfall is
                 named so the judgement is informed.
  UNRELIABLE     cited but not confirmed, or recalled rather than searched, or
                 self-contradicting. Kept because knowing an agent found this
                 and could not stand it up is itself informative - it tells an
                 analyst the figure is in circulation and where.

**The grade is computed, not asserted.** Every input is observable: how many
sources were independently re-fetched, whether they were returned by a search
this turn or recalled, what class of publisher they are, how far apart the
figures sit, and how old the newest one is. A model grading its own output
would be the same judgement twice.

**A grade is not a permission.** It describes what was found. What may enter an
estimate is a separate, governed decision, and only VERY_RELIABLE maps to
EVIDENCED_PUBLIC without a person. RELIABLE is promotable by a named analyst
who has read the shortfall; UNRELIABLE is not promotable at all. Keeping those
two questions apart is what stops "we kept everything" becoming "we used
everything".
"""
from decimal import Decimal

VERY_RELIABLE = "VERY_RELIABLE"
RELIABLE = "RELIABLE"
UNRELIABLE = "UNRELIABLE"

GRADES = (UNRELIABLE, RELIABLE, VERY_RELIABLE)

# Publisher classes, strongest first. Deliberately coarse: the distinction that
# matters is whether the publisher is accountable for the figure, not a ranking
# of individual outlets.
PRIMARY_HINTS = (
    "annual report", "10-k", "20-f", "form 10", "sec.gov", "investor",
    "regulator", "bundesnetzagentur", "ofcom", "arcep", "fcc.gov", "europa.eu",
    "destatis", "eurostat", "sustainability report", "esg report",
    "capital markets", "prospectus", "handelsregister", "companieshouse",
)
SECONDARY_HINTS = (
    "reuters", "bloomberg", "financial times", "wsj", "handelsblatt",
    "boersen", "trade press", "statista", "ngo", "association",
)


# What the agent reports, mapped to accountability. A filing, a regulator and
# a company's own publication are documents someone is answerable for; press
# and directories report on them.
ACCOUNTABLE = {"PRIMARY_FILING", "REGULATOR", "COMPANY_PUBLISHED"}
REPORTING = {"TRADE_PRESS", "AGGREGATOR"}


def _classify_source(source: dict) -> str:
    """PRIMARY, SECONDARY or UNKNOWN.

    Taken from the agent's reported source_class where it gave one. It read the
    page and knows; keyword-matching a hostname was a guess that was silently
    wrong for anything unfamiliar - a regulator this list has never heard of
    graded the same as a blog.

    The keyword fallback stays for a reply that predates the field or omits it,
    so an older run still grades rather than dropping to UNKNOWN.
    """
    declared = str(source.get("source_class") or "").upper()
    if declared in ACCOUNTABLE:
        return "PRIMARY"
    if declared in REPORTING:
        return "SECONDARY"
    if declared == "OTHER":
        return "UNKNOWN"

    text = " ".join(str(source.get(k) or "").lower()
                    for k in ("publisher", "url", "source_url", "title"))
    if any(hint in text for hint in PRIMARY_HINTS):
        return "PRIMARY"
    if any(hint in text for hint in SECONDARY_HINTS):
        return "SECONDARY"
    return "UNKNOWN"


def grade(*, verified_sources: list, claimed_sources: int, band: dict | None,
          policy, price_year: int, value_parsed: bool = True) -> dict:
    """Grade one finding, and say why.

    `verified_sources` are those independently re-fetched and confirmed to
    contain the claim. `claimed_sources` is what the agent cited, including any
    that could not be confirmed - the gap between the two is the strongest
    single signal there is.
    """
    verified = list(verified_sources or [])
    n_verified = len(verified)
    classes = [_classify_source(s) for s in verified]
    n_primary = classes.count("PRIMARY")
    unconfirmed = max(0, int(claimed_sources or 0) - n_verified)

    signals, penalties = [], []

    if n_verified == 0:
        signals.append("no source was independently confirmed to contain the claim")
        return _result(UNRELIABLE, signals, penalties, n_verified, n_primary,
                       unconfirmed, band)

    if not value_parsed:
        signals.append("the figure is stated in words rather than as a number")
        penalties.append("cannot be priced")

    signals.append(f"{n_verified} source(s) independently re-fetched and "
                   f"confirmed to contain the claim")

    snippets = [s for s in verified
                if str(s.get("how_read") or "").upper() == "SNIPPET_ONLY"]
    if snippets:
        penalties.append(
            f"{len(snippets)} source(s) were seen only as a search snippet, "
            f"not read")
    inferred = [s for s in verified
                if str(s.get("figure_basis") or "").upper() == "INFERRED"]
    if inferred:
        penalties.append(
            f"{len(inferred)} source(s) do not state the figure - it was "
            f"inferred from them")
    if n_primary:
        signals.append(f"{n_primary} of them publish figures they are "
                       f"accountable for (annual report, regulator, filing)")

    # --- the axes a finding can fall short on -----------------------------
    minimum = int(policy.min_independent_sources_material_fact)
    if n_verified < minimum:
        penalties.append(
            f"{n_verified} confirmed source(s) against a governed minimum of "
            f"{minimum}")
    if unconfirmed:
        penalties.append(
            f"{unconfirmed} cited source(s) could not be confirmed to contain "
            f"the claim")
    if not n_primary:
        penalties.append("no source is a publisher accountable for the figure")

    spread = (band or {}).get("spread_share")
    if spread is not None and spread > float(policy.material_spread_share):
        penalties.append(
            f"sources disagree by {spread:.0%}, beyond the governed "
            f"{float(policy.material_spread_share):.0%}")

    newest = (band or {}).get("newest_year")
    if newest and (price_year - int(newest)) > int(policy.stale_after_years):
        penalties.append(
            f"the most recent source is from {newest}, older than the governed "
            f"{policy.stale_after_years}-year window")

    # --- the rule ---------------------------------------------------------
    # Clean on every axis and at or above the source minimum, with at least one
    # accountable publisher. Anything else has a named shortfall, and one
    # shortfall is a downgrade rather than a discard.
    if not penalties and n_verified >= minimum and n_primary:
        return _result(VERY_RELIABLE, signals, penalties, n_verified, n_primary,
                       unconfirmed, band)
    if n_verified >= 1 and value_parsed:
        return _result(RELIABLE, signals, penalties, n_verified, n_primary,
                       unconfirmed, band)
    return _result(UNRELIABLE, signals, penalties, n_verified, n_primary,
                   unconfirmed, band)


def _result(level, signals, penalties, n_verified, n_primary, unconfirmed,
            band) -> dict:
    return {
        "grade": level,
        "supports": signals,
        "shortfalls": penalties,
        "verified_sources": n_verified,
        "primary_sources": n_primary,
        "unconfirmed_sources": unconfirmed,
        "spread_share": (band or {}).get("spread_share"),
        "newest_year": (band or {}).get("newest_year"),
        "statement": _statement(level, signals, penalties),
        # What this grade permits, stated with it so the two are never confused.
        "may_evidence_without_review": level == VERY_RELIABLE,
        "promotable_by_named_analyst": level in (VERY_RELIABLE, RELIABLE),
    }


def _statement(level, signals, penalties) -> str:
    head = {
        VERY_RELIABLE: "Very reliable",
        RELIABLE: "Reliable, with a named shortfall",
        UNRELIABLE: "Unreliable, and kept for what it tells you",
    }[level]
    body = "; ".join(signals[:2])
    tail = ("Short of the bar because " + "; ".join(penalties)
            if penalties else "")
    return ". ".join(p for p in (head, body, tail) if p) + "."


def disposition_for(level: str) -> tuple:
    """(disposition, reason) for a graded finding.

    Only VERY_RELIABLE becomes evidence without a person looking. The other two
    are recorded, visible and promotable-or-not by grade - because a grade
    describes a finding and a disposition governs what may enter an estimate,
    and collapsing the two is how "we kept everything" becomes "we used
    everything".

    RELIABLE and UNRELIABLE stay DECLARED_UNKNOWN deliberately, and not as a
    slight: summarise() counts any other disposition toward domain
    completeness, which feeds confidence, so grading a thin finding upward
    would raise the confidence of an estimate that had not improved.
    """
    if level == VERY_RELIABLE:
        return "EVIDENCED_PUBLIC", None
    if level == RELIABLE:
        return "DECLARED_UNKNOWN", "PARTIAL_EVIDENCE_BELOW_THRESHOLD"
    return "DECLARED_UNKNOWN", "UNRELIABLE_FINDING_RECORDED"
