"""Deterministic Stage 0 TCO and scenario engine (spec 0.3 step 5, 12.1).

Every cost component carries the provenance of its *quantity*. That is what makes
the 0.6A simulated share computable rather than assumed: a component counts as
simulated when the simulation decided how many there are, even though its unit
price came from an approved reference prior.

The decomposition that matters: the primary access circuit count follows
deterministically from the supplied footprint, so it inherits the footprint's
origin. Only the backup layer is decided by the seeded draw. Attributing the
whole underlay to SIMULATED would overstate what the simulation actually
contributed, and would push confidence down for the wrong reason.

Levers apply per cost layer, using reference.savings_lever.cost_layers, and
compound on each component's remaining value rather than on the whole baseline.
That is the double-counting control in 0.2D.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from .money import D, Range, as_str

SIMULATED = "SIMULATED"

# The scope frame the analyst declared at intake: how many sites, how many
# users. It is a premise of the engagement, not a claim about the world, so it
# does not trip the assertion ceiling - though it is not evidenced either, and
# lowers baseline confidence through the driver blend.
#
# ANALYST_ASSERTED_PRIOR previously covered both this and a registered known
# fact under 0.1B. Overloading them meant asserted share read ~0.96 on every
# default run and the ceiling fired every time, which made it a constant rather
# than a control.
ANALYST_ENTERED_SCOPE = "ANALYST_ENTERED_SCOPE"
ANALYST_ASSERTED_PRIOR = "ANALYST_ASSERTED_PRIOR"

# Two distinct things shared one origin until now, and the conflation made a
# control useless. `ANALYST_ASSERTED_PRIOR` meant both "the analyst typed a site
# count into the scope form" and "someone registered a known fact under 0.1B".
# On a default run the typed footprint drove primary access, overlay, SSE and
# operations, so asserted share read ~0.96 against a 0.25 trigger and the
# asserted-baseline ceiling fired on every estimate ever produced - a constant
# wearing a control's clothing.
#
# They are different claims. Typed scope is the perimeter of the question being
# asked; it earns no evidenced credit and therefore already depresses the
# baseline through the evidenced-share driver. A registered known fact is an
# attributable assumption about the world, and relying on one is what the
# ceiling exists to penalise.
ANALYST_ENTERED_SCOPE = "ANALYST_ENTERED_SCOPE"
ANALYST_ASSERTED_PRIOR = "ANALYST_ASSERTED_PRIOR"
EVIDENCED_PUBLIC = "EVIDENCED_PUBLIC"

LAYERS = ("L0", "L1", "L2", "L3", "L4", "OPS")
MONTHS = D("12")


@dataclass
class Component:
    key: str
    layer: str
    driver: str                  # what sets the quantity
    quantity: int
    quantity_origin: str         # SIMULATED | ANALYST_ENTERED_SCOPE | ANALYST_ASSERTED_PRIOR ...
    unit_cost_origin: str        # BENCHMARK_PRIOR for every Stage 0 component
    value: Range = field(default_factory=Range.zero)
    source_ref: str | None = None    # known_fact_id where a fact supplied it

    def to_dict(self):
        return {"key": self.key, "layer": self.layer, "driver": self.driver,
                "quantity": self.quantity, "quantity_origin": self.quantity_origin,
                "unit_cost_origin": self.unit_cost_origin,
                "source_ref": self.source_ref, "value": self.value.to_dict()}


def build_components(*, sim_output: dict, users: int, ops_cost_per_site: dict,
                     priors: dict,
                     driver_origins: dict | None = None,
                     driver_refs: dict | None = None,
                     overlay_unit: dict | None = None,
                     sse_unit: dict | None = None) -> tuple[list[Component], list[dict]]:
    """priors keyed by (country, product) with low/base/high monthly recurring charge.

    Returns (components, unpriced) - unpriced quantities are excluded from the
    total and reported, never defaulted to a neighbouring country's rate and
    never valued at zero (spec 0.3C.2).
    """
    # Platform rates come from reference.platform_unit_cost. There is no fallback
    # constant: a missing platform prior is unpriced scope, reported and
    # excluded, exactly like a missing access prior.
    # Per-driver provenance. Defaults to the declared scope frame; a registered
    # known fact under 0.1B overrides its driver, and corroborating that fact
    # upgrades it again to EVIDENCED_PUBLIC.
    origins = {"sites": ANALYST_ENTERED_SCOPE, "users": ANALYST_ENTERED_SCOPE}
    origins.update(driver_origins or {})
    site_origin, users_origin = origins["sites"], origins["users"]

    # Attribution: the known_fact_id that supplied the origin, so a reader can
    # get from a figure to the person who asserted the number behind it.
    refs = driver_refs or {}
    footprint_ref, users_ref = refs.get("sites"), refs.get("users")

    components: list[Component] = []
    unpriced: list[dict] = []

    for row in sim_output.get("products", []):
        prior = priors.get((row["country"], row["product"]))
        if not prior:
            unpriced.append({**row, "reason": "NO_APPROVED_PRIOR"})
            continue
        # A backup circuit exists only because the seeded draw put it there.
        origin = SIMULATED if row["role"] == "BACKUP" else site_origin
        qty = int(row["count"])
        value = Range(prior["low"], prior["base"], prior["high"]).scale(D(qty) * MONTHS)
        components.append(Component(
            key=f"L0_{row['role'].lower()}_{row['country']}_{row['product']}",
            layer="L0", driver="circuits", quantity=qty,
            quantity_origin=origin, unit_cost_origin="BENCHMARK_PRIOR", value=value,
            source_ref=None if row["role"] == "BACKUP" else footprint_ref))

    sites = int(sim_output.get("sites", 0))
    if overlay_unit:
        components.append(Component(
            key="L2_overlay", layer="L2", driver="sites", quantity=sites,
            quantity_origin=site_origin, unit_cost_origin="BENCHMARK_PRIOR",
            source_ref=footprint_ref,
            value=Range(overlay_unit["low"], overlay_unit["base"],
                        overlay_unit["high"]).scale(D(sites) * MONTHS)))
    else:
        unpriced.append({"product": "SDWAN_OVERLAY", "role": "PLATFORM",
                         "reason": "NO_APPROVED_PRIOR"})

    if sse_unit:
        components.append(Component(
            key="L4_sse", layer="L4", driver="users", quantity=int(users),
            quantity_origin=users_origin, unit_cost_origin="BENCHMARK_PRIOR",
            source_ref=users_ref,
            value=Range(sse_unit["low"], sse_unit["base"],
                        sse_unit["high"]).scale(D(users) * MONTHS)))
    else:
        unpriced.append({"product": "SSE_LICENCE", "role": "PLATFORM",
                         "reason": "NO_APPROVED_PRIOR"})

    components.append(Component(
        # Quantity is sites, so it inherits the footprint's provenance. The
        # per-site rate is a separate axis: unit_cost_origin. A known fact about
        # operating cost supplies a rate, not a quantity, and the 0.6A shares are
        # quantity-weighted - so it is not bindable here and stays informational.
        key="OPS_operations", layer="OPS", driver="sites", quantity=sites,
        quantity_origin=site_origin, unit_cost_origin="BENCHMARK_PRIOR",
        source_ref=footprint_ref,
        value=Range(ops_cost_per_site["low"], ops_cost_per_site["base"],
                    ops_cost_per_site["high"]).scale(D(sites))))

    return components, unpriced


def total(components) -> Range:
    out = Range.zero()
    for c in components:
        out = out + c.value
    return out


def simulated_share(components) -> Decimal:
    """Spec 0.6A input: share of bill-of-materials value whose quantity came from
    simulated structure. Computed on the base case; zero when nothing is simulated."""
    tot = total(components).base
    if tot == 0:
        return D(0)
    sim = sum((c.value.base for c in components
               if c.quantity_origin == SIMULATED), D(0))
    return (D(sim) / tot).quantize(D("0.0001"))


def _share_of(components, origin) -> Decimal:
    tot = total(components).base
    if tot == 0:
        return D(0)
    part = sum((c.value.base for c in components
                if c.quantity_origin == origin), D(0))
    return (D(part) / tot).quantize(D("0.0001"))


def asserted_share(components) -> Decimal:
    """Value share whose quantity came from a *registered known fact*.

    This is what the 0.6A asserted-baseline ceiling triggers on, so it now fires
    only when the estimate actually leans on an uncorroborated assertion. A
    corroborated known fact is superseded by the public fact that corroborated
    it (0.1B) and carries EVIDENCED_PUBLIC, so it does not count here - which
    makes corroboration worth doing rather than merely recorded.
    """
    return _share_of(components, ANALYST_ASSERTED_PRIOR)


def entered_scope_share(components) -> Decimal:
    """The declared scope frame. Reported so a reader can see how much of the
    estimate rests on the premise they supplied, but never a ceiling trigger:
    it is what they asked to have estimated, not a claim about the world."""
    return _share_of(components, ANALYST_ENTERED_SCOPE)


def known_fact_refs(components) -> dict:
    """known_fact_id -> value it accounts for, so the interface can show which
    registered facts are actually load-bearing rather than merely filed."""
    out: dict = {}
    for c in components:
        if c.source_ref:
            out[c.source_ref] = out.get(c.source_ref, D(0)) + c.value.base
    return {k: as_str(v) for k, v in sorted(out.items())}


def entered_share(components) -> Decimal:
    """Value share whose quantity is the analyst's typed scope. Reported, and it
    depresses the baseline through the evidenced-share driver, but it does not
    trigger the assertion ceiling: declaring a perimeter is not the same act as
    relying on an unverified claim about the world."""
    return _share_of(components, ANALYST_ENTERED_SCOPE)


def lever_stage_mix(scenario: dict, levers_by_id: dict) -> dict:
    """Savings value grouped by the stage at which its supporting evidence first
    becomes admissible. Feeds realization confidence."""
    mix: dict[str, Decimal] = {}
    for applied in scenario.get("levers", []):
        stage = (levers_by_id.get(applied["lever_id"], {})
                 .get("earliest_supported_stage") or "V3")
        mix[stage] = mix.get(stage, D(0)) + D(applied["saving_base"])
    return mix


def origin_breakdown(components) -> dict:
    """Value by quantity origin, so the interface can show where the share comes
    from rather than only that it exists."""
    tot = total(components).base
    agg: dict[str, Decimal] = {}
    for c in components:
        agg[c.quantity_origin] = agg.get(c.quantity_origin, D(0)) + c.value.base
    return {k: {"value": as_str(v),
                "share": str((v / tot).quantize(D("0.0001"))) if tot else "0.0000"}
            for k, v in sorted(agg.items())}


SCENARIOS = [("A", "Reprice current state"), ("B", "Optimized SD-WAN"),
             ("C", "SASE northstar"), ("D", "Carrier-managed NaaS")]


def scenarios(components: list[Component], levers: list[dict]) -> dict:
    """Apply each lever only to the cost layers it names, compounding on each
    component's remaining value. Layer composition is preserved into the target,
    which is what makes the target-side simulated share meaningful."""
    current = total(components)
    out = {}

    for code, label in SCENARIOS:
        remaining = {c.key: [c.value.low, c.value.base, c.value.high] for c in components}
        by_key = {c.key: c for c in components}
        applied = []

        for lever in sorted([l for l in levers if l["scenario"] == code],
                            key=lambda x: x["lever_id"]):
            layers = set(lever.get("cost_layers") or [])
            s_lo, s_ba, s_hi = (D(lever["saving_low"]), D(lever["saving_base"]),
                                D(lever["saving_high"]))
            cut_total = D(0)
            for key, comp in by_key.items():
                if comp.layer not in layers:
                    continue
                lo, ba, hi = remaining[key]
                # Conservative pairing: the small saving comes off the high cost.
                c_lo, c_ba, c_hi = hi * s_lo, ba * s_ba, lo * s_hi
                remaining[key] = [lo - c_hi, ba - c_ba, hi - c_lo]
                cut_total += c_ba
            if cut_total:
                applied.append({"lever_id": lever["lever_id"], "family": lever["family"],
                                "description": lever["description"],
                                "cost_layers": sorted(layers),
                                "saving_base": as_str(cut_total)})

        target_components = [
            Component(key=c.key, layer=c.layer, driver=c.driver, quantity=c.quantity,
                      quantity_origin=c.quantity_origin,
                      unit_cost_origin=c.unit_cost_origin,
                      value=Range(*remaining[c.key]), source_ref=c.source_ref)
            for c in components]

        target = total(target_components)
        saving = current - target
        out[code] = {
            "label": label,
            "target_tco": target.to_dict(),
            "gross_run_rate_savings": saving.to_dict(),
            "savings_pct_base": (f"{(saving.base / current.base):.3f}"
                                 if current.base else "0.000"),
            "levers": applied,
            # Derived per scenario. Scenario C strips L2/L4, which are not
            # simulated, so its simulated share is higher than scenario A's.
            "simulated_share": str(simulated_share(target_components)),
            "origin_breakdown": origin_breakdown(target_components),
            "target_components": [c.to_dict() for c in target_components],
        }
    return out


def current_tco(components: list[Component]) -> dict:
    by_layer: dict[str, Range] = {}
    for c in components:
        by_layer[c.layer] = by_layer.get(c.layer, Range.zero()) + c.value
    return {"by_layer": {k: v.to_dict() for k, v in sorted(by_layer.items())},
            "total": total(components).to_dict(),
            "simulated_share": str(simulated_share(components)),
            "origin_breakdown": origin_breakdown(components),
            "components": [c.to_dict() for c in components]}
