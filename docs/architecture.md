# Initial architecture decisions

## Orchestration split

- **Prefect** controls the outer V0-V5 workflow, schedules, retries, batch execution, and approval waits.
- **LangGraph** controls bounded stateful agent sub-workflows. The implementation adapter is intentionally deferred until a real provider adapter is configured.
- **LangChain** provides model, tool, retriever, and structured-output integrations inside LangGraph.
- **FastAPI** is the only control-plane interface used by Streamlit or external clients.
- **Streamlit** is a thin HTTP client and receives no PostgreSQL, Internet-research, or LLM-provider credentials.

## Data zones

1. **Client evidence vault** — tenant-scoped structured metadata in PostgreSQL; original documents in object storage.
2. **Public market intelligence** — approved source-backed facts and immutable source metadata.
3. **Proprietary benchmark vault** — normalized, anonymized, rights-cleared observations and released cohorts.

Only released benchmark cohorts are accessible to general analytical services. Raw cross-client observations are never included in agent context.

## Execution integrity

Agent execution modes are explicit:

- `LIVE`: real approved provider invocation; provider response ID mandatory.
- `MOCK`: test-only and blocked in production.
- `REPLAY`: reuses a captured provider response and retains its lineage.
- `DETERMINISTIC_ONLY`: no LLM call.

Provider failure is surfaced as a failure. No plausible hard-coded fallback may be returned for a `LIVE` run.

## Initial repository boundaries

This first commit implements the contracts and deterministic core. It does not yet implement:

- model-provider adapters;
- LangGraph graphs;
- object-storage adapters;
- authentication and authorization;
- benchmark promotion workflows;
- contract or invoice parsers;
- topology graph ingestion.

Those are deliberate follow-on increments, not hidden stubs that pretend to execute agents.
