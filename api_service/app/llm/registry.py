"""Agent registry.

Only modes with a registered executor are advertised. An earlier revision listed
MOCK and REPLAY for every agent while implementing neither, so a MOCK request in
a non-production environment created an agent_run row that could never
transition - an orphan QUEUED run and a false capability claim.
"""

# Modes this build actually implements. Anything else is rejected before a run
# row is created, so no orphan can accumulate. DETERMINISTIC_ONLY joins LIVE
# here for Tranche 2 (LLM-06, LLM-07) - safe to add build-wide because
# _assert_mode_permitted also requires the mode in the *agent's own*
# permitted_execution_modes, and only LLM-06/LLM-07 declare it below. The five
# LIVE_ONLY agents are unaffected.
IMPLEMENTED_MODES = ("LIVE", "DETERMINISTIC_ONLY")

# Declared for schema and policy completeness; not executable in this build.
DECLARED_MODES = ("LIVE", "MOCK", "REPLAY", "DETERMINISTIC_ONLY")
EXECUTION_MODES = DECLARED_MODES

_LIVE_ONLY = {"permitted_execution_modes": ["LIVE"],
              "deterministic_fallback_endpoint": None,
              "graph_version": "v1.0.0"}

# deterministic_fallback_endpoint is documentary, not dynamically resolved -
# nothing in gateway.py imports this string. It records which function in
# domain/savings_advisory.py actually is the fallback, for a reader auditing
# the registry against the code. The wiring itself is an ordinary Python
# import in that module.
_ADVISORY_WITH_FALLBACK = {"permitted_execution_modes": ["LIVE", "DETERMINISTIC_ONLY"],
                          "graph_version": "v1.0.0"}

AGENTS = {
    "LLM-01": {"name": "public evidence, footprint and current-state proposals", **_LIVE_ONLY},
    "LLM-02": {"name": "questionnaire prefill and evidence mapping", **_LIVE_ONLY},
    "LLM-08": {"name": "source-backed market-data gathering", **_LIVE_ONLY},
    "LLM-09": {"name": "benchmark extraction - structuring a heterogeneous "
                       "source into observations; interpretation only, no "
                       "arithmetic", **_LIVE_ONLY},
    "ENTITY-RESOLVE": {"name": "subject-entity candidate generation (0.1A)", **_LIVE_ONLY},
    "KNOWN-FACT-CORROBORATE": {"name": "known-fact corroboration (0.1B.3)", **_LIVE_ONLY},
    "LLM-07": {"name": "savings advisory - scenario, percentile and basis recommendation",
               **_ADVISORY_WITH_FALLBACK,
               "deterministic_fallback_endpoint":
                   "app.domain.savings_advisory:deterministic_recommend"},
    "LLM-06": {"name": "recommendation narrative",
               **_ADVISORY_WITH_FALLBACK,
               "deterministic_fallback_endpoint":
                   "app.domain.savings_advisory:deterministic_narrate"},
}
