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

from . import locations
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
# First-party client data (Tranche 3). A distinct origin, not a synonym for
# either neighbour - see dispositions.DISPOSITIONS. Deliberately excluded from
# asserted_share(): the 0.6A asserted-baseline ceiling penalises reliance on an
# unverified *analyst* claim, and a client's statement about their own estate
# is not that. It is discounted instead through the governed
# client_confirmed_evidence_weight in the confidence model.
CLIENT_CONFIRMED = "CLIENT_CONFIRMED"

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
    # What this component is actually made of, where that is known.
    #
    # A lever declares the cost layers it acts on, and layer membership was the
    # only eligibility test: LEV-MPLS-001 declares ["L0"] and L0 is the whole
    # access layer, so MPLS substitution was applied to broadband and mobile
    # circuits identically. On 100 HFC stores that books 24,000 of savings from
    # substituting MPLS in an estate holding no MPLS.
    #
    # The key already encoded the product. Parsing it back out would be a
    # second source of truth for the same fact, so the component carries it.
    product: str | None = None
    role: str | None = None          # PRIMARY | BACKUP | PLATFORM

    def to_dict(self):
        return {"key": self.key, "layer": self.layer, "driver": self.driver,
                "quantity": self.quantity, "quantity_origin": self.quantity_origin,
                "unit_cost_origin": self.unit_cost_origin,
                "product": self.product, "role": self.role,
                "source_ref": self.source_ref, "value": self.value.to_dict()}



def match_prior(priors: dict, country: str, product: str, mbps) -> tuple:
    """Find the price for this circuit, at the bandwidth it needs.

    `priors` is keyed (country, product, bandwidth_mbps). An exact tier is
    used as-is. Failing that, the cheapest tier *at or above* the requirement
    is used - a 100 Mbps rate cannot serve a 500 Mbps circuit, so substituting
    downward would understate the estimate, which is the direction that turns
    into a savings number nobody can deliver.

    Returns (prior, substituted_bandwidth). substituted_bandwidth is None on
    an exact match and the tier actually used otherwise, so the substitution
    is recorded on the component rather than absorbed - the same rule the rest
    of this module applies to unpriced scope: report it, never default it
    silently.
    """
    exact = priors.get((country, product, mbps))
    if exact:
        return exact, None
    above = sorted(
        ((bw, pr) for (c, p, bw), pr in priors.items()
         if c == country and p == product and bw is not None and mbps is not None
         and bw >= mbps),
        key=lambda t: D(t[1]["base"]))
    if above:
        return above[0][1], above[0][0]
    return None, None


def build_components(*, sim_output: dict, users: int, ops_cost_per_site: dict,
                     priors: dict,
                     driver_origins: dict | None = None,
                     # What share of each country's estate exists as a named
                     # location. Optional: without it every site-driven
                     # component keeps one origin, which is how this behaved
                     # before locations existed.
                     enumeration: dict | None = None,
                     driver_refs: dict | None = None,
                     overlay_unit: dict | None = None,
                     sse_unit: dict | None = None) -> tuple[list[Component], list[dict]]:
    """priors keyed by (country, product, bandwidth_mbps) with low/base/high
    monthly recurring charge. See match_prior for how a circuit finds its tier.

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

    def _estate_components(base: Component) -> list[Component]:
        """A component driven by the whole site count rather than one country.

        The overlay and the operations line are per site across the estate, so
        there is no country to look up - the split uses the overall enumerated
        share. These carried one origin for the whole estate while the L0
        circuits were split, so the origin mix was only partly
        enumeration-aware.
        """
        if not enumeration or not enumeration.get("total"):
            return [base]
        share = D(enumeration.get("enumerated_share") or 0)
        if share <= 0 or share >= 1:
            return [base]
        residual = locations._residual_origin(base.quantity_origin)
        if residual == base.quantity_origin:
            return [base]
        return _split(base, [(base.quantity_origin, share),
                             (residual, D(1) - share)])

    def _site_components(base: Component, country: str) -> list[Component]:
        """One site-driven component, split by how much of that country is named.

        A footprint that is part named and part tallied cannot be described by a
        single origin, and Component carries one - so the value is apportioned
        by exact share across the split the enumeration reports. Deterministic:
        no sampling, and the shares sum to the original value.

        The residual takes the weaker of PUBLIC_DERIVED and the footprint's own
        origin, so naming sites raises confidence for the part that was named
        and never for the rest.
        """
        split = (locations.origin_split(enumeration, country,
                                        base.quantity_origin)
                 if enumeration else [(base.quantity_origin, D(1))])
        if len(split) == 1:
            return [base]
        return _split(base, split)

    def _split(base: Component, split: list) -> list[Component]:
        """Apportion one component's quantity and value across an origin split.

        Largest remainder, not truncation: int(350 * 0.107) + int(350 * 0.893)
        is 349, so every split lost a circuit and a quantity of 1 vanished
        entirely. The component list is serialised into the snapshot, so the
        audit record showed fewer circuits than the simulation produced - which
        is the one thing that list exists to make checkable.
        """
        raw = [D(base.quantity) * share for _o, share in split]
        counts = [int(r) for r in raw]
        remaining = base.quantity - sum(counts)
        for index in sorted(range(len(raw)),
                            key=lambda i: raw[i] - counts[i],
                            reverse=True)[:remaining]:
            counts[index] += 1

        out = []
        for (origin, share), quantity in zip(split, counts):
            if share <= 0:
                continue
            out.append(Component(
                key=f"{base.key}_{origin.lower()}",
                layer=base.layer, driver=base.driver,
                quantity=quantity,
                quantity_origin=origin,
                unit_cost_origin=base.unit_cost_origin,
                # Value scales by the exact share, not by the apportioned
                # count: the shares sum to one so the parts sum to the whole,
                # and rounding a value to follow a rounded quantity would move
                # money to make a count tidy.
                value=base.value.scale(share),
                source_ref=base.source_ref))
        return out

    for row in sim_output.get("products", []):
        mbps = row.get("bandwidth_mbps")
        prior, substituted = match_prior(priors, row["country"], row["product"], mbps)
        if not prior:
            unpriced.append({**row, "reason": "NO_APPROVED_PRIOR_AT_BANDWIDTH"
                             if mbps else "NO_APPROVED_PRIOR"})
            continue
        # A backup circuit exists only because the seeded draw put it there.
        origin = SIMULATED if row["role"] == "BACKUP" else site_origin
        qty = int(row["count"])
        value = Range(prior["low"], prior["base"], prior["high"]).scale(D(qty) * MONTHS)
        _base = Component(
            key=(f"L0_{row['role'].lower()}_{row['country']}_{row['product']}"
                 + (f"_{mbps}M" if mbps else "")
                 + (f"_priced_at_{substituted}M" if substituted else "")),
            layer="L0", driver="circuits", quantity=qty,
            quantity_origin=origin, unit_cost_origin="BENCHMARK_PRIOR",
            product=row["product"], role=row["role"],
            value=value,
            source_ref=None if row["role"] == "BACKUP" else footprint_ref)
        # A backup circuit is SIMULATED whatever the enumeration says, so it is
        # not split: the seeded draw put it there, not a named site.
        components.extend([_base] if row["role"] == "BACKUP"
                          else _site_components(_base, row["country"]))

    sites = int(sim_output.get("sites", 0))
    if overlay_unit:
        # Split like the circuits. This carried one origin for the whole
        # estate while the L0 circuits were split, so the origin mix was only
        # partly enumeration-aware - and the overlay is per site, which is
        # exactly the quantity the enumeration describes.
        components.extend(_estate_components(Component(
            key="L2_overlay", layer="L2", driver="sites", quantity=sites,
            quantity_origin=site_origin, unit_cost_origin="BENCHMARK_PRIOR",
            product="SD_WAN_OVERLAY", role="PLATFORM",
            source_ref=footprint_ref,
            value=Range(overlay_unit["low"], overlay_unit["base"],
                        overlay_unit["high"]).scale(D(sites) * MONTHS))))
    else:
        unpriced.append({"product": "SDWAN_OVERLAY", "role": "PLATFORM",
                         "reason": "NO_APPROVED_PRIOR"})

    if sse_unit:
        components.append(Component(
            key="L4_sse", layer="L4", driver="users",
            product="SSE_LICENCE", role="PLATFORM", quantity=int(users),
            quantity_origin=users_origin, unit_cost_origin="BENCHMARK_PRIOR",
            source_ref=users_ref,
            value=Range(sse_unit["low"], sse_unit["base"],
                        sse_unit["high"]).scale(D(users) * MONTHS)))
    else:
        unpriced.append({"product": "SSE_LICENCE", "role": "PLATFORM",
                         "reason": "NO_APPROVED_PRIOR"})

    # Split like the circuits and the overlay. This is per site across the
    # estate, so leaving it on one origin meant the OPS layer's whole value
    # counted as evidenced while the circuits driven by the same site count
    # were split - the origin mix was partly enumeration-aware, which is worse
    # than not at all because it is not visible in the total.
    components.extend(_estate_components(Component(
        # Quantity is sites, so it inherits the footprint's provenance. The
        # per-site rate is a separate axis: unit_cost_origin. A known fact about
        # operating cost supplies a rate, not a quantity, and the 0.6A shares are
        # quantity-weighted - so it is not bindable here and stays informational.
        key="OPS_operations", layer="OPS", driver="sites", quantity=sites,
        product=None, role="PLATFORM",
        quantity_origin=site_origin, unit_cost_origin="BENCHMARK_PRIOR",
        source_ref=footprint_ref,
        value=Range(ops_cost_per_site["low"], ops_cost_per_site["base"],
                    ops_cost_per_site["high"]).scale(D(sites)))))

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


def client_confirmed_share(components) -> Decimal:
    """Value share whose quantity came from the client's own statement.

    Reported so a reader can see how much of the baseline rests on
    first-party data. Not a ceiling trigger: it is discounted through the
    evidenced driver instead, which is the proportionate treatment for a
    source that is attributable and relevant but not independently checkable.
    """
    return _share_of(components, CLIENT_CONFIRMED)


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
        applied, not_applied = [], []

        for lever in sorted([l for l in levers if l["scenario"] == code],
                            key=lambda x: x["lever_id"]):
            layers = set(lever.get("cost_layers") or [])
            # What the lever can act on, beyond the layer it sits in.
            #
            # Layer membership was the whole eligibility test, and L0 is the
            # entire access layer - so LEV-MPLS-001 applied MPLS substitution
            # to broadband and mobile circuits and booked savings from
            # replacing MPLS in estates that held none. On 100 HFC stores that
            # is 24,000 of savings against zero MPLS circuits.
            #
            # The arithmetic was correct throughout. The result was
            # semantically false, which is worse than an arithmetic error
            # because nothing in the output looks wrong.
            #
            # None means unconstrained: repricing and billing cleanup act on
            # any circuit whatever its technology.
            eligible = lever.get("applies_to_products")
            eligible = set(eligible) if eligible else None
            s_lo, s_ba, s_hi = (D(lever["saving_low"]), D(lever["saving_base"]),
                                D(lever["saving_high"]))
            cut_total = D(0)
            skipped = []
            for key, comp in by_key.items():
                if comp.layer not in layers:
                    continue
                if eligible is not None and comp.product not in eligible:
                    # Recorded, not silently dropped: "this lever found nothing
                    # to act on" is a finding about the estate, and an analyst
                    # comparing scenarios needs to know a lever was offered and
                    # did not apply.
                    skipped.append(comp.product or "unknown")
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
                                "applies_to_products": (sorted(eligible)
                                                        if eligible else None),
                                "saving_base": as_str(cut_total)})
            elif eligible is not None:
                # Offered and inapplicable. A scenario that quietly contains
                # fewer levers than it declares reads as a weaker opportunity
                # rather than a different estate, and the difference matters:
                # "no MPLS to substitute" is a fact about the client.
                not_applied.append({
                    "lever_id": lever["lever_id"], "family": lever["family"],
                    "applies_to_products": sorted(eligible),
                    "products_present": sorted(set(skipped)),
                    "reason": (
                        f"{lever['family']} acts on "
                        f"{', '.join(sorted(eligible))}, and this estate's "
                        f"{', '.join(sorted(set(skipped))) or 'components'} in "
                        f"{'/'.join(sorted(layers))} contain none of them. No "
                        f"saving is booked.")})

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
            # Levers this scenario offers that found nothing to act on. A
            # scenario quietly containing fewer levers than it declares reads
            # as a weaker opportunity rather than a different estate.
            "levers_not_applicable": not_applied,
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
