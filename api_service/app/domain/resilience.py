"""Resilience as two things: what a site needs, and what the industry demands.

The industry benchmark carries a criticality tier, a committed share and a
dual-access probability for each industry's *representative* site. Those
figures reached almost nothing: they were applied only where the benchmark's
named archetype appeared in the industry's estate mix, and it does not for 43
of 47 industries. Chemicals, household products and semiconductors returned
byte-identical baselines despite benchmark rows differing by nearly 10x.

Bandwidth never had this problem, because `archetype_bandwidth` is keyed
`(industry, archetype)` - the same key the estate mix uses - and covers 100% of
the pairs that actually occur. This module keys resilience the same way.

**Two axes, not one.**

  what the site needs      a data centre is diverse because it is a data
                           centre; a store is not, because it is a store

  what the industry demands a pharmaceutical office and a retail office are
                           the same building with different consequences when
                           the line drops

Composed rather than chosen between. A pure industry multiplier would give a
Tier 3 industry's data centre 0.5 dual access, which is wrong - a data centre
is a data centre. A pure archetype baseline is what the model already had, and
it is why three industries priced identically.

**The composition.**

Dual access closes the gap toward full diversity by an amount the industry's
criticality tier sets:

    dual = baseline + (1 - baseline) x closure(tier)

A site already fully diverse stays there at every tier. A store in a Tier 1
industry becomes materially more diverse than a store in a Tier 3 one, and
never exceeds 1.0 without a clamp doing the work.

Committed share sits between the site type's need and the industry's posture:

    committed = baseline + (industry_share - baseline) x blend

Both `closure` and `blend` are governed thresholds, because they are the two
numbers that decide how much the industry dimension is allowed to move an
estate, and that is a judgement a steward should be able to retune without a
release.

**What this does not do.** It does not invent a criticality tier for an
industry the benchmark does not cover, and it does not override a tier the
benchmark states. Retail banking is Tier 3 with 0.35 dual access in the
supplied benchmark - arguably wrong for a branch that cannot transact when the
line drops, but that is a data question for whoever stewards the benchmark, not
a correction to make in code.
"""
from decimal import Decimal as D

# How much of the gap to full diversity an industry's criticality closes.
#
# Tier 3 closes none: the site type's own need is the whole answer, which is
# what the model did for every industry before this. Tier 1 closes most of it.
# Calibrated so a Tier 1 industry's representative site lands at or near the
# dual-access figure its own benchmark row states.
TIER_CLOSURE = {
    "Tier 1": D("0.65"),
    "Tier 2": D("0.25"),
    "Tier 3": D("0.00"),
}

# Where committed share sits between the site type and the industry. A half
# weight, because both claims are real: a data hall bursts whatever industry
# owns it, and a regulated industry commits more of whatever it runs.
COMMITTED_BLEND = D("0.5")

# The tier assumed where the benchmark states none. The middle one, so a
# missing tier neither inflates nor flattens an estate.
DEFAULT_TIER = "Tier 2"


def closure_for(tier: str | None) -> D:
    """How much diversity gap this criticality tier closes."""
    return TIER_CLOSURE.get((tier or DEFAULT_TIER).strip(),
                            TIER_CLOSURE[DEFAULT_TIER])


def derive(*, archetype_dual, archetype_committed,
           industry_tier=None, industry_committed=None,
           closure=None, blend=None) -> dict:
    """Resilience for one (industry, archetype) pair, with its arithmetic.

    Returns a record rather than two numbers, for the same reason
    `currency.convert` does: a figure that has been modulated by an industry
    should not be indistinguishable from one that has not.

    Both inputs are optional. With no industry figures this returns the
    archetype baseline unchanged and says so - which is the correct answer for
    an industry the benchmark does not cover, and keeps this callable for an
    estate with no industry at all.
    """
    base_dual = D(str(archetype_dual))
    base_committed = D(str(archetype_committed))

    if industry_tier is None and industry_committed is None:
        return {"dual_access_probability": base_dual,
                "committed_fraction": base_committed,
                "industry_tier": None, "closure": None, "blend": None,
                "basis": "archetype baseline; no industry benchmark applies"}

    gap_closure = D(str(closure)) if closure is not None \
        else closure_for(industry_tier)
    dual = base_dual + (D("1") - base_dual) * gap_closure
    # Clamped rather than trusted. A closure above 1, from a retuned threshold
    # or a bad row, would otherwise produce a probability above certainty.
    dual = max(D("0"), min(D("1"), dual))

    if industry_committed is None:
        committed = base_committed
        used_blend = None
    else:
        used_blend = D(str(blend)) if blend is not None else COMMITTED_BLEND
        committed = base_committed + (
            D(str(industry_committed)) - base_committed) * used_blend
        committed = max(D("0"), min(D("1"), committed))

    return {
        "dual_access_probability": dual,
        "committed_fraction": committed,
        "industry_tier": industry_tier,
        "closure": gap_closure,
        "blend": used_blend,
        "basis": (
            f"site type {base_dual} dual / {base_committed} committed, "
            f"modulated by industry {industry_tier or 'unstated'}"),
    }


def rows_for(archetypes, benchmark_rows, estate_pairs) -> list:
    """Every (industry, archetype) pair an estate can contain, resolved.

    `estate_pairs` is what the estate mixes actually produce - the same key
    space bandwidth already uses. Generating for the benchmark's archetypes
    instead is precisely the defect this replaces: rows keyed on site types
    that no estate contains.

    An industry's tier and committed share come from its benchmark row. Where
    an industry has several rows - an integrated oil company has both an HQ
    and a refinery - the most critical is taken, because an estate's resilience
    posture is set by what it cannot afford to lose, not by its average.
    """
    baseline = {a: (dual, committed) for a, dual, committed in archetypes}

    posture = {}
    for row in benchmark_rows:
        code = row.get("industry_code")
        tier = row.get("criticality_tier")
        share = row.get("committed_share_base")
        if code is None:
            continue
        keep = posture.get(code)
        # "Tier 1" sorts before "Tier 3", so the lexically smallest tier is
        # the most critical.
        if keep is None or str(tier or "Tier 9") < str(keep[0] or "Tier 9"):
            posture[code] = (tier, share)

    out = []
    for industry, archetype in sorted(estate_pairs):
        if archetype not in baseline:
            continue
        base_dual, base_committed = baseline[archetype]
        tier, share = posture.get(industry, (None, None))
        result = derive(archetype_dual=base_dual,
                        archetype_committed=base_committed,
                        industry_tier=tier, industry_committed=share)
        out.append((industry, archetype,
                    str(result["dual_access_probability"]),
                    str(result["committed_fraction"]),
                    tier))
    return out
