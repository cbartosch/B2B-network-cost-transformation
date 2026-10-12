"""What it costs to get from the current estate to the target one.

Audit finding P3. The model had no one-time, transition or dual-running cost at
all: every scenario reported `gross_run_rate_savings` and nothing net, so
payback could not be computed and a reader comparing scenarios was comparing
prizes without their price.

The bias probe called the understatement total rather than partial, which was
right - and the direction matters. Adding these costs makes the model more
conservative, which is the correct direction for an addition that carries no
transaction evidence behind it.
"""
import types

import pytest

from app.domain import transition
from app.domain.money import D, Range

# The seeded transition_policy, as a stand-in so these stay unit tests. The
# component shares and the reference density are required fields on the real
# policy - CR-04 reads them whenever an estate mix is supplied, CR-05 reads
# them always, because delivery capacity is expressed in circuits.
POLICY = types.SimpleNamespace(
    one_time_cost_per_site_low="400", one_time_cost_per_site_base="900",
    one_time_cost_per_site_high="1800", dual_running_months="3",
    sites_migrated_per_month="120", evidence_grade="E",
    one_time_share_hardware="0.35", one_time_share_migration="0.25",
    one_time_share_integration="0.20",
    one_time_share_project_management="0.20",
    one_time_reference_circuits_per_site="1.25")


def _net(sites=1842, gross=("1000000", "1500000", "2000000"),
         monthly="700000", policy=POLICY):
    return transition.net(
        gross_annual=Range(D(gross[0]), D(gross[1]), D(gross[2])),
        sites=sites, monthly_run_rate=D(monthly), policy=policy)


def test_a_gross_saving_is_no_longer_reported_as_the_answer():
    """The finding. 1,842 sites at 900 apiece is 1.66m of one-time cost against
    a 1.5m annual saving - so the first year is negative, and every scenario
    used to report the 1.5m alone."""
    out = _net()
    assert D(out["total_transition_cost"]["base"]) > D("1500000")
    assert D(out["first_year_net"]) < 0, (
        "a transition costing more than a year's saving must show a negative "
        "first year")


def test_payback_pairs_the_high_cost_with_the_low_saving():
    """Deliberately crossed. The pessimistic case is the high cost and the low
    saving, because those are the same world - pairing high with high reports a
    payback nobody could have."""
    out = _net()
    months = out["payback_months"]
    assert months["optimistic"] < months["base"] < months["pessimistic"]


def test_a_saving_that_cannot_repay_the_cost_has_no_payback():
    """None, not a very large number. A 400-month payback reads as a long one;
    the truth is that it never repays."""
    out = _net(gross=("0", "0", "0"))
    assert out["payback_months"]["base"] is None


def test_the_programme_duration_is_reported_beside_the_payback():
    """A payback of fifteen months means nothing if the programme takes
    sixteen: savings do not begin until a site is cut over."""
    out = _net()
    assert out["programme_months"] == 16          # 1842 sites at 120 a month
    # The note used to warn that "a payback shorter than the programme is
    # arithmetic, not a schedule". It was describing its own output - the
    # payback divided total cost by the full-year saving and so assumed the
    # whole estate was live on day one. CR-05 computes it against the
    # rollout, so the note says what the rollout is instead of apologising
    # for ignoring it.
    assert "Savings accrue as circuits are cut over" in out["note"]
    assert "16 month(s)" in out["note"]


# ---------------------------------------------------------------- CR-05

def test_the_payback_is_never_faster_than_if_everything_were_live_on_day_one():
    """The invariant that makes a ramped payback a ramped payback.

    Savings arrive as circuits are cut over, so cumulative net can only ever
    turn positive later than it would if the full run-rate saving started in
    month one - never sooner. If this ever fails, the ramp is being applied
    to the cost and not to the saving, or not at all.
    """
    for sites in (50, 400, 1842, 16406):
        out = _net(sites=sites)
        simple, ramped = out["payback_simple_months"], out["payback_months"]["base"]
        assert simple and ramped, (sites, simple, ramped)
        assert ramped >= simple, (
            f"{sites} sites: ramped payback {ramped} is faster than the "
            f"day-one payback {simple}, which is not possible")


def test_a_long_programme_no_longer_reports_a_short_payback():
    """The case CR-NCT-001 named: McDonald's, 16,406 sites, a 137-month
    programme and a 12-month payback. The payback assumed the whole estate
    was live immediately, which for an eleven-year rollout is not a number
    anybody could have."""
    out = _net(sites=16406, gross=("12000000", "15000000", "18000000"),
               monthly="7000000")
    assert out["programme_months"] > 36
    assert out["programme_flag"] == "LONG_PROGRAMME"
    assert out["payback_months"]["base"] > out["payback_simple_months"], (
        "an estate that takes years to migrate cannot pay back at the "
        "day-one rate")


def test_a_short_programme_is_not_flagged():
    out = _net(sites=400)
    assert out["programme_months"] <= 36
    assert out["programme_flag"] is None


def test_the_programme_is_reported_as_a_band():
    out = _net(sites=1842)
    band = out["programme_months_band"]
    assert band["low"] <= band["base"] <= band["high"]
    assert band["base"] == out["programme_months"]


def test_capacity_stays_in_sites_when_no_estate_mix_is_known():
    """Converting to circuits would assert the estate runs at the reference
    density, which is a claim and not a default."""
    out = _net(sites=1842)
    assert out["programme"]["capacity_unit"] == "sites"
    assert out["programme"]["capacity_per_month"] == "120.00"
    assert "no estate mix was supplied" in out["programme"]["basis"]


def test_a_dual_access_estate_takes_longer_than_a_single_circuit_one():
    """The behaviour the governed site rate could not express: 1,000 data
    centres at two circuits each is twice the cutover work of 1,000 stores
    at one, and used to be reported as the same eight-month programme."""
    stores = [{"archetype": "STORE", "sites": 1000, "circuits": 1000}]
    dcs = [{"archetype": "DC", "sites": 1000, "circuits": 2000}]
    a = transition.net(gross_annual=Range(D("1000000"), D("1500000"), D("2000000")),
                       sites=1000, monthly_run_rate=D("700000"),
                       policy=POLICY, site_mix=stores)
    b = transition.net(gross_annual=Range(D("1000000"), D("1500000"), D("2000000")),
                       sites=1000, monthly_run_rate=D("700000"),
                       policy=POLICY, site_mix=dcs)
    assert b["programme_months"] > a["programme_months"], (
        a["programme_months"], b["programme_months"])
    assert a["programme"]["capacity_unit"] == "circuits"


def test_the_wave_plan_accounts_for_every_circuit():
    """A rollout that loses or invents work is not a plan."""
    plan = transition.wave_plan(circuits=D("1842"), policy=POLICY)
    total = sum(D(w["circuits"]) for w in plan["waves"])
    assert total == D("1842")
    assert plan["waves"][-1]["cumulative_share"] == "1.00"
    assert len(plan["waves"]) == plan["months"]


def test_what_the_wave_model_does_not_claim():
    """Pilot waves, a capacity ramp and site dependencies are owner inputs
    and none is sourced, so the plan names them rather than inventing a
    shape nobody chose."""
    plan = transition.wave_plan(circuits=D("1000"), policy=POLICY)
    assert set(plan["not_modelled"]) == {
        "pilot_wave", "capacity_ramp", "site_dependencies"}
    assert plan["parallel_waves"] == 1


def test_parallel_waves_shorten_the_programme_proportionally():
    """The parameter an owner's delivery plan drops into."""
    one = transition.wave_plan(circuits=D("1200"), policy=POLICY)
    two = transition.wave_plan(circuits=D("1200"), policy=POLICY,
                               parallel_waves=2)
    assert two["months"] * 2 == one["months"]


def test_a_saving_that_never_repays_has_no_payback():
    """None, not a large number, which would read as a long payback."""
    out = _net(sites=1842, gross=("0", "0", "0"))
    assert out["payback_months"]["base"] is None
    assert out["payback_simple_months"] is None


def test_the_reconciliation_note_appears_only_on_a_real_gap():
    """CR-05 asks for a note wherever the two paybacks differ by more than
    25%. The comparison is against total transition cost, not one-time cost
    alone - see docs/CR-NCT-001-ROOT-CAUSE.md F3, where the CR's own formula
    omits dual-running and would fire on every small estate."""
    big = _net(sites=16406, gross=("12000000", "15000000", "18000000"),
               monthly="7000000")
    assert big["payback_reconciliation_note"], (
        "a 137-month rollout differs from the day-one payback by far more "
        "than 25% and must say so")
    assert "runs" in big["payback_reconciliation_note"]


def test_dual_running_scales_with_duration_not_only_size():
    """A programme migrating 120 sites a month has 120 sites paying twice at
    any moment, for as long as it runs. Doubling the estate at the same rate
    doubles the duration, not the sites in flight."""
    slow = types.SimpleNamespace(**{**POLICY.__dict__,
                                    "sites_migrated_per_month": "30"})
    fast = _net(policy=POLICY)["dual_running_cost"]["base"]
    slower = _net(policy=slow)["dual_running_cost"]["base"]
    assert D(slower) < D(fast), (
        "fewer sites in flight at once is less duplicated billing per month")
    assert _net(policy=slow)["programme_months"] > _net()["programme_months"]


def test_the_one_time_cost_is_a_band_not_a_point():
    """A single number for a cost nobody has quoted implies a precision that
    does not exist, and the low and high decide whether a payback sits inside a
    contract term."""
    out = _net()
    otc = out["one_time_cost"]
    assert D(otc["low"]) < D(otc["base"]) < D(otc["high"])


def test_the_payback_says_it_is_modelled_and_what_it_omits():
    """A payback computed from grade E assumptions is a modelled payback. An
    omission that is stated is a limitation; one that is not is an error."""
    out = _net()
    assert "evidence grade E" in out["payback_basis"]
    assert "not a business case" in out["payback_basis"]
    for omitted in ("CPE purchase or refresh",
                    "early-termination liability on the existing contracts",
                    "internal programme and project cost"):
        assert omitted in out["not_modelled"], omitted


def test_a_single_site_estate_does_not_divide_by_zero():
    out = _net(sites=1, monthly="500")
    assert out["programme_months"] == 1


def test_an_empty_estate_is_not_charged_a_transition():
    out = _net(sites=0, monthly="0")
    assert D(out["one_time_cost"]["base"]) == 0
    assert D(out["dual_running_cost"]["base"]) == 0


@pytest.mark.parametrize("field", [
    "one_time_cost", "dual_running_cost", "total_transition_cost",
    "gross_run_rate_savings"])
def test_every_money_figure_is_a_band(field):
    """A point estimate for anything here would be false precision."""
    out = _net()
    assert set(out[field]) == {"low", "base", "high"}

# ----------------------------------------------- what the estimate feeds it
# The transition model was complete, tested and unreachable: TransitionPolicy
# could not be constructed, and no call site built one. These pin the two
# numbers the estimate has to supply, because getting either wrong is silent -
# a wrong site count produces a plausible payback rather than an error.

def _component(key, layer, driver, quantity, base):
    from app.domain.estimate import Component
    return Component(
        key=key, layer=layer, driver=driver, quantity=quantity,
        quantity_origin="ANALYST_ENTERED_SCOPE",
        unit_cost_origin="BENCHMARK_PRIOR", product="X", role="PRIMARY",
        service_class="IPVPN", access_technology="ETHERNET_FIBRE",
        value=Range(D(base) * D("0.8"), D(base), D(base) * D("1.3")))


def test_the_site_count_is_read_back_from_the_components():
    """Rather than passed alongside them, where it could disagree."""
    from app.domain import estimate
    assert estimate.site_count([
        _component("L0_circuits", "L0", "circuits", 9999, "1000"),
        _component("OPS_operations", "OPS", "sites", 4000, "2000")]) == 4000


def test_a_split_site_line_is_summed_not_counted_twice():
    """_split() divides a site-driven line across origins, so the OPS layer
    arrives as several components that together describe one estate."""
    from app.domain import estimate
    assert estimate.site_count([
        _component("OPS_a", "OPS", "sites", 2400, "1200"),
        _component("OPS_b", "OPS", "sites", 1600, "800")]) == 4000


def test_two_site_driven_layers_describe_one_estate_not_two():
    """Both the OPS line and the L2 overlay are driven by the site count. A
    flat sum over driver=="sites" would report 8,000 sites for a 4,000-site
    estate, double every one-time cost and halve every payback."""
    from app.domain import estimate
    assert estimate.site_count([
        _component("OPS_a", "OPS", "sites", 2400, "1200"),
        _component("OPS_b", "OPS", "sites", 1600, "800"),
        _component("L2_overlay", "L2", "sites", 4000, "500")]) == 4000


def test_an_estate_with_no_site_line_reports_no_sites():
    """And so gets no transition block, which is the honest outcome rather
    than a payback computed from a site count nobody has."""
    from app.domain import estimate
    assert estimate.site_count([
        _component("L0_circuits", "L0", "circuits", 120, "1000")]) == 0


def test_the_run_rate_handed_over_is_monthly():
    """Component values are annual - every rate is scaled by MONTHS where it
    is built - and dual_running works in months, because a month is how long
    a site spends paying for two circuits. Handing it the annual figure would
    overstate dual running twelvefold."""
    from app.domain import estimate
    comps = [_component("OPS_operations", "OPS", "sites", 10, "1200")]
    assert estimate.monthly_run_rate(comps) == D("100")
    assert estimate.total(comps).base == D("1200")

# ------------------------------------------- CR-04: one-time cost by component

POLICY_BUILD = types.SimpleNamespace(
    **{**vars(POLICY),
       "one_time_share_hardware": D("0.35"),
       "one_time_share_migration": D("0.25"),
       "one_time_share_integration": D("0.20"),
       "one_time_share_project_management": D("0.20"),
       "one_time_reference_circuits_per_site": D("1.25")})


def test_cost_per_site_differs_between_a_store_and_a_data_centre():
    """The acceptance CR-04 names.

    Every company in the twenty-company sample reported exactly 900.00 per
    site - four currencies, estates from 43 sites to 16,406, a retail store
    costing what a data centre costs. That figure was the governed reference
    cost and said nothing about any estate.
    """
    out = transition.one_time_build(
        site_mix=[{"archetype": "STORE", "sites": 100, "circuits": 105},
                  {"archetype": "DC", "sites": 10, "circuits": 20}],
        policy=POLICY_BUILD)
    by_type = {r["archetype"]: D(r["cost_per_site_base"])
               for r in out["by_site_type"]}
    assert by_type["DC"] > by_type["STORE"], by_type
    # A DC drawing two circuits against a store drawing ~1.05 is not a
    # rounding difference.
    assert by_type["DC"] / by_type["STORE"] > D("1.3")


def test_the_build_reproduces_the_reference_cost_at_the_reference_density():
    """Structure without moving the governed level.

    The decomposition is only honest if it leaves the reference cost alone
    where the reference assumptions hold; otherwise it is a re-tuning
    wearing a component breakdown.
    """
    out = transition.one_time_build(
        site_mix=[{"archetype": "STORE", "sites": 400, "circuits": 500}],
        policy=POLICY_BUILD)                       # 500/400 = 1.25 = ref
    assert out["total"].base == D("900") * 400


def test_the_components_sum_to_the_total():
    out = transition.one_time_build(
        site_mix=[{"archetype": "STORE", "sites": 100, "circuits": 130},
                  {"archetype": "PLANT", "sites": 20, "circuits": 38}],
        policy=POLICY_BUILD)
    parts = sum(D(v) for v in out["by_component"].values())
    assert parts == out["total"].base, (parts, out["total"].base)


def test_what_it_does_not_vary_by_is_declared_rather_than_modelled():
    """Country and target architecture are not sourced. A factor invented to
    vary them would read as evidence, which principle 1 forbids."""
    out = transition.one_time_build(
        site_mix=[{"archetype": "STORE", "sites": 10, "circuits": 12}],
        policy=POLICY_BUILD)
    assert set(out["not_varied_by"]) == {"country", "target_architecture"}
    assert all("DECLARED_UNKNOWN" in v for v in out["not_varied_by"].values())
    assert out["origin"]["shares"] == "ASSUMED"
    assert out["origin"]["circuits"] == "SIMULATED"


def test_an_estimate_with_no_estate_says_so_rather_than_looking_built():
    """The ANCHOR method never simulates an estate. Its one-time cost is the
    flat reference, and the build records why instead of presenting a number
    indistinguishable from a built one."""
    out = transition.net(gross_annual=Range(D("1"), D("2"), D("3")),
                         sites=100, monthly_run_rate=D("1000"),
                         policy=POLICY_BUILD, site_mix=None)
    build = out["one_time_cost_build"]
    assert build["origin"]["circuits"] == "NOT_SUPPLIED"
    assert "no estate mix" in build["note"]


def test_a_truncated_estate_does_not_shrink_the_cost():
    """The simulation publishes at most 5,000 estate rows. McDonald's 16,406
    sites arrive as 5,000 with estate_truncated: 11406, so counting rows
    counts a third of the estate - and the one-time cost came out at 287.80
    per site against a formula whose floor is 792.

    The error is silent and proportional: it scales the cost by the
    truncation ratio and leaves a number that still looks like one.
    """
    from app.domain import estimate

    footprint = [{"country": "US", "archetype": "STORE", "sites": 16000},
                 {"country": "US", "archetype": "DC", "sites": 6}]
    # A sample, as the simulation would publish it: a fraction of the stores.
    estate = ([{"archetype": "STORE", "backup_product": None}] * 900
              + [{"archetype": "STORE", "backup_product": "PON"}] * 100
              + [{"archetype": "DC", "backup_product": "ETHERNET"}] * 6)

    mix = {m["archetype"]: m for m in
           estimate.site_mix_from_estate(estate, footprint)}
    assert mix["STORE"]["sites"] == 16000, "site count must come from the footprint"
    # Density measured on the sample - 1.1 circuits per store - applied to all.
    assert mix["STORE"]["circuits"] == 17600
    assert mix["STORE"]["circuit_density_sampled_sites"] == 1000
    assert mix["DC"]["sites"] == 6 and mix["DC"]["circuits"] == 12


def test_an_archetype_missing_from_the_sample_is_marked_not_dropped():
    """Truncation can cut a whole site type out of the sample. Dropping it
    would silently remove its cost; assuming one circuit would understate
    it. It takes the estate-wide density and says where that came from."""
    from app.domain import estimate

    footprint = [{"archetype": "STORE", "sites": 100},
                 {"archetype": "PLANT", "sites": 10}]
    estate = [{"archetype": "STORE", "backup_product": "PON"}] * 50
    mix = {m["archetype"]: m for m in
           estimate.site_mix_from_estate(estate, footprint)}
    assert mix["PLANT"]["sites"] == 10
    assert mix["PLANT"]["circuit_density_origin"] == "SIMULATED_ESTATE_AVERAGE"
    assert mix["PLANT"]["circuits"] == 20       # estate-wide density of 2.0
    assert mix["STORE"]["circuit_density_origin"] == "SIMULATED"


def test_the_site_mix_is_counted_from_the_estate_not_assumed():
    """Circuits come from whether each simulated site drew a backup product,
    so a second access is counted rather than inferred from a probability."""
    from app.domain import estimate

    estate = ([{"archetype": "STORE", "backup_product": None}] * 8
              + [{"archetype": "STORE", "backup_product": "BROADBAND_PON"}] * 2
              + [{"archetype": "DC", "backup_product": "ETHERNET"}] * 3)
    mix = {m["archetype"]: m for m in estimate.site_mix_from_estate(estate)}
    assert mix["STORE"] == {"archetype": "STORE", "sites": 10, "circuits": 12}
    assert mix["DC"] == {"archetype": "DC", "sites": 3, "circuits": 6}
    assert estimate.site_mix_from_estate([]) == []

