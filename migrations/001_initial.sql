CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS tenant;
CREATE SCHEMA IF NOT EXISTS engagement;
CREATE SCHEMA IF NOT EXISTS workflow;
CREATE SCHEMA IF NOT EXISTS evidence;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS benchmark;
CREATE SCHEMA IF NOT EXISTS analysis;
CREATE SCHEMA IF NOT EXISTS agent_runtime;

CREATE TABLE tenant.tenant (
    tenant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION tenant.current_tenant_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
$$;

CREATE TABLE engagement.engagement (
    engagement_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant.tenant(tenant_id),
    name text NOT NULL,
    status text NOT NULL DEFAULT 'ACTIVE',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workflow.stage_run (
    stage_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id uuid NOT NULL REFERENCES engagement.engagement(engagement_id),
    tenant_id uuid NOT NULL REFERENCES tenant.tenant(tenant_id),
    stage_version text NOT NULL CHECK (stage_version IN ('V0','V1','V2','V3','V4','V5')),
    stage_status text NOT NULL DEFAULT 'CREATED',
    evidence_cutoff_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence.source_document (
    document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id uuid NOT NULL REFERENCES engagement.engagement(engagement_id),
    tenant_id uuid NOT NULL REFERENCES tenant.tenant(tenant_id),
    object_uri text NOT NULL,
    content_hash text NOT NULL,
    rights_class text NOT NULL DEFAULT 'CLIENT_RESTRICTED',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, content_hash)
);

CREATE TABLE market.public_fact (
    public_fact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_type text NOT NULL,
    subject text NOT NULL,
    value_json jsonb NOT NULL,
    source_url text NOT NULL,
    source_excerpt text NOT NULL,
    published_at timestamptz,
    retrieved_at timestamptz NOT NULL DEFAULT now(),
    review_at timestamptz,
    approval_status text NOT NULL DEFAULT 'PROPOSED'
);

CREATE TABLE benchmark.release (
    benchmark_release_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    version text NOT NULL,
    status text NOT NULL DEFAULT 'DRAFT',
    published_at timestamptz,
    UNIQUE (name, version)
);

CREATE TABLE analysis.estimate_snapshot (
    estimate_snapshot_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id uuid NOT NULL REFERENCES engagement.engagement(engagement_id),
    tenant_id uuid NOT NULL REFERENCES tenant.tenant(tenant_id),
    stage_run_id uuid NOT NULL REFERENCES workflow.stage_run(stage_run_id),
    prior_snapshot_id uuid REFERENCES analysis.estimate_snapshot(estimate_snapshot_id),
    current_tco numeric(20,2) NOT NULL,
    target_tco numeric(20,2) NOT NULL,
    currency char(3) NOT NULL,
    stage_status text NOT NULL CHECK (stage_status IN ('PARTIAL','COMPLETE')),
    covered_spend_percentage numeric(7,4) NOT NULL DEFAULT 100,
    scope_version text NOT NULL,
    fx_rate_set_id text NOT NULL,
    benchmark_release_id uuid REFERENCES benchmark.release(benchmark_release_id),
    calculation_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agent_runtime.agent_run (
    agent_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id uuid REFERENCES engagement.engagement(engagement_id),
    tenant_id uuid REFERENCES tenant.tenant(tenant_id),
    agent_id text NOT NULL,
    execution_mode text NOT NULL CHECK (
        execution_mode IN ('LIVE','MOCK','REPLAY','DETERMINISTIC_ONLY')
    ),
    status text NOT NULL,
    provider text,
    model text,
    provider_response_id text,
    request_hash text,
    prompt_version text,
    output_schema_version text,
    promotable boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

ALTER TABLE engagement.engagement ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow.stage_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence.source_document ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis.estimate_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runtime.agent_run ENABLE ROW LEVEL SECURITY;

CREATE POLICY engagement_tenant_policy ON engagement.engagement
    USING (tenant_id = tenant.current_tenant_id())
    WITH CHECK (tenant_id = tenant.current_tenant_id());
CREATE POLICY stage_run_tenant_policy ON workflow.stage_run
    USING (tenant_id = tenant.current_tenant_id())
    WITH CHECK (tenant_id = tenant.current_tenant_id());
CREATE POLICY source_document_tenant_policy ON evidence.source_document
    USING (tenant_id = tenant.current_tenant_id())
    WITH CHECK (tenant_id = tenant.current_tenant_id());
CREATE POLICY estimate_snapshot_tenant_policy ON analysis.estimate_snapshot
    USING (tenant_id = tenant.current_tenant_id())
    WITH CHECK (tenant_id = tenant.current_tenant_id());
CREATE POLICY agent_run_tenant_policy ON agent_runtime.agent_run
    USING (tenant_id = tenant.current_tenant_id())
    WITH CHECK (tenant_id = tenant.current_tenant_id());
