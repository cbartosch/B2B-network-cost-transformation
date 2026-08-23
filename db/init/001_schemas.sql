-- Knowledge zones as separate schemas (spec 2.2). In production these are
-- separate databases and cloud accounts; the access and promotion boundaries
-- are what matter and they are enforced in the domain layer.
CREATE SCHEMA IF NOT EXISTS engagement;   -- Client Evidence Vault
CREATE SCHEMA IF NOT EXISTS outside_in;   -- Stage 0 working set
CREATE SCHEMA IF NOT EXISTS market;       -- Public Market Intelligence
CREATE SCHEMA IF NOT EXISTS reference;    -- Reference Knowledge
CREATE SCHEMA IF NOT EXISTS benchmark;    -- Proprietary Benchmark Vault
CREATE SCHEMA IF NOT EXISTS analysis;     -- Analysis and Version Ledger
CREATE SCHEMA IF NOT EXISTS agent_runtime;
CREATE SCHEMA IF NOT EXISTS audit;
