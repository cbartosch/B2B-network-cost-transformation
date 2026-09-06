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
# 1.5.0: a footprint row may name a density band, and what the site type asks
# for is resolved against what can be delivered there. A rural store takes a
# different circuit from an urban one of the same format, so the same seed and
# footprint produce a different hash than 1.4.0 did wherever a band is set.
# 1.6.0: the backup path is serviceability-resolved, and a backup landing on
# the primary's own product is not counted as a second path. dual_sites can
# therefore be lower than the archetype's dual-access draw implies - which is
# the point: it now reflects what can be delivered.
# 1.7.0: the backbone plan becomes priced circuits. topology.plan() produced
# inter-site transport that one_pass accepted and never read, so it was
# modelled, displayed and excluded from every cost. `circuits` now includes it
# and `circuits_backbone` reports it separately.
# 1.8.0: serviceability resolves on the bearer that can carry a service, not
# on whether a carrier sells the product. An IPVPN in a rural town is now
# deliverable if VDSL reaches it - true, and the product-keyed table could not
# say so - while Ethernet transport there is not, because Ethernet transport is
# fibre and no fibre reaches.
# 1.9.0: a site emits the speed pair it actually gets, not one figure. The
# committed fraction of the bearer for a committed service, the technology's
# upstream for a best-effort one, symmetric for a DIA - so an IPVPN on a
# 100 Mbps bearer prices on what it buys rather than on what was installed.
# 1.10.0: carrier diversity is judged on who supplies each path, where the
# case records it. A second product from one carrier is not a second carrier -
# it is the same duct with a different service on it - and the product rule of
# 1.6.0 was a proxy for exactly this. Silent where no provider is recorded: an
# estate is not single-carrier because nobody wrote the carriers down.
# sim-1.11.0: a product row carries the bearer beside the priced rate, so a
# lever that reduces a committed rate can see how much there is to reduce.
SIMULATION_MODEL_VERSION = "sim-1.11.0"
# calc-1.1.0: the saving band is accumulated with matched pairing rather than
# derived as current - target. The target is a function of the current, so
# subtracting the two crossed bounds a second time and produced worlds that
# cannot occur - a 71% overstatement on the optimistic case and a negative
# floor. Stored snapshots stay readable and are not reproducible under this
# version, which is what a calculation version is for.
# calc-1.2.0: right-sizing is capped by the headroom a circuit actually has.
# It applied a flat band whatever the commitment, so a 100/95 branch was
# right-sized as hard as a 100/50 one. Stored snapshots stay readable and do
# not reproduce under this version.
# calc-1.3.0: a benchmark band is derived from observations normalised onto one
# commercial basis. Pooling a 12-month and a 36-month quote made a band's
# spread partly a spread of contract terms rather than of market price.
CALCULATION_VERSION = "calc-1.3.0"
