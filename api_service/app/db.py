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
    Column("base_currency", String(3)), Column("price_year", Integer),
    Column("fx_convention", String(16)),
    Column("analysis_horizon_years", Integer), Column("discount_rate_set_id", String(64)),
    Column("engagement_purpose", String(32)), Column("client_contact_status", String(32)),
    Column("baseline_reference_period", String(32)),
    # resolution state
    Column("resolved_entity_id", String(36)), Column("perimeter_version", Integer, default=0),
    Column("entity_confirmed_by", String(120)),
    Column("entity_confirmed_at", DateTime(timezone=True)),
    schema="engagement",
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

unit_cost_prior = Table(
    "unit_cost_prior", metadata,
    Column("id", String(64), primary_key=True),
    Column("country", String(2)), Column("product", String(48)), Column("cost_layer", String(16)),
    Column("low", Numeric(14, 2)), Column("base", Numeric(14, 2)), Column("high", Numeric(14, 2)),
    Column("currency", String(3)), Column("price_year", Integer), Column("approved", Boolean, default=True),
    schema="reference",
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
