"""Reference-data seed. Spec 18.1: no material threshold, weight or prior may
exist only as a code constant - they live here and are versioned in the database."""
from datetime import date as _date

from sqlalchemy import delete, insert, select

from .domain import access, bics, industry_benchmark, industries
from .domain.research_briefs import (
    BRIEF_CATALOGUE_VERSION, RESEARCH_BRIEFS)
# The agent map lives with the research module; the brief rows record which
# agent a domain routes to so a steward editing a brief can see it.
DOMAIN_AGENT_MAP_SEED = {
    1: 'LLM-01', 2: 'LLM-01', 6: 'LLM-01', 7: 'LLM-01', 8: 'LLM-01',
    12: 'LLM-01', 13: 'LLM-01', 14: 'LLM-01', 15: 'LLM-01', 16: 'LLM-01',
    9: 'LLM-08', 10: 'LLM-08', 18: 'LLM-08', 19: 'LLM-08', 20: 'LLM-08',
    21: 'LLM-08', 22: 'LLM-08',
}
from .db import (SessionLocal, archetype_bandwidth, archetype_prior,
                 archetype_resilience,
                 fx_rate,
                 density_mix,
                 # Aliased: the table and the domain module that parses it
                 # share a name, and importing both unaliased would let Python
                 # keep whichever came last.
                 industry_benchmark as industry_benchmark_table,
                 serviceability,
                 country_region, topology_template, lever, platform_unit_cost,
                 research_brief,
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
    # A baseline built on unsourced rates cannot claim the confidence of one
    # built on quotes. Audit finding A-02: priced_spend_pct counted a circuit
    # as priced whatever stood behind the number, so an estate priced entirely
    # from seeded assumptions scored the same as one priced from cleared
    # benchmarks.
    #
    # Applied when the value-weighted share of grade E or F rates exceeds the
    # trigger. 0.40 is the ceiling, below the 0.55 stage ceiling, so it binds:
    # an estimate resting mostly on assumptions is capped by what its rates are
    # worth rather than by the stage it is at.
    ("confidence_policy", "unsourced_price_share_trigger", "0.50"),
    ("confidence_policy", "unsourced_price_ceiling", "0.40"),
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
    # The largest a bindable quantity can plausibly be.
    #
    # The unit check catches a cost line whose unit gives it away - "EUR/year"
    # under Location footprint. It does not catch one whose unit says "sites",
    # and the entry form defaulted every class to "sites", so a disclosed spend
    # of 460,000,000 arrived unit-consistent and value-absurd. Every stage
    # after it then behaved correctly on 460 million branches.
    #
    # Set far above any real estate rather than near it: the largest retail and
    # postal networks in the world are in the low hundreds of thousands of
    # outlets, so a million refuses nothing genuine while catching every money
    # figure, which for an annual spend is a million or more by construction.
    ("known_fact_policy", "max_plausible_sites", "1000000"),
    # The largest employers on earth are a few million people.
    ("known_fact_policy", "max_plausible_users", "10000000"),
    ("known_fact_policy", "agreement_tolerance", "0.10"),

    # --- researched price vs the benchmark it would displace.
    # A researched price previously landed as a separate unapproved row with
    # nobody computing how far it sat from the approved band. A steward saw
    # one number and approved it; a research finding 40% off the benchmark was
    # indistinguishable from one that confirmed it, and the disagreement -
    # the most informative thing in the comparison - was never surfaced.
    # Inside the band is agreement. Outside it, divergence is measured against
    # the nearest edge, and beyond this share it is material: the promotion is
    # still recorded, and it is flagged for adjudication before approval.
    ("price_divergence_policy", "material_divergence_share", "0.25"),

    # --- anchor method (V0 ANCHOR).
    # A disclosed telecom or IT cost line is an upper bound, not an addressable
    # pool: it carries voice, mobile, non-WAN services and sites out of scope.
    # These say how much of a public anchor a Stage 0 estimate may claim to
    # model. They are assumptions and are labelled as such wherever they reach
    # a number - the point of the method is that the assumption is explicit and
    # governed rather than buried in a spreadsheet.
    ("anchor_policy", "addressable_share_low", "0.45"),
    ("anchor_policy", "addressable_share_base", "0.55"),
    ("anchor_policy", "addressable_share_high", "0.65"),
    # How the addressable pool splits across cost layers, so the seeded levers
    # - which name the layers they act on - apply to it exactly as they apply
    # to a built-up estate. Must sum to 1.
    ("anchor_policy", "layer_mix_L0", "0.60"),
    ("anchor_policy", "layer_mix_L2", "0.10"),
    ("anchor_policy", "layer_mix_L4", "0.20"),
    ("anchor_policy", "layer_mix_OPS", "0.10"),
    # Below this addressable share the anchor explains too little of its own
    # cost line to be an estimate of anything.
    ("anchor_policy", "min_addressable_share", "0.25"),

    # --- agent quality gate.
    # How many times a rejected call is retried with the rejection reason
    # before the run fails closed. Governed rather than a constant because it
    # trades provider spend against acceptance rate, and because raising it is
    # the tempting response to a falling acceptance rate - which is usually
    # the wrong one. A gate rejecting more often is information about the
    # agent, not a budget to be increased until the complaints stop.
    ("agent_quality_policy", "max_attempts_per_call", "3"),
    # A cut connection is not a poor answer. It gets its own small budget so a
    # transient network fault does not consume the attempts reserved for
    # judging what the model said - and so a domain is not lost to a firewall
    # dropping one long-lived request out of seventeen.
    ("agent_quality_policy", "max_transport_retries", "2"),
    ("agent_quality_policy", "transport_retry_backoff_seconds", "5"),

    # --- triangulation.
    # How far sources may disagree before the disagreement is the finding
    # rather than noise to be averaged away, and how old the newest source may
    # be before the band is called stale. Governed because both decide whether
    # a person is asked to look, and "how much disagreement is acceptable" is
    # a judgement about the engagement, not a constant.
    ("triangulation_policy", "material_spread_share", "0.15"),
    ("triangulation_policy", "stale_after_years", "3"),

    # --- footprint allocation.
    # The largest number of sites that may sit under a single archetype row.
    # A row carries one bandwidth, one primary and backup product, one
    # dual-access probability and one users-per-site figure, so a bulk total in
    # one row asserts that every site in it is identical. At a handful of sites
    # that is a reasonable simplification; at several hundred it is a claim
    # about an estate nobody made, and it prices every one of them at a tier
    # nobody chose.
    # Transition cost, per site, one-time.
    #
    # Audit finding P3: the model had no one-time, transition or dual-running
    # cost at all, so net savings and payback could not be computed - the
    # understatement was total rather than partial, and every scenario reported
    # a gross figure as though it were the answer.
    #
    # These are evidence grade E, like the rate card: expert assumptions with
    # no transaction behind them. They make the model more conservative, not
    # less, which is the right direction for an unevidenced addition - but a
    # payback computed from them is a modelled payback and the output says so.
    ("transition_policy", "one_time_cost_per_site_low", "400"),
    ("transition_policy", "one_time_cost_per_site_base", "900"),
    ("transition_policy", "one_time_cost_per_site_high", "1800"),
    # Both circuits billed while a site is cut over. Three months is a
    # commonplace for a co-ordinated programme and optimistic for a large one.
    ("transition_policy", "dual_running_months", "3"),
    # Sites migrated per month once the programme is running. 4,000 sites at
    # 120 a month is nearly three years, which is why a payback computed
    # without it is meaningless.
    ("transition_policy", "sites_migrated_per_month", "120"),
    # transition_policy.evidence_grade is deliberately NOT seeded here.
    #
    # reference.threshold.value is Numeric(12,4) - a threshold is a number you
    # compare against - and seeding the letter "E" into it made the whole seed
    # fail on insert: "invalid input syntax for type numeric". One row out of
    # eighty-four, and it took the other eighty-three with it.
    #
    # TransitionPolicy.from_rows reads it with .get("evidence_grade", "E")
    # rather than _require, so the default already covers it and nothing needed
    # the row. A steward wanting to raise the grade once real transition data
    # exists changes the field, not a threshold.
    ("footprint_policy", "max_sites_per_archetype_row", "100"),
    # The same rule for a row that says where its sites are. 100 was set when a
    # row meant (country, archetype) and every site in it was claimed identical
    # on no evidence. A row that also names a density band is a real cluster -
    # same country, same type, same deliverable access - so the claim is much
    # weaker and the limit can be looser.
    #
    # A 4,000-store chain split across four bands is ~1,000 per row, which the
    # old limit would have refused and which is a reasonable statement about a
    # discounter's urban estate. Still bounded: 4,000 stores in one row is not
    # a cluster, it is a tally.
    ("footprint_policy", "max_sites_per_cluster_row", "2000"),

    # --- quality gate.
    # How many times a registered call may be re-issued after the gate rejects
    # it. Two means one correction: enough for a drafting slip, not enough for
    # a service that is failing systematically to hide behind retries. Raising
    # it makes a broken prompt look healthy and costs provider spend to do so.
    ("quality_policy", "max_attempts_per_call", "2"),

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
    # Output tokens for one research call. The gateway default of 1500 predates
    # both the hosted web search and the structured `quantities` block: a
    # domain that searched properly and answered fully was cut off mid-JSON at
    # roughly 4,900 characters, and surfaced as "model output was not valid
    # JSON" - a prompt problem that was really a budget problem.
    ("research_budget_profile", "max_output_tokens_per_call", "16000"),
    # The public sweep asks about one fact class per call now, so its replies
    # are small - but a searching call carries its results in the response, so
    # the budget is not just the prose. Governed rather than hardcoded because
    # the right number depends on the provider and the search volume, and
    # discovering it should not need a rebuild.
    ("research_budget_profile", "max_output_tokens_per_sweep_call", "6000"),
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

# Indicative monthly recurring charge per circuit, by country, product and
# bandwidth. (country, product, cost_layer, mbps, low, base, high)
#
# Bandwidth is a dimension because a circuit price is meaningless without it:
# a 100 Mbps DIA and a 1 Gbps DIA differ by more than most of the levers this
# system models are worth. Until 4.53.0 the table was keyed (country, product)
# alone, so every archetype from a 50 Mbps STORE to a 10 Gbps DC was priced at
# one rate - and a real benchmark could not be loaded without discarding the
# tier it described.
#
# BROADBAND is split into its two access technologies. They are separate
# products, not variants: HFC is a shared coaxial segment with asymmetric
# upstream, PON is fibre to the premises. Real RFP responses price them
# separately and materially differently, and collapsing them made the single
# BROADBAND band a blend of two distributions that meant neither.
#
# Bandwidth tiers follow the archetype bandwidth_mbps_base values below, so a
# site's required bandwidth has a price to match rather than a nearest guess.
# Consumer-access prices from the supplied Global Access Pricing Workbook.
#
# GPON and HFC only, at 100 / 250 / 500 / 1000 Mbps across twenty market
# clusters - the store and branch products, which is where most of a retail or
# branch estate's site count sits. Four complete tiers against the seeded
# assumption they replace.
#
# **DIA, Ethernet and MPLS are deliberately NOT loaded.** The workbook quotes
# one tier for each (1G) and does not state whether that is a full 1 Gbps
# committed rate or a 1 Gbps port with a lower CIR. The model prices a
# committed service on its CIR, so it cannot place the figure without knowing
# which - and a German quote for a 1G port with a 300 Mbit CIR came in 31%
# below the workbook's Germany DIA 1G, which is what both readings would look
# like. A number that might mean two products is worse in the card than an
# assumption known to be one.
#
# GPON and HFC have no such ambiguity: a 250 Mbps GPON service is a 250 Mbps
# GPON service, best-effort by construction, and the model already treats
# BEST_EFFORT as priced on its headline rate.
#
# **HFC is blank for four clusters** - GCC, Middle East Other, Africa Other and
# Singapore - because those markets have no cable network. Left blank rather
# than filled: the serviceability table reaches the same conclusion
# independently, and inventing a cable price for Singapore would price a market
# that does not exist.
#
# Grade C: a benchmark somebody compiled that a person can check, and the
# workbook states no source or date - so it is not B. The currency is inferred
# as USD from the UK cluster matching a separately sourced GB figure to within
# 2%, which is an inference and is recorded as one.
WORKBOOK_CURRENCY = "USD"
WORKBOOK_CURRENCY_BASIS = (
    "inferred, not stated. UK & Ireland GPON 100M is 70 and HFC 100M is 80, "
    "which match the independently sourced GB rows exactly; DIA 1G at 750 "
    "matches a sourced 737. A workbook that stated its currency would not "
    "need this note.")

# (cluster, product, mbps, monthly price)
WORKBOOK_ACCESS_PRICES = [
    ("UK & Ireland", "BROADBAND_HFC", 100, 80),
    ("UK & Ireland", "BROADBAND_HFC", 250, 108),
    ("UK & Ireland", "BROADBAND_HFC", 500, 140),
    ("UK & Ireland", "BROADBAND_HFC", 1000, 176),
    ("UK & Ireland", "BROADBAND_PON", 100, 70),
    ("UK & Ireland", "BROADBAND_PON", 250, 95),
    ("UK & Ireland", "BROADBAND_PON", 500, 120),
    ("UK & Ireland", "BROADBAND_PON", 1000, 155),
    ("Benelux", "BROADBAND_HFC", 100, 78),
    ("Benelux", "BROADBAND_HFC", 250, 105),
    ("Benelux", "BROADBAND_HFC", 500, 135),
    ("Benelux", "BROADBAND_HFC", 1000, 171),
    ("Benelux", "BROADBAND_PON", 100, 62),
    ("Benelux", "BROADBAND_PON", 250, 83),
    ("Benelux", "BROADBAND_PON", 500, 105),
    ("Benelux", "BROADBAND_PON", 1000, 136),
    ("Germany", "BROADBAND_HFC", 100, 74),
    ("Germany", "BROADBAND_HFC", 250, 99),
    ("Germany", "BROADBAND_HFC", 500, 128),
    ("Germany", "BROADBAND_HFC", 1000, 162),
    ("Germany", "BROADBAND_PON", 100, 78),
    ("Germany", "BROADBAND_PON", 250, 105),
    ("Germany", "BROADBAND_PON", 500, 132),
    ("Germany", "BROADBAND_PON", 1000, 171),
    ("France", "BROADBAND_HFC", 100, 84),
    ("France", "BROADBAND_HFC", 250, 113),
    ("France", "BROADBAND_HFC", 500, 145),
    ("France", "BROADBAND_HFC", 1000, 184),
    ("France", "BROADBAND_PON", 100, 68),
    ("France", "BROADBAND_PON", 250, 91),
    ("France", "BROADBAND_PON", 500, 115),
    ("France", "BROADBAND_PON", 1000, 149),
    ("Nordics", "BROADBAND_HFC", 100, 88),
    ("Nordics", "BROADBAND_HFC", 250, 118),
    ("Nordics", "BROADBAND_HFC", 500, 152),
    ("Nordics", "BROADBAND_HFC", 1000, 193),
    ("Nordics", "BROADBAND_PON", 100, 60),
    ("Nordics", "BROADBAND_PON", 250, 80),
    ("Nordics", "BROADBAND_PON", 500, 100),
    ("Nordics", "BROADBAND_PON", 1000, 130),
    ("Southern Europe", "BROADBAND_HFC", 100, 82),
    ("Southern Europe", "BROADBAND_HFC", 250, 110),
    ("Southern Europe", "BROADBAND_HFC", 500, 142),
    ("Southern Europe", "BROADBAND_HFC", 1000, 180),
    ("Southern Europe", "BROADBAND_PON", 100, 65),
    ("Southern Europe", "BROADBAND_PON", 250, 88),
    ("Southern Europe", "BROADBAND_PON", 500, 110),
    ("Southern Europe", "BROADBAND_PON", 1000, 143),
    ("Eastern Europe", "BROADBAND_HFC", 100, 65),
    ("Eastern Europe", "BROADBAND_HFC", 250, 88),
    ("Eastern Europe", "BROADBAND_HFC", 500, 112),
    ("Eastern Europe", "BROADBAND_HFC", 1000, 145),
    ("Eastern Europe", "BROADBAND_PON", 100, 50),
    ("Eastern Europe", "BROADBAND_PON", 250, 68),
    ("Eastern Europe", "BROADBAND_PON", 500, 84),
    ("Eastern Europe", "BROADBAND_PON", 1000, 110),
    ("North America", "BROADBAND_HFC", 100, 120),
    ("North America", "BROADBAND_HFC", 250, 162),
    ("North America", "BROADBAND_HFC", 500, 208),
    ("North America", "BROADBAND_HFC", 1000, 264),
    ("North America", "BROADBAND_PON", 100, 85),
    ("North America", "BROADBAND_PON", 250, 114),
    ("North America", "BROADBAND_PON", 500, 145),
    ("North America", "BROADBAND_PON", 1000, 187),
    ("Mexico", "BROADBAND_HFC", 100, 105),
    ("Mexico", "BROADBAND_HFC", 250, 142),
    ("Mexico", "BROADBAND_HFC", 500, 182),
    ("Mexico", "BROADBAND_HFC", 1000, 230),
    ("Mexico", "BROADBAND_PON", 100, 78),
    ("Mexico", "BROADBAND_PON", 250, 105),
    ("Mexico", "BROADBAND_PON", 500, 132),
    ("Mexico", "BROADBAND_PON", 1000, 171),
    ("Brazil", "BROADBAND_HFC", 100, 115),
    ("Brazil", "BROADBAND_HFC", 250, 155),
    ("Brazil", "BROADBAND_HFC", 500, 198),
    ("Brazil", "BROADBAND_HFC", 1000, 250),
    ("Brazil", "BROADBAND_PON", 100, 82),
    ("Brazil", "BROADBAND_PON", 250, 110),
    ("Brazil", "BROADBAND_PON", 500, 138),
    ("Brazil", "BROADBAND_PON", 1000, 180),
    ("LatAm Other", "BROADBAND_HFC", 100, 125),
    ("LatAm Other", "BROADBAND_HFC", 250, 169),
    ("LatAm Other", "BROADBAND_HFC", 500, 216),
    ("LatAm Other", "BROADBAND_HFC", 1000, 273),
    ("LatAm Other", "BROADBAND_PON", 100, 90),
    ("LatAm Other", "BROADBAND_PON", 250, 121),
    ("LatAm Other", "BROADBAND_PON", 500, 152),
    ("LatAm Other", "BROADBAND_PON", 1000, 198),
    ("GCC", "BROADBAND_PON", 100, 68),
    ("GCC", "BROADBAND_PON", 250, 91),
    ("GCC", "BROADBAND_PON", 500, 105),
    ("GCC", "BROADBAND_PON", 1000, 132),
    ("Middle East Other", "BROADBAND_PON", 100, 72),
    ("Middle East Other", "BROADBAND_PON", 250, 96),
    ("Middle East Other", "BROADBAND_PON", 500, 120),
    ("Middle East Other", "BROADBAND_PON", 1000, 156),
    ("South Africa", "BROADBAND_HFC", 100, 125),
    ("South Africa", "BROADBAND_HFC", 250, 169),
    ("South Africa", "BROADBAND_HFC", 500, 216),
    ("South Africa", "BROADBAND_HFC", 1000, 273),
    ("South Africa", "BROADBAND_PON", 100, 80),
    ("South Africa", "BROADBAND_PON", 250, 108),
    ("South Africa", "BROADBAND_PON", 500, 135),
    ("South Africa", "BROADBAND_PON", 1000, 176),
    ("Africa Other", "BROADBAND_PON", 100, 105),
    ("Africa Other", "BROADBAND_PON", 250, 142),
    ("Africa Other", "BROADBAND_PON", 500, 178),
    ("Africa Other", "BROADBAND_PON", 1000, 231),
    ("India", "BROADBAND_HFC", 100, 55),
    ("India", "BROADBAND_HFC", 250, 75),
    ("India", "BROADBAND_HFC", 500, 95),
    ("India", "BROADBAND_HFC", 1000, 125),
    ("India", "BROADBAND_PON", 100, 40),
    ("India", "BROADBAND_PON", 250, 55),
    ("India", "BROADBAND_PON", 500, 70),
    ("India", "BROADBAND_PON", 1000, 92),
    ("North Asia", "BROADBAND_HFC", 100, 70),
    ("North Asia", "BROADBAND_HFC", 250, 95),
    ("North Asia", "BROADBAND_HFC", 500, 122),
    ("North Asia", "BROADBAND_HFC", 1000, 155),
    ("North Asia", "BROADBAND_PON", 100, 55),
    ("North Asia", "BROADBAND_PON", 250, 74),
    ("North Asia", "BROADBAND_PON", 500, 93),
    ("North Asia", "BROADBAND_PON", 1000, 120),
    ("Singapore", "BROADBAND_PON", 100, 68),
    ("Singapore", "BROADBAND_PON", 250, 91),
    ("Singapore", "BROADBAND_PON", 500, 115),
    ("Singapore", "BROADBAND_PON", 1000, 149),
    ("ASEAN Tier 2", "BROADBAND_HFC", 100, 65),
    ("ASEAN Tier 2", "BROADBAND_HFC", 250, 88),
    ("ASEAN Tier 2", "BROADBAND_HFC", 500, 112),
    ("ASEAN Tier 2", "BROADBAND_HFC", 1000, 143),
    ("ASEAN Tier 2", "BROADBAND_PON", 100, 60),
    ("ASEAN Tier 2", "BROADBAND_PON", 250, 80),
    ("ASEAN Tier 2", "BROADBAND_PON", 500, 100),
    ("ASEAN Tier 2", "BROADBAND_PON", 1000, 130),
    ("Oceania", "BROADBAND_HFC", 100, 115),
    ("Oceania", "BROADBAND_HFC", 250, 155),
    ("Oceania", "BROADBAND_HFC", 500, 198),
    ("Oceania", "BROADBAND_HFC", 1000, 250),
    ("Oceania", "BROADBAND_PON", 100, 75),
    ("Oceania", "BROADBAND_PON", 250, 101),
    ("Oceania", "BROADBAND_PON", 500, 127),
    ("Oceania", "BROADBAND_PON", 1000, 165),
]


# Which countries each workbook cluster covers.
#
# 78 of the 242 countries the model maps. The clusters are finer than the
# model's ten regions where it matters - Benelux apart from Germany, Nordics
# apart from Southern Europe, GCC apart from the rest of the Middle East, South
# Africa apart from the rest of the continent - and those are distinctions the
# model could not previously make.
#
# A country outside every cluster keeps the regional fallback it already had.
# Loading this must not narrow coverage from 242 countries to 78, which is
# what using the clusters as the only scope would do.
WORKBOOK_CLUSTERS = {
    "ASEAN Tier 2": ["ID", "MY", "PH", "TH", "VN"],
    "Africa Other": ["AO", "CI", "GH", "KE", "NG", "SN", "TZ", "UG"],
    "Benelux": ["BE", "LU", "NL"],
    "Brazil": ["BR"],
    "Eastern Europe": ["BG", "CZ", "EE", "HR", "HU", "LT", "LV", "PL", "RO", "RS", "SI", "SK"],
    "France": ["FR"],
    "GCC": ["AE", "BH", "KW", "OM", "QA", "SA"],
    "Germany": ["AT", "CH", "DE"],
    "India": ["IN"],
    "LatAm Other": ["AR", "CL", "CO", "CR", "EC", "PA", "PE", "UY"],
    "Mexico": ["MX"],
    "Middle East Other": ["EG", "IL", "JO", "MA", "TR"],
    "Nordics": ["DK", "FI", "IS", "NO", "SE"],
    "North America": ["CA", "US"],
    "North Asia": ["CN", "HK", "JP", "KR", "TW"],
    "Oceania": ["AU", "NZ"],
    "Singapore": ["SG"],
    "South Africa": ["ZA"],
    "Southern Europe": ["CY", "ES", "GR", "IT", "MT", "PT"],
    "UK & Ireland": ["GB", "IE"],
}


def _workbook_priors(prices, clusters):
    """Workbook cluster prices as per-country rows.

    Written per country rather than per cluster, because the scope ladder has
    no cluster rung: a price scoped to "Benelux" would sit below COUNTRY and
    above REGION with nothing to rank it, and `scope_rank` returns the same
    value for every unrecognised scope so the order would come from sort
    stability rather than from the ladder.

    A band around the point, because the model needs low/base/high and the
    workbook gives one figure. +/-25%, which is narrower than the published UK
    retail spread of roughly +/-40% and wider than nothing - and it is an
    invented spread, which is why these stay grade C rather than becoming the
    evidence the point itself is.
    """
    from decimal import Decimal as _D

    by_cluster = {}
    for cluster, product, mbps, price in prices:
        by_cluster.setdefault(cluster, []).append((product, int(mbps), price))

    out = []
    for cluster, entries in sorted(by_cluster.items()):
        for country in clusters.get(cluster, []):
            for product, mbps, price in entries:
                base = _D(price)
                out.append((country, product, "L0", mbps,
                            int(base * _D("0.75")), int(base),
                            int(base * _D("1.25"))))
    return out


# Committed access from the supplied workbook, v2.
#
# v1 quoted a single "DIA 1G" and did not say whether it meant a gigabit
# committed rate or a gigabit port. The model prices a committed service on its
# CIR, so it could not place the figure and DIA was held back. v2 separates
# port speed from CIR and its methodology sheet says so, which is what unblocked
# this.
#
# **Sixty observations and sixty derivations, kept apart.** Every cluster's
# three extra DIA columns are a fixed ratio of that cluster's own 1G CIR -
# 0.6496-0.6507, 0.8000 in all twenty rows, and 0.9197-0.9203. So the four DIA
# tiers are one observation restated four times, not four benchmarks, and the
# methodology sheet is honest about it: "added", not measured. Loading them as
# four independent rates would make the card look four times better evidenced
# than it is.
#
# What follows is that if a cluster's 1G CIR is wrong, all four of its tiers
# are wrong by the same factor - which is why the ratio is a governed
# assumption below rather than a constant here.
#
# A real German quote of EUR 950 for a 1 Gbps port with a 300 Mbit CIR converts
# to USD 1,091 against the workbook's Germany 300M CIR of 1,264: 0.86x, and
# 0.69x of the 1G CIR where the workbook models 0.80. One data point against
# one model, and it says the CIR discount may be steeper than assumed.

# The ratio each derived DIA tier bears to its cluster's 1G CIR. Governed,
# because it is the single number that moves three of the four tiers and the
# only real quote in evidence already disagrees with the middle one.
WORKBOOK_CIR_RATIOS = {
    ("DIA_BE", 1000): "0.65",     # best effort on a gigabit port
    ("DIA_CIR", 300): "0.80",     # the German quote implies nearer 0.69
    ("DIA_CIR", 500): "0.92",
}

# (cluster, kind, mbps, price) - the workbook's own observations.
WORKBOOK_COMMITTED_OBSERVED = [
    ("UK & Ireland", "DIA_CIR", 1000, 750),
    ("UK & Ireland", "ETHERNET", 1000, 750),
    ("UK & Ireland", "MPLS", 100, 1000),
    ("Benelux", "DIA_CIR", 1000, 1350),
    ("Benelux", "ETHERNET", 1000, 1100),
    ("Benelux", "MPLS", 100, 950),
    ("Germany", "DIA_CIR", 1000, 1580),
    ("Germany", "ETHERNET", 1000, 1250),
    ("Germany", "MPLS", 100, 1050),
    ("France", "DIA_CIR", 1000, 1520),
    ("France", "ETHERNET", 1000, 1200),
    ("France", "MPLS", 100, 1000),
    ("Nordics", "DIA_CIR", 1000, 1250),
    ("Nordics", "ETHERNET", 1000, 1050),
    ("Nordics", "MPLS", 100, 950),
    ("Southern Europe", "DIA_CIR", 1000, 1300),
    ("Southern Europe", "ETHERNET", 1000, 1050),
    ("Southern Europe", "MPLS", 100, 950),
    ("Eastern Europe", "DIA_CIR", 1000, 950),
    ("Eastern Europe", "ETHERNET", 1000, 800),
    ("Eastern Europe", "MPLS", 100, 750),
    ("North America", "DIA_CIR", 1000, 1350),
    ("North America", "ETHERNET", 1000, 1050),
    ("North America", "MPLS", 100, 900),
    ("Mexico", "DIA_CIR", 1000, 1450),
    ("Mexico", "ETHERNET", 1000, 1150),
    ("Mexico", "MPLS", 100, 1050),
    ("Brazil", "DIA_CIR", 1000, 1600),
    ("Brazil", "ETHERNET", 1000, 1300),
    ("Brazil", "MPLS", 100, 1250),
    ("LatAm Other", "DIA_CIR", 1000, 1750),
    ("LatAm Other", "ETHERNET", 1000, 1450),
    ("LatAm Other", "MPLS", 100, 1350),
    ("GCC", "DIA_CIR", 1000, 2400),
    ("GCC", "ETHERNET", 1000, 2000),
    ("GCC", "MPLS", 100, 1600),
    ("Middle East Other", "DIA_CIR", 1000, 2000),
    ("Middle East Other", "ETHERNET", 1000, 1650),
    ("Middle East Other", "MPLS", 100, 1350),
    ("South Africa", "DIA_CIR", 1000, 1650),
    ("South Africa", "ETHERNET", 1000, 1350),
    ("South Africa", "MPLS", 100, 1300),
    ("Africa Other", "DIA_CIR", 1000, 2600),
    ("Africa Other", "ETHERNET", 1000, 2100),
    ("Africa Other", "MPLS", 100, 1900),
    ("India", "DIA_CIR", 1000, 900),
    ("India", "ETHERNET", 1000, 700),
    ("India", "MPLS", 100, 750),
    ("North Asia", "DIA_CIR", 1000, 1400),
    ("North Asia", "ETHERNET", 1000, 1100),
    ("North Asia", "MPLS", 100, 1000),
    ("Singapore", "DIA_CIR", 1000, 1800),
    ("Singapore", "ETHERNET", 1000, 1450),
    ("Singapore", "MPLS", 100, 1150),
    ("ASEAN Tier 2", "DIA_CIR", 1000, 1400),
    ("ASEAN Tier 2", "ETHERNET", 1000, 1150),
    ("ASEAN Tier 2", "MPLS", 100, 1000),
    ("Oceania", "DIA_CIR", 1000, 1750),
    ("Oceania", "ETHERNET", 1000, 1450),
    ("Oceania", "MPLS", 100, 1250),
]

# (cluster, kind, mbps, price, ratio) - restatements of the 1G CIR above.
WORKBOOK_COMMITTED_DERIVED = [
    ("UK & Ireland", "DIA_BE", 1000, 488, "0.65"),
    ("UK & Ireland", "DIA_CIR", 300, 600, "0.80"),
    ("UK & Ireland", "DIA_CIR", 500, 690, "0.92"),
    ("Benelux", "DIA_BE", 1000, 878, "0.65"),
    ("Benelux", "DIA_CIR", 300, 1080, "0.80"),
    ("Benelux", "DIA_CIR", 500, 1242, "0.92"),
    ("Germany", "DIA_BE", 1000, 1027, "0.65"),
    ("Germany", "DIA_CIR", 300, 1264, "0.80"),
    ("Germany", "DIA_CIR", 500, 1454, "0.92"),
    ("France", "DIA_BE", 1000, 988, "0.65"),
    ("France", "DIA_CIR", 300, 1216, "0.80"),
    ("France", "DIA_CIR", 500, 1398, "0.92"),
    ("Nordics", "DIA_BE", 1000, 812, "0.65"),
    ("Nordics", "DIA_CIR", 300, 1000, "0.80"),
    ("Nordics", "DIA_CIR", 500, 1150, "0.92"),
    ("Southern Europe", "DIA_BE", 1000, 845, "0.65"),
    ("Southern Europe", "DIA_CIR", 300, 1040, "0.80"),
    ("Southern Europe", "DIA_CIR", 500, 1196, "0.92"),
    ("Eastern Europe", "DIA_BE", 1000, 618, "0.65"),
    ("Eastern Europe", "DIA_CIR", 300, 760, "0.80"),
    ("Eastern Europe", "DIA_CIR", 500, 874, "0.92"),
    ("North America", "DIA_BE", 1000, 878, "0.65"),
    ("North America", "DIA_CIR", 300, 1080, "0.80"),
    ("North America", "DIA_CIR", 500, 1242, "0.92"),
    ("Mexico", "DIA_BE", 1000, 942, "0.65"),
    ("Mexico", "DIA_CIR", 300, 1160, "0.80"),
    ("Mexico", "DIA_CIR", 500, 1334, "0.92"),
    ("Brazil", "DIA_BE", 1000, 1040, "0.65"),
    ("Brazil", "DIA_CIR", 300, 1280, "0.80"),
    ("Brazil", "DIA_CIR", 500, 1472, "0.92"),
    ("LatAm Other", "DIA_BE", 1000, 1138, "0.65"),
    ("LatAm Other", "DIA_CIR", 300, 1400, "0.80"),
    ("LatAm Other", "DIA_CIR", 500, 1610, "0.92"),
    ("GCC", "DIA_BE", 1000, 1560, "0.65"),
    ("GCC", "DIA_CIR", 300, 1920, "0.80"),
    ("GCC", "DIA_CIR", 500, 2208, "0.92"),
    ("Middle East Other", "DIA_BE", 1000, 1300, "0.65"),
    ("Middle East Other", "DIA_CIR", 300, 1600, "0.80"),
    ("Middle East Other", "DIA_CIR", 500, 1840, "0.92"),
    ("South Africa", "DIA_BE", 1000, 1072, "0.65"),
    ("South Africa", "DIA_CIR", 300, 1320, "0.80"),
    ("South Africa", "DIA_CIR", 500, 1518, "0.92"),
    ("Africa Other", "DIA_BE", 1000, 1690, "0.65"),
    ("Africa Other", "DIA_CIR", 300, 2080, "0.80"),
    ("Africa Other", "DIA_CIR", 500, 2392, "0.92"),
    ("India", "DIA_BE", 1000, 585, "0.65"),
    ("India", "DIA_CIR", 300, 720, "0.80"),
    ("India", "DIA_CIR", 500, 828, "0.92"),
    ("North Asia", "DIA_BE", 1000, 910, "0.65"),
    ("North Asia", "DIA_CIR", 300, 1120, "0.80"),
    ("North Asia", "DIA_CIR", 500, 1288, "0.92"),
    ("Singapore", "DIA_BE", 1000, 1170, "0.65"),
    ("Singapore", "DIA_CIR", 300, 1440, "0.80"),
    ("Singapore", "DIA_CIR", 500, 1656, "0.92"),
    ("ASEAN Tier 2", "DIA_BE", 1000, 910, "0.65"),
    ("ASEAN Tier 2", "DIA_CIR", 300, 1120, "0.80"),
    ("ASEAN Tier 2", "DIA_CIR", 500, 1288, "0.92"),
    ("Oceania", "DIA_BE", 1000, 1138, "0.65"),
    ("Oceania", "DIA_CIR", 300, 1400, "0.80"),
    ("Oceania", "DIA_CIR", 500, 1610, "0.92"),
]


# How a workbook "kind" becomes the model's own vocabulary.
#
# DIA_CIR is a committed internet service: priced on its CIR, which is the
# bandwidth on the row. DIA_BE is a gigabit port sold best-effort, so its
# service class is BEST_EFFORT and its priced rate is the port - a different
# product from a committed gigabit, which is the distinction v1 could not make.
WORKBOOK_KIND = {
    "DIA_CIR": ("DIA", "DIA"),
    "ETHERNET": ("ETHERNET", "ETHERNET"),
    "MPLS": ("IPVPN", "MPLS"),
}

# DIA_BE - a gigabit fibre port sold best effort - is NOT loaded.
#
# The two-dimension vocabulary handles it: BEST_EFFORT over ETHERNET_FIBRE is a
# valid pair and `carriers_for("BEST_EFFORT")` returns ETHERNET_FIBRE. What is
# missing is a name for it in the legacy `product` column the rate card is
# still keyed on, whose best-effort products are PON, HFC and 5G only.
#
# Mapping it to "DIA" put a best-effort port and a committed gigabit at the
# same (country, product, bandwidth) key - so a Dutch 1 Gbps DIA came back at
# 878 or 1350 depending on which row the query returned last. Caught by the
# duplicate-key and monotonicity checks together.
#
# Naming a new product is a vocabulary change that touches the simulation key,
# the legacy fallback and every migration that derived dimensions from a
# product string. It deserves its own release rather than the end of this one,
# and until then this figure is recorded in the workbook and not in the card.
WORKBOOK_UNLOADED = {
    "DIA_BE": ("a best-effort gigabit fibre port has no name in the legacy "
               "product vocabulary, whose best-effort products are PON, HFC "
               "and 5G. BEST_EFFORT over ETHERNET_FIBRE is valid in the "
               "two-dimension vocabulary and the card is not yet keyed on it."),
}


def _workbook_committed(observed, derived, clusters):
    """Committed-access rows per country, from cluster prices.

    Per country because the scope ladder has no cluster rung, same as the
    consumer-access loader above.

    The band is +/-25% around the point, and the point is the workbook's. A
    derived tier carries the same band as an observed one, because the width
    reflects market spread rather than confidence in the figure - the
    confidence difference is recorded in the source note instead, where a
    reader can act on it.
    """
    from decimal import Decimal as _D

    entries = [(c, k, m, v, None) for c, k, m, v in observed
               if k in WORKBOOK_KIND]
    entries += [(c, k, m, v, r) for c, k, m, v, r in derived
                if k in WORKBOOK_KIND]

    by_cluster = {}
    for cluster, kind, mbps, price, ratio in entries:
        by_cluster.setdefault(cluster, []).append((kind, mbps, price, ratio))

    out = []
    for cluster, rows in sorted(by_cluster.items()):
        for country in clusters.get(cluster, []):
            for kind, mbps, price, _ratio in rows:
                _service, product = WORKBOOK_KIND[kind]
                base = _D(price)
                out.append((country, product, "L0", int(mbps),
                            int(base * _D("0.75")), int(base),
                            int(base * _D("1.25"))))
    return out


# Rates sourced to a publication, superseding the seeded assumption for the
# same key.
#
# The seeded GB card was overstated against the published market by 1.3x to
# 1.9x, averaging about 1.5x - and GB is the anchol EUROPE_WEST and EMEA derive
# from, so the overstatement propagated to every European estate and roughly
# half the baseline in every run.
#
# **The band is the published range, not a point with an invented spread.**
# 150-350 becomes the low and the high. Narrowing a market range to a midpoint
# and then generating a band around it would assert a precision the sources do
# not have, and the width is the information: a 1 Gbps circuit genuinely costs
# two to three times more in one postcode than another.
#
# **The basis is SME retail, and that is a known bias.** These ranges come from
# comparison sites and ISP guides. A fifty-site enterprise on a framework pays
# materially less than a single-site SME quote, and a two-thousand-site estate
# less again. So this corrects an overstatement and installs a smaller one in
# the same direction for large estates - which is recorded on the row rather
# than discovered later.
#
# Grade C: a market benchmark somebody published and a person can check. Not B,
# which is a real transactable price from the seller; not A, which is an
# invoice. Only the Openreach wholesale figure below is a seller's own tariff.
#
# (country, product, mbps, low_local, high_local, currency, grade, source)
SOURCED_RATES = [
    # UK leased line / DIA retail market, September 2026. Five independent
    # sources agree on these bands to within about 15%.
    ("GB", "DIA", 100, 150, 350, "GBP", "C",
     "UK leased line market survey, Sept 2026 (Cloudswitched, Purple, "
     "CompareYourBusinessCosts); SME retail basis"),
    ("GB", "DIA", 1000, 300, 800, "GBP", "C",
     "UK leased line market survey, Sept 2026; SME retail basis"),
    ("GB", "ETHERNET", 500, 250, 600, "GBP", "C",
     "UK leased line market survey, Sept 2026; SME retail basis"),
    ("GB", "ETHERNET", 1000, 300, 800, "GBP", "C",
     "UK leased line market survey, Sept 2026; SME retail basis"),
    ("GB", "ETHERNET", 10000, 800, 3500, "GBP", "C",
     "UK leased line market survey, Sept 2026; SME retail basis"),
    # Virgin Media Business publishes an entry price for its own 100 Mbps
    # dedicated access, which is a seller's tariff rather than a survey - so
    # grade B, and it anchors the bottom of the band above.
    ("GB", "DIA", 100, 185, 185, "GBP", "B",
     "Virgin Media Business published entry price for 100 Mbps Dedicated "
     "Internet Access, Sept 2026"),
]

# Where a country's rate is quoted in its own currency. The seeded card is USD
# throughout, so a sourced sterling rate has to be converted before it can sit
# beside one - and the conversion is recorded rather than folded in silently.
#
# This is the mistake that produced the 1.5x finding in the first place: the
# seeded priors are USD and were compared against sterling market figures, so
# the overstatement was reported as 2.6x when it is 1.9x. The model has a
# currency module built to prevent exactly that; the comparison was done
# outside it.
SOURCED_FX = {"GBP": "1.34"}     # GBP/USD mid-market, 16 September 2026
SOURCED_FX_NOTE = ("GBP/USD 1.34, mid-market 16 September 2026. A rate this "
                   "old prices a circuit at last month's exchange rate; the "
                   "case's own fx_convention governs a live estimate.")


def _sourced_priors(rows):
    """Sourced rates in the seed's tuple shape, converted to USD.

    The base is the midpoint of the published band, because a band needs one.
    Which is the one invented number here, and it is an average of two figures
    that were both published rather than a figure conjured between them.

    A finer grade wins on the same key: the Virgin Media tariff is grade B and
    supersedes the survey band at 100 Mbps.
    """
    from decimal import Decimal as _D

    # A point observation ANCHORS the band; it does not replace it.
    #
    # The first version let a finer grade win outright, so Virgin Media's
    # published 185 entry price superseded the 150-350 survey band and the
    # rate collapsed to a single number. An entry price is the bottom of a
    # market, not the whole of it: one seller's cheapest tariff says nothing
    # about what the same circuit costs in a harder postcode.
    bands, anchors = {}, {}
    for country, product, mbps, low, high, currency, grade, source in rows:
        key = (country, product, int(mbps))
        if low == high:
            # A single quoted price. Kept as a floor for the band.
            keep = anchors.get(key)
            if keep is None or _D(low) < _D(keep[0]):
                anchors[key] = (low, currency, grade, source)
        else:
            bands[key] = (low, high, currency, grade, source)

    out = []
    for key in sorted(set(bands) | set(anchors)):
        country, product, mbps = key
        if key in bands:
            low, high, currency, _grade, _source = bands[key]
        else:
            # Only a point, so the band is that point - honest about having
            # one observation rather than inventing a spread around it.
            low, currency, _grade, _source = anchors[key]
            high = low
        fx = _D(SOURCED_FX.get(currency, "1"))
        lo, hi = _D(low) * fx, _D(high) * fx
        if key in anchors and key in bands:
            # The seller's own tariff sets the floor if it is below the
            # survey's, because a published price is better evidence of what
            # the cheapest end of the market is than a survey's estimate of it.
            anchor_low = _D(anchors[key][0]) * _D(
                SOURCED_FX.get(anchors[key][1], "1"))
            lo = min(lo, anchor_low)
        out.append((country, product, "L0", int(mbps),
                    int(lo), int((lo + hi) / 2), int(hi)))
    return out




# Regional fallback rates, derived from the member countries that have a card.
#
# The three regions held exactly one row each - ETHERNET at 10 Gbps, for the
# backbone - so a country without its own card fell through to a region that
# could not price a branch, a store or an office. Brazil and India were mapped
# and still came back unpriced.
#
# **Derived, and only where there is something to derive from.** A region takes
# the median of its member countries at each (product, tier), which is a
# defensible average of real markets where several exist. Where only one member
# has a card, the region is that country wearing a regional label - so it is
# still emitted, because refusing leaves every estate in the region unpriced,
# but `member_count` records how thin it is and the source note says so.
#
# The median, not the mean: EMEA spans Germany and Egypt, and one expensive
# market should not carry the region.
#
# Grade E, and a wider grade E than a country row - the scope ladder records
# that a REGION price was used, and `unsourced_price_share` counts it. A
# regional average across EMEA is a starting point for research, not an answer.
def _regional_tiers(rows, country_region):
    """One row per (region, product, tier) the region's members price."""
    from decimal import Decimal as _D

    region_of = dict(country_region)
    present = {(country, product, mbps)
               for country, product, _l, mbps, *_r in rows}

    grouped, members = {}, {}
    for country, product, layer, mbps, low, base, high in rows:
        region = region_of.get(country)
        if region is None or len(country) != 2:
            continue
        key = (region, product, int(mbps))
        grouped.setdefault(key, []).append(
            (_D(low), _D(base), _D(high), layer))
        members.setdefault(region, set()).add(country)

    def _median(values):
        ordered = sorted(values)
        middle = len(ordered) // 2
        return (ordered[middle] if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / 2)

    out = []
    for (region, product, mbps), quotes in sorted(grouped.items()):
        if (region, product, mbps) in present:
            # A row already exists at this key, and for the regions that means
            # the backbone: ETHERNET at 10 Gbps between a hub and the core.
            #
            # Not overwritten, and not added beside. `match_prior` is keyed
            # (scope, product, bandwidth) and ignores role, so one row has to
            # serve both a backbone leg and a 10 Gbps site access circuit in
            # an unlisted country - and EMEA's backbone price is 7000 against
            # GB's 3700 for access. Overwriting would underprice the backbone;
            # adding a second row is impossible on a shared key; leaving it
            # means a Polish data centre prices at 1.9x.
            #
            # So the region declines to price site access at that tier. An
            # unlisted-country 10 Gbps site is unpriced scope, reported by the
            # coverage gate, which is the model's answer everywhere else it
            # cannot tell two things apart.
            continue
        out.append((region, product, quotes[0][3], mbps,
                    int(_median([q[0] for q in quotes])),
                    int(_median([q[1] for q in quotes])),
                    int(_median([q[2] for q in quotes]))))
    return out


# The tiers each country's own estates need and its card does not quote.
#
# A Dutch and French estate came back 67% covered while the same estate in the
# US covered 100%: FR and NL quote no Ethernet at all and no DIA above 500
# Mbps, while GB, DE and US quote both. Nothing caught it because the
# priceability check asked "does *any* country quote this tier" - and ETHERNET
# 250 exists in the US, so it passed while France could not price it.
#
# Derived from each country's own DIA curve rather than copied from Germany.
# France and the Netherlands both price DIA at 100 and 500, so the shape of
# their own market is known; what is missing is the top of the curve and the
# Ethernet product beside it. Copying DE would assert that a French circuit
# costs what a German one costs, which is the thing a rate card exists to
# answer rather than assume.
#
# Grade E, like every seeded rate. They make these estates priceable; they do
# not make them evidenced, and a real engagement in France should replace them
# with a quote.
_TIER_FILL = (
    # (product, tier, multiple of this country's own DIA 500 base)
    #
    # DIA 500 is emitted too, for a country anchored on its 100 row: leaving a
    # hole between 100 and 1000 means match_prior takes the next tier up, so a
    # 500 Mbps circuit in the UAE would have been priced at the gigabit rate.
    ("DIA", 500, "1.00"),
    ("DIA", 1000, "1.45"),        # DE and GB both run ~1.45x from 500 to 1000
    ("ETHERNET", 500, "0.80"),    # Ethernet undercuts DIA at the same tier
    ("ETHERNET", 1000, "1.15"),
    ("ETHERNET", 10000, "3.80"),  # DE runs 4000/1090 = 3.7x from DIA 500
)


def _fill_country_tiers(rows):
    """Tiers a country's estates need, scaled from that country's own DIA 500.

    Only for a country that already quotes DIA at 500 - that row is the anchor,
    and a country without one has no curve to extend. Never overwrites an
    existing row.
    """
    from decimal import Decimal as _D

    anchors, present = {}, set()
    for country, product, layer, mbps, low, base, high in rows:
        present.add((country, product, mbps))
        # DIA 500 is the preferred anchor. The UAE quotes DIA at 100 only, so
        # its curve starts lower - scaled from 100 with the step to 500 that
        # every other market shows, rather than left unpriceable. A country
        # with no DIA row at all is left alone: there is no curve to extend and
        # inventing one would assert a market.
        if product == "DIA" and len(country) == 2:
            rank = {500: 2, 100: 1}.get(mbps)
            if rank and rank > anchors.get(country, (0,))[0]:
                scale = _D("1") if mbps == 500 else _D("1.90")
                anchors[country] = (rank, layer, _D(low) * scale,
                                    _D(base) * scale, _D(high) * scale)

    out = []
    for country, (_rank, layer, low, base, high) in sorted(anchors.items()):
        for product, tier, factor in _TIER_FILL:
            if (country, product, tier) in present:
                continue
            f = _D(factor)
            out.append((country, product, layer, tier,
                        int(low * f), int(base * f), int(high * f)))
    return out


# Consumer-access tiers above 100 Mbps, added in 4.205.0.
#
# The BICS benchmark puts a supermarket store at 275 Mbps and the card quoted
# BROADBAND_HFC and BROADBAND_PON at 50 and 100 only - so every store in every
# retail estate was unpriced scope. A nine-company run came back at 2% coverage
# for Carrefour, 15% for Aldi and 15% for Marks & Spencer, and correctly
# refused to price the rest.
#
# The gate was working. The card had simply not kept up with the bandwidths
# 4.193 introduced, and nothing caught it because the pricing tests use
# industries whose figures happen to land on a quoted tier.
#
# 250 / 500 / 1000 are the commonest business broadband tiers in these markets.
# Priced by extending each country's own 100 Mbps row rather than by inventing
# a figure: the step from 100 to 250 costs less than 2.5x because the access is
# the same and only the profile changes, which is how these are actually sold.
#
# Grade E, like every other seeded rate. They make a retail estate priceable;
# they do not make it evidenced.
_CONSUMER_UPLIFT = ((250, "1.35"), (500, "1.70"), (1000, "2.20"))


def _consumer_tiers(rows):
    """Higher tiers for each country that already prices consumer access.

    Extends what is there rather than adding countries: a country with no HFC
    row has no HFC market recorded, and inventing three tiers for it would be
    asserting a market rather than extending one.
    """
    from decimal import Decimal as _D

    # Anchored on each country's own highest existing tier, not on a 100 Mbps
    # row. France and the Netherlands price HFC at 50 only, so keying on 100
    # skipped them - and a French supermarket estate stayed unpriceable, which
    # is the defect this whole change exists to fix, reproduced one level down.
    highest = {}
    for country, product, layer, mbps, low, base, high in rows:
        if product not in ("BROADBAND_HFC", "BROADBAND_PON"):
            continue
        key = (country, product)
        if key not in highest or mbps > highest[key][0]:
            highest[key] = (mbps, layer, low, base, high)

    out = []
    for (country, product), (mbps, layer, low, base, high) in highest.items():
        for tier, factor in _CONSUMER_UPLIFT:
            if tier <= mbps:
                continue                 # already priced at or above this
            # Scaled from the anchor's own bandwidth, so a country anchored at
            # 50 is not charged as though it were anchored at 100.
            scale = _D(factor) * _D(100) / _D(mbps)
            out.append((country, product, layer, tier,
                        int(_D(low) * scale), int(_D(base) * scale),
                        int(_D(high) * scale)))
    return out


PRIORS = [
    # --- GB
    ("GB", "DIA", "L0", 100, 380, 520, 720), ("GB", "DIA", "L0", 500, 720, 980, 1350),
    ("GB", "DIA", "L0", 1000, 1050, 1420, 1950),
    ("GB", "BROADBAND_PON", "L0", 50, 38, 58, 90),
    ("GB", "BROADBAND_PON", "L0", 100, 45, 70, 110),
    ("GB", "BROADBAND_HFC", "L0", 50, 42, 65, 100),
    ("GB", "BROADBAND_HFC", "L0", 100, 52, 80, 125),
    ("GB", "MPLS", "L0", 100, 700, 980, 1400),
    ("GB", "ETHERNET", "L0", 500, 550, 780, 1100),
    ("GB", "ETHERNET", "L0", 10000, 2600, 3700, 5200),
    ("GB", "MOBILE_5G", "L0", 50, 25, 45, 80),

    # --- DE
    ("DE", "DIA", "L0", 100, 420, 580, 800), ("DE", "DIA", "L0", 500, 800, 1090, 1500),
    ("DE", "DIA", "L0", 1000, 1160, 1580, 2170),
    ("DE", "BROADBAND_PON", "L0", 50, 42, 64, 100),
    ("DE", "BROADBAND_PON", "L0", 100, 50, 78, 120),
    ("DE", "BROADBAND_HFC", "L0", 50, 46, 72, 112),
    ("DE", "BROADBAND_HFC", "L0", 100, 58, 89, 138),
    ("DE", "MPLS", "L0", 100, 760, 1050, 1500),
    ("DE", "ETHERNET", "L0", 500, 600, 840, 1180),
    ("DE", "ETHERNET", "L0", 10000, 2850, 4000, 5600),
    ("DE", "MOBILE_5G", "L0", 50, 28, 50, 88),

    # --- Regional backbone. Priced against the region, not a country, because
    # a hub-to-core circuit belongs to a region: match_prior keys on
    # (country, product, bandwidth) and the simulation puts the region name in
    # the country position for these rows.
    #
    # Without these every backbone circuit is unpriced, and adding a core would
    # have dragged coverage down rather than improving the baseline - a change
    # that made the estimate worse while looking more complete.
    #
    # Indicative 10 GbE wavelength / carrier-ethernet monthly rates. Wide bands
    # because a regional average spans metro and long-haul.
    ("EMEA", "ETHERNET", "L0", 10000, 4500, 7000, 11000),
    ("AMER", "ETHERNET", "L0", 10000, 4000, 6200, 9800),
    ("APAC", "ETHERNET", "L0", 10000, 6500, 9500, 15000),

    # --- US. The business-broadband bands are wider and higher than the
    # single pre-split BROADBAND band they replace, which described
    # residential-grade service and understated business connectivity at
    # branch sites. These are indicative market figures like every other row
    # here - seed defaults a steward is expected to replace with real
    # benchmarks through the ingestion path, not values carried over from any
    # engagement.
    ("US", "DIA", "L0", 100, 350, 480, 660), ("US", "DIA", "L0", 500, 680, 920, 1270),
    ("US", "DIA", "L0", 1000, 990, 1340, 1840),
    ("US", "BROADBAND_PON", "L0", 50, 70, 105, 165),
    ("US", "BROADBAND_PON", "L0", 100, 85, 125, 195),
    ("US", "BROADBAND_HFC", "L0", 50, 110, 150, 225),
    ("US", "BROADBAND_HFC", "L0", 100, 130, 170, 260),
    ("US", "MPLS", "L0", 100, 650, 900, 1300),
    ("US", "ETHERNET", "L0", 500, 520, 720, 1000),
    ("US", "ETHERNET", "L0", 10000, 2500, 3450, 4800),
    ("US", "MOBILE_5G", "L0", 50, 30, 55, 95),

    # --- FR
    ("FR", "DIA", "L0", 100, 400, 550, 760), ("FR", "DIA", "L0", 500, 760, 1050, 1450),
    ("FR", "BROADBAND_PON", "L0", 50, 36, 56, 88),
    ("FR", "BROADBAND_PON", "L0", 100, 42, 68, 105),
    ("FR", "BROADBAND_HFC", "L0", 50, 40, 62, 97),
    ("FR", "MPLS", "L0", 100, 720, 1000, 1420),
    ("FR", "MOBILE_5G", "L0", 50, 26, 47, 84),

    # --- NL
    ("NL", "DIA", "L0", 100, 360, 500, 690), ("NL", "DIA", "L0", 500, 690, 950, 1310),
    ("NL", "BROADBAND_PON", "L0", 50, 34, 53, 84),
    ("NL", "BROADBAND_PON", "L0", 100, 40, 62, 98),
    ("NL", "BROADBAND_HFC", "L0", 50, 38, 59, 92),
    ("NL", "MOBILE_5G", "L0", 50, 24, 43, 78),

    # --- SG
    ("SG", "DIA", "L0", 100, 480, 660, 920), ("SG", "DIA", "L0", 500, 910, 1250, 1740),
    ("SG", "BROADBAND_PON", "L0", 50, 52, 82, 126),
    ("SG", "BROADBAND_PON", "L0", 100, 60, 95, 145),
    ("SG", "MOBILE_5G", "L0", 50, 35, 62, 105),

    # --- AE
    ("AE", "DIA", "L0", 100, 900, 1300, 1900),
    ("AE", "BROADBAND_PON", "L0", 50, 105, 165, 250),
    ("AE", "BROADBAND_PON", "L0", 100, 120, 190, 290),
    ("AE", "MOBILE_5G", "L0", 50, 55, 95, 160),
]

def _reprice_between_sourced(rows):
    """Unsourced tiers that now sit above a sourced tier above them.

    Sourcing GB DIA at 100 and 1000 left the seeded 500 Mbps row untouched at
    980 while the sourced gigabit came in at 737 - a 500 Mbps circuit priced
    above a 1 Gbps one. `match_prior` takes the cheapest tier at or above the
    requirement so it self-corrects in the estimate, but the card is then
    internally inconsistent and a reader comparing two rows sees nonsense.

    Interpolated on log bandwidth between the two sourced neighbours, because
    access pricing is roughly logarithmic in capacity - doubling the bearer
    does not double the charge. Marked nowhere as sourced: it is an
    interpolation between two published points and stays grade E.
    """
    from decimal import Decimal as _D
    import math

    sourced = {}
    for country, product, mbps, low, high, currency, _g, _s in SOURCED_RATES:
        fx = _D(SOURCED_FX.get(currency, "1"))
        key = (country, product)
        sourced.setdefault(key, {})[int(mbps)] = (
            _D(low) * fx, _D(high) * fx)

    out = []
    for row in rows:
        country, product, layer, mbps, low, base, high = row
        tiers = sourced.get((country, product))
        if not tiers or int(mbps) in tiers:
            out.append(row)
            continue
        below = [t for t in tiers if t < int(mbps)]
        above = [t for t in tiers if t > int(mbps)]
        if not below or not above:
            out.append(row)
            continue
        lo_t, hi_t = max(below), min(above)
        # Only reprice where the row actually contradicts its neighbour.
        if _D(base) <= (tiers[hi_t][0] + tiers[hi_t][1]) / 2:
            out.append(row)
            continue
        span = math.log(hi_t / lo_t)
        position = math.log(int(mbps) / lo_t) / span if span else 0
        def _between(a, b):
            return a * (b / a) ** _D(str(position)) if a > 0 else b
        new_low = _between(tiers[lo_t][0], tiers[hi_t][0])
        new_high = _between(tiers[lo_t][1], tiers[hi_t][1])
        out.append((country, product, layer, int(mbps), int(new_low),
                    int((new_low + new_high) / 2), int(new_high)))
    return out


# Workbook consumer-access prices supersede the seeded assumption for the same
# (country, product, bandwidth). Applied before the regional derivation, so
# EUROPE_NORTH, EUROPE_SOUTH and the African bands derive from real cluster
# figures instead of falling through to a European median - which is the first
# time those bands have anything of their own.
_WORKBOOK_ROWS = _workbook_priors(WORKBOOK_ACCESS_PRICES, WORKBOOK_CLUSTERS)
_WORKBOOK_KEYS = {(r[0], r[1], r[3]) for r in _WORKBOOK_ROWS}
PRIORS = [row for row in PRIORS
          if (row[0], row[1], int(row[3])) not in _WORKBOOK_KEYS]
PRIORS = PRIORS + _WORKBOOK_ROWS

# The 50 Mbps tier the workbook does not quote.
#
# The workbook starts at 100, so the seeded 50 Mbps rows survived - and where
# the workbook came in below the assumption they replaced, the old 50 was left
# sitting ABOVE the new 100. The US quoted PON at 105 for 50 Mbps and 85 for
# 100, which reads as nonsense and would make right-sizing recommend an
# upgrade to save money.
#
# Scaled down from the workbook's own 100 Mbps figure by the ratio the seeded
# card used between its 50 and 100 tiers, so the shape of the market is kept
# and only the level moves. Stays grade E: it is an extrapolation below the
# lowest published point, and extrapolating is exactly what the term-factor
# work refuses to do for the same reason.
def _rescale_lowest_tier(rows, workbook_keys):
    """A tier below the workbook's floor, rescaled to sit under it."""
    from decimal import Decimal as _D

    base = {(c, p, bw): ba for c, p, _l, bw, _lo, ba, _hi in rows}
    out = []
    for row in rows:
        country, product, layer, mbps, low, mid, high = row
        if (country, product, mbps) in workbook_keys or mbps != 50:
            out.append(row)
            continue
        above = base.get((country, product, 100))
        if above is None or _D(mid) <= _D(above):
            out.append(row)
            continue
        # The seeded card's own 50/100 ratio, applied to the workbook's 100.
        ratio = _D("0.80")          # every seeded pair sat within 0.78-0.84
        new = _D(above) * ratio
        out.append((country, product, layer, mbps,
                    int(new * _D("0.75")), int(new), int(new * _D("1.25"))))
    return out


PRIORS = _rescale_lowest_tier(PRIORS, _WORKBOOK_KEYS)

# Committed access from v2, on the same terms: supersedes the seeded row for
# the same key, applied before the regional derivation so the bands derive from
# cluster figures.
_V2_ROWS = _workbook_committed(WORKBOOK_COMMITTED_OBSERVED,
                               WORKBOOK_COMMITTED_DERIVED, WORKBOOK_CLUSTERS)
_V2_KEYS = {(r[0], r[1], r[3]) for r in _V2_ROWS}
PRIORS = [row for row in PRIORS
          if (row[0], row[1], int(row[3])) not in _V2_KEYS]
PRIORS = PRIORS + _V2_ROWS

# A sourced rate supersedes the seeded assumption for the same key, and does so
# BEFORE the regional derivation - so EUROPE_WEST and EMEA are derived from the
# published GB band rather than from the overstatement it replaced.
_SOURCED_KEYS = {(r[0], r[1], int(r[2])) for r in SOURCED_RATES}
PRIORS = [row for row in PRIORS
          if (row[0], row[1], int(row[3])) not in _SOURCED_KEYS]
PRIORS = PRIORS + _sourced_priors(SOURCED_RATES)
PRIORS = _reprice_between_sourced(PRIORS)

PRIORS = PRIORS + _consumer_tiers(PRIORS)
PRIORS = PRIORS + _fill_country_tiers(PRIORS)

# How an estate of a given kind typically distributes. Shares of the whole
# estate, so each industry's rows sum to 1.
#
# These are starting positions, not findings. A discount grocer is overwhelm-
# ingly stores with a handful of regional distribution centres; a bank is
# branches with more office weight; a distributor sits between the two with far
# more warehouse. Getting the shape roughly right beats an empty table, and
# getting it exactly right is what the named locations and domain 2 are for.
# Generated from domain/industries.py rather than hand-written.
#
# Twenty-eight industries x five archetypes x four density bands is a hundred
# and eighty-seven rows, and twenty-eight hand-written mixes would be
# twenty-eight chances to fat-finger a share that has to sum to exactly one.
# The shapes are the thing that differs; the industries choose a shape.
# BICS L3 is the taxonomy. Two existed and three of forty-two codes overlapped,
# so an analyst picking AIRPORTS or DEFENSE from the intake list got no
# benchmark row and the published data was unreachable for twenty-five of
# twenty-eight industries.
#
# The mix is derived from the estate shape rather than from the benchmark: the
# benchmark names one representative archetype per industry and an estate has
# several. A supermarket chain has stores, distribution centres and a head
# office, and the benchmark says only "STORE".
#
# The workbench's own rows are kept as well, so a case created before this
# still resolves its industry.
# The supplied BICS L3 WAN benchmark, parsed at seed time rather than stored
# pre-parsed. A refused row is named in the seed log rather than silently
# dropped: an industry left with no benchmark and no explanation is discovered
# as a missing figure three screens later.
INDUSTRY_BENCHMARK = industry_benchmark.seeded()

# BICS supersedes, never adds. RETAIL_BANKING, INSURANCE and LOGISTICS exist
# in both taxonomies - the three-code overlap - and appending gave each of them
# two mixes summing to 2.0000, which the footprint resolver would have read as
# twice the estate.
_BICS_MIX = bics.density_mix_rows(INDUSTRY_BENCHMARK["industries"],
                                  industries.SHAPES)
_BICS_CODES = {row[0] for row in _BICS_MIX}
DENSITY_MIX = ([row for row in industries.density_mix_rows()
                if row[0] not in _BICS_CODES]
               + _BICS_MIX)

# Density bands, weakest coverage last. Derivable from a postcode without a
# survey, which is why the model clusters on them: serviceability itself needs
# a regulator lookup per area, and this predicts it well enough to price with.
DENSITY_BANDS = ("DENSE_URBAN", "URBAN", "SUBURBAN", "RURAL")

# What can be delivered in each band. (country, density, product, available,
# max_mbps)
#
# The pattern that matters for a retail estate: DIA and Ethernet thin out with
# density while broadband and mobile persist, so a rural store is not a cheaper
# version of an urban one - it is a different circuit, and sometimes an
# unserviceable one.
#
# Indicative and governed. A steward retunes these per engagement, and a
# researched fact about a specific area replaces them.
# What physically reaches a building, by density band.
#
# Keyed on the access technology rather than the product. The old table asked
# "is MPLS available in rural Germany", which a carrier answers by whether it
# will sell there; this asks whether a bearer reaches the site, which is what a
# survey establishes. Every service class that bearer can carry then follows
# from domain/access.SERVICE_ACCESS.
#
# The practical difference: an IPVPN in a rural town is now deliverable if VDSL
# reaches it, which is true and the old table could not say. A DIA in the same
# town is not, because no dedicated bearer reaches it - which the old table
# said for the wrong reason.
SERVICEABILITY = [
    (c, band, technology, available, mbps)
    for c in ("DE", "GB", "FR", "NL", "US")
    for band, technology, available, mbps in (
        ("DENSE_URBAN", "ETHERNET_FIBRE", True, 10000),
        ("DENSE_URBAN", "DARK_FIBRE", True, 100000),
        ("DENSE_URBAN", "PON", True, 1000),
        ("DENSE_URBAN", "HFC", True, 1000),
        ("DENSE_URBAN", "VDSL", True, 80),
        ("DENSE_URBAN", "ADSL", True, 24),
        ("DENSE_URBAN", "MOBILE_5G", True, 300),
        ("DENSE_URBAN", "MOBILE_4G", True, 50),

        ("URBAN", "ETHERNET_FIBRE", True, 1000),
        ("URBAN", "DARK_FIBRE", True, 10000),
        ("URBAN", "PON", True, 1000),
        ("URBAN", "HFC", True, 1000),
        ("URBAN", "VDSL", True, 80),
        ("URBAN", "ADSL", True, 24),
        ("URBAN", "MOBILE_5G", True, 300),
        ("URBAN", "MOBILE_4G", True, 50),

        # Dedicated fibre thins out first, and at a lower tier.
        ("SUBURBAN", "ETHERNET_FIBRE", True, 500),
        ("SUBURBAN", "DARK_FIBRE", False, None),
        ("SUBURBAN", "PON", True, 300),
        ("SUBURBAN", "HFC", True, 500),
        ("SUBURBAN", "VDSL", True, 80),
        ("SUBURBAN", "ADSL", True, 24),
        ("SUBURBAN", "MOBILE_5G", True, 200),
        ("SUBURBAN", "MOBILE_4G", True, 50),

        # Rural is where a retail estate's assumptions break. Dedicated fibre
        # is a build rather than a service, so it is unavailable rather than
        # expensive: an estimate that prices a circuit nobody can deliver is
        # worse than one that reports it cannot be delivered.
        #
        # Copper and cable still reach, which is why a best-effort or a
        # committed VPN is deliverable here and a DIA is not.
        ("RURAL", "ETHERNET_FIBRE", False, None),
        ("RURAL", "DARK_FIBRE", False, None),
        ("RURAL", "PON", True, 100),
        ("RURAL", "HFC", True, 200),
        ("RURAL", "VDSL", True, 40),
        ("RURAL", "ADSL", True, 16),
        ("RURAL", "FWA", True, 100),
        ("RURAL", "MOBILE_5G", True, 100),
        ("RURAL", "MOBILE_4G", True, 30),
        ("RURAL", "SATELLITE", True, 50),
    )
]

# Which region each country clusters into. Only the countries this build seeds
# prices for, plus the ones the illustrative footprint uses - a mapping is
# useless without prices behind the products it implies, and an unmapped
# country is reported rather than guessed.
# Exchange rates, as governed reference data.
#
# Only two are sourced. GBP/USD and EUR/USD were looked up this month while
# correcting the GB rate card, so they carry a date and a basis; the rest are
# indicative and say so. That asymmetry is the honest state of it, and a
# steward replacing a row with a client's own budget rate is the normal case
# rather than an exception.
#
# All quoted as X per USD, because every seeded prior is USD and the
# conversion an estimate needs is card -> case. `currency.convert()` derives
# the inverse, so a USD case against a GBP card works from the same rows.
#
# SPOT dated when it was read. A BUDGET rate is what a client sets for their
# year and this model has no client's budget rate, so none is seeded - an
# engagement that has one adds it, and `select_rate` will prefer it over these
# the moment it exists.
#
# (from, to, rate, as_of, convention, grade, source)
FX_RATES = [
    ("USD", "GBP", "0.7463", "2026-09-16", "SPOT", "B",
     "mid-market GBP/USD 1.3400 inverted, 16 September 2026; the rate used to "
     "convert the sourced UK market bands on this card"),
    ("USD", "EUR", "0.8711", "2026-09-17", "SPOT", "B",
     "mid-market EUR/USD 1.1480 inverted, 17 September 2026; the rate used to "
     "read a German quote against this card"),
    # Indicative. Grade E and dated the start of the pricing year rather than
    # a day, because a figure nobody looked up should not wear a date that
    # says somebody did.
    ("USD", "CHF", "0.80", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "SEK", "9.50", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "NOK", "10.30", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "DKK", "6.50", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "PLN", "3.80", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "CZK", "21.50", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "AED", "3.6725", "2026-01-01", "SPOT", "C",
     "the UAE dirham is pegged to the dollar at 3.6725; a peg is better "
     "evidence than a guess and worse than a quote"),
    ("USD", "SGD", "1.28", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "AUD", "1.48", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "CAD", "1.36", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "JPY", "148.0", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "INR", "84.0", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "BRL", "5.50", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "MXN", "18.50", "2026-01-01", "SPOT", "E", "indicative only"),
    ("USD", "ZAR", "18.00", "2026-01-01", "SPOT", "E", "indicative only"),
]


# Which region a country falls back to when it has no card of its own.
#
# Ten regions. EMEA was one, spanning Germany and Ethiopia - 125 countries
# taking a median of five European markets, which is a number with very little
# information in it. It is now eight: five European bands, the Middle East, and
# Africa north and south of the Sahara.
#
# **A sub-region only prices what its own members price, so most of these have
# no rates yet.** Only western Europe (GB, FR, NL), central Europe (DE) and the
# Middle East (AE) contain a country with a card. The other five would leave
# every estate in them unpriced - which is why REGION_PARENT exists below and
# the fallback is a chain rather than a single rung.
#
# The split is the structure for research to land in: when an African or Nordic
# rate card arrives, AFRICA_SSA or EUROPE_NORTH starts pricing from it and
# nothing else has to change.
#
# Generated against the system's iso-codes list, not typed from memory - which
# is how the previous map ended up with eight African countries out of
# fifty-four.
#
# Assignments are carrier-market judgements. Turkey sits in MIDDLE_EAST and
# Russia in EUROPE_EAST because that is how carriers sell, not where the
# borders are; these are governed rows a steward retunes without a release.
COUNTRY_REGION = [
    # --- EUROPE_WEST (11)
    ("BE", "EUROPE_WEST"), ("FO", "EUROPE_WEST"), ("FR", "EUROPE_WEST"), ("GB", "EUROPE_WEST"), ("GG", "EUROPE_WEST"),
    ("IE", "EUROPE_WEST"), ("IM", "EUROPE_WEST"), ("JE", "EUROPE_WEST"), ("LU", "EUROPE_WEST"), ("MC", "EUROPE_WEST"),
    ("NL", "EUROPE_WEST"),
    # --- EUROPE_CENTRAL (9)
    ("AT", "EUROPE_CENTRAL"), ("CH", "EUROPE_CENTRAL"), ("CZ", "EUROPE_CENTRAL"), ("DE", "EUROPE_CENTRAL"), ("HU", "EUROPE_CENTRAL"),
    ("LI", "EUROPE_CENTRAL"), ("PL", "EUROPE_CENTRAL"), ("SI", "EUROPE_CENTRAL"), ("SK", "EUROPE_CENTRAL"),
    # --- EUROPE_NORTH (10)
    ("AX", "EUROPE_NORTH"), ("DK", "EUROPE_NORTH"), ("EE", "EUROPE_NORTH"), ("FI", "EUROPE_NORTH"), ("IS", "EUROPE_NORTH"),
    ("LT", "EUROPE_NORTH"), ("LV", "EUROPE_NORTH"), ("NO", "EUROPE_NORTH"), ("SE", "EUROPE_NORTH"), ("SJ", "EUROPE_NORTH"),
    # --- EUROPE_SOUTH (16)
    ("AD", "EUROPE_SOUTH"), ("AL", "EUROPE_SOUTH"), ("BA", "EUROPE_SOUTH"), ("CY", "EUROPE_SOUTH"), ("ES", "EUROPE_SOUTH"),
    ("GI", "EUROPE_SOUTH"), ("GR", "EUROPE_SOUTH"), ("HR", "EUROPE_SOUTH"), ("IT", "EUROPE_SOUTH"), ("ME", "EUROPE_SOUTH"),
    ("MK", "EUROPE_SOUTH"), ("MT", "EUROPE_SOUTH"), ("PT", "EUROPE_SOUTH"), ("RS", "EUROPE_SOUTH"), ("SM", "EUROPE_SOUTH"),
    ("VA", "EUROPE_SOUTH"),
    # --- EUROPE_EAST (6)
    ("BG", "EUROPE_EAST"), ("BY", "EUROPE_EAST"), ("MD", "EUROPE_EAST"), ("RO", "EUROPE_EAST"), ("RU", "EUROPE_EAST"),
    ("UA", "EUROPE_EAST"),
    # --- MIDDLE_EAST (15)
    ("AE", "MIDDLE_EAST"), ("BH", "MIDDLE_EAST"), ("IL", "MIDDLE_EAST"), ("IQ", "MIDDLE_EAST"), ("IR", "MIDDLE_EAST"),
    ("JO", "MIDDLE_EAST"), ("KW", "MIDDLE_EAST"), ("LB", "MIDDLE_EAST"), ("OM", "MIDDLE_EAST"), ("PS", "MIDDLE_EAST"),
    ("QA", "MIDDLE_EAST"), ("SA", "MIDDLE_EAST"), ("SY", "MIDDLE_EAST"), ("TR", "MIDDLE_EAST"), ("YE", "MIDDLE_EAST"),
    # --- AFRICA_NORTH (8)
    ("DZ", "AFRICA_NORTH"), ("EG", "AFRICA_NORTH"), ("EH", "AFRICA_NORTH"), ("LY", "AFRICA_NORTH"), ("MA", "AFRICA_NORTH"),
    ("MR", "AFRICA_NORTH"), ("SD", "AFRICA_NORTH"), ("TN", "AFRICA_NORTH"),
    # --- AFRICA_SSA (50)
    ("AO", "AFRICA_SSA"), ("BF", "AFRICA_SSA"), ("BI", "AFRICA_SSA"), ("BJ", "AFRICA_SSA"), ("BW", "AFRICA_SSA"),
    ("CD", "AFRICA_SSA"), ("CF", "AFRICA_SSA"), ("CG", "AFRICA_SSA"), ("CI", "AFRICA_SSA"), ("CM", "AFRICA_SSA"),
    ("CV", "AFRICA_SSA"), ("DJ", "AFRICA_SSA"), ("ER", "AFRICA_SSA"), ("ET", "AFRICA_SSA"), ("GA", "AFRICA_SSA"),
    ("GH", "AFRICA_SSA"), ("GM", "AFRICA_SSA"), ("GN", "AFRICA_SSA"), ("GQ", "AFRICA_SSA"), ("GW", "AFRICA_SSA"),
    ("KE", "AFRICA_SSA"), ("KM", "AFRICA_SSA"), ("LR", "AFRICA_SSA"), ("LS", "AFRICA_SSA"), ("MG", "AFRICA_SSA"),
    ("ML", "AFRICA_SSA"), ("MU", "AFRICA_SSA"), ("MW", "AFRICA_SSA"), ("MZ", "AFRICA_SSA"), ("NA", "AFRICA_SSA"),
    ("NE", "AFRICA_SSA"), ("NG", "AFRICA_SSA"), ("RE", "AFRICA_SSA"), ("RW", "AFRICA_SSA"), ("SC", "AFRICA_SSA"),
    ("SH", "AFRICA_SSA"), ("SL", "AFRICA_SSA"), ("SN", "AFRICA_SSA"), ("SO", "AFRICA_SSA"), ("SS", "AFRICA_SSA"),
    ("ST", "AFRICA_SSA"), ("SZ", "AFRICA_SSA"), ("TD", "AFRICA_SSA"), ("TG", "AFRICA_SSA"), ("TZ", "AFRICA_SSA"),
    ("UG", "AFRICA_SSA"), ("YT", "AFRICA_SSA"), ("ZA", "AFRICA_SSA"), ("ZM", "AFRICA_SSA"), ("ZW", "AFRICA_SSA"),
    # --- AMER (55)
    ("AG", "AMER"), ("AI", "AMER"), ("AR", "AMER"), ("AW", "AMER"), ("BB", "AMER"),
    ("BL", "AMER"), ("BM", "AMER"), ("BO", "AMER"), ("BQ", "AMER"), ("BR", "AMER"),
    ("BS", "AMER"), ("BZ", "AMER"), ("CA", "AMER"), ("CL", "AMER"), ("CO", "AMER"),
    ("CR", "AMER"), ("CU", "AMER"), ("CW", "AMER"), ("DM", "AMER"), ("DO", "AMER"),
    ("EC", "AMER"), ("FK", "AMER"), ("GD", "AMER"), ("GF", "AMER"), ("GL", "AMER"),
    ("GP", "AMER"), ("GT", "AMER"), ("GY", "AMER"), ("HN", "AMER"), ("HT", "AMER"),
    ("JM", "AMER"), ("KN", "AMER"), ("KY", "AMER"), ("LC", "AMER"), ("MF", "AMER"),
    ("MQ", "AMER"), ("MS", "AMER"), ("MX", "AMER"), ("NI", "AMER"), ("PA", "AMER"),
    ("PE", "AMER"), ("PM", "AMER"), ("PR", "AMER"), ("PY", "AMER"), ("SR", "AMER"),
    ("SV", "AMER"), ("SX", "AMER"), ("TC", "AMER"), ("TT", "AMER"), ("US", "AMER"),
    ("UY", "AMER"), ("VC", "AMER"), ("VE", "AMER"), ("VG", "AMER"), ("VI", "AMER"),
    # --- APAC (62)
    ("AF", "APAC"), ("AM", "APAC"), ("AS", "APAC"), ("AU", "APAC"), ("AZ", "APAC"),
    ("BD", "APAC"), ("BN", "APAC"), ("BT", "APAC"), ("CC", "APAC"), ("CK", "APAC"),
    ("CN", "APAC"), ("CX", "APAC"), ("FJ", "APAC"), ("FM", "APAC"), ("GE", "APAC"),
    ("GU", "APAC"), ("HK", "APAC"), ("ID", "APAC"), ("IN", "APAC"), ("JP", "APAC"),
    ("KG", "APAC"), ("KH", "APAC"), ("KI", "APAC"), ("KP", "APAC"), ("KR", "APAC"),
    ("KZ", "APAC"), ("LA", "APAC"), ("LK", "APAC"), ("MH", "APAC"), ("MM", "APAC"),
    ("MN", "APAC"), ("MO", "APAC"), ("MP", "APAC"), ("MV", "APAC"), ("MY", "APAC"),
    ("NC", "APAC"), ("NF", "APAC"), ("NP", "APAC"), ("NR", "APAC"), ("NU", "APAC"),
    ("NZ", "APAC"), ("PF", "APAC"), ("PG", "APAC"), ("PH", "APAC"), ("PK", "APAC"),
    ("PN", "APAC"), ("PW", "APAC"), ("SB", "APAC"), ("SG", "APAC"), ("TH", "APAC"),
    ("TJ", "APAC"), ("TK", "APAC"), ("TL", "APAC"), ("TM", "APAC"), ("TO", "APAC"),
    ("TV", "APAC"), ("TW", "APAC"), ("UZ", "APAC"), ("VN", "APAC"), ("VU", "APAC"),
    ("WF", "APAC"), ("WS", "APAC"),
]


# REGION_PARENT lives in domain/scope.py, which is where region logic
# belongs - the API router needs it and must not import this module,
# because importing the seed builds every rate list as a side effect.
from .domain.scope import REGION_PARENT  # noqa: E402

# The regions a price may be scoped to, taken from COUNTRY_REGION so the two
# cannot drift: a backbone price for a region nobody maps to is unreachable,
# and a region that has no price leaves its core circuits unpriced.
# The regions a BACKBONE price is scoped to: the hub tier, not the bands.
#
# A backbone connects regional hubs to the global core, and an estate has one
# EMEA hub - not one per European band. So this is the parent tier plus the
# regions that are their own parent, and it stayed at three when EMEA split
# into eight.
#
# Deriving it from COUNTRY_REGION made it ten, which asked for a backbone
# price for EUROPE_NORTH - a hub nobody has.
BACKBONE_REGIONS = sorted(
    set(REGION_PARENT.values())
    | {r for _c, r in COUNTRY_REGION if r not in REGION_PARENT})

# Every scope that is a region rather than a country, for labelling a rate row
# `scope_kind="REGION"`. Both tiers: a EUROPE_CENTRAL rate is as much a
# regional price as an EMEA one, and labelling it COUNTRY would put it on the
# wrong rung of the ladder.
REGION_CODES = sorted(
    {r for _c, r in COUNTRY_REGION} | set(REGION_PARENT.values()))

# Applied here, after COUNTRY_REGION exists. A region's rates are derived from
# its member countries, so the map has to be read before they can be.
# Sub-region rates first, from the countries that have a card. Then the parent,
# from the same countries - so EMEA still exists as the rung beneath a
# sub-region that prices nothing, and Ethiopia reaches a rate instead of
# refusing.
PRIORS = PRIORS + _regional_tiers(PRIORS, COUNTRY_REGION)
PRIORS = PRIORS + _regional_tiers(
    PRIORS, [(country, REGION_PARENT[region])
             for country, region in COUNTRY_REGION
             if region in REGION_PARENT])

# Again, after the derivation. A region's 50 Mbps row is the median of its
# members' 50 Mbps rows, which is computed from the rescaled country figures -
# but EUROPE_CENTRAL took its 100 from a workbook cluster and its 50 from the
# median of countries whose own 50 came from elsewhere, so the inversion
# reappeared one level up. The check that caught it is the same one.
PRIORS = _rescale_lowest_tier(PRIORS, _WORKBOOK_KEYS)

# The backbone. ETHERNET at 10 Gbps between a data centre and its regional hub,
# and between a regional hub and the global core - which is the shape and the
# order of magnitude a real enterprise core runs at, and both tiers are dual by
# default because a core with one path is a design nobody ships.
TOPOLOGY_TEMPLATE = [
    ("standard-3-tier", "1.0.0", "ETHERNET", 10000, "ETHERNET", 10000,
     True, True,
     "Access per site from the archetype; data centres clustered into regional "
     "hubs; regional hubs connected to a global core. Head offices are access "
     "tier by design - a large office is a big local connection, not a core "
     "node."),
]

# Bandwidth per site type per industry. (industry, archetype, mbps)
#
# DEFAULT is the fallback for an industry not listed, so an unknown sector is
# priced at the generic tier rather than refused. Every tier here must exist in
# PRIORS for the products the archetype uses, or the circuit is unpriceable -
# the same constraint the archetype defaults are under.
#
# The differences are the point. A retail bank branch runs card, teller and
# video traffic back to a data centre; a parts depot of the same size runs
# scanning and a warehouse session. A distributor's trade counter sits between
# the two. Treating them alike is what one bandwidth per archetype did.
# Generated, for the same reason. A quick-service restaurant and an airport
# terminal are both "a site" and one needs two orders of magnitude more
# circuit - which is the whole point of keeping the industry dimension.
# Bandwidth per (industry, archetype). The workbench's own rows plus one per
# BICS industry for the archetype its benchmark names - so a case on a BICS
# code prices the site type that industry actually has, at the published
# figure, rather than falling back to a seeded guess for BRANCH.
# Same rule: a published figure supersedes a seeded one for the same
# (industry, archetype), and the workbench row survives where BICS is silent -
# a BICS industry still needs a bandwidth for the supporting archetypes its
# estate shape includes and its benchmark does not name.
# Capped at the top tier the rate card quotes. The benchmark runs to 250 Gbps
# for a hyperscale campus and the card stops at 10 Gbps, so 22 of its 44 rows
# would have asked for a tier no prior covers - and an unpriceable site is
# unpriced scope, which defeats the coverage gate rather than informing it.
#
# industries.MAX_PRICEABLE_MBPS already existed for this and the BICS rows
# bypassed it. Capping is not pretending the site is smaller: the benchmark
# figure is kept on industry_benchmark, where a reader can see the site needs
# more than the card can price, and extending the card is the real fix.
_BICS_BW = [(r["industry_code"], r["archetype_code"],
             min(int(r["bandwidth_base_mbps"]), industries.MAX_PRICEABLE_MBPS))
            for r in INDUSTRY_BENCHMARK["rows"]]
_BICS_BW_KEYS = {(i, a) for i, a, _ in _BICS_BW}
# Every archetype a BICS estate shape includes needs a figure, not just the one
# its benchmark names. A supermarket shape has stores, a warehouse, an office
# and a DC; the benchmark says only STORE, and the other three would have been
# in the mix and unpriceable.
#
# The supporting ones take the DEFAULT industry's figure for that archetype:
# this repository's own judgement, which is what it was before BICS existed,
# and it is not pretending the benchmark said anything about them.
_DEFAULT_BW = {a: m for i, a, m in industries.bandwidth_rows()
               if i == "DEFAULT"}
_SURVIVING_BW = {(row[0], row[1]) for row in industries.bandwidth_rows()
                 if (row[0], row[1]) not in _BICS_BW_KEYS}
_SUPPORTING = []
for _industry in {row[0] for row in _BICS_MIX}:
    for _archetype in {row[1] for row in _BICS_MIX if row[0] == _industry}:
        # Not already priced by the benchmark, and not already priced by the
        # workbench rows that survive. RETAIL_BANKING, INSURANCE and LOGISTICS
        # are in both taxonomies, so their supporting archetypes were added a
        # second time - ten duplicate keys, where whichever the query returned
        # last would have won silently.
        if ((_industry, _archetype) not in _BICS_BW_KEYS
                and (_industry, _archetype) not in _SURVIVING_BW
                and _archetype in _DEFAULT_BW):
            _SUPPORTING.append((_industry, _archetype,
                                _DEFAULT_BW[_archetype]))

# Resilience per (industry, archetype), generated the way bandwidth already is.
#
# The industry benchmark's criticality tier, committed share and dual-access
# probability reached almost nothing: they applied only where the benchmark's
# representative archetype appeared in the industry's estate mix, and it does
# not for 43 of 47 industries. Three industries with benchmark rows differing
# by nearly 10x in bandwidth returned byte-identical baselines.
#
# Bandwidth never had this problem because ARCHETYPE_BANDWIDTH is keyed
# (industry, archetype) - the key the estate mix uses - and covers 100% of the
# pairs that occur. This is the same key, built from the same pairs.
#
# Generated rather than typed: 249 rows, each a composition of the site type's
# own need and the industry's posture, and a hand-written table of that size
# would drift from the mixes it is supposed to mirror.
def _archetype_resilience():
    """(industry, archetype, dual, committed, tier) for every estate pair."""
    from .domain import resilience as _resilience

    pairs = {(industry, archetype)
             for industry, archetype, _band, _share in DENSITY_MIX}
    return _resilience.rows_for(
        [(a, d, cf) for a, _u, _bw, d, _pp, _bp, cf in ARCHETYPES],
        industry_benchmark.seeded()["rows"],
        pairs)


ARCHETYPE_BANDWIDTH = (
    [row for row in industries.bandwidth_rows()
     if (row[0], row[1]) not in _BICS_BW_KEYS]
    + _BICS_BW + _SUPPORTING)


# bandwidth_mbps_base is now also the tier a circuit is priced at, so every
# value here must have a matching row in PRIORS or the archetype is unpriceable.
# WAREHOUSE moved from 200 to 100: 200 was a tier no benchmark quotes, and an
# invented tier prices nothing.
# (archetype, users, bandwidth_mbps, dual_access_probability,
#  primary_product, backup_product, committed_fraction)
#
# `committed_fraction` is how much of the installed bearer is actually
# guaranteed - the 30 in "Access/Port = 100/30". It applies only to a committed
# service: an IPVPN or an Ethernet service port. A best-effort circuit has an
# upstream instead, which is a property of the access technology rather than
# the site type (see access.UPSTREAM_SHARE), and a DIA is symmetric.
#
# Set from an analyst's judgement, 4.180.0: a data centre buys a small fraction
# of a very large bearer because its peak is bursty and bearer capacity is
# cheap at that scale; a store or branch needs most of its small pipe
# guaranteed because there is no headroom to burst into.
#
# LARGE_OFFICE is the one to revisit first. It sits between the two patterns -
# a 500 Mbps bearer is large enough for the data-centre logic to start applying
# - and it is set at the small-site value rather than interpolated, because
# inventing a number between two stated ones would look like evidence.
ARCHETYPES = [
    ("BRANCH", 25, 100, "0.55", "DIA", "BROADBAND_PON", "0.50"),
    ("LARGE_OFFICE", 250, 500, "0.90", "ETHERNET", "DIA", "0.50"),
    ("WAREHOUSE", 60, 100, "0.45", "DIA", "BROADBAND_HFC", "0.50"),
    ("DC", 0, 10000, "1.00", "ETHERNET", "ETHERNET", "0.30"),
    ("STORE", 12, 50, "0.35", "BROADBAND_HFC", "MOBILE_5G", "0.50"),
    # A research, engineering or manufacturing campus.
    #
    # Not a big office and not a data centre. A DC has no users and bursts; a
    # campus has thousands of people AND the compute they use, so it carries
    # both a high committed rate and a platform layer a data hall gets none of.
    #
    # Every figure except the user count comes from the benchmark's own campus
    # rows rather than from judgement: R_D_CAMPUS, RESEARCH_CAMPUS and
    # ENGINEERING_CAMPUS all sit at 10.5 Gbps with a committed share of 0.9 to
    # 1.0 and criticality Tier 1, which is a dual-access probability of 1.00.
    # Capped at 10 Gbps because that is the top tier the rate card quotes.
    #
    # 5,000 users is the one invented number, and it is the number a real
    # engagement replaces first: a campus is one footprint row carrying a
    # workforce, so the platform layers scale off it.
    ("CAMPUS", 5000, 10000, "1.00", "ETHERNET", "ETHERNET", "0.95"),
]

# Platform unit costs. These were code constants in an earlier revision, which
# spec 18.1 forbids for any material prior. They are ~40% of modelled TCO.
PLATFORM = [
    ("SDWAN_OVERLAY", "L2", "per site per month", 40, 55, 75),
    ("SSE_LICENCE", "L4", "per user per month", 6, 9, 13),
]

# earliest_supported_stage: the gate at which the evidence supporting the lever
# first becomes admissible under 0.5A. Drives realization confidence.
# (id, family, description, cost_layers, low, base, high,
#  applies_to_products, scenario, earliest_stage)
#
# applies_to_products is the eligibility constraint audit finding C-10 asked
# for. cost_layers alone was the whole test, and L0 is the entire access layer
# - so MPLS substitution applied to broadband and mobile circuits and booked
# savings from replacing MPLS in estates holding none.
#
# None means unconstrained, which is the honest answer for repricing and
# billing cleanup: they act on any circuit regardless of technology, and making
# them enumerate every product would be a list to maintain rather than a
# control.
# (id, family, description, cost_layers, low, base, high,
#  service_classes, access_technologies, platform_products, scenario, stage)
#
# Eligibility on the dimension each lever actually acts on. `applies_to_products`
# held one list for two unrelated things - the L0 levers named MPLS and DIA,
# the L2/L4 levers named SDWAN_OVERLAY and SSE_LICENCE - and was keyed on the
# vocabulary 4.166 replaced. "MPLS" is no longer a service class.
#
# None on a dimension means unconstrained there. A component is eligible when
# it satisfies every constraint that is declared.
LEVERS = [
    ("LEV-REPRICE-001", "Same-service repricing", "Re-rate current products to benchmark",
     ["L0"], "0.06", "0.12", "0.18", None, None, None, "A", "V2"),
    ("LEV-CLEANUP-001", "Billing cleanup", "Cease unused and duplicate services",
     ["L0"], "0.01", "0.03", "0.06", None, None, None, "A", "V2"),
    # Only a committed VPN service can be substituted for internet plus overlay.
    # Was ["MPLS"], which no longer exists.
    ("LEV-MPLS-001", "MPLS substitution", "Substitute IPVPN with DIA plus overlay where eligible",
     ["L0"], "0.15", "0.25", "0.35", ["IPVPN"], None, None, "B", "V3"),
    # Right-sizing needs a committed rate to reduce. Was
    # ["DIA","ETHERNET","MPLS"] - the committed classes listed one by one,
    # which is what "not BEST_EFFORT" says directly: a 100/20 broadband line
    # is not sold at 60/12.
    ("LEV-BANDWIDTH-001", "Right-sizing", "Right-size committed bandwidth against utilisation prior",
     ["L0"], "0.03", "0.07", "0.12", ["DIA", "IPVPN", "ETHERNET"], None, None,
     "B", "V3"),
    # Platform components, not access circuits. These never were service
    # classes and could not be expressed on that dimension at all.
    ("LEV-SASE-001", "Platform consolidation", "Converge SD-WAN, SSE and remote access",
     ["L2", "L4"], "0.12", "0.22", "0.32", None, None,
     ["SDWAN_OVERLAY", "SSE_LICENCE"], "C", "V3"),
    ("LEV-SECRETIRE-001", "Security appliance retirement", "Retire on-site firewall estate",
     ["L4"], "0.05", "0.10", "0.16", None, None, ["SSE_LICENCE"], "C", "V3"),
    ("LEV-NAAS-001", "Supplier consolidation", "Single global prime with managed edge",
     ["L0", "OPS"], "0.08", "0.16", "0.24", None, None, None, "D", "V4"),
    ("LEV-OPS-001", "Operating-model optimisation", "Consolidate NOC and vendor management",
     ["OPS"], "0.10", "0.18", "0.28", None, None, None, "D", "V3"),
]


def _rows():
    """Table -> row builder. Kept together so a new reference table cannot be
    added to the model without also being given seed content."""
    # Imported here, as every other builder in this module does. The fx row
    # builder used a bare `D` that this module does not define - the seed
    # would have raised NameError on the first run, and the unbound-name check
    # caught it before it shipped.
    from decimal import Decimal as _D

    return [
        (threshold, lambda: [
            {"set_name": a, "key": b, "value": c, "version": 1,
             "approved_by": "seed", "note": "MVP default"} for a, b, c in THRESHOLDS]),
        (density_mix, lambda: [
            {"id": f"{i}-{a}-{b}", "industry": i, "archetype": a,
             "density_band": b, "share": share, "approved_by": "seed",
             "note": "seed starting position; retune per engagement"}
            for i, a, b, share in DENSITY_MIX]),
        (serviceability, lambda: [
            {"id": f"{c}-{b}-{t}", "country": c, "density_band": b,
             # Both, so a resolver reading either still works. `product` is
             # None because the row no longer describes one: it describes a
             # bearer, and every product that bearer can carry follows.
             "access_technology": t, "product": None,
             "available": a, "max_bandwidth_mbps": m,
             "approved_by": "seed",
             "note": "seed default; retune per engagement"}
            for c, b, t, a, m in SERVICEABILITY]),
        (industry_benchmark_table, lambda: [
            {"industry_benchmark_id":
                 f"{r['industry_code']}-{r['archetype_code']}",
             "sector": r["sector"], "industry_l3": r["industry_l3"],
             "industry_code": r["industry_code"],
             "site_archetype": r["site_archetype"],
             "archetype_code": r["archetype_code"],
             "location_context": r["location_context"],
             "density_band": r["density_band"],
             "bandwidth_low_mbps": r["bandwidth_low_mbps"],
             "bandwidth_base_mbps": r["bandwidth_base_mbps"],
             "bandwidth_high_mbps": r["bandwidth_high_mbps"],
             "committed_share_low": r["committed_share_low"],
             "committed_share_base": r["committed_share_base"],
             "committed_share_high": r["committed_share_high"],
             "criticality_tier": r["criticality_tier"],
             "dual_access_probability": r["dual_access_probability"],
             "cloud_requirement": r["cloud_requirement"],
             "cloud_direct": r["cloud_direct"],
             "source": "Comprehensive Industry WAN Benchmark, BICS L3"}
            for r in INDUSTRY_BENCHMARK["rows"]]),
        (fx_rate, lambda: [
            {"fx_rate_id": f"{f}-{t}-{a}-{cv}",
             "from_currency": f, "to_currency": t, "rate": _D(r),
             "as_of": _date.fromisoformat(a), "convention": cv,
             "evidence_grade": g, "source": src,
             "approved_by": "seed",
             "note": ("indicative: nobody looked this up, and an estimate "
                      "converted at it should say so"
                      if g == "E" else None)}
            for f, t, r, a, cv, g, src in FX_RATES]),
        (country_region, lambda: [
            {"country": c, "region": r, "note": "seed default"}
            for c, r in COUNTRY_REGION]),
        (topology_template, lambda: [
            {"name": n, "version": v, "dc_to_region_product": dp,
             "dc_to_region_mbps": dm, "region_to_core_product": cp,
             "region_to_core_mbps": cm, "dc_dual": dd, "core_dual": cd,
             "note": note}
            for n, v, dp, dm, cp, cm, dd, cd, note in TOPOLOGY_TEMPLATE]),
        (archetype_resilience, lambda: [
            {"industry": i, "archetype": a,
             "dual_access_probability": _D(d),
             "committed_fraction": _D(cf),
             "criticality_tier": tier,
             "note": ("archetype baseline; the benchmark covers no such "
                      "industry" if tier is None else
                      f"site-type baseline modulated by industry {tier}")}
            for i, a, d, cf, tier in _archetype_resilience()]),
        (archetype_bandwidth, lambda: [
            {"id": f"{ind}-{arch}", "industry": ind, "archetype": arch,
             "bandwidth_mbps": mbps, "approved_by": "seed",
             "note": "seed default; retune per engagement"}
            for ind, arch, mbps in ARCHETYPE_BANDWIDTH]),
        (research_brief, lambda: [
            {"brief_id": f"{no}-{BRIEF_CATALOGUE_VERSION}", "domain_no": no,
             "brief_version": BRIEF_CATALOGUE_VERSION,
             "agent_id": DOMAIN_AGENT_MAP_SEED.get(no),
             "asks": b.get("asks"), "wants": b.get("wants"),
             "search": b.get("search") or [], "sources": b.get("sources") or [],
             "example": b.get("example"), "reject": b.get("reject"),
             "active": True, "approved_by": "seed",
             "note": "catalogue default; retune in place and bump the version"}
            for no, b in sorted(RESEARCH_BRIEFS.items())]),
        (unit_cost_prior, lambda: [
            {"id": f"{c}-{p}-{bw}", "country": c, "product": p, "cost_layer": l,
             # Derived from the region table rather than from the length of the
             # code: a two-letter region would otherwise be stamped COUNTRY,
             # and "infer the kind from the string" is the guess this column
             # was added to remove.
             "scope_kind": "REGION" if c in REGION_CODES else "COUNTRY",
             # Derived, not restated: LEGACY_PRODUCT is the one mapping from
             # the old single field to the two dimensions, and duplicating it
             # here would be a second copy to drift.
             "service_class": access.LEGACY_PRODUCT[p][0],
             "access_technology": access.LEGACY_PRODUCT[p][1],
             "bandwidth_mbps": bw, "low": lo, "base": ba, "high": hi,
             "currency": "USD", "price_year": 2026, "approved": True,
             "price_basis": "SEED",
             # Graded E - expert assumption - not F. F implies a claim to a
             # source that cannot be produced; these claim none. The commercial
             # basis is stated because a rate without it is not comparable to a
             # quote: a 36-month price with equipment included is a different
             # number from a 12-month price without, and an audit cannot
             # normalise what was never declared.
             "evidence_grade": "E",
             "source": "indicative starting position set at seed time; "
                       "no transaction, quote or published benchmark behind it",
             "source_date": "2026-01-01", "sample_size": None,
             "term_months": 36, "sla": "STANDARD_BUSINESS",
             "taxes_included": False, "equipment_included": False,
             "managed_services_included": False,
             "expires": "2026-12-31"}
            for c, p, l, bw, lo, ba, hi in PRIORS]),
        (platform_unit_cost, lambda: [
            {"product": p, "cost_layer": l, "unit": u, "low": lo, "base": ba,
             "high": hi, "currency": "USD", "price_year": 2026,
             "approved": True}
            for p, l, u, lo, ba, hi in PLATFORM]),
        (archetype_prior, lambda: [
            {"archetype": a, "users_base": u, "bandwidth_mbps_base": b,
             "dual_access_probability": d, "primary_product": pp, "backup_product": bp,
             # Derived from the one mapping, not restated.
             "primary_service_class": access.LEGACY_PRODUCT[pp][0],
             "backup_service_class": access.LEGACY_PRODUCT[bp][0],
             "committed_fraction": cf}
            for a, u, b, d, pp, bp, cf in ARCHETYPES]),
        (lever, lambda: [
            {"lever_id": i, "family": f, "description": d, "cost_layers": cl,
             "saving_low": lo, "saving_base": ba, "saving_high": hi,
             "applies_to_service_classes": svc,
             "applies_to_access_technologies": tech,
             "applies_to_platform_products": plat, "scenario": sc,
             "evidence_required": "see reference.savings_lever_rule",
             "earliest_supported_stage": st}
            for i, f, d, cl, lo, ba, hi, svc, tech, plat, sc, st in LEVERS]),
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
