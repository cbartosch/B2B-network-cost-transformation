"""Reference-data seed. Spec 18.1: no material threshold, weight or prior may
exist only as a code constant - they live here and are versioned in the database."""
from sqlalchemy import delete, insert, select

from .db import (SessionLocal, archetype_prior, lever, platform_unit_cost,
                 threshold, unit_cost_prior)

# Every governed number the analytical model uses. Nothing in the domain layer
# carries a default, so anything absent here raises PolicyIncomplete at load
# rather than silently reverting to a constant (spec 18.1).
THRESHOLDS = [
    # --- 0.3C coverage gate
    ("v0_coverage_threshold_set", "v0_prior_coverage_min", "0.70"),
    ("v0_coverage_threshold_set", "v0_prior_coverage_floor", "0.40"),
    ("v0_coverage_threshold_set", "v0_material_country_floor", "0.10"),
    ("v0_coverage_threshold_set", "v0_product_coverage_min", "0.60"),
    ("v0_coverage_threshold_set", "prior_recency_annual_decay", "0.15"),
    ("v0_coverage_threshold_set", "prior_recency_floor", "0.20"),

    # --- 13.2 component weighting; must sum to 1
    ("confidence_policy", "weight_current_baseline", "0.35"),
    ("confidence_policy", "weight_target_cost", "0.35"),
    ("confidence_policy", "weight_realization", "0.30"),
    ("confidence_policy", "component_cap_headroom", "0.15"),

    # --- 13.2 band floors
    ("confidence_policy", "band_a_floor", "0.85"),
    ("confidence_policy", "band_b_floor", "0.70"),
    ("confidence_policy", "band_c_floor", "0.50"),

    # --- stage ceilings: V0 has no contract, telemetry, serviceability or bid
    # evidence, so its realization confidence is bounded whatever the analysis
    ("confidence_policy", "stage_ceiling_V0_current_baseline", "0.55"),
    ("confidence_policy", "stage_ceiling_V0_target_cost", "0.75"),
    ("confidence_policy", "stage_ceiling_V0_realization", "0.35"),

    # --- 0.6A simulated-share bands; ceiling 1.00 means no cap
    ("confidence_policy", "simulated_band_1_upper", "0.10"),
    ("confidence_policy", "simulated_band_1_ceiling", "1.00"),
    ("confidence_policy", "simulated_band_2_upper", "0.35"),
    ("confidence_policy", "simulated_band_2_ceiling", "0.70"),
    ("confidence_policy", "simulated_band_3_upper", "0.65"),
    ("confidence_policy", "simulated_band_3_ceiling", "0.60"),
    ("confidence_policy", "simulated_band_4_upper", "1.00"),
    ("confidence_policy", "simulated_band_4_ceiling", "0.50"),

    # --- realization by the stage at which lever evidence becomes admissible
    ("confidence_policy", "lever_stage_weight_V2", "1.00"),
    ("confidence_policy", "lever_stage_weight_V3", "0.50"),
    ("confidence_policy", "lever_stage_weight_V4", "0.25"),
    ("confidence_policy", "lever_stage_weight_V5", "0.10"),

    # --- component driver blends; each group must sum to 1
    ("confidence_policy", "baseline_driver_priced_spend", "0.40"),
    ("confidence_policy", "baseline_driver_evidenced", "0.35"),
    ("confidence_policy", "baseline_driver_completeness", "0.25"),
    ("confidence_policy", "target_driver_prior_coverage", "0.55"),
    ("confidence_policy", "target_driver_prior_recency", "0.45"),

    # --- 0.6A assertion and display
    ("confidence_policy", "asserted_baseline_confidence_ceiling", "0.50"),
    ("confidence_policy", "asserted_share_trigger", "0.25"),
    ("confidence_policy", "simulated_display_badge_threshold", "0.10"),
    ("confidence_policy", "partial_penalty_factor", "0.80"),
    # How far a known fact may sit from the quantity the model carries before it
    # can no longer be credited as that quantity's source (0.1B).
    ("confidence_policy", "known_fact_binding_tolerance", "0.05"),

    # --- how far a client's own statement counts toward the evidenced driver.
    # 0.70 is a placeholder pending an approved figure, not a considered
    # default: it says a client's self-report about their own estate is worth
    # substantially more than an analyst's recollection and meaningfully less
    # than an independently-checkable public source. Where exactly it sits is
    # a judgement a steward should make, and the number is here rather than in
    # Python precisely so they can.
    ("confidence_policy", "client_confirmed_evidence_weight", "0.70"),

    # --- 0.1B known-fact binding
    # How close a nominated fact must be to the figure the run uses before it
    # can be credited as its source.
    ("known_fact_policy", "agreement_tolerance", "0.10"),

    # --- 0.3A research budget
    ("research_budget_profile", "max_queries_per_domain", "6"),
    ("research_budget_profile", "max_captures_per_domain", "12"),
    ("research_budget_profile", "max_captures_per_run", "150"),
    ("research_budget_profile", "min_independent_sources_material_fact", "2"),
    ("research_budget_profile", "research_wall_clock_budget_minutes", "45"),
    # Ceiling on one domain. The 45-minute budget above is a *run* budget and
    # was only ever checked between domains, so a single domain could retry
    # until its query and capture caps ran out with no time bound at all -
    # 6 provider calls carrying web searches plus a dozen source fetches.
    # Once the interface began walking domains one request at a time, each
    # request started a fresh run clock and the run budget stopped binding
    # anything. This is the bound that actually holds.
    ("research_budget_profile", "max_seconds_per_domain", "240"),
    # Hosted web-search tool invocations per domain (domain/research.py) -
    # a separate, provider-billed cost dimension from max_queries_per_domain.
    ("research_budget_profile", "max_web_searches_per_domain", "8"),

    # --- 0.3B.6 calibration
    ("simulation_calibration_threshold", "flag_mdape", "0.25"),
    ("simulation_calibration_threshold", "retire_mdape", "0.40"),
    ("simulation_calibration_threshold", "min_engagements", "5"),
    ("simulation_calibration_threshold", "review_observation_count", "20"),

    # --- 7.2E reconciliation
    ("provider_reconciliation_tier", "tier_a_tolerance_pct", "2.0"),
    ("provider_reconciliation_tier", "tier_b_tolerance_pct", "5.0"),
    ("provider_reconciliation_tier", "consecutive_gap_incident", "3"),

    # (The 0.3A research budget lives above under research_budget_profile.
    # Tranche 1 added a second set named research_policy with the same four
    # counts and a wall clock of 20 minutes, described in a comment as "a
    # placeholder pending an approved figure". The approved figure was already
    # here - 45 minutes - and was never looked for. ResearchPolicy now reads
    # research_budget_profile and the duplicate is gone. Found by the
    # dead-governance guard, which flagged research_budget_profile as seeded
    # and read by nothing: the two sets were the symptom, not the cause.)

    # --- Tranche 2 (LLM-07, LLM-06). A lever whose saving_base is at or above
    # this share of current TCO makes its inclusion a material assumption,
    # gating the narrative on named approval rather than blocking the
    # recommendation itself.
    ("recommendation_policy", "material_lever_share_threshold", "0.03"),
]

# Indicative monthly recurring charge per circuit, by country and product.
PRIORS = [
    ("GB", "DIA", "L0", 380, 520, 720), ("GB", "BROADBAND", "L0", 45, 70, 110),
    ("GB", "MPLS", "L0", 700, 980, 1400), ("GB", "ETHERNET", "L0", 550, 780, 1100),
    ("DE", "DIA", "L0", 420, 580, 800), ("DE", "BROADBAND", "L0", 50, 78, 120),
    ("DE", "MPLS", "L0", 760, 1050, 1500), ("DE", "ETHERNET", "L0", 600, 840, 1180),
    ("US", "DIA", "L0", 350, 480, 660), ("US", "BROADBAND", "L0", 55, 85, 130),
    ("US", "MPLS", "L0", 650, 900, 1300), ("US", "ETHERNET", "L0", 520, 720, 1000),
    ("FR", "DIA", "L0", 400, 550, 760), ("FR", "BROADBAND", "L0", 42, 68, 105),
    ("FR", "MPLS", "L0", 720, 1000, 1420),
    ("NL", "DIA", "L0", 360, 500, 690), ("NL", "BROADBAND", "L0", 40, 62, 98),
    ("SG", "DIA", "L0", 480, 660, 920), ("SG", "BROADBAND", "L0", 60, 95, 145),
    ("AE", "DIA", "L0", 900, 1300, 1900), ("AE", "BROADBAND", "L0", 120, 190, 290),
    # MOBILE_5G is the STORE archetype's backup product. It had no prior in any
    # country, so those circuits were unsizable - which the C2-02 fix correctly
    # surfaces as PARTIAL. Seeding it removes a spurious gap in the demo path;
    # a genuinely unpriceable product will still be caught.
    ("GB", "MOBILE_5G", "L0", 25, 45, 80), ("DE", "MOBILE_5G", "L0", 28, 50, 88),
    ("US", "MOBILE_5G", "L0", 30, 55, 95), ("FR", "MOBILE_5G", "L0", 26, 47, 84),
    ("NL", "MOBILE_5G", "L0", 24, 43, 78), ("SG", "MOBILE_5G", "L0", 35, 62, 105),
    ("AE", "MOBILE_5G", "L0", 55, 95, 160),
]

ARCHETYPES = [
    ("BRANCH", 25, 100, "0.55", "DIA", "BROADBAND"),
    ("LARGE_OFFICE", 250, 500, "0.90", "ETHERNET", "DIA"),
    ("WAREHOUSE", 60, 200, "0.45", "DIA", "BROADBAND"),
    ("DC", 0, 10000, "1.00", "ETHERNET", "ETHERNET"),
    ("STORE", 12, 50, "0.35", "BROADBAND", "MOBILE_5G"),
]

# Platform unit costs. These were code constants in an earlier revision, which
# spec 18.1 forbids for any material prior. They are ~40% of modelled TCO.
PLATFORM = [
    ("SDWAN_OVERLAY", "L2", "per site per month", 40, 55, 75),
    ("SSE_LICENCE", "L4", "per user per month", 6, 9, 13),
]

# earliest_supported_stage: the gate at which the evidence supporting the lever
# first becomes admissible under 0.5A. Drives realization confidence.
LEVERS = [
    ("LEV-REPRICE-001", "Same-service repricing", "Re-rate current products to benchmark",
     ["L0"], "0.06", "0.12", "0.18", "A", "V2"),
    ("LEV-CLEANUP-001", "Billing cleanup", "Cease unused and duplicate services",
     ["L0"], "0.01", "0.03", "0.06", "A", "V2"),
    ("LEV-MPLS-001", "MPLS substitution", "Substitute MPLS with DIA plus overlay where eligible",
     ["L0"], "0.15", "0.25", "0.35", "B", "V3"),
    ("LEV-BANDWIDTH-001", "Right-sizing", "Right-size access bandwidth against utilisation prior",
     ["L0"], "0.03", "0.07", "0.12", "B", "V3"),
    ("LEV-SASE-001", "Platform consolidation", "Converge SD-WAN, SSE and remote access",
     ["L2", "L4"], "0.12", "0.22", "0.32", "C", "V3"),
    ("LEV-SECRETIRE-001", "Security appliance retirement", "Retire on-site firewall estate",
     ["L4"], "0.05", "0.10", "0.16", "C", "V3"),
    ("LEV-NAAS-001", "Supplier consolidation", "Single global prime with managed edge",
     ["L0", "OPS"], "0.08", "0.16", "0.24", "D", "V4"),
    ("LEV-OPS-001", "Operating-model optimisation", "Consolidate NOC and vendor management",
     ["OPS"], "0.10", "0.18", "0.28", "D", "V3"),
]


def _rows():
    """Table -> row builder. Kept together so a new reference table cannot be
    added to the model without also being given seed content."""
    return [
        (threshold, lambda: [
            {"set_name": a, "key": b, "value": c, "version": 1,
             "approved_by": "seed", "note": "MVP default"} for a, b, c in THRESHOLDS]),
        (unit_cost_prior, lambda: [
            {"id": f"{c}-{p}", "country": c, "product": p, "cost_layer": l,
             "low": lo, "base": ba, "high": hi, "currency": "USD",
             "price_year": 2026, "approved": True}
            for c, p, l, lo, ba, hi in PRIORS]),
        (platform_unit_cost, lambda: [
            {"product": p, "cost_layer": l, "unit": u, "low": lo, "base": ba,
             "high": hi, "currency": "USD", "price_year": 2026, "approved": True}
            for p, l, u, lo, ba, hi in PLATFORM]),
        (archetype_prior, lambda: [
            {"archetype": a, "users_base": u, "bandwidth_mbps_base": b,
             "dual_access_probability": d, "primary_product": pp, "backup_product": bp}
            for a, u, b, d, pp, bp in ARCHETYPES]),
        (lever, lambda: [
            {"lever_id": i, "family": f, "description": d, "cost_layers": cl,
             "saving_low": lo, "saving_base": ba, "saving_high": hi, "scenario": sc,
             "evidence_required": "see reference.savings_lever_rule",
             "earliest_supported_stage": st}
            for i, f, d, cl, lo, ba, hi, sc, st in LEVERS]),
    ]


def seed(force: bool = False):
    """Idempotent per row, not per table.

    An earlier revision ran unconditionally at startup with DELETE at the top,
    so every restart destroyed governed reference data. The fix for that
    skipped the whole seed if `threshold` held any row - which meant a table
    added by a later build (platform_unit_cost) stayed empty forever, silently
    dropping about 40% of modelled TCO. That was fixed per *table*: each table
    is checked and topped up on its own. But a table can be non-empty and
    still be missing a row a later build added to its own THRESHOLDS/PRIORS/etc
    list - `confidence_policy.client_confirmed_evidence_weight` did exactly
    this: threshold already had 40-odd rows from an older seed, so "any row
    exists" was true and the newly-added key was never inserted. The run that
    needed it then failed closed with PolicyIncomplete, which is correct
    behaviour for a governed value with no code default - but the fix belongs
    here, not in an operator re-running --force and hoping nothing else in the
    table had been hand-edited since.

    So the check is now per primary key, not per table: only the rows this
    build's builder would add that the database doesn't already have. An
    existing row - including one a steward edited by hand - is left alone
    whether or not --force is passed; --force only controls whether truly
    stale rows (a key seed used to produce and no longer does) are removed.
    """
    s = SessionLocal()
    try:
        loaded, topped_up, skipped, removed = [], [], [], []
        for table, builder in _rows():
            name = f"{table.schema}.{table.name}"
            pk_cols = [c.name for c in table.primary_key.columns]
            rows = builder()
            wanted = {tuple(r[c] for c in pk_cols): r for r in rows}

            existing_pks = {
                tuple(row) for row in
                s.execute(select(*[table.c[c] for c in pk_cols])).all()}

            stale_pks = existing_pks - set(wanted)
            if force and stale_pks:
                for pk in stale_pks:
                    cond = [table.c[c] == v for c, v in zip(pk_cols, pk)]
                    s.execute(delete(table).where(*cond))
                removed.append(f"{name} ({len(stale_pks)})")
                existing_pks -= stale_pks

            missing = {pk: r for pk, r in wanted.items() if pk not in existing_pks}
            if not missing:
                if existing_pks:
                    skipped.append(name)
                continue
            s.execute(insert(table), list(missing.values()))
            (loaded if not existing_pks else topped_up).append(
                f"{name} ({len(missing)})")
        s.commit()
        if loaded:
            print(f"seeded (new table): {', '.join(loaded)}")
        if topped_up:
            print(f"topped up (new keys added, existing rows untouched): "
                 f"{', '.join(topped_up)}")
        if removed:
            print(f"removed stale rows (--force): {', '.join(removed)}")
        if skipped:
            print(f"already complete, left untouched: {', '.join(skipped)}")
        if not (loaded or topped_up or removed or skipped):
            print("nothing to seed")
    finally:
        s.close()


if __name__ == "__main__":
    import sys
    seed(force="--force" in sys.argv)
