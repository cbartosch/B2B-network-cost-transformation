"""Comparing what the estimator said against what turned out to be true.

Audit finding A-01: no case had ever been compared against a real portfolio,
and there was no machinery to do it with. This is that machinery. It does not
constitute validation - a harness with no cases in it validates nothing, and
the corpus is empty.

Two things it deliberately does not do.

**It does not accept synthetic cases as evidence.** A case carries its own
`evidence_tier`, and the statistics report per tier. A mean absolute percentage
error computed over cases somebody invented measures the inventor, and
reporting it beside a real one as though they were the same number is the
failure this module exists to prevent.

**It does not report a central tendency without a spread and a direction.** A
model that is 30% high on half its cases and 30% low on the other half has a
mean signed error near zero and is useless. Bias is the finding; magnitude
alone is not.
"""
from decimal import Decimal, InvalidOperation

# The mandate's preference order. A case records which it is, and the harness
# refuses to blend them.
TIER_ACTUAL = "HISTORICAL_ACTUAL"          # known outturn
TIER_VALIDATED = "VALIDATED_INVENTORY"     # inventory and spend confirmed
TIER_SOURCING = "COMPLETED_SOURCING"       # a finished sourcing exercise
TIER_QUOTED = "CARRIER_QUOTED"             # quoted target design
TIER_SYNTHETIC = "EXPERT_SYNTHETIC"        # reviewed, invented

EMPIRICAL_TIERS = (TIER_ACTUAL, TIER_VALIDATED, TIER_SOURCING, TIER_QUOTED)

# What a case may be compared on. Each is a number the estimator produces and a
# real engagement eventually knows.
MEASURES = ("site_count", "circuit_count", "bandwidth_mbps_total",
            "current_annual_cost", "target_annual_cost", "one_time_cost",
            "feasible_annual_savings")


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def compare(case: dict) -> dict:
    """One case: estimator output against actuals, measure by measure.

    Signed error, not absolute, because the direction is the finding. An
    estimator that understates rural access cost and overstates sourcing
    savings is wrong twice in the same direction - toward a larger prize - and
    an absolute error hides that.
    """
    actual = case.get("actual") or {}
    estimated = case.get("estimated") or {}
    rows = []
    for measure in MEASURES:
        a, e = _dec(actual.get(measure)), _dec(estimated.get(measure))
        if a is None or e is None:
            rows.append({"measure": measure, "actual": None, "estimated": None,
                         "status": "NOT_COMPARABLE",
                         "note": ("the case records no actual for this measure"
                                  if a is None else
                                  "the estimator produced no value")})
            continue
        error = e - a
        rows.append({
            "measure": measure,
            "actual": str(a), "estimated": str(e),
            "signed_error": str(error),
            "abs_error": str(abs(error)),
            "pct_error": (str((error / a * 100).quantize(Decimal("0.1")))
                          if a else None),
            "direction": ("OVER" if error > 0 else
                          "UNDER" if error < 0 else "EXACT"),
            "status": "COMPARED",
        })
    return {
        "case_id": case.get("case_id"),
        "evidence_tier": case.get("evidence_tier"),
        "geography": case.get("geography"),
        "portfolio_size": case.get("site_count_band"),
        "rows": rows,
    }


def statistics(comparisons: list, *, tier_filter: tuple | None = None) -> dict:
    """Error statistics per measure, over cases of one evidence tier.

    `tier_filter` defaults to the empirical tiers. Synthetic cases are excluded
    unless asked for by name, because the whole point of the tier is that a
    number computed over invented cases must not be read as accuracy.
    """
    tiers = tier_filter or EMPIRICAL_TIERS
    included = [c for c in comparisons if c.get("evidence_tier") in tiers]

    per_measure = {}
    for measure in MEASURES:
        errors, pcts = [], []
        for case in included:
            row = next((r for r in case["rows"] if r["measure"] == measure), None)
            if not row or row["status"] != "COMPARED":
                continue
            errors.append(Decimal(row["signed_error"]))
            if row["pct_error"] is not None:
                pcts.append(Decimal(row["pct_error"]))
        if not errors:
            per_measure[measure] = {"n": 0,
                                    "note": "no comparable case for this measure"}
            continue
        abs_pcts = sorted(abs(p) for p in pcts)
        n = len(errors)
        per_measure[measure] = {
            "n": n,
            "mean_absolute_error": str(sum(abs(e) for e in errors) / n),
            "mean_absolute_pct_error": (str(sum(abs_pcts) / len(abs_pcts))
                                        if abs_pcts else None),
            "median_absolute_pct_error": (str(abs_pcts[len(abs_pcts) // 2])
                                          if abs_pcts else None),
            "root_mean_squared_error": str(
                (sum(e * e for e in errors) / n).sqrt()),
            # The direction. A model wrong in one direction is biased; a model
            # wrong in both is imprecise. They need different remedies and the
            # absolute statistics cannot tell them apart.
            "mean_signed_error": str(sum(errors) / n),
            "overestimated": sum(1 for e in errors if e > 0),
            "underestimated": sum(1 for e in errors if e < 0),
        }

    return {
        "cases_included": len(included),
        "cases_excluded_as_synthetic": len(comparisons) - len(included),
        "tiers_included": list(tiers),
        "per_measure": per_measure,
        "note": (
            f"{len(included)} case(s) of tier {list(tiers)}. "
            "These statistics describe those cases and nothing else."
            if included else
            "No case of an empirical tier exists. The estimator has not been "
            "empirically validated against actual enterprise network "
            "portfolios, and no statistic computed here changes that."),
    }


def bias_probes(*, priors: list, archetypes: dict, model_source: str) -> list:
    """The systematic biases an audit asks about, answered structurally.

    Several of the mandate's bias questions do not need actuals: whether the
    model omits taxes, whether it treats wireless backup as equivalent
    capacity, whether it understates transition cost. Those are answerable from
    the model's own structure, and answering them now is worth more than
    waiting for a corpus that does not exist.

    The ones that genuinely need actuals - does it oversize warehouse
    bandwidth, does it misprice small sites - are reported as requiring the
    corpus rather than guessed at.
    """
    findings = []

    def _probe(question, verdict, evidence, needs_corpus=False):
        findings.append({"question": question, "verdict": verdict,
                         "evidence": evidence,
                         "needs_corpus": needs_corpus})

    # --- answerable now, from the model's structure
    # Searched for the concept in the cost build-up, not for the word anywhere
    # in the source. The first version looked for "tax" across every domain
    # module and found it in the prose describing its own absence, so the probe
    # reported NOT_CONFIRMED about a gap it had just documented.
    def _costs_include(*needles):
        """Searches the whole cost module, not just the build-up.

        Bounded to build_components, this reported transition cost absent
        after it was added - because a one-time cost is not a component of the
        recurring baseline and correctly lives in the scenario, where the
        saving it offsets is. A probe scoped to the wrong half of the module
        answers a narrower question than the one it prints.
        """
        return any(n in model_source for n in needles)

    _probe("Does the model omit taxes and one-time charges?",
           "CONFIRMED" if not _costs_include(
               "tax=", "surcharge", "one_time", "nrc=", "install_charge")
           else "NOT_CONFIRMED",
           "no tax, surcharge, NRC or install-charge concept appears in the "
           "cost build-up; every component is a recurring monthly rate "
           "annualised")

    _probe("Does the model understate transition cost?",
           "PARTIALLY_MITIGATED" if _costs_include(
               "transition.net(", "dual_running") else "CONFIRMED",
           "one-time cost, dual running and payback exist since 4.165 and are "
           "evidence grade E - expert assumptions with no quoted transaction "
           "behind them. Six cost categories remain unmodelled and are named "
           "in the output: CPE, licence ramp, internal programme cost, "
           "early-termination liability, construction, temporary capacity")

    _probe("Does the model treat wireless backup as equivalent capacity?",
           "CONFIRMED",
           "a MOBILE_5G backup is counted as a second access path with no "
           "capacity, contention or data-cap distinction from a fixed circuit; "
           "only product identity is checked, and that only since 4.157")

    _probe("Does the model treat satellite as universally available?",
           "NOT_APPLICABLE",
           "satellite is not a product in the vocabulary at all, so the model "
           "cannot assume it - a gap rather than a bias")

    _probe("Does the model assume excessive redundancy?",
           "PARTIALLY_MITIGATED",
           "dual access is a seeded per-archetype probability, not a universal "
           "assumption, and since 4.157 an undeliverable or same-product "
           "backup no longer counts; but the probabilities themselves are "
           "evidence grade F")

    _probe("Does nominal bandwidth stand in for usable throughput?",
           "CONFIRMED",
           "bandwidth_mbps is a single figure used for both sizing and "
           "pricing; no overhead, contention ratio or usable-throughput "
           "concept exists")

    # --- these need the corpus
    for question in (
            "Does the model oversize warehouse bandwidth?",
            "Does the model misprice small sites?",
            "Does the model misprice data centres?",
            "Does the model understate rural access cost?",
            "Does the model overstate sourcing savings?",
            "Does the model understate managed-service scope?"):
        _probe(question, "NOT_ASSESSED",
               "requires cases with known actuals; the corpus is empty",
               needs_corpus=True)

    return findings
