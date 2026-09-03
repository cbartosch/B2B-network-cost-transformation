"""Confidence model: derived components, spec 13.2 weighting, 0.6A ceilings.

Two rounds of defect live behind this module, and both are worth remembering.

First, the three component scores were passed in as literals (0.42 / 0.68 /
0.35), so every V0 published the same confidence whatever the evidence. That is
fixed by `derive_components`.

Second - and this is the subtler one - the *weights* that combined them stayed as
Python constants after the unit costs had been moved to reference data. A
governed model whose inputs are governed and whose weights are not is only half
governed. Every number is now supplied by a ConfidencePolicy loaded from
`reference.threshold`, and this module holds no defaults: a missing value raises
rather than silently reverting to a constant.

Order of operations is fixed:
  1. derive the three components from evidence
  2. scale by the stage ceiling. The ceiling is the most a stage could ever
     justify - V0 cannot be confident about realization because the gate matrix
     forbids the evidence that would justify it - and the derived quality
     attains a fraction of it. Truncating instead of scaling looked equivalent
     and was not: the V0 baseline ceiling is 0.55 while a typed-scope run
     already derives 0.65, so every raw score above the ceiling collapsed to the
     same number and the evidence drivers had no effect at V0 whatsoever
  3. weighted sum
  4. spec 13.2 authoritative cap: min(weighted, min(components) + headroom)
  5. spec 0.6A ceilings, which compose downward only

Simulated share deliberately appears only in step 5. Letting it also depress a
component would double-count it against the same evidence.
"""
from decimal import Decimal

from .money import D
from .policy import ConfidencePolicy, PolicyIncomplete, PolicyInvalid  # noqa: F401


def _clamp(v):
    return max(D("0"), min(D("1"), D(v)))


def derive_components(*, policy: ConfidencePolicy, stage: str = "V0",
                      priced_spend_pct, origin_breakdown: dict,
                      domain_completeness, prior_recency, prior_coverage,
                      lever_stage_mix: dict | None = None) -> dict:
    """Returns the three components with the drivers that produced each."""
    if stage not in policy.stage_ceilings:
        raise PolicyIncomplete(f"{policy.set_name} defines no ceilings for stage {stage}")
    ceil = policy.stage_ceilings[stage]

    def share(origin):
        return D((origin_breakdown.get(origin) or {}).get("share", "0"))

    # Public evidence counts fully; a client's first-party statement counts at
    # the governed weight. Summing them at parity would say a self-report and
    # an independently-checkable source are the same kind of claim, and
    # excluding client data entirely would say it is worth nothing - neither is
    # true. See dispositions.DISPOSITIONS for why CLIENT_CONFIRMED is its own
    # class rather than folded into a neighbour.
    client_confirmed = share("CLIENT_CONFIRMED")
    evidenced = (share("EVIDENCED_PUBLIC") + share("DERIVED_PUBLIC")
                 + policy.client_confirmed_evidence_weight * client_confirmed)

    # --- current-baseline: how much of the estate we can actually see and price
    bd = policy.baseline_drivers
    baseline_raw = (bd["priced_spend"] * D(priced_spend_pct)
                    + bd["evidenced"] * evidenced
                    + bd["completeness"] * D(domain_completeness))
    baseline = _clamp(baseline_raw) * ceil["current_baseline"]


    # --- target-cost: quality of the priors the target is built from
    td = policy.target_drivers
    target_raw = (td["prior_coverage"] * D(prior_coverage)
                  + td["prior_recency"] * D(prior_recency))
    target = _clamp(target_raw) * ceil["target_cost"]

    # --- realization: how much of the opportunity rests on evidence that is
    # admissible now versus evidence that only arrives at V3 or V4
    mix = lever_stage_mix or {}
    total_value = sum((D(v) for v in mix.values()), D(0))
    if total_value > 0:
        missing = sorted(set(mix) - set(policy.lever_stage_weight))
        if missing:
            raise PolicyIncomplete(
                f"{policy.set_name} has no lever_stage_weight for {missing}")
        realization_raw = sum((D(v) / total_value) * policy.lever_stage_weight[k]
                              for k, v in mix.items())
    else:
        realization_raw = D("0")
    realization = _clamp(realization_raw) * ceil["realization"]

    return {
        "current_baseline": _clamp(baseline),
        "target_cost": _clamp(target),
        "realization": _clamp(realization),
        "drivers": {
            "priced_spend_pct": str(D(priced_spend_pct)),
            "evidenced_value_share": str(evidenced),
            # Reported separately so a reader can see how much of the
            # evidenced driver rests on the client's own word rather than on
            # something independently checkable.
            "client_confirmed_value_share": str(client_confirmed),
            "client_confirmed_evidence_weight": str(
                policy.client_confirmed_evidence_weight),
            "domain_completeness": str(D(domain_completeness)),
            "prior_coverage": str(D(prior_coverage)),
            "prior_recency": str(D(prior_recency)),
            "lever_stage_mix": {k: str(v) for k, v in mix.items()},
            "policy_set": policy.set_name,
            # Raw quality before the stage scaling, so a reader can tell a weak
            # analysis from a strong one that the stage simply does not permit
            # to be confident yet.
            "raw_before_stage_scaling": {
                "current_baseline": str(_clamp(baseline_raw).quantize(D("0.001"))),
                "target_cost": str(_clamp(target_raw).quantize(D("0.001"))),
                "realization": str(_clamp(realization_raw).quantize(D("0.001")))},
            "stage_ceilings": {k: str(v) for k, v in ceil.items()},
        },
    }


def simulated_ceiling(simulated_share, policy: ConfidencePolicy) -> Decimal | None:
    s = D(simulated_share)
    for upper, ceiling in policy.simulated_bands:
        if s <= upper:
            return ceiling
    # Validation guarantees the top band covers a share of 1, so this is
    # unreachable for a share in [0, 1] and is a bug, not a fallback.
    raise PolicyInvalid(
        f"simulated share {s} falls outside every band in {policy.set_name}")


def band(score, policy: ConfidencePolicy) -> str:
    s, f = D(score), policy.band_floors
    if s >= f["A"]:
        return "A - Confirmed"
    if s >= f["B"]:
        return "B - Supported"
    if s >= f["C"]:
        return "C - Directional"
    return "D - Indicative"


def _one_band_lower(score, policy: ConfidencePolicy) -> Decimal:
    """Below the lowest floor there is no lower band, so apply a proportional
    reduction rather than silently doing nothing."""
    s, f = D(score), policy.band_floors
    for floor in (f["A"], f["B"], f["C"]):
        if s >= floor:
            return floor - D("0.01")
    return _clamp(s * policy.partial_penalty_factor)


def compute(*, policy: ConfidencePolicy, current_baseline, target_cost, realization,
            simulated_share, asserted_share, v0_status,
            # A-02: the share of priced value resting on grade E or F rates.
            # Optional so an estimate that cannot report it behaves as before,
            # rather than a missing figure silently becoming a ceiling.
            unsourced_price_share=None,
            drivers: dict | None = None) -> dict:
    """Every input to a ceiling is required.

    These three defaulted to 0, 0 and "COMPLETE" - the unpenalised state in all
    three cases. A caller that forgot one silently published a higher confidence
    than the evidence supported, which is the direction that matters. A guard
    whose default is "off" is not a guard.
    """
    asserted_ceiling = policy.asserted_ceiling
    asserted_trigger = policy.asserted_trigger

    cb, tc, rz = D(current_baseline), D(target_cost), D(realization)
    applied = []

    # A-02: a baseline built on unsourced rates cannot claim the confidence of
    # one built on quotes. priced_spend_pct counts a circuit as priced whatever
    # stands behind the number, so without this a seeded guess and a cleared
    # benchmark score identically.
    #
    # A ceiling rather than a weight: the estate may be perfectly enumerated
    # and completely priced and still be priced from assumptions. That is a
    # limit on what the number means, not a reduction in how much was seen.
    if unsourced_price_share is not None:
        unsourced = D(str(unsourced_price_share))
        if (unsourced > policy.unsourced_price_share_trigger
                and cb > policy.unsourced_price_ceiling):
            cb = policy.unsourced_price_ceiling
            applied.append(
                f"unsourced_price_ceiling={policy.unsourced_price_ceiling} "
                f"({unsourced:.0%} of priced value rests on expert "
                f"assumptions rather than evidence)")

    if D(asserted_share) > asserted_trigger and cb > asserted_ceiling:
        cb = asserted_ceiling
        applied.append(f"asserted_baseline_confidence_ceiling={asserted_ceiling}")

    sim_ceiling = simulated_ceiling(simulated_share, policy)
    if sim_ceiling is not None and tc > sim_ceiling:
        tc = sim_ceiling
        applied.append(f"simulated_target_confidence_ceiling={sim_ceiling}")

    components = {"current_baseline": cb, "target_cost": tc, "realization": rz}
    weighted = sum(v * policy.weights[k] for k, v in components.items())
    capped = min(weighted, min(components.values()) + policy.component_cap_headroom)

    if v0_status == "PARTIAL":
        lowered = _one_band_lower(capped, policy)
        if lowered < capped:
            capped = lowered
            applied.append("unpriced_scope_confidence_penalty=one_band")

    overall = _clamp(capped)
    out = {
        "current_baseline": str(cb.quantize(D("0.001"))),
        "target_cost": str(tc.quantize(D("0.001"))),
        "realization": str(rz.quantize(D("0.001"))),
        "weighted": str(D(weighted).quantize(D("0.001"))),
        "overall": str(overall.quantize(D("0.001"))),
        "band": band(overall, policy),
        "policy_set": policy.set_name,
        "ceilings_applied": applied,
        "simulated_share": str(D(simulated_share)),
        "asserted_share": str(D(asserted_share)),
    }
    if drivers:
        out["drivers"] = drivers
    return out
