"""V0 ANCHOR: estimating from a disclosed cost line rather than a priced estate.

The build-up method enumerates sites, turns them into circuits and prices each
one. It is the better method when the estate can be enumerated. For a large
group it usually cannot: DHL's 2025 accounts disclose EUR 213M of
telecommunication costs and EUR 912M of IT services, and no site-by-site WAN,
circuit mix or security-tooling inventory - which is the normal shape of
outside-in Stage 0 work, not an exception. Run through the build-up path such
a case prices zero circuits, coverage computes 0%, and the gate refuses -
correctly by its own rules, and uselessly, because the refusal is about
circuits when the available evidence was never circuits.

This method starts where the evidence is. A disclosed spend line is an
**upper bound**, not an addressable pool: it carries voice, mobile, non-WAN
services and sites outside scope. So the anchor is multiplied by a governed
addressable share to get the pool the transformation could actually touch,
split across cost layers by a governed mix, and handed to the *same* savings
engine the built-up estate uses - the levers name the layers they act on, so
they apply to a pool exactly as they apply to a priced estate.

**What this method is honest about.** The addressable share is an assumption.
It is governed (anchor_policy), stated on the output, and carried into the
confidence model as an assumption rather than as evidence: an anchor estimate
whose anchor is a typed figure cannot present as better-evidenced than one
whose anchor is a corroborated public disclosure. What it does *not* do is
pretend to a site-level precision the source never had - there are no circuit
counts here because none were observed.

Two methods, one savings engine, one confidence model, one set of ceilings.
The analyst chooses the method; neither is a fallback that fires silently.
"""
from decimal import Decimal

from .estimate import Component, MONTHS  # noqa: F401  (MONTHS documents intent)
from .money import D, Range, as_str

METHOD_BUILD_UP = "BUILD_UP"
METHOD_ANCHOR = "ANCHOR"
METHODS = (METHOD_BUILD_UP, METHOD_ANCHOR)

# The anchor's own origin, distinct from the quantity origins the build-up
# path uses: this is a spend figure, not a count of anything.
ANCHOR_DISCLOSED = "EVIDENCED_PUBLIC"
ANCHOR_ASSERTED = "ANALYST_ASSERTED_PRIOR"


class AnchorUnusable(ValueError):
    """The anchor cannot support an estimate."""


def build_pool_components(*, anchor_value, policy, anchor_origin: str,
                          anchor_ref: str | None = None) -> tuple[list, dict]:
    """Turn a disclosed annual spend figure into layer components.

    Returns (components, basis). The components are annual values already -
    unlike the build-up path, which multiplies a monthly circuit rate by
    MONTHS - because a disclosed cost line is an annual figure and converting
    it to a monthly rate only to multiply it back would invent precision.

    The low/high band comes from the governed addressable share, not from any
    spread in the anchor itself: the uncertainty in this method is how much of
    the line is addressable, which is precisely what is not known.
    """
    anchor = D(anchor_value)
    if anchor <= 0:
        raise AnchorUnusable(
            "an anchor of zero or less cannot support an estimate; supply the "
            "disclosed annual spend figure the pool is a share of")

    pool = Range(anchor * policy.addressable_share_low,
                 anchor * policy.addressable_share_base,
                 anchor * policy.addressable_share_high)

    components = []
    for layer, share in sorted(policy.layer_mix.items()):
        if share <= 0:
            continue
        components.append(Component(
            key=f"{layer}_anchor_pool",
            layer=layer,
            driver="addressable_spend",
            # No count was observed. Quantity 1 says "one pool", not one of
            # anything real - the build-up path's quantity-weighted shares
            # would otherwise read a site count into a figure that has none.
            quantity=1,
            quantity_origin=anchor_origin,
            unit_cost_origin="PUBLIC_SPEND_ANCHOR",
            value=Range(pool.low * share, pool.base * share, pool.high * share),
            source_ref=anchor_ref))

    basis = {
        "method": METHOD_ANCHOR,
        "anchor_value": as_str(anchor),
        "anchor_origin": anchor_origin,
        "anchor_known_fact_id": anchor_ref,
        "addressable_share": {
            "low": str(policy.addressable_share_low),
            "base": str(policy.addressable_share_base),
            "high": str(policy.addressable_share_high)},
        "addressable_pool": {"low": as_str(pool.low), "base": as_str(pool.base),
                             "high": as_str(pool.high)},
        "layer_mix": {k: str(v) for k, v in sorted(policy.layer_mix.items())},
        "policy_set": policy.set_name,
        "caveat": (
            "The anchor is a disclosed cost line and an upper bound: it "
            "carries voice, mobile, non-WAN services and out-of-scope sites. "
            "The addressable share is a governed assumption, not an "
            "observation, and the band above is that assumption's range - not "
            "a measurement error on the anchor."),
    }
    return components, basis


def assess_coverage(*, basis: dict, policy, anchor_origin: str) -> dict:
    """Coverage, for a method that has no circuits to count.

    The build-up gate asks what share of the estate could be priced. That
    question has no meaning here: nothing was enumerated. The equivalent
    question is what share of the anchor this estimate claims to explain, and
    whether the anchor itself is evidence or an assertion.

    Returns the same keys the estimate and confidence model already consume,
    so both methods flow through one path from here on.
    """
    share = policy.addressable_share_base
    if share < policy.min_addressable_share:
        status, reason = "REFUSED", (
            f"addressable share {share} is below the governed floor "
            f"{policy.min_addressable_share}: an estimate that claims to "
            f"explain less than that of its own anchor is not an estimate of "
            f"the anchor")
    elif anchor_origin == ANCHOR_DISCLOSED:
        status, reason = "COMPLETE", (
            "anchored on a disclosed figure; the addressable share remains a "
            "governed assumption")
    else:
        status, reason = "PARTIAL", (
            "the anchor is an analyst assertion rather than a disclosed "
            "figure, so the whole estimate rests on an unevidenced number - "
            "register it as a known fact and corroborate it to lift this")

    return {
        "status": status, "reason": reason,
        "coverage_basis": "ADDRESSABLE_SHARE_OF_PUBLIC_ANCHOR",
        "effective_coverage_pct": f"{share:.3f}",
        "priced_spend_pct": f"{share:.3f}",
        "circuit_coverage_pct": "0.000",
        "priced_circuits": 0, "total_circuits": 0,
        "priced_spend": basis["addressable_pool"]["base"],
        "total_estimated_spend": basis["anchor_value"],
        "spend_basis": "PUBLIC_SPEND_ANCHOR_TIMES_ADDRESSABLE_SHARE",
        "unpriced_countries": [], "material_country_breaches": [],
        "unpriced_pairs": [], "unsizable_pairs": [], "unpriced_layers": [],
        "layer_coverage_pct": "1.000",
        "scope": [],
        "policy_set": policy.set_name,
        "unpriced_scope_treatment": "NOT_APPLICABLE_NO_ENUMERATED_SCOPE",
        "anchor_basis": basis,
        "note": (
            "Circuit coverage is zero because no circuits were enumerated, "
            "not because they could not be priced. Comparing this figure with "
            "a BUILD_UP run's coverage compares two different questions."),
    }
