"""Table definitions and session handling.

Tables live in SQLAlchemy metadata rather than in hand-written DDL so there is
exactly one definition of each. The init SQL creates schemas only.
"""
from datetime import datetime, timezone
from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Index,
                        Integer, MetaData, Numeric, String, Table, Text,
                        UniqueConstraint, create_engine, JSON)
from sqlalchemy.orm import sessionmaker
from . import config

SCHEMAS = ("engagement", "outside_in", "market", "reference",
           "benchmark", "analysis", "agent_runtime", "audit")


def make_engine(url: str):
    """SQLite is supported so the control tests can run against a real database
    without a Postgres container. Schemas are attached as in-memory databases."""
    if url.startswith("sqlite"):
        from sqlalchemy import event
        from sqlalchemy.pool import StaticPool
        eng = create_engine(url, future=True, poolclass=StaticPool,
                            connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _attach(dbapi_conn, _record):        # noqa: ANN001
            cur = dbapi_conn.cursor()
            for name in SCHEMAS:
                cur.execute(f"ATTACH DATABASE ':memory:' AS {name}")
            cur.close()
        return eng
    return create_engine(url, pool_pre_ping=True, future=True)


engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
metadata = MetaData()


def _now():
    return datetime.now(timezone.utc)


case = Table(
    "engagement_case", metadata,
    Column("case_id", String(36), primary_key=True),
    Column("created_at", DateTime(timezone=True), default=_now),
    Column("created_by", String(120), nullable=False),
    # 0.1A mandatory intake block
    Column("subject_entity_legal_name", Text), Column("entity_identifier", Text),
    Column("country_of_domicile", String(2)), Column("group_perimeter", String(32)),
    Column("included_entities", JSON), Column("excluded_entities", JSON),
    Column("in_scope_countries", JSON), Column("in_scope_cost_layers", JSON),
    Column("in_scope_service_families", JSON),
    # Descriptor for how in_scope_countries was chosen: null for an explicit
    # list, a region code, or "GLOBAL". Never read for pricing or coverage -
    # in_scope_countries is still the literal list every consumer expects -
    # this exists so the intake page can show and re-edit the analyst's
    # actual selection instead of just the countries it expanded to.
    Column("in_scope_region", String(32)),
    # Trading names, brands and abbreviations the subject is known by.
    # A legal name is often not what sources call the entity: UniCredit's
    # German bank trades as HypoVereinsbank, and a perimeter check comparing
    # tokens against the legal name alone quarantines every good German source
    # as being about a different company. Aliases are also the strongest
    # search terms available - a brand almost always out-searches a registered
    # legal name.
    Column("entity_aliases", JSON),
    Column("base_currency", String(3)), Column("price_year", Integer),
    Column("fx_convention", String(16)),
    Column("analysis_horizon_years", Integer), Column("discount_rate_set_id", String(64)),
    Column("engagement_purpose", String(32)), Column("client_contact_status", String(32)),
    Column("baseline_reference_period", String(32)),
    # resolution state
    Column("resolved_entity_id", String(36)), Column("perimeter_version", Integer, default=0),
    Column("entity_confirmed_by", String(120)),
    Column("entity_confirmed_at", DateTime(timezone=True)),
    # Stage (Tranche 3). V0 until a named person advances it - never inferred
    # from activity, because "a questionnaire exists" is not the same claim as
    # "this engagement is at V1", and only a person can make the second one.
    Column("stage", String(4), default="V0"),
    Column("stage_advanced_by", String(120)),
    Column("stage_advanced_at", DateTime(timezone=True)),
    schema="engagement",
)

# V1 questionnaire (Tranche 3). One row per question per case.
#
# answer_value/answer_text hold what the *client* said, which is not the same
# kind of claim as anything already in this system: known_facts.BASES are all
# analyst-mediated recollections capped at ANALYST_ASSERTED_PRIOR, and
# EVIDENCED_PUBLIC/DERIVED_PUBLIC mean public evidence. A client's direct
# answer about their own estate is neither. This build deliberately does not
# resolve where it sits in the disposition taxonomy - see the README's known
# gaps. Answers are stored and reported; nothing here writes a disposition or
# moves a confidence figure, because doing so would require picking an
# evidence class nobody has approved yet.
questionnaire_item = Table(
    "questionnaire_item", metadata,
    Column("item_id", String(36), primary_key=True),
    Column("case_id", String(36), ForeignKey("engagement.engagement_case.case_id"),
           index=True),
    Column("question_key", String(64)),        # stable identifier, see domain/questionnaire.py
    Column("question_text", Text),
    Column("domain_no", Integer),              # the 0.3A input domain this informs
    # Prefill: what LLM-02 (or the deterministic rule) proposed as a likely
    # answer, and where that proposal came from. Never presented to the client
    # as fact, and never counted as an answer.
    Column("prefill_value", Text), Column("prefill_basis", Text),
    Column("prefill_label", String(24)),       # LLM_PROPOSED | DETERMINISTIC_PROPOSED
    Column("prefill_agent_run_id", String(36)),
    # Answer: what the client actually said. answered_by is a named person at
    # the client, same bar as known_facts.asserted_by.
    Column("answer_value", Text), Column("answered_by", String(120)),
    Column("answered_at", DateTime(timezone=True)),
    # Evidence mapping (Tranche 3 fix). What this answer did - or was refused
    # permission to do - to the 0.3A disposition for its input domain. See
    # domain/questionnaire.py MAPPING_STATES.
    Column("mapping_state", String(32)), Column("mapping_note", Text),
    Column("mapped_at", DateTime(timezone=True)),
    # Set only where an answer met existing independent evidence and a named
    # person adjudicated. Never written by the automatic mapping pass.
    Column("mapping_resolution", String(32)),
    Column("mapping_resolved_by", String(120)),
    Column("mapping_resolved_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), default=_now),
    UniqueConstraint("case_id", "question_key", name="uq_questionnaire_case_question"),
    schema="outside_in",
)

# Stage-readiness report (Tranche 3). Deliberately a separate table from
# preflight_report rather than a reused one: 0.1C answers "may this V0 run
# execute", this answers "is this engagement ready to be called V1". Same
# BLOCK/WARN/PASS shape and the same named-acknowledgement discipline, but
# conflating them would mean acknowledging one silently satisfies the other.
stage_readiness_report = Table(
    "stage_readiness_report", metadata,
    Column("report_id", String(36), primary_key=True),
    Column("case_id", String(36), ForeignKey("engagement.engagement_case.case_id"),
           index=True),
    Column("target_stage", String(4)),
    Column("created_at", DateTime(timezone=True), default=_now),
    Column("conditions", JSON), Column("blocked", Boolean),
    Column("acknowledged_by", String(120)),
    Column("acknowledged_at", DateTime(timezone=True)),
    schema="outside_in",
)

entity_candidate = Table(
    "entity_candidate", metadata,
    Column("candidate_id", String(36), primary_key=True),
    Column("case_id", String(36), ForeignKey("engagement.engagement_case.case_id"), index=True),
    Column("legal_name", Text), Column("identifier", Text), Column("domicile", String(2)),
    Column("industry", Text), Column("revenue", Text), Column("employees", Text),
    Column("group_parent", Text), Column("website", Text),
    Column("match_score", Numeric(4, 3)), Column("sources", JSON),
    Column("agent_run_id", String(36)), Column("created_at", DateTime(timezone=True), default=_now),
    schema="outside_in",
)

known_fact = Table(
    "known_fact", metadata,
    Column("known_fact_id", String(36), primary_key=True),
    Column("case_id", String(36), ForeignKey("engagement.engagement_case.case_id"), index=True),
    Column("fact_class", String(64), nullable=False), Column("subject", Text, nullable=False),
    Column("value_low", Numeric(20, 4)), Column("value_base", Numeric(20, 4)),
    Column("value_high", Numeric(20, 4)),
    Column("unit", String(32)), Column("currency", String(3)),
    Column("asserted_by", String(120), nullable=False),      # 0.1B: never a team or a role
    Column("assertion_date", Date, nullable=False),
    Column("basis", String(32), nullable=False),
    Column("verifiability", String(32), nullable=False),
    Column("self_reported_confidence", Numeric(4, 3)),
    Column("corroboration_state", String(24), default="PENDING"),
    Column("corroboration_note", Text),
    Column("rights_cleared", Boolean, default=False),        # required when basis=PRIOR_ENGAGEMENT
    Column("superseded_by", String(64)),
    Column("created_at", DateTime(timezone=True), default=_now),
    schema="outside_in",
)

known_fact_conflict = Table(
    "known_fact_conflict", metadata,
    Column("conflict_id", String(36), primary_key=True),
    Column("case_id", String(36), index=True),
    Column("known_fact_id", String(36)), Column("driver", String(32)),
    Column("asserted_value", String(64)), Column("value_used_by_run", String(64)),
    Column("asserted_by", String(120)),
    Column("detected_at", DateTime(timezone=True), default=_now),
    Column("resolution", String(32)), Column("reason", Text),
    Column("resolved_by", String(120)),
    Column("resolved_at", DateTime(timezone=True)),
    schema="outside_in",
)

preflight_report = Table(
    "preflight_report", metadata,
    Column("report_id", String(36), primary_key=True),
    Column("case_id", String(36), ForeignKey("engagement.engagement_case.case_id"), index=True),
    Column("created_at", DateTime(timezone=True), default=_now),
    Column("conditions", JSON), Column("blocked", Boolean),
    Column("acknowledged_by", String(120)),
    Column("acknowledged_at", DateTime(timezone=True)),
    schema="outside_in",
)

simulation_run = Table(
    "simulation_run", metadata,
    Column("simulation_run_id", String(36), primary_key=True),
    Column("case_id", String(36), ForeignKey("engagement.engagement_case.case_id"), index=True),
    Column("model_version", String(32), nullable=False),
    Column("seed", Integer, nullable=False), Column("ensemble_size", Integer, nullable=False),
    Column("params", JSON), Column("pinned_priors", JSON),
    Column("output", JSON), Column("output_hash", String(64)),
    Column("created_at", DateTime(timezone=True), default=_now),
    # Job state. `partial` holds per-pass summaries so a cancelled or failed run
    # resumes from where it stopped rather than restarting - and, because every
    # pass is a pure function of seed + index, resuming reproduces the identical
    # result rather than a similar one.
    Column("status", String(16), default="QUEUED"),
    Column("progress_completed", Integer, default=0),
    Column("progress_total", Integer),
    Column("partial", JSON),
    Column("cancel_requested", Boolean, default=False),
    Column("started_at", DateTime(timezone=True)),
    Column("ended_at", DateTime(timezone=True)),
    Column("error", Text),
    schema="outside_in",
)

domain_disposition = Table(
    "domain_disposition", metadata,
    Column("id", String(36), primary_key=True),
    Column("case_id", String(36), index=True), Column("estimate_snapshot_id", String(36)),
    Column("domain_no", Integer), Column("domain_name", Text),
    Column("disposition", String(32)), Column("reason", String(48)),
    # Null for a manually-entered disposition. Set for a research-derived one,
    # pointing at the agent_run that produced it - the link execution-integrity
    # (page 7) needs to show provenance for a disposition rather than just a
    # provider call in isolation.
    Column("agent_run_id", String(36)),
    # {"sources": [{"url", "publisher", "as_of", "fetched", "fragment"}],
    #  "queries_used", "captures_used"} for a research-derived row. Null for a
    # manual one - EVIDENCED_PUBLIC without this is not distinguishable from
    # EVIDENCED_PUBLIC asserted with nothing behind it.
    Column("evidence", JSON),
    schema="outside_in",
)

estimate_snapshot = Table(
    "estimate_snapshot", metadata,
    Column("estimate_snapshot_id", String(36), primary_key=True),
    Column("case_id", String(36), index=True), Column("version_label", String(8)),
    Column("created_at", DateTime(timezone=True), default=_now),
    Column("v0_status", String(16)),                       # COMPLETE | PARTIAL
    Column("current_tco", JSON), Column("target_tco", JSON), Column("scenarios", JSON),
    Column("gross_run_rate_savings", JSON),
    Column("confidence", JSON), Column("coverage", JSON),
    Column("simulated_share", Numeric(4, 3)), Column("asserted_share", Numeric(4, 3)),
    Column("pins", JSON), Column("levers", JSON),
    schema="analysis",
)

recommendation = Table(
    "recommendation", metadata,
    Column("recommendation_id", String(36), primary_key=True),
    Column("estimate_snapshot_id", String(36), index=True),
    Column("case_id", String(36), index=True),
    Column("scenario_code", String(1)), Column("percentile", String(8)),
    Column("basis", Text),
    # LLM_PROPOSED for a LIVE run, DETERMINISTIC_PROPOSED for DETERMINISTIC_ONLY -
    # never the same label, so a rule-based pick is never presented as the
    # model's judgment (spec 7.2C mode honesty, applied to this record too).
    Column("label", String(24)),
    # Looked up from the snapshot's own scenarios JSON after scenario_code and
    # percentile are chosen - never a figure the model (or the rule) stated
    # directly. The model proposes a choice; this is the engine's number for
    # that choice.
    Column("gross_run_rate_savings", JSON),
    Column("material_levers", JSON),          # lever_ids at/above the governed threshold
    Column("approved_by", String(120)),       # named person, never a role or team
    Column("approved_at", DateTime(timezone=True)),
    Column("agent_run_id", String(36)),       # LLM-07's run (LIVE or DETERMINISTIC_ONLY)
    Column("narrative", Text),
    Column("narrative_label", String(24)),
    Column("narrative_agent_run_id", String(36)),   # LLM-06's run
    Column("created_at", DateTime(timezone=True), default=_now),
    schema="analysis",
)

agent_run = Table(
    "agent_run", metadata,
    Column("agent_run_id", String(36), primary_key=True),
    Column("case_id", String(36)), Column("agent_id", String(32), nullable=False),
    Column("graph_version", String(32), nullable=False),
    Column("execution_mode", String(24), nullable=False),
    Column("environment", String(16), nullable=False),      # server-resolved, 7.2C
    Column("status", String(24), nullable=False),
    Column("produced_without_llm", Boolean, default=False),
    Column("idempotency_key", String(120)),
    Column("started_at", DateTime(timezone=True)), Column("ended_at", DateTime(timezone=True)),
    Column("error", Text), Column("result", JSON),
    UniqueConstraint("idempotency_key", name="uq_agent_run_idempotency"),
    schema="agent_runtime",
)

llm_run = Table(
    "llm_run", metadata,
    Column("llm_run_id", String(36), primary_key=True),
    Column("agent_run_id", String(36), ForeignKey("agent_runtime.agent_run.agent_run_id")),
    Column("provider", String(32)), Column("model", String(64)),
    Column("request_hash", String(64)), Column("response_hash", String(64)),
    # Liveness proof (7.2C). Uniqueness is the control that detects a replayed
    # response presented as live; it is a database constraint, not a code check.
    Column("provider_response_id", String(160), nullable=False),
    Column("provider_request_id", String(160)),
    # Provider-issued. Compared against local_request_at; the skew is the proof.
    Column("provider_request_at", DateTime(timezone=True), nullable=False),
    Column("local_request_at", DateTime(timezone=True)),
    Column("clock_skew_seconds", Numeric(12, 3)),
    Column("egress_proxy", String(200)),
    Column("http_status", Integer),
    # Independence layer: the pin of the connection the answer arrived on, and
    # the provenance strength it earned. Recorded even when not enforced, so a
    # run's evidential weight is stored rather than assumed.
    Column("tls_pin", String(96)),
    Column("tls_cert_not_after", DateTime(timezone=True)),
    Column("provenance_strength", String(32)),
    # --- registered-call identity (WP1). Which instructions produced this
    # answer. Without these a stored finding cannot be interpreted against the
    # prompt that produced it, and a prompt change cannot be correlated with a
    # change in what the agents find.
    Column("prompt_id", String(80)), Column("prompt_version", String(24)),
    Column("prompt_hash", String(64)),
    Column("output_schema_version", String(80)),
    Column("tool_policy_version", String(48)),
    Column("parsed_output", JSON),
    Column("supplied_source_ids", JSON),
    Column("reviewer_outcome", String(32)),
    # The quality gate's verdict on this specific call: accepted or rejected,
    # the typed reasons, and which attempt it was. Every attempt is recorded,
    # so a service that passes first time and one that passes on the third are
    # distinguishable - that difference is the earliest signal a prompt has
    # drifted, and an average hides it.
    Column("quality_reasons", JSON),
    # Whether this call carries a provider-issued request identifier, which is
    # the handle the provider's own logs are indexed by. Not a barrier to
    # forgery - anyone controlling the endpoint mints both identifiers - but it
    # is what makes the out-of-band attestation a spot check rather than an
    # aggregate comparison.
    Column("externally_verifiable", Boolean, default=False),
    Column("input_tokens", Integer, nullable=False), Column("output_tokens", Integer, nullable=False),
    Column("latency_ms", Integer), Column("policy_version", String(32)),
    Column("created_at", DateTime(timezone=True), default=_now),
    # Scoped to the provider. A global constraint would treat two providers
    # issuing the same identifier string as a replay, failing a genuine run with
    # a message accusing it of presenting a stored response as a fresh call.
    # Unique *indexes* rather than constraints: nullable, so absent identifiers
    # do not collide, and addable to an existing table on both engines.
    Index("uq_llm_run_provider_response", "provider", "provider_response_id",
          unique=True),
    Index("uq_llm_run_provider_request", "provider", "provider_request_id",
          unique=True),
    schema="audit",
)

rejected_run = Table(
    "rejected_run", metadata,
    Column("id", String(36), primary_key=True),
    Column("created_at", DateTime(timezone=True), default=_now),
    Column("agent_id", String(32)), Column("execution_mode", String(24)),
    Column("environment", String(16)), Column("reason", Text),
    schema="agent_runtime",
)

usage_reconciliation = Table(
    "provider_usage_reconciliation", metadata,
    Column("id", String(36), primary_key=True),
    Column("period_start", DateTime(timezone=True)), Column("period_end", DateTime(timezone=True)),
    Column("provider", String(32)), Column("environment", String(16)),
    Column("tier", String(1)),
    Column("claimed_calls", Integer), Column("claimed_tokens", Integer),
    Column("reported_calls", Integer), Column("reported_tokens", Integer),
    Column("variance_pct", Numeric(8, 4)), Column("tolerance_pct", Numeric(8, 4)),
    Column("status", String(24)),                          # PASS | BREACH | GAP
    # Who reconciled, and through which channel. A manual reading of the
    # provider console is the out-of-band evidence; an API call from this host
    # would be weaker, because a compromised host could fake it.
    Column("source", String(24)), Column("recorded_by", String(120)),
    Column("incident_id", String(36)),
    Column("created_at", DateTime(timezone=True), default=_now),
    schema="audit",
)

# --- integrity findings ----------------------------------------------------
# A duplicate provider identifier discovered during a migration is precisely the
# event the uniqueness constraint exists to catch. Deleting the offending rows
# to let the migration proceed would destroy the evidence of the one thing most
# worth knowing about, so they are preserved here in full and the identifier is
# released on the later copies only.
integrity_incident = Table(
    "integrity_incident", metadata,
    Column("incident_id", String(36), primary_key=True),
    Column("kind", String(64), nullable=False),
    Column("severity", String(4), nullable=False),          # P1 | P2 | P3
    Column("detected_at", DateTime(timezone=True), default=_now),
    Column("detected_by", String(64)),
    Column("summary", Text), Column("detail", JSON),
    Column("resolved_at", DateTime(timezone=True)),
    Column("resolved_by", String(120)), Column("resolution_note", Text),
    schema="audit",
)

quarantined_row = Table(
    "quarantined_row", metadata,
    Column("id", String(36), primary_key=True),
    Column("incident_id", String(36), index=True),
    Column("source_schema", String(32)), Column("source_table", String(64)),
    Column("reason", String(64)),
    Column("original_row", JSON, nullable=False),
    Column("quarantined_at", DateTime(timezone=True), default=_now),
    schema="audit",
)

threshold = Table(
    "threshold", metadata,
    Column("set_name", String(64), primary_key=True), Column("key", String(64), primary_key=True),
    Column("value", Numeric(12, 4), nullable=False), Column("version", Integer, default=1),
    Column("approved_by", String(120)), Column("note", Text),
    schema="reference",
)

# The Proprietary Benchmark Vault (spec 2.2). Declared in SCHEMAS from the
# first build and empty until now: benchmarks existed only as constants in
# seed.py, so there was elaborate governance around *using* a benchmark and no
# way to *get* one.
#
# One row per observed data point, as received. Nothing here is derived and
# nothing here prices anything - reference.unit_cost_prior bands are derived
# FROM these, deterministically and unapproved, so the arithmetic between a
# quote and a governed band is inspectable rather than a model's assertion.
#
# The dimensions exist because real benchmarks carry them and the old target
# schema could not: a $367 DIA quote that fails the latency SLA is not the
# same product as a $477 that meets it, a 12-month price is not a 36-month
# price, and MRC is not one-time cost.
benchmark_observation = Table(
    "benchmark_observation", metadata,
    Column("observation_id", String(36), primary_key=True),
    Column("created_at", DateTime(timezone=True), default=_now),
    # --- where it came from
    Column("source_document", Text), Column("source_locator", String(120)),
    Column("source_org", String(160)), Column("as_of", String(32)),
    Column("raw_text", Text),
    # --- rights. A benchmark taken from prior client work carries another
    # client's commercial position; it cannot contribute to a derived band
    # until a named person clears it (same rule as known_facts, 2.4).
    Column("rights_basis", String(32)),          # PUBLISHED | PRIOR_ENGAGEMENT | VENDOR_SUPPLIED
    Column("rights_cleared", Boolean, default=False),
    Column("rights_cleared_by", String(120)),
    # --- what was observed
    Column("metric", String(48)),                # MRC | NRC | LEAD_TIME_DAYS | ...
    Column("country", String(2)), Column("product", String(48)),
    Column("bandwidth_mbps", Integer),
    Column("vendor", String(120)),
    Column("value", Numeric(16, 4)), Column("unit", String(32)),
    Column("currency", String(3)), Column("price_year", Integer),
    Column("term_months", Integer), Column("tax_basis", String(24)),
    Column("sla_compliant", Boolean),
    # --- how it got here
    Column("agent_run_id", String(36)),
    Column("extraction_confidence", String(16)),
    Column("inferred_fields", JSON),             # what the agent guessed, not read
    Column("note", Text),
    schema="benchmark",
)

# Research briefs as governed reference data, one row per domain per version.
#
# These were a dict in the research module, so retuning the single largest
# lever on whether a domain finds anything required a code change and a
# rebuild. The loop they sit in - read the prompt, run the domain, look at
# what came back, adjust the wording - is one an analyst runs, and it should
# not need an engineer.
#
# Versioned rather than mutable: a finding is only interpretable against the
# brief that produced it, and overwriting a brief in place would silently
# change what a stored disposition means. The active row per domain is the
# one research uses; superseded rows are retained.
research_brief = Table(
    "research_brief", metadata,
    Column("brief_id", String(64), primary_key=True),      # {domain_no}-{version}
    Column("domain_no", Integer, index=True),
    Column("brief_version", String(24)),
    Column("agent_id", String(16)),
    Column("asks", Text), Column("wants", Text),
    Column("search", JSON), Column("sources", JSON),
    Column("example", Text), Column("reject", Text),
    Column("active", Boolean, default=True),
    Column("approved_by", String(120)), Column("note", Text),
    Column("updated_at", DateTime(timezone=True), default=_now),
    schema="reference",
)

unit_cost_prior = Table(
    "unit_cost_prior", metadata,
    Column("id", String(64), primary_key=True),
    Column("country", String(2)), Column("product", String(48)), Column("cost_layer", String(16)),
    # The bandwidth this price is for. A circuit rate without one is not a
    # rate: a 100 Mbps and a 1 Gbps DIA differ by more than most levers here
    # are worth, and a benchmark cannot be loaded without the tier it quotes.
    Column("bandwidth_mbps", Integer),
    Column("low", Numeric(14, 2)), Column("base", Numeric(14, 2)), Column("high", Numeric(14, 2)),
    Column("currency", String(3)), Column("price_year", Integer), Column("approved", Boolean, default=True),
    # Provenance for a researched price. A governed value that appeared from
    # nowhere is worse than no value: these say which agent run produced it
    # and under whose name it was promoted, so a steward approving it can see
    # what they are approving.
    Column("source_agent_run_id", String(36)), Column("source_note", Text),
    schema="reference",
)

# Site counts promoted from research onto a case (Tier 3). Case-scoped rather
# than governed: these describe one client's estate, not a market rate, so
# they do not carry an `approved` flag the way unit_cost_prior does. The
# simulation page reads them as its evidenced starting point.
evidenced_footprint = Table(
    "evidenced_footprint", metadata,
    Column("id", String(36), primary_key=True),
    Column("case_id", String(36), index=True),
    Column("country", String(2)), Column("archetype", String(48)),
    Column("sites", Integer), Column("as_of", String(32)),
    # The observed range behind `sites`, and how many sources produced it. A
    # single number in an estimate hides whether three sources agreed on it or
    # one source stated it, and those carry very different weight.
    Column("band_low", Integer), Column("band_high", Integer),
    Column("source_count", Integer),
    Column("domain_no", Integer), Column("agent_run_id", String(36)),
    Column("source_urls", JSON),
    Column("promoted_by", String(120)),
    Column("promoted_at", DateTime(timezone=True), default=_now),
    schema="outside_in",
)

platform_unit_cost = Table(
    "platform_unit_cost", metadata,
    Column("product", String(48), primary_key=True),
    Column("cost_layer", String(16)), Column("unit", String(24)),
    Column("low", Numeric(14, 2)), Column("base", Numeric(14, 2)),
    Column("high", Numeric(14, 2)),
    Column("currency", String(3)), Column("price_year", Integer),
    Column("approved", Boolean, default=True),
    schema="reference",
)

archetype_prior = Table(
    "archetype_prior", metadata,
    Column("archetype", String(48), primary_key=True),
    Column("users_base", Integer), Column("bandwidth_mbps_base", Integer),
    Column("dual_access_probability", Numeric(4, 3)),
    Column("primary_product", String(48)), Column("backup_product", String(48)),
    schema="reference",
)

lever = Table(
    "lever", metadata,
    Column("lever_id", String(48), primary_key=True), Column("family", String(48)),
    Column("description", Text), Column("cost_layers", JSON),
    Column("saving_low", Numeric(4, 3)), Column("saving_base", Numeric(4, 3)),
    Column("saving_high", Numeric(4, 3)),
    Column("scenario", String(1)), Column("evidence_required", Text),
    # Stage at which the evidence supporting this lever first becomes admissible
    # under the 0.5A gate matrix. Drives realization confidence.
    Column("earliest_supported_stage", String(4)),
    schema="reference",
)


def init_db():
    metadata.create_all(engine)


class DestructiveOperationRefused(RuntimeError):
    """Raised when a schema-destroying call targets a persistent database."""


def assert_disposable(target=None) -> None:
    """Refuse any destructive operation against a non-SQLite engine.

    The guard lives here, on the operation, rather than in the test fixture that
    calls it. A fixture can be rewritten by someone who does not know why the
    check existed; this cannot be bypassed without deleting it deliberately.
    """
    eng = target or engine
    backend = eng.url.get_backend_name()
    if backend != "sqlite":
        raise DestructiveOperationRefused(
            f"refused: engine backend is {backend!r}, not 'sqlite'. "
            f"Schema-destroying operations are permitted only against a disposable "
            f"in-memory database. Set DATABASE_URL=sqlite:// for the test process."
        )


def reset_schema(target=None) -> None:
    """Drop and recreate every table. SQLite only - see assert_disposable."""
    eng = target or engine
    assert_disposable(eng)
    metadata.drop_all(eng)
    metadata.create_all(eng)
