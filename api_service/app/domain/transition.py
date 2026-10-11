"""What it costs to get from the current estate to the target one.

Audit finding P3: the model had no one-time, transition or dual-running cost at
all. Every scenario reported `gross_run_rate_savings` and nothing net, so
payback could not be computed and a reader comparing scenarios was comparing
prizes without their price. The bias probe called the understatement total
rather than partial, which was right.

Three costs, and they are different in kind:

**One-time transition.** Ordering, installing, configuring and cutting over a
site. Charged once per site that changes.

**Dual running.** Both circuits billed while a site is cut over. This is not a
project cost but a duplicated run-rate, and it scales with how long the
migration takes rather than how many sites there are - a 4,000-site programme
at 120 sites a month runs for nearly three years, and three months of dual
running on each site is three months of two bills.

**Nothing for equipment, licences or people.** Those are real and this model
has no basis for them, so it reports them as absent rather than assuming a
number. An omission that is stated is a limitation; one that is not is an
error.

Everything here is evidence grade E - expert assumption, no transaction behind
it - like the rate card. It makes the model more conservative, which is the
right direction for an unevidenced addition. A payback computed from grade E
assumptions is a modelled payback, and `payback_basis` says so.
"""
from decimal import Decimal

from .money import D, Range, as_str

# What this model has no basis for. Reported, not assumed: a reader comparing
# this payback with a real business case needs to know what is missing from it.
NOT_MODELLED = (
    "CPE purchase or refresh",
    "SD-WAN and SASE licence ramp",
    "internal programme and project cost",
    "early-termination liability on the existing contracts",
    "site-survey and construction charges where access is not on-net",
    "temporary capacity during cutover",
)


def _per_site_cost(unit, circuits_per_site, policy):
    """One site's one-time cost at a given circuit density.

    Work that scales with circuits - a CPE and a port per access, the
    cutover of each - and work that scales with the site - configuring and
    testing it once, and the programme overhead of touching it at all.

    At the reference density the two halves reproduce `unit` exactly, so the
    decomposition adds structure without moving the governed level.
    """
    per_circuit = (D(policy.one_time_share_hardware)
                   + D(policy.one_time_share_migration))
    per_site = (D(policy.one_time_share_integration)
                + D(policy.one_time_share_project_management))
    ref = D(policy.one_time_reference_circuits_per_site)
    return D(unit) * (per_circuit * (D(circuits_per_site) / ref) + per_site)


def one_time_build(*, site_mix, policy) -> dict:
    """The one-time cost built by component, over a real estate mix.

    `site_mix` is [{"archetype", "sites", "circuits"}], aggregated from the
    simulated estate, so circuits are the ones the simulation actually drew
    rather than a multiplier anyone chose.

    Replaces a flat charge per site. Every company in the twenty-company
    sample reported exactly 900.00 per site - in four currencies, across
    estates from 43 sites to 16,406, a retail store costing the same as a
    data centre. That number was the governed reference cost and nothing
    about any particular estate.

    Not varied by country or target architecture. Neither is sourced, and
    inventing a country factor to make the output look richer is the thing
    principle 1 of CR-NCT-001 forbids. Both are reported DECLARED_UNKNOWN in
    `not_varied_by`.
    """
    rows, totals = [], {"low": D(0), "base": D(0), "high": D(0)}
    comps = {k: D(0) for k in
             ("hardware", "migration", "integration", "project_management")}
    ref = D(policy.one_time_reference_circuits_per_site)

    for m in site_mix:
        n = int(m.get("sites") or 0)
        if n <= 0:
            continue
        circuits = D(str(m.get("circuits") or n))
        cps = circuits / D(n)
        band = {}
        for k, unit in (("low", policy.one_time_cost_per_site_low),
                        ("base", policy.one_time_cost_per_site_base),
                        ("high", policy.one_time_cost_per_site_high)):
            per_site = _per_site_cost(unit, cps, policy)
            band[k] = per_site * D(n)
            totals[k] += band[k]
        base_unit = D(policy.one_time_cost_per_site_base)
        comps["hardware"] += (circuits * (base_unit / ref)
                              * D(policy.one_time_share_hardware))
        comps["migration"] += (circuits * (base_unit / ref)
                               * D(policy.one_time_share_migration))
        comps["integration"] += (D(n) * base_unit
                                 * D(policy.one_time_share_integration))
        comps["project_management"] += (
            D(n) * base_unit * D(policy.one_time_share_project_management))
        rows.append({
            "archetype": m.get("archetype"),
            "sites": n,
            "circuits": as_str(circuits),
            "circuits_per_site": str(cps.quantize(D("0.001"))),
            "cost_per_site_base": as_str(band["base"] / D(n)),
            "cost_base": as_str(band["base"])})

    return {
        "total": Range(totals["low"], totals["base"], totals["high"]),
        "by_component": {k: as_str(v) for k, v in comps.items()},
        "by_site_type": rows,
        # Every component here is an assumed share of a governed reference
        # cost. None of it is a quoted transaction.
        "origin": {"shares": "ASSUMED", "reference_cost": "ASSUMED",
                   "circuits": "SIMULATED"},
        "not_varied_by": {
            "country": "DECLARED_UNKNOWN - no sourced per-country transition "
                       "cost, and a factor invented to vary it would read as "
                       "evidence",
            "target_architecture": "DECLARED_UNKNOWN - same reason"},
    }


def one_time(*, sites: int, policy) -> Range:
    """The one-time cost of changing `sites` sites, as a band.

    A band rather than a point, because a single number for a cost nobody has
    quoted implies a precision that does not exist - and the low and high
    matter more than the base when the question is whether a payback is inside
    a contract term.
    """
    return Range(D(policy.one_time_cost_per_site_low) * sites,
                 D(policy.one_time_cost_per_site_base) * sites,
                 D(policy.one_time_cost_per_site_high) * sites)


def dual_running(*, sites: int, monthly_run_rate, policy) -> Range:
    """Both circuits billed while each site is cut over.

    Scales with the *duration* of the programme, not just its size: the monthly
    run rate of the sites in flight at any moment, for as long as the migration
    takes. A programme that migrates 120 sites a month has 120 sites paying
    twice at any given time, for `dual_running_months` each.
    """
    per_site_month = (D(monthly_run_rate) / sites) if sites else D(0)
    in_flight = min(sites, int(policy.sites_migrated_per_month))
    months = D(policy.dual_running_months)
    central = per_site_month * in_flight * months
    # The band reflects programme slippage, not price uncertainty: a migration
    # that takes twice as long pays twice as much dual running.
    return Range(central * D("0.6"), central, central * D("2.0"))


def programme_months(*, sites: int, policy) -> int:
    """How long the migration runs, which is what makes a payback real.

    A payback of eighteen months means nothing if the programme itself takes
    thirty-three: the savings do not begin until a site is cut over.
    """
    rate = int(policy.sites_migrated_per_month) or 1
    return -(-sites // rate)          # ceiling division


def net(*, gross_annual: Range, sites: int, monthly_run_rate, policy,
        site_mix=None) -> dict:
    """Net savings and payback, with what they rest on.

    `gross_annual` is the run-rate saving once the estate is fully migrated.
    Net subtracts nothing from it - a run-rate saving is a run-rate saving -
    but payback is computed against the one-time and dual-running cost, which
    is the number a business case turns on.

    Sign convention: cost is positive, saving is positive, and payback is
    reported in months with `None` where the saving cannot repay the cost at
    all. Returning a very large number there would read as a long payback
    rather than as no payback.
    """
    # The component build where the estate mix is known, the flat reference
    # where it is not. A caller without a mix gets what it always got, and
    # the origin says which it was.
    build = (one_time_build(site_mix=site_mix, policy=policy)
             if site_mix else None)
    otc = build["total"] if build else one_time(sites=sites, policy=policy)
    dual = dual_running(sites=sites, monthly_run_rate=monthly_run_rate,
                        policy=policy)
    total_cost = Range(otc.low + dual.low, otc.base + dual.base,
                       otc.high + dual.high)

    def _payback(cost, annual):
        if annual <= 0:
            return None
        return int((cost / annual * 12).to_integral_value(rounding="ROUND_CEILING"))

    # Deliberately crossed: the pessimistic payback pairs the high cost with
    # the low saving, because those are the same world. Pairing high with high
    # would report a payback nobody could have.
    return {
        "one_time_cost": otc.to_dict(),
        # CR-04: what the one-time cost is made of, and what it does not vary
        # by. Absent when the caller supplied no estate mix, which is itself
        # the answer to "why is this flat?".
        "one_time_cost_build": (
            {k: v for k, v in build.items() if k != "total"} if build
            else {"origin": {"shares": "ASSUMED",
                             "reference_cost": "ASSUMED",
                             "circuits": "NOT_SUPPLIED"},
                  "note": "flat per-site reference cost: no estate mix was "
                          "supplied, so cost per site is identical for every "
                          "site type"}),
        "dual_running_cost": dual.to_dict(),
        "total_transition_cost": total_cost.to_dict(),
        "gross_run_rate_savings": gross_annual.to_dict(),
        # Year one only: the saving accrues as sites migrate, and the
        # transition is paid during the same period.
        "first_year_net": as_str(gross_annual.base - total_cost.base),
        "payback_months": {
            "optimistic": _payback(total_cost.low, gross_annual.high),
            "base": _payback(total_cost.base, gross_annual.base),
            "pessimistic": _payback(total_cost.high, gross_annual.low),
        },
        "programme_months": programme_months(sites=sites, policy=policy),
        "payback_basis": (
            f"Modelled. Transition cost is evidence grade "
            f"{policy.evidence_grade} - an expert assumption with no quoted "
            f"transaction behind it - so this payback is a modelled payback "
            f"and not a business case. It excludes "
            f"{len(NOT_MODELLED)} cost categories this model has no basis "
            f"for."),
        "not_modelled": list(NOT_MODELLED),
        "note": (
            f"Savings do not begin until a site is cut over, and this "
            f"programme runs {programme_months(sites=sites, policy=policy)} "
            f"month(s) at {policy.sites_migrated_per_month} sites a month. A "
            f"payback shorter than the programme is arithmetic, not a "
            f"schedule."),
    }
