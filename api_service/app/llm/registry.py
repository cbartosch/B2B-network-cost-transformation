"""Agent registry.

Only modes with a registered executor are advertised. An earlier revision listed
MOCK and REPLAY for every agent while implementing neither, so a MOCK request in
a non-production environment created an agent_run row that could never
transition - an orphan QUEUED run and a false capability claim.
"""

# Modes this build actually implements. Anything else is rejected before a run
# row is created, so no orphan can accumulate.
IMPLEMENTED_MODES = ("LIVE",)

# Declared for schema and policy completeness; not executable in this build.
DECLARED_MODES = ("LIVE", "MOCK", "REPLAY", "DETERMINISTIC_ONLY")
EXECUTION_MODES = DECLARED_MODES

_LIVE_ONLY = {"permitted_execution_modes": ["LIVE"],
              "deterministic_fallback_endpoint": None,
              "graph_version": "v1.0.0"}

AGENTS = {
    "LLM-01": {"name": "public evidence, footprint and current-state proposals", **_LIVE_ONLY},
    "LLM-02": {"name": "questionnaire prefill and evidence mapping", **_LIVE_ONLY},
    "LLM-08": {"name": "source-backed market-data gathering", **_LIVE_ONLY},
    "ENTITY-RESOLVE": {"name": "subject-entity candidate generation (0.1A)", **_LIVE_ONLY},
    "KNOWN-FACT-CORROBORATE": {"name": "known-fact corroboration (0.1B.3)", **_LIVE_ONLY},
}
