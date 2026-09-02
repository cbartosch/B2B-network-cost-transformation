"""Server-side configuration. Nothing here is ever taken from a request body."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://workbench:workbench_dev_only@db:5432/workbench")

VALID_ENVIRONMENTS = ("DEV", "TEST", "STAGING", "PRODUCTION")

def environment() -> str:
    """Spec 7.2C: environment is resolved server-side from deployment configuration.
    It is never accepted from the caller and never inferred from a header or token claim."""
    env = os.getenv("WORKBENCH_ENVIRONMENT", "DEV").upper()
    if env not in VALID_ENVIRONMENTS:
        raise RuntimeError(f"WORKBENCH_ENVIRONMENT={env!r} is not one of {VALID_ENVIRONMENTS}")
    return env

def is_production() -> bool:
    return environment() == "PRODUCTION"

PROVIDERS = {
    "anthropic": {"api_key": os.getenv("ANTHROPIC_API_KEY", ""),
                  "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")},
    "openai":    {"api_key": os.getenv("OPENAI_API_KEY", ""),
                  "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini")},
}

PREFLIGHT_PROBE_LIVE = os.getenv("PREFLIGHT_PROBE_LIVE", "false").lower() == "true"

# Maximum tolerated difference between the provider's reported clock and ours.
MAX_CLOCK_SKEW_SECONDS = int(os.getenv("MAX_CLOCK_SKEW_SECONDS", "300"))

# The provider's transport-issued request identifier (Anthropic `request-id`,
# OpenAI `x-request-id`). Off by default because a provider or an intermediary
# can legitimately omit the header, and a hard requirement would fail genuine
# calls. Absence is always recorded and downgrades the run's verifiability.
REQUIRE_PROVIDER_REQUEST_ID = (
    os.getenv("REQUIRE_PROVIDER_REQUEST_ID", "false").lower() == "true")

# Optional shared secret. When set, every request must carry AUTH_HEADER.
API_TOKEN = os.getenv("API_TOKEN", "")

# Single definition, copied into both images. See contract/auth.py.
from contract.auth import AUTH_EXEMPT_PATHS, AUTH_HEADER  # noqa: E402,F401

# Simulation bounds (DoS guard).
MAX_ENSEMBLE_SIZE = int(os.getenv("MAX_ENSEMBLE_SIZE", "100"))
MAX_SIM_SITES = int(os.getenv("MAX_SIM_SITES", "50000"))
SAMPLE_NODES, SAMPLE_EDGES = 200, 400

# Simulation job runner. Bounded so a burst cannot exhaust the pool, and
# checkpointed often enough that a cancellation loses little work.
SIM_WORKERS = int(os.getenv("SIM_WORKERS", "2"))
SIM_QUEUE_MAX = int(os.getenv("SIM_QUEUE_MAX", "32"))
SIM_CHECKPOINT_EVERY = max(1, int(os.getenv("SIM_CHECKPOINT_EVERY", "5")))

# How long the deep half of /v1/health is cached. The container healthcheck
# polls the shallow half, which touches no database.
HEALTH_DEEP_TTL_SECONDS = int(os.getenv("HEALTH_DEEP_TTL_SECONDS", "30"))
# 1.1.0: product rows carry bandwidth_mbps (4.53.0). A version that does not
# move when the output shape changes is a version that means nothing - and a
# stored 1.0.0 output run through the 1.1.0 pricing lookup prices zero
# circuits, which reads as a badly evidenced estimate rather than a stale run.
# Provider read timeouts. Two values because they bound two different things.
#
# A plain completion answers in seconds. A call carrying the hosted web-search
# tool runs the searches server-side before the model replies, so the whole
# sweep sits inside one HTTP response - eight searches across six fact classes
# is minutes, not seconds. One 60-second timeout for both meant every
# search-using service timed out before it could return anything, three times
# over, and reported it as a transport error.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_SEARCH_TIMEOUT_SECONDS = float(
    os.getenv("LLM_SEARCH_TIMEOUT_SECONDS", "480"))

# 1.2.0: sample edges carry bandwidth_mbps (4.100.0), and the tier itself now
# comes from reference.archetype_bandwidth rather than archetype_prior - so the
# same seed and footprint produce a different output_hash than 1.1.0 did. The
# page states that a re-run reproduces the hash exactly; leaving the version at
# 1.1.0 made that claim false across builds, which is the defect the bump to
# 1.1.0 was itself introduced to fix.
# 1.3.0: three-tier topology. Every site used to get an access circuit and
# nothing else, which is a set of unconnected local loops rather than a WAN -
# so the baseline understated itself and no backbone lever had anything to act
# on. Data centres now cluster into regional hubs and hubs into a global core,
# which adds circuits and changes the output hash for the same seed and
# footprint.
# 1.4.0: the estate is materialised site by site and returned. Every circuit
# now belongs to a row that says whether the site is one somebody named or one
# the pass generated to make the count up - so the output carries an estate,
# and the same seed and footprint produce a different hash than 1.3.0 did.
SIMULATION_MODEL_VERSION = "sim-1.4.0"
CALCULATION_VERSION = "calc-1.0.0"
