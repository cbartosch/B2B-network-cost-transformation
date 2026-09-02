"""Reference-data seed. Spec 18.1: no material threshold, weight or prior may
exist only as a code constant - they live here and are versioned in the database."""
from sqlalchemy import delete, insert, select

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
                 density_mix,
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
    ("research_budget_profile", "max_output_tokens_per_call", "8000"),
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

# How an estate of a given kind typically distributes. Shares of the whole
# estate, so each industry's rows sum to 1.
#
# These are starting positions, not findings. A discount grocer is overwhelm-
# ingly stores with a handful of regional distribution centres; a bank is
# branches with more office weight; a distributor sits between the two with far
# more warehouse. Getting the shape roughly right beats an empty table, and
# getting it exactly right is what the named locations and domain 2 are for.
DENSITY_MIX = [
    # --- retail: many small customer-facing sites, few of anything else
    ("RETAIL", "STORE", "DENSE_URBAN", "0.1000"),
    ("RETAIL", "STORE", "URBAN", "0.4000"),
    ("RETAIL", "STORE", "SUBURBAN", "0.3200"),
    ("RETAIL", "STORE", "RURAL", "0.1400"),
    ("RETAIL", "WAREHOUSE", "SUBURBAN", "0.0250"),
    ("RETAIL", "LARGE_OFFICE", "URBAN", "0.0100"),
    ("RETAIL", "DC", "URBAN", "0.0050"),

    # --- distribution and wholesale: trade counters plus real warehousing
    ("DISTRIBUTION", "STORE", "URBAN", "0.3000"),
    ("DISTRIBUTION", "STORE", "SUBURBAN", "0.3000"),
    ("DISTRIBUTION", "STORE", "RURAL", "0.1200"),
    ("DISTRIBUTION", "WAREHOUSE", "SUBURBAN", "0.1800"),
    ("DISTRIBUTION", "WAREHOUSE", "RURAL", "0.0600"),
    ("DISTRIBUTION", "LARGE_OFFICE", "URBAN", "0.0300"),
    ("DISTRIBUTION", "DC", "URBAN", "0.0100"),

    # --- banking: branches concentrate where people are, with office weight
    ("FINANCIAL_SERVICES", "STORE", "DENSE_URBAN", "0.2000"),
    ("FINANCIAL_SERVICES", "STORE", "URBAN", "0.4500"),
    ("FINANCIAL_SERVICES", "STORE", "SUBURBAN", "0.2300"),
    ("FINANCIAL_SERVICES", "STORE", "RURAL", "0.0500"),
    ("FINANCIAL_SERVICES", "LARGE_OFFICE", "DENSE_URBAN", "0.0400"),
    ("FINANCIAL_SERVICES", "DC", "URBAN", "0.0300"),

    # --- logistics: depots dominate and sit where land is cheap
    ("LOGISTICS", "WAREHOUSE", "SUBURBAN", "0.4500"),
    ("LOGISTICS", "WAREHOUSE", "RURAL", "0.2500"),
    ("LOGISTICS", "STORE", "URBAN", "0.2000"),
    ("LOGISTICS", "LARGE_OFFICE", "URBAN", "0.0700"),
    ("LOGISTICS", "DC", "URBAN", "0.0300"),

    # --- manufacturing: plants, not outlets
    ("MANUFACTURING", "WAREHOUSE", "SUBURBAN", "0.4000"),
    ("MANUFACTURING", "WAREHOUSE", "RURAL", "0.3000"),
    ("MANUFACTURING", "LARGE_OFFICE", "URBAN", "0.2000"),
    ("MANUFACTURING", "STORE", "URBAN", "0.0700"),
    ("MANUFACTURING", "DC", "URBAN", "0.0300"),

    # --- the fallback for a sector with no row of its own. Deliberately
    # office-and-branch shaped rather than retail-shaped: an unknown industry
    # is more likely a general enterprise than a grocer.
    ("DEFAULT", "BRANCH", "URBAN", "0.4000"),
    ("DEFAULT", "BRANCH", "SUBURBAN", "0.2500"),
    ("DEFAULT", "LARGE_OFFICE", "URBAN", "0.1500"),
    ("DEFAULT", "WAREHOUSE", "SUBURBAN", "0.1500"),
    ("DEFAULT", "DC", "URBAN", "0.0500"),
]

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
SERVICEABILITY = [
    (c, band, product, available, mbps)
    for c in ("DE", "GB", "FR", "NL", "US")
    for band, product, available, mbps in (
        ("DENSE_URBAN", "DIA", True, 10000),
        ("DENSE_URBAN", "ETHERNET", True, 10000),
        ("DENSE_URBAN", "BROADBAND_HFC", True, 1000),
        ("DENSE_URBAN", "BROADBAND_PON", True, 1000),
        ("DENSE_URBAN", "MPLS", True, 1000),
        ("DENSE_URBAN", "MOBILE_5G", True, 300),

        ("URBAN", "DIA", True, 1000),
        ("URBAN", "ETHERNET", True, 1000),
        ("URBAN", "BROADBAND_HFC", True, 1000),
        ("URBAN", "BROADBAND_PON", True, 1000),
        ("URBAN", "MPLS", True, 1000),
        ("URBAN", "MOBILE_5G", True, 300),

        # Dedicated access thins out first, and at a lower tier.
        ("SUBURBAN", "DIA", True, 500),
        ("SUBURBAN", "ETHERNET", True, 500),
        ("SUBURBAN", "BROADBAND_HFC", True, 500),
        ("SUBURBAN", "BROADBAND_PON", True, 300),
        ("SUBURBAN", "MPLS", True, 200),
        ("SUBURBAN", "MOBILE_5G", True, 200),

        # Rural is where a retail estate's assumptions break. Dedicated fibre
        # is often a build rather than a service, so it is marked unavailable
        # rather than expensive: an estimate that prices a circuit nobody can
        # deliver is worse than one that reports it cannot be delivered.
        ("RURAL", "DIA", False, None),
        ("RURAL", "ETHERNET", False, None),
        ("RURAL", "BROADBAND_HFC", True, 200),
        ("RURAL", "BROADBAND_PON", True, 100),
        ("RURAL", "MPLS", False, None),
        ("RURAL", "MOBILE_5G", True, 100),
    )
]

# Which region each country clusters into. Only the countries this build seeds
# prices for, plus the ones the illustrative footprint uses - a mapping is
# useless without prices behind the products it implies, and an unmapped
# country is reported rather than guessed.
COUNTRY_REGION = [
    ("GB", "EMEA"), ("DE", "EMEA"), ("FR", "EMEA"), ("NL", "EMEA"),
    ("AE", "EMEA"), ("US", "AMER"), ("BR", "AMER"), ("SG", "APAC"),
    ("IN", "APAC"),
]

# The regions a price may be scoped to, taken from COUNTRY_REGION so the two
# cannot drift: a backbone price for a region nobody maps to is unreachable,
# and a region that has no price leaves its core circuits unpriced.
REGION_CODES = sorted({r for _c, r in COUNTRY_REGION})

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
ARCHETYPE_BANDWIDTH = [
    # --- generic fallback, matching the archetype defaults
    ("DEFAULT", "BRANCH", 100), ("DEFAULT", "STORE", 50),
    ("DEFAULT", "WAREHOUSE", 100), ("DEFAULT", "LARGE_OFFICE", 500),
    ("DEFAULT", "DC", 10000),

    # --- banking and insurance: branches are transaction and video heavy
    ("FINANCIAL_SERVICES", "STORE", 100),
    ("FINANCIAL_SERVICES", "BRANCH", 100),
    ("FINANCIAL_SERVICES", "LARGE_OFFICE", 1000),
    ("FINANCIAL_SERVICES", "WAREHOUSE", 100),
    ("FINANCIAL_SERVICES", "DC", 10000),

    # --- logistics: depots and hubs move scan and telemetry traffic, and the
    # sorting sites are the bandwidth-heavy ones rather than the offices
    ("LOGISTICS", "WAREHOUSE", 500),
    ("LOGISTICS", "STORE", 50),
    ("LOGISTICS", "BRANCH", 100),
    ("LOGISTICS", "LARGE_OFFICE", 500),
    ("LOGISTICS", "DC", 10000),

    # --- distribution and wholesale: a trade counter is a small shop with a
    # stock system behind it
    ("DISTRIBUTION", "STORE", 100),
    ("DISTRIBUTION", "WAREHOUSE", 500),
    ("DISTRIBUTION", "BRANCH", 100),
    ("DISTRIBUTION", "LARGE_OFFICE", 500),
    ("DISTRIBUTION", "DC", 10000),

    # --- retail: many small sites, card and stock traffic
    ("RETAIL", "STORE", 50),
    ("RETAIL", "WAREHOUSE", 500),
    ("RETAIL", "BRANCH", 100),
    ("RETAIL", "LARGE_OFFICE", 500),
    ("RETAIL", "DC", 10000),

    # --- manufacturing: plants carry machine and telemetry traffic
    ("MANUFACTURING", "WAREHOUSE", 500),
    ("MANUFACTURING", "LARGE_OFFICE", 500),
    ("MANUFACTURING", "BRANCH", 100),
    ("MANUFACTURING", "STORE", 50),
    ("MANUFACTURING", "DC", 10000),
]

# bandwidth_mbps_base is now also the tier a circuit is priced at, so every
# value here must have a matching row in PRIORS or the archetype is unpriceable.
# WAREHOUSE moved from 200 to 100: 200 was a tier no benchmark quotes, and an
# invented tier prices nothing.
ARCHETYPES = [
    ("BRANCH", 25, 100, "0.55", "DIA", "BROADBAND_PON"),
    ("LARGE_OFFICE", 250, 500, "0.90", "ETHERNET", "DIA"),
    ("WAREHOUSE", 60, 100, "0.45", "DIA", "BROADBAND_HFC"),
    ("DC", 0, 10000, "1.00", "ETHERNET", "ETHERNET"),
    ("STORE", 12, 50, "0.35", "BROADBAND_HFC", "MOBILE_5G"),
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
        (density_mix, lambda: [
            {"id": f"{i}-{a}-{b}", "industry": i, "archetype": a,
             "density_band": b, "share": share, "approved_by": "seed",
             "note": "seed starting position; retune per engagement"}
            for i, a, b, share in DENSITY_MIX]),
        (serviceability, lambda: [
            {"id": f"{c}-{b}-{p}", "country": c, "density_band": b,
             "product": p, "available": a, "max_bandwidth_mbps": m,
             "approved_by": "seed",
             "note": "seed default; retune per engagement"}
            for c, b, p, a, m in SERVICEABILITY]),
        (country_region, lambda: [
            {"country": c, "region": r, "note": "seed default"}
            for c, r in COUNTRY_REGION]),
        (topology_template, lambda: [
            {"name": n, "version": v, "dc_to_region_product": dp,
             "dc_to_region_mbps": dm, "region_to_core_product": cp,
             "region_to_core_mbps": cm, "dc_dual": dd, "core_dual": cd,
             "note": note}
            for n, v, dp, dm, cp, cm, dd, cd, note in TOPOLOGY_TEMPLATE]),
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
             "bandwidth_mbps": bw, "low": lo, "base": ba, "high": hi,
             "currency": "USD", "price_year": 2026, "approved": True}
            for c, p, l, bw, lo, ba, hi in PRIORS]),
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
