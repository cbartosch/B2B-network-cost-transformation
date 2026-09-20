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
# sim-1.12.0: twenty-eight industry segments, each choosing a site shape that
# decides how a total splits across density bands and what bandwidth each site
# type gets. An estate of airports and an estate of quick-service restaurants
# no longer split or size the same way.
# sim-1.13.0: bandwidth, committed share and dual-access probability come from the
# supplied BICS L3 benchmark where it covers the industry, and from this
# repository's judgement where it does not. A supermarket store at 25-75% and a
# trading floor at 100% were both being modelled at 50%.
# sim-1.14.0: serviceability resolves again. The loader kept keying on `product`
# after the 4.175 re-key while the seed writes it as None, so every key was
# (country, band, None) and every lookup missed - and an empty table reads as
# "nothing known", so every site came back priced with no constraint applied.
# sim-1.15.0: BICS L3 is the industry taxonomy. Two existed and three of
# forty-two codes overlapped, so an analyst picking from the intake list got no
# benchmark row and the published bandwidth, committed share and criticality
# were unreachable for twenty-five of twenty-eight industries.
# sim-1.16.0: five industries the supplied benchmark does not cover. A
# thirty-company run mapped fourteen to a nearest neighbour - a steelmaker to
# forestry and paper among them, which is indefensible however sound the
# estate shape.
# sim-1.17.0: a site count declares what it counts. The case named which countries
# and which cost layers and nothing about what a site is, so a footprint of
# 5,230 was unanswerable - and a published store count could not be reconciled
# against it because nobody had written the rule down.
# sim-1.18.0: a CAMPUS archetype and a campus-centric estate shape. Six BICS codes
# name a campus in their own benchmark row while office-centric put 53% of
# their sites in branches - so AstraZeneca was modelled with a branch network
# it does not have, and the shape contradicted the benchmark beside it.
SIMULATION_MODEL_VERSION = "sim-1.18.0"
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
# calc-1.4.0: where observations differ only by term, the factor between them is
# measured rather than assumed. A pair like that is evidence about the factor,
# and the convention would otherwise trust itself over the two quotes in front
# of it. A measured factor grades C; the convention still caps at E.
# calc-1.5.0: a client's own invoiced rates price their case ahead of the market
# card. All eleven reference tables the estimate read were global, so two
# clients in the same industry and country got the same rate card and only
# their footprints differed - and there was nowhere to put an invoice, which
# is the best evidence this model can have.
# calc-1.6.0: consumer access is priced above 100 Mbps. The BICS benchmark put a
# supermarket store at 275 Mbps and the card stopped at 100, so every store in
# every retail estate was unpriced scope - 2% coverage for a French grocer.
# calc-1.6.1: two site-inclusion rules are compared on breadth of basis AND
# breadth of inclusions. Comparing the basis alone reported a narrower rule as
# wider and flagged a correct pair of counts as impossible - a France-only
# company-operated footprint against a published global store count.
# calc-1.7.0: every country prices the primary circuits its own estates need.
# France and the Netherlands quoted no Ethernet and no DIA above 500 Mbps while
# GB, DE and US quoted both, so a Dutch and French estate covered 67% where the
# same estate in the US covered 100%.
# calc-1.8.0: 70 countries fall back to a regional rate derived from the member
# countries that have a card. The three regions held one backbone row each, so
# a country without its own card fell through to a region that could not price
# a branch - and the map had nine rows, so most countries reached no region.
# calc-1.9.0: every ISO-3166-1 country reaches a region, generated against the
# system's iso-codes list. The map had seventy rows chosen by thinking about
# where clients are - eight African countries out of fifty-four - so Ethiopian
# Airlines came back 37% covered because nobody had listed Ethiopia.
# calc-1.10.0: EMEA split into five European bands, the Middle East, and Africa
# north and south of the Sahara. A country falls to its band, a band with no
# priced member falls to EMEA - so Saudi Arabia takes the Middle East rate of
# 1300 rather than a pan-EMEA 550, a 2.4x correction one region could not make.
# calc-1.11.0: the GB card is sourced to published market ranges at grade C. The
# seeded assumption was overstated 1.3x to 1.9x, and GB is the anchor
# EUROPE_WEST and EMEA derive from - so roughly a third came off every European
# baseline. The band is the published range, not a point with a spread.
# calc-1.12.0: consumer access is priced from the supplied Global Access Pricing
# Workbook - GPON and HFC at four tiers across twenty market clusters, 78
# countries with their own card instead of seven. DIA, Ethernet and MPLS are
# held back until the workbook states whether its 1G figure is a committed rate
# or a port.
# calc-1.13.0: committed access from workbook v2, which separates port speed from
# CIR. DIA at 300/500/1000 Mbps CIR, Ethernet and MPLS, across 78 countries.
# The three extra DIA columns are a fixed ratio of each cluster's own 1G CIR,
# so they are one observation restated and the ratio is governed - a real
# German quote implies nearer 0.69 where the workbook models 0.80.
# calc-1.14.0: a case priced in one currency against a card in another converts,
# at a rate from reference.fx_rate chosen by the case's own fx_convention -
# the field pre-flight has always collected and no calculation ever read. A
# pair with no rate still refuses: parity assumed is invisible in the result.
CALCULATION_VERSION = "calc-1.14.0"
