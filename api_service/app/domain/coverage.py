"""V0 prior-coverage gate (spec 0.3C).

Measured against approved reference priors, never against released benchmark
cohorts - the vault is empty until an engagement reaches V2, so a cohort-based
gate would be unsatisfiable for a first engagement.

Two defects in the earlier revision are closed here:

  * the denominator arrived in the request body, so omitting the unpriced
    markets flipped PARTIAL to COMPLETE. Estimated spend is now derived from the
    simulated scope and the priors, and any caller-supplied figure is a
    cross-check that is reported, never the denominator.
  * coverage was assessed per country, so one broadband prior made an all-MPLS
    country "priced". Assessment is now per (country, product) pair.

A third defect, found in the second audit, is closed here. Sizing unpriced scope
by a cross-country median only works when *some* country has a prior for that
product. Where none does, the row was valued at zero - so the exact scope that
could not be priced contributed nothing to the denominator that exists to count
it, and an estate with 500 unpriceable circuits reported COMPLETE at 100%.

The answer is not to invent a rate. It is to stop relying on a measure that
unsizable scope can vanish from. Every row carries a circuit count, always, so
coverage is now assessed on two bases and the worse one governs:

    value coverage    - priced value / total sizable value
    circuit coverage  - priced circuits / total circuits   (never zero-able)
    effective         - min(value, circuit)

and any row that cannot be sized at all forces at minimum PARTIAL, because
COMPLETE asserts that every coverage test passed and no test can pass over scope
whose size is unknown.
"""
from decimal import Decimal
from statistics import median

from .money import D, as_str
from .policy import CoveragePolicy

MONTHS = D("12")


def _fallback_rates(priors: dict) -> dict:
    """Cross-country median rate per product. Used only to size unpriced scope
    for the denominator so it can count against coverage. It never prices a
    component and never reaches the headline."""
    by_product: dict[str, list] = {}
    for key, p in priors.items():
        product = key[1]                     # (country, product, bandwidth_mbps)
        by_product.setdefault(product, []).append(D(p["base"]))
    return {k: D(median(v)) for k, v in by_product.items() if v}


def derive_scope(*, sim_output: dict, priors: dict,
                 sizing_priors: dict | None = None) -> list[dict]:
    """One row per (country, product, role) the simulation actually produced.

    `priors` are the in-scope country priors and determine whether a row is
    *priced*. `sizing_priors` may be the whole approved prior set across every
    country: a German MPLS rate cannot price a Brazilian circuit, but it can
    size one for the denominator. Keeping the two separate shrinks the unsizable
    population without pricing anything at a rate that does not apply to it.
    """
    from .estimate import match_prior
    fallback = _fallback_rates(sizing_priors or priors)
    scope = []
    for row in sim_output.get("products", []):
        mbps = row.get("bandwidth_mbps")
        # Same matcher the estimate prices with. Two different notions of
        # "priced" between the coverage gate and the calculation would mean the
        # gate was measuring something the total did not contain.
        prior, substituted = match_prior(priors, row["country"], row["product"], mbps)
        rate = D(prior["base"]) if prior else fallback.get(row["product"])
        scope.append({
            "country": row["country"], "product": row["product"], "role": row["role"],
            "bandwidth_mbps": mbps,
            "priced_at_bandwidth_mbps": substituted,
            "count": int(row["count"]),
            "priced": prior is not None,
            "rate_basis": "APPROVED_PRIOR" if prior
                          else ("CROSS_COUNTRY_MEDIAN" if rate else "UNSIZED"),
            # Where the approved price itself came from. "APPROVED_PRIOR" said
            # a price existed and not whether it was an indicative seeded
            # figure or a steward-approved benchmark - so coverage reported
            # 100% priced on a portfolio made entirely of placeholders, which
            # measures the seed rather than the client.
            "price_basis": (getattr(prior, "price_basis", None) or "SEED")
                           if prior is not None else None,
            "annual_value": as_str(D(rate) * D(row["count"]) * MONTHS) if rate else "0.00",
        })
    return scope


def assess(*, scope: list[dict], layers_in_scope: list, layers_priced: set,
           policy: CoveragePolicy,
           declared_spend_by_country: dict | None = None) -> dict:
    # No thresholds dict with code defaults behind it: the policy is required
    # and was validated when it was loaded from reference data.
    t = {"v0_prior_coverage_min": policy.prior_coverage_min,
         "v0_prior_coverage_floor": policy.prior_coverage_floor,
         "v0_material_country_floor": policy.material_country_floor,
         "v0_product_coverage_min": policy.product_coverage_min}

    total_value = sum((D(r["annual_value"]) for r in scope), D(0))
    priced_value = sum((D(r["annual_value"]) for r in scope if r["priced"]), D(0))
    total_circuits = sum((int(r["count"]) for r in scope), 0)
    priced_circuits = sum((int(r["count"]) for r in scope if r["priced"]), 0)

    if total_circuits == 0:
        return {"status": "REFUSED", "reason": "no scope to assess",
                "effective_coverage_pct": "0.000", "priced_spend_pct": "0.000",
                "circuit_coverage_pct": "0.000", "scope": scope,
                "unpriced_countries": [], "material_country_breaches": [],
                "unpriced_pairs": [], "unsizable_pairs": [],
                "unpriced_layers": list(layers_in_scope),
                "layer_coverage_pct": "0.000", "thresholds": _fmt(t),
                "policy_set": policy.set_name,
                "unpriced_scope_treatment": "EXCLUDED_FROM_HEADLINE"}

    value_pct = (priced_value / total_value) if total_value else D(0)
    circuit_pct = D(priced_circuits) / D(total_circuits)
    # Unsizable scope cannot hide from a circuit count, so the worse of the two
    # governs. This is what closes the audit finding.
    effective = min(value_pct, circuit_pct)

    by_country: dict[str, list] = {}
    for r in scope:
        by_country.setdefault(r["country"], []).append(r)

    unsizable = sorted({(r["country"], r["product"]) for r in scope
                        if r["rate_basis"] == "UNSIZED"})
    unpriced_pairs = sorted({(r["country"], r["product"]) for r in scope if not r["priced"]})
    unpriced_countries = sorted({c for c, rows in by_country.items()
                                 if not any(r["priced"] for r in rows)})

    # Materiality on either basis, so a wholly unsizable country - whose value
    # share is zero by construction - is still assessed. The earlier version
    # skipped exactly that case.
    material_breaches = []
    for c, rows in sorted(by_country.items()):
        c_value = sum((D(r["annual_value"]) for r in rows), D(0))
        c_circuits = sum((int(r["count"]) for r in rows), 0)
        v_share = (c_value / total_value) if total_value else D(0)
        c_share = D(c_circuits) / D(total_circuits)
        if max(v_share, c_share) < t["v0_material_country_floor"]:
            continue
        c_priced_value = sum((D(r["annual_value"]) for r in rows if r["priced"]), D(0))
        c_priced_circuits = sum((int(r["count"]) for r in rows if r["priced"]), 0)
        v_ratio = (c_priced_value / c_value) if c_value else D(0)
        c_ratio = (D(c_priced_circuits) / D(c_circuits)) if c_circuits else D(0)
        if min(v_ratio, c_ratio) < t["v0_prior_coverage_min"]:
            material_breaches.append(c)

    layer_pct = (D(len(set(layers_priced) & set(layers_in_scope))) / D(len(layers_in_scope))
                 if layers_in_scope else D(0))
    unpriced_layers = sorted(set(layers_in_scope) - set(layers_priced))

    if effective < t["v0_prior_coverage_floor"]:
        status = "REFUSED"
        reason = (f"effective coverage {effective:.1%} is below the absolute floor "
                  f"{t['v0_prior_coverage_floor']:.0%}; an estimate priced on less "
                  f"than two-fifths of its own scope is not an estimate")
    elif (effective < t["v0_prior_coverage_min"] or unsizable or material_breaches
          or layer_pct < t["v0_product_coverage_min"]):
        status = "PARTIAL"
        bits = []
        if effective < t["v0_prior_coverage_min"]:
            bits.append(f"effective coverage {effective:.1%} below minimum "
                        f"{t['v0_prior_coverage_min']:.0%} "
                        f"(value {value_pct:.1%}, circuits {circuit_pct:.1%})")
        if unsizable:
            bits.append("scope that cannot be sized at any approved rate: "
                        + ", ".join(f"{c}/{p}" for c, p in unsizable))
        if material_breaches:
            bits.append("material country floor breached by " + ", ".join(material_breaches))
        if layer_pct < t["v0_product_coverage_min"]:
            bits.append(f"layer coverage {layer_pct:.0%} below minimum "
                        f"{t['v0_product_coverage_min']:.0%}")
        reason = "; ".join(bits)
    else:
        status, reason = "COMPLETE", "all coverage tests passed"

    out = {
        "status": status, "reason": reason,
        "effective_coverage_pct": f"{effective:.3f}",
        "coverage_basis": "MIN_OF_VALUE_AND_CIRCUIT_COVERAGE",
        "priced_spend_pct": f"{value_pct:.3f}",
        "circuit_coverage_pct": f"{circuit_pct:.3f}",
        "priced_spend": as_str(priced_value), "total_estimated_spend": as_str(total_value),
        "priced_circuits": priced_circuits, "total_circuits": total_circuits,
        "spend_basis": "DERIVED_FROM_SIMULATED_SCOPE_AND_PRIORS",
        "unpriced_countries": unpriced_countries,
        "unpriced_pairs": [f"{c}/{p}" for c, p in unpriced_pairs],
        # What share of the priced value rests on an indicative seeded price
        # rather than an approved benchmark. Both were approved=True and
        # indistinguishable, so coverage reported 100% priced on a portfolio
        # entirely made of placeholders - which is a measurement of the seed,
        # not of the client.
        "seeded_price_share": str(
            (D(sum(int(r["count"]) for r in scope
                   if r["priced"] and r.get("price_basis") == "SEED"))
             / D(priced_circuits)).quantize(D("0.001")))
        if priced_circuits else "0",
        "unsizable_pairs": [f"{c}/{p}" for c, p in unsizable],
        "unsizable_circuits": sum(int(r["count"]) for r in scope
                                  if r["rate_basis"] == "UNSIZED"),
        "material_country_breaches": material_breaches,
        "unpriced_layers": unpriced_layers,
        "layer_coverage_pct": f"{layer_pct:.3f}",
        "thresholds": _fmt(t), "policy_set": policy.set_name,
        "unpriced_scope_treatment": "EXCLUDED_FROM_HEADLINE",
        "unpriced_scope_basis": ("circuit count; no approved rate exists for these "
                                 "products in any country, so their value is unknown "
                                 "rather than zero"),
        "scope": scope,
    }

    if declared_spend_by_country:
        declared_total = sum((D(v) for v in declared_spend_by_country.values()), D(0))
        out["declared_spend_crosscheck"] = {
            "declared_total": as_str(declared_total),
            "derived_total": as_str(total_value),
            "divergence_pct": (f"{((declared_total - total_value) / total_value):.3f}"
                               if total_value else "n/a"),
            "countries_declared_but_not_in_scope":
                sorted(set(declared_spend_by_country) - set(by_country)),
            "countries_in_scope_but_not_declared":
                sorted(set(by_country) - set(declared_spend_by_country)),
        }
    return out


def prior_recency(priors: dict, current_year: int, policy: CoveragePolicy) -> Decimal:
    """1.0 for current-year priors, decaying at the governed annual rate and
    floored at the governed minimum. Both were code constants."""
    years = [p.get("price_year") for p in priors.values() if p.get("price_year")]
    if not years:
        return D("0")
    age = D(current_year) - D(int(median(sorted(years))))
    return max(policy.prior_recency_floor,
               min(D("1"), D("1") - policy.prior_recency_annual_decay * age))


def _fmt(t):
    return {k: str(v) for k, v in t.items()}
