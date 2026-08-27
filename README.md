# Enterprise Network Cost Transformation Workbench

A Stage 0 **outside-in estimator** for enterprise network cost. Given a client's name and a
footprint, it produces a defensible current-state TCO and a savings range — and refuses to
produce one when it cannot support the number.

That refusal is the design, not a limitation. Most of what follows exists to make it work.

---

## What this is, and what it isn't

**Is:** the Stage 0 spine. Entity resolution, attributed known facts, a pre-flight gate, a
seeded topology simulation, a 24-domain evidence contract, a Decimal cost engine, a coverage
gate, a savings advisory, and a V1 client questionnaire. Seven LLM agents behind a gateway
that records provider-issued proof for every call.

**Isn't:** the full specification. That is a 26–35 week build for 7–9 FTEs. V2 onward —
contract and invoice ingestion, object storage, benchmark promotion — does not exist.

**The numbers are not yet real.** `seed.py` ships *indicative* reference priors, not sourced
ones. The arithmetic, the gates and the provenance are real; the unit costs are
placeholders. Replace them before any figure leaves the building.

---

## Quick start

**Windows** — `make` is not available, so `make.ps1` mirrors every target:

```powershell
.\make.ps1 check          # validate build config - no Docker needed
.\make.ps1 up             # build and start
.\make.ps1 test           # run the suite in the container
```

**Linux / macOS:** `make check`, `make up`, `make test`.

Then open **http://localhost:8501** for the interface, **http://localhost:8000/docs** for
the API.

### On a managed corporate network

If the build stops at `verify_tls_before_build.py`, that check is **working** — it detected
that your network re-signs HTTPS and stopped before pip failed with an opaque
`CERTIFICATE_VERIFY_FAILED`.

```powershell
.\make.ps1 bootstrap-ca   # acquire the inspection CA, verify it, rebuild --no-cache
.\make.ps1 up
```

`bootstrap-ca` reads the Windows machine store first, which needs no network at all: on a
managed laptop the CA is already installed there, which is precisely why your browser works
and the container does not. `--no-cache` is not optional — the `COPY certs/` layer caches on
directory contents, so a plain rebuild after adding a certificate reuses the
pre-certificate layer and fails identically.

`.\make.ps1 tls-doctor` diagnoses per endpoint and needs no Docker.

### Without a provider API key

Everything except LIVE agent calls works. Choose **`DETERMINISTIC_ONLY`** as the intended
mode on the pre-flight page — `LIVE` will correctly BLOCK on provider availability and
refuse to unlock the simulation. Entity resolution returns 503 and you confirm the entity by
hand; the rest of the V0 path runs end to end.

---

## The workflow is a chain of gates

Not a menu. Each step refuses until the one before it is satisfied, and each refusal names
the condition that is open rather than failing generically.

| # | Page | Gate |
|---|---|---|
| 1 | Intake and entity resolution | Subject entity confirmed by a **named** person (0.1A) |
| 2 | Known facts | Attributed, rights-checked, corroborated where verifiable (0.1B) |
| 3 | Pre-flight | Every BLOCK condition cleared and acknowledged (0.1C) |
| 4 | Simulation | Seeded topology, reproducible from one pinned integer (0.3B) |
| 5 | Domain dispositions | All 24 input domains disposed (0.3A) |
| 6 | Run V0 | Coverage gate: COMPLETE, PARTIAL, or refused (0.3C) |
| 8 | Savings recommendation | The model proposes; the Decimal engine decides |
| 9 | V1 questionnaire and stage | Client answers mapped, then advance to V1 |
| 7 | Execution integrity | Provider provenance for every agent run (7.2C) |

The home page shows where a case actually stands, read live from the API rather than from
what the interface last remembered.

**Why this order.** Researching an entity you have not resolved produces confident findings
about the wrong company. A blocked pre-flight stops a simulation, with no "run anyway". An
unstated input domain blocks publication rather than silently defaulting to a benchmark. V0
publishes COMPLETE, PARTIAL, or nothing.

---

## What the estimate is actually driven by

**Topology and geography.** `footprint [{country, archetype, sites}]` → each site takes its
archetype's product and draws a backup circuit against `dual_access_probability` → product
counts per (country, product, role) → priced from `reference.unit_cost_prior` → × 12 months,
plus platform per user and ops per site. Site counts, archetype mix, product mix,
dual-homing rate and country all move the number. The low/base/high spread comes from the
Monte Carlo draw over dual access — that draw is the one thing the simulation decides, which
is why only the backup layer is attributed `SIMULATED`.

**Headcount is derived from the footprint** (`Σ sites × users_base`) unless you supply one.
The response reports which, because a derived figure and a typed one are different claims.
Where neither is available it refuses rather than defaulting to a constant.

**Not industry.** It is captured and stored, and read by nothing in the cost engine. See
*Open decisions*.

**Not bandwidth.** The profile is reported, but `unit_cost_prior` has no speed dimension, so
a 100 Mbps branch and a 10 Gbps data centre on the same product price identically. The
response carries `bandwidth_is_priced: false` rather than letting a reader assume otherwise.

---

## The controls are the point

Everything here exists to stop a plausible number appearing without support.

- **Fail closed, never downgrade.** No provider configured means a LIVE run FAILS. It does
  not quietly return canned output. A deterministic result is a *separate, explicitly
  requested* run — never an automatic fallback from a failed one.
- **Provider-issued proof.** Every LIVE call records the provider's own response ID, request
  timestamp and token counts. Uniqueness is enforced by the database, not by application
  code.
- **Named attribution, never a role.** Entity confirmation, known facts, pre-flight
  acknowledgement, material-assumption approval, stage advancement, client answers. A
  person, reproduced beside the figure.
- **Governed reference data, no code constants.** Confidence weights, coverage thresholds,
  reconciliation tolerances and research budgets live in `reference.threshold` with an
  approver. A policy constant in Python is a decision nobody can change or audit.
- **Evidence classes that mean different things.** `EVIDENCED_PUBLIC` (independently
  checkable), `DERIVED_PUBLIC`, `CLIENT_CONFIRMED` (first-party, discounted through a
  governed weight), `BENCHMARK_PRIOR`, `SIMULATED`, `ANALYST_ASSERTED_PRIOR`,
  `DECLARED_UNKNOWN`. A client answer never silently overwrites public evidence — two
  independent sources disagreeing is information, and it is routed to a named adjudicator.
- **Decimal throughout.** No float appears in any monetary path.

---

## Verification

```
python tools/verify_shim.py       # 35 checks - the offline harness verifies ITSELF first
python tools/run_pure_tests.py    # 407 tests, no dependencies required
.\make.ps1 test                   # the real thing: Postgres, FastAPI, in Docker
.\make.ps1 test-all               # plus the build-config tests, repo mounted
```

**407 offline tests pass.** They run against a SQLAlchemy subset backed by real `sqlite3`, so
constraints, types and NULL handling are enforced by an actual database rather than by a
stub. The harness verifies itself before anything is read from it — and caught five defects
in its own shim before any could be misread as an application failure.

**`make test` has run in a real container: 376 passed, 5 failed.** All five are fixed, but
**that fix has not been re-run.** Doing so is the single most valuable thing a new reader can
do, and it is why `test` and `test-all` are both listed above: `test` proves the image can
test itself, `test-all` proves the build configuration is correct, and neither substitutes
for the other.

**Twenty-three defects were found across six audit passes and two execution passes.** Six
were real application bugs that repeated code review had missed and only execution
surfaced — including a migration that emitted SQL SQLite rejects, so it could never complete
under `make test` while working fine on Postgres.

---

## Open decisions — yours, not mine

Deliberately unresolved. Each needs a judgement that should not be made by inference.

1. **The TLS pin override has two names.** ENFORCE without `cryptography` is refused in two
   places, one naming `TLS_ALLOW_CERT_ONLY_PINNING` and the other `TLS_PIN_ALLOW_CERT_ONLY`.
   Both fail closed, so there is no security hole — the trap is operational: setting the
   name one message gives leaves you refused by the other, whose message never mentions it.
2. **Duplicate `provider_response_id` refuses startup.** A legacy database holding
   duplicates will not start until someone resolves them by hand, because a duplicate
   provider identifier may be the trace of a replayed response — the exact thing this system
   exists to detect. Should it self-heal instead?
3. **Industry does not affect cost.** Wiring it means inventing multipliers. Either seed
   approved industry factors, or rename input domain 1 to what it actually informs — entity
   resolution, not the arithmetic.
4. **`client_confirmed_evidence_weight` is 0.70**, a placeholder. Where a client
   self-report sits between an analyst assertion and an independently-checkable public
   source is a stewardship judgement.
5. **`DOMAIN_AGENT_MAP` is inferred**, not sourced. No spec table assigning the 24 input
   domains to research agents was available; ten route to LLM-01 and seven to LLM-08, based
   on the domain catalogue and the agents' own descriptions.

---

## Known limitations

- **Reference priors are indicative.** Replace `seed.py` before any real use.
- **`MOCK` and `REPLAY` are declared and not implemented.** The registry advertises `LIVE`
  and `DETERMINISTIC_ONLY`; the specification requires four. An unimplemented mode is
  rejected before a run row exists, rather than silently substituted.
- **A client answer cannot bind to a cost quantity.** `CLIENT_CONFIRMED` exists as a
  quantity origin, but only `known_facts` can bind a driver. Client data reaches confidence
  through domain completeness, not the value-weighted origin breakdown.
- **Reconciliation is one-sided.** Claimed usage is aggregated from `audit.llm_run`; the
  provider-side figure needs a scheduled job per adapter.
- **Simulation calibration is not implemented.** 7.2D needs realised engagement outcomes to
  compute an MdAPE against, and a Stage 0 build has none. Its thresholds are seeded anyway
  so they are governed from the start rather than invented later.
- **Auth is a single shared token, opt-in.** No per-user identity, no authorisation on
  `case_id`, no audit of who acted. It ships open by default, and `created_by` is typed
  rather than authenticated — wire OIDC before named attribution means anything.
- **TLS pinning under interception pins the inspector**, not the provider. A corporate proxy
  is a man-in-the-middle by policy. ENFORCE still detects the inspector's certificate
  changing, which is worth having, but it cannot attest that Anthropic or OpenAI was
  reached.
- **Seven offline tests do not run:** three need a real engine, four need real `httpx`
  against a local server. All seven work under `make test`.

---

## Layout

```
api_service/app/
  domain/          the model: estimate, simulation, confidence, coverage,
                   dispositions, research, savings_advisory, stage,
                   questionnaire, known_facts, entity_resolution, preflight,
                   reconciliation, policy
  llm/             gateway (execution discipline), registry, provider adapters
  routers/api.py   every endpoint
  db.py            one definition of each table
  migrations.py    forward-only, stamped, refuses a half-applied state
  seed.py          governed reference data
analyst_ui/        Streamlit, nine pages
tests/             407 tests
tools/             tls_doctor, CA export, offline test harness
docs/              build-history.md, audit-1..5.md
contract/          the one definition shared by both images
```

## Exchanging work

`make.ps1 bundle-out` produces a git bundle carrying history, so a change can come back as a
commit whose parent is genuinely yours and fast-forwards. `bundle-in <path>` fetches one for
review before merging. A bundle is an ordinary file containing your history — if that
history holds anything sensitive, it travels with it.

---

**`docs/build-history.md` records why any of this is the way it is** — 56 build entries,
each with the reasoning, including the several where an earlier claim turned out to be
wrong. It is long, and it is the honest version.
