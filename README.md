# Enterprise Network Cost Transformation Workbench — Docker Desktop bundle

A runnable Stage 0 vertical slice of specification v4.7. Postgres + FastAPI + Streamlit,
three containers, one `docker compose up`.

```bash
cp .env.example .env      # add at least one provider key
make check                # validates build config; no Docker needed
make up                   # UI  http://localhost:8501
                          # API http://localhost:8000/docs
make test                 # the full suite, inside the api container
```

### Running on a corporate network

Managed laptops usually inspect TLS: a proxy terminates HTTPS and re-signs it
with a corporate CA. Nothing in the container will verify against that until the
CA is supplied, so the symptom is an SSL error during `pip install` at build
time and on every provider call afterwards.

**This is not a bug to work around.** The transport sets `trust_env=False`, so
`SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` are ignored on purpose — an ambient
variable that silently changes who is trusted is the defect that made provider
calls redirectable in the first place. The anchor is supplied as a build input
instead.

```powershell
# 1. Export the inspection CA (see certs/README.md for the one-liner)
#    and save it as certs\corporate-root.crt

# 2. Diagnose before building - says which step is failing
python tools	ls_doctor.py

# 3. Build. The CA is installed before pip runs, which is the order that matters
docker compose up -d --build
```

`make tls-doctor` distinguishes the three cases that need different fixes:

| Symptom | Meaning | Fix |
|---|---|---|
| `certificate not trusted` | The inspection CA is missing from the image | `.crt` into `certs/`, rebuild |
| `timed out` | Blocked by policy, or a proxy is mandatory | `LLM_EGRESS_PROXY=http://host:port` |
| Issuer is not a public CA | TLS is being inspected — expected, not a fault | Supply the anchor |

**If Anthropic and OpenAI are blocked but PyPI is not**, the bundle still builds
and runs. LIVE agent runs fail closed by design, and every deterministic part of
Stage 0 — simulation, coverage, confidence, the savings engine — works without a
provider.

**Two honest limitations.** `LLM_INSECURE_SKIP_TLS_VERIFY=true` exists as a last
resort and turns verification off for every provider call; it is refused in
combination with `TLS_PIN_MODE=ENFORCE`, because pinning an unverified
connection is theatre. And behind an inspecting proxy a pinned connection pins
**the inspector**, not the provider — `ENFORCE` still detects the inspector's
certificate changing, but it cannot attest that Anthropic or OpenAI was reached.
`/v1/health` reports this rather than presenting a pinned connection as
end-to-end.

### Re-extracting

`Expand-Archive` **will not overwrite existing files** and does not say so clearly, so
extracting a new bundle over an old folder can silently leave the old files in place. Two
reported launch failures were this, not the bundle.

Extract to a **new** folder, or force the overwrite:

```powershell
Expand-Archive -Path network-workbench-docker-bundle.zip -DestinationPath . -Force
# or, unambiguously:
Expand-Archive -Path network-workbench-docker-bundle.zip -DestinationPath .\wb-new
cd .\wb-new\network-workbench
```

Check which build you have before anything else — it prints the number:

```powershell
python tests\check_build_config.py
```

Also check the download itself: repeated downloads become
`network-workbench-docker-bundle (1).zip`, `(2)`, and so on. Extract the newest.

**Windows / no `make`:**

```powershell
python tests\check_build_config.py
docker compose up -d --build
docker compose exec -e DATABASE_URL=sqlite:// -e WORKBENCH_ENVIRONMENT=TEST `
  api python -m pytest /app/tests -v
```

Keep the two `-e` flags on the test command: they are what keeps the suite off your
Postgres data.

## What this is, and what it isn't

The full specification is a 26–35 week build for 7–9 FTEs. This bundle is **not** that.
It is the Stage 0 spine — the parts your last four requests were about — built properly
rather than the whole system built shallowly.

**Implemented and enforced:**

| Spec | Capability |
|---|---|
| 0.1A | Mandatory intake block; entity candidate generation; named confirmation; versioned perimeter |
| 0.1B | Known-facts register with `ANALYST_ASSERTED_PRIOR`; rights gate; corroboration workflow |
| 0.1C | Pre-flight readiness check that actually blocks execution |
| 0.3A | 24-domain disposition contract; `BUDGET_EXHAUSTED` recorded distinctly |
| 0.3B | Seeded topology simulation; reproducible from one integer; `SIMULATED` diversity only |
| 0.3C | Prior-coverage gate; COMPLETE / PARTIAL / refused; material-country floor |
| 0.6A | Banded confidence ceilings, composing downward only |
| 7.2C | Environment binding, liveness proof, no automatic downgrade |
| 12.1 | Deterministic Decimal savings engine, scenarios A–D, per-layer lever application |
| 0.6A | **Derived** simulated share with component-level quantity provenance |

**Stubbed or absent:** Prefect, LangGraph, pgvector retrieval, contract/invoice
intelligence, benchmark promotion pipeline, V1–V5 stages, object storage, RLS,
OIDC. The `market`, `benchmark` and `engagement` schemas are created but only
lightly used.

## The anti-fake controls are the point

You asked to be sure the LLM calls are real. The design answer is that faking them
has to be *structurally impossible*, not merely discouraged.

1. **No stub path exists.** `app/llm/providers/*.py` contain one code path each and it
   is an HTTPS call. There is no fixture, no `if not api_key: return sample`.
2. **Fail closed.** With no key configured, a LIVE run **fails**. The UI shows the
   failure. It never produces plausible output instead. Try it: start without a key and
   click *Generate candidates*.
3. **Liveness proof.** A LIVE run reaches `SUCCEEDED` only with an unrepeated
   `provider_response_id`, a `provider_request_at` inside the run's own window, and
   non-zero input **and** output tokens.
4. **Uniqueness is a database constraint,** not a code check — replaying a stored
   response as a fresh call fails at the storage layer.
5. **No automatic downgrade.** Provider failure yields `FAILED`. A deterministic result
   is a separate, explicitly requested run flagged `produced_without_llm`.
6. **MOCK is rejected at creation** in a `PRODUCTION` environment, with a durable
   rejection record — before it executes or reaches the interface.
7. **Environment is server-resolved** from deployment config, never from a request.
8. **The timestamp comes from the provider, not from us**, and the skew against our own
   clock is bounded. On its own this establishes consistency, not liveness — an
   interceptor returns `Date: <now>` and passes — so it is not presented as independent
   proof. Independence comes from (10).
9. **The transport is pinned.** `trust_env=False`, so an ambient proxy cannot redirect a
   "real" call. Any deliberate proxy is named in config and recorded per call.
10. **TLS pinning survives a subverted trust store**, which is what makes (8) and (9)
    independent rather than one control with two names. Each run records whether it was
    enforced, observed or neither, so evidential weight is stored rather than assumed.

Page 7 of the UI shows the provider response ID, timestamp and token counts for every
run. If those aren't there, the run didn't happen.

## Sequence

The UI is ordered and each step gates the next. V0 cannot execute until entity
resolution, known facts and pre-flight are done — which is the point of your first
request.

```
1 Intake & entity resolution → 2 Known facts → 3 Pre-flight
       → 4 Simulation → 5 Domain dispositions → 6 Run V0 → 7 Execution integrity
```

## Audit remediation (build 4.7.1)

An adversarial audit of build 4.7.0 found 3 critical, 6 high, 8 medium and 7 low
findings, and concluded the central integrity claim did not hold. All criticals and
highs are closed. `Workbench_Red_Team_Audit.md` has the original findings.

| # | Finding | Fix |
|---|---|---|
| C-01 | Liveness timestamp was generated locally and checked against a window from the same clock — tautological | `provider_request_at` now comes from the provider (Anthropic `Date` header, OpenAI `created`), stored beside `local_request_at`, with the **skew** bounded by `MAX_CLOCK_SKEW_SECONDS`. A response with no provider timestamp fails the run. A second independent identifier (`request-id` / `x-request-id`) is also recorded |
| C-02 | `httpx` trust_env meant an ambient `HTTPS_PROXY` redirected every "real" call | All calls go through `providers/_transport.py` with `trust_env=False`, `verify=True`, no redirects. A proxy is used only when named in `LLM_EGRESS_PROXY`, and is recorded on every `llm_run` row |
| C-03 | The three confidence components were literals (0.42/0.68/0.35) — every V0 published the same score | `confidence.derive_components()` computes each from priced-spend share, evidenced-value share, domain completeness, prior coverage and recency, and the lever stage mix. Stage ceilings bound V0 realization structurally. Every score carries its drivers |
| H-01 | Coverage denominator arrived in the request body — omitting unpriced markets flipped PARTIAL to COMPLETE | Denominator derived from the simulated scope and priors. A declared figure is reconciled and reported as a cross-check, never used as the denominator |
| H-02 | `layers_priced` was a literal in the endpoint, so the layer test could never fire | Computed from the components actually built |
| H-03 | Coverage was per country, so one broadband prior made an all-MPLS country "priced" | Assessed per (country, product) pair; the material-country floor now tests a country's own priced ratio |
| H-04 | `seed()` ran on every startup with `DELETE` at the top, destroying governed reference data | Idempotent by default; reseeding is `make seed` (`--force`) |
| H-05 | 0 of 37 tests touched the database — the controls that matter were untested | `tests/test_controls_db.py`: 17 tests against a real engine (SQLite with attached schemas) covering succeed() gating, response-id uniqueness, idempotency, mode rejection, MOCK-in-production, non-destructive seed |
| H-06 | The "anti-stub" test grepped for four self-chosen strings | Deleted. Replaced by behavioural tests: adapters raise without a key; no adapter may build a raw `httpx.Client` |

Mediums closed: platform unit costs moved to `reference.platform_unit_cost` (M-01);
ensemble and site bounds with O(sites) memory instead of O(ensemble×sites) (M-02);
idempotency keys enforced (M-03); unimplemented modes rejected before a run row exists
(M-04); pre-flight `GET` no longer creates a report (M-05); Decimal throughout the ops
path (M-06); asserted share value-weighted like simulated share (M-07); untrusted input
fenced in the data position (M-08).

### Second audit — C2-01 closed (build 4.7.2)

A follow-up audit found the test harness was itself the most destructive thing in the
bundle. `tests/conftest.py` used `os.environ.setdefault("DATABASE_URL", "sqlite://")`,
which is a no-op when the variable already exists — and the `api` container sets it to
Postgres. `make test` therefore ran `metadata.drop_all()` against the live database,
once per test. The command this README recommended running first destroyed all data.

Three independent layers now prevent it:

1. **`make test` passes `DATABASE_URL=sqlite://` explicitly** to the test process, so
   the suite cannot bind to Postgres regardless of what `conftest.py` does.
2. **`conftest.py` assigns rather than defaults**, and `pytest_configure` aborts the
   whole session before collection if the engine is not disposable — which also stops
   `seed(force=True)`, a destructive call no fixture guards.
3. **`db.assert_disposable()` guards the operation, not the caller.** `db.reset_schema()`
   refuses any non-SQLite engine by name. A future fixture rewrite cannot reintroduce
   the defect by accident; it would have to delete the guard deliberately.

Three meta-tests cover it, including the one that was missing: an assertion that the
engine the suite is bound to is actually disposable.

### C2-02 closed (build 4.7.3)

The C2-02 finding was a regression the first remediation created. Sizing unpriced scope
by a cross-country median only works when *some* country has a prior for that product;
where none did, the row was valued at zero, so the exact scope that could not be priced
contributed nothing to the denominator meant to count it. An estate that was DIA in the
UK and MPLS in Brazil and India, with no MPLS prior anywhere, reported **COMPLETE at
100%** while 500 circuits were invisible.

The fix does not invent a rate. It stops the gate depending on a measure that unsizable
scope can vanish from:

| Measure | Property |
|---|---|
| Value coverage | priced value / total sizable value — still 1.000 on the attack above |
| Circuit coverage | priced circuits / total circuits — **cannot be zeroed away** |
| **Effective** | `min(value, circuit)` — governs the gate |

Plus three supporting changes:

- **Any row that cannot be sized at all forces at minimum PARTIAL.** COMPLETE asserts
  every coverage test passed, and no test can pass over scope whose size is unknown.
- **The material-country floor no longer skips zero-value countries** — which was exactly
  the unsizable case. Materiality is now the greater of a country's value share and its
  circuit share, so a wholly unsizable country is always assessed. Both Brazil and India
  now breach.
- **Sizing priors are separated from pricing priors.** A German MPLS rate cannot price a
  Brazilian circuit but can size one for the denominator, which shrinks the unsizable
  population without pricing anything at a rate that does not apply. `rate_basis` records
  which was used per row.

The fix immediately exposed a real gap in the seeded data: `MOBILE_5G` is the STORE
archetype's backup product and had no prior in any country. It is now seeded, and a test
asserts every archetype product is priceable — a genuinely unpriceable product will still
be caught.

### C2-03 closed (build 4.7.4)

`metadata.create_all()` creates missing *tables* only — it never adds a column, never
renames one, and never notices that an existing database is the wrong shape. Upgrading a
4.7.0 volume would therefore have failed every `llm_run` INSERT (so no LIVE run could
record its proof), orphaned every existing case behind an empty `engagement_case`, and —
worst — skipped the seed because thresholds were present, leaving `platform_unit_cost`
empty and silently dropping ~40% of modelled TCO. That last shape is the dangerous one:
a system that starts, runs, and is quietly wrong.

`app/migrations.py` makes the state explicit and either migrates it or refuses to boot.

| Behaviour | Detail |
|---|---|
| Version stamp | `audit.schema_version`; an unstamped database with existing tables is inferred as legacy, an empty one as fresh |
| Forward steps | v2 adds the five liveness columns and `lever.earliest_supported_stage`; v3 renames `engagement.case` → `engagement_case`, preserving rows |
| Type safety | Column DDL is compiled from the model, so a migration cannot drift from the definition it is catching up to |
| Ordering | Migrations run **before** `create_all`, so a rename is never defeated by an empty table having just been made under the new name |
| Idempotent | Re-running applies nothing and is not an error |
| Refuses | A schema newer than the build (rollback), and a half-applied rename where both tables exist — choosing one risks discarding live cases |

The seed hole is closed separately, because it was independent of the schema: `seed()` is
now idempotent **per table** rather than skipping everything if `threshold` held a row.
An analyst-tuned threshold survives an upgrade while a table introduced by a later build
is still populated.

`make doctor` reports version and drift without changing anything; `make migrate` applies
pending steps; `/v1/health` carries the schema state. Eleven tests build a 4.7.0-shaped
database and upgrade it, covering data preservation, idempotency, fresh detection and
both refusal paths — because this is the failure that only appears on the *second*
deployment, which is the one nobody rehearses.

### C2-04 closed (build 4.7.5)

The API enforced `X-API-Token` on every route; the Streamlit client sent no headers at
all. Setting `API_TOKEN` therefore broke the entire interface with 401s — the only
authentication control in the bundle could not be switched on. Each half was entirely
plausible on its own, which is why nothing caught it.

The header name now has **one definition**, in `contract/auth.py`, copied into both
images at build time. The mismatch class is gone rather than merely tested for. The
compose build context moved to the repository root so both Dockerfiles can reach it.

| Change | Detail |
|---|---|
| Client attaches the token | `api_client.auth_headers()` on every request; empty when unset, so the default open path is unchanged |
| Constant-time comparison | `secrets.compare_digest`; `!=` on a secret leaks its length and prefix through response timing |
| Exempt set minimised | `/v1/health` only. `/docs` and `/openapi.json` were previously exempt, publishing the API surface while a token was configured |
| Docs off when locked | Swagger UI cannot attach the header, so it is disabled rather than left half-working |
| Runtime agreement probe | `/v1/health` is exempt, so it succeeds even when every other route 401s. `probe_auth()` makes one authenticated call and the home page **refuses to load** on a mismatch, naming the cause |
| 11 tests | Enforcement through a real request stack — missing, wrong and correct tokens, write routes, health staying open, the exempt set, and that the contract file carries no secret |

A token mismatch between the two services is a separate failure that a shared constant
cannot prevent, which is what the runtime probe is for.

### C2-05 closed (build 4.7.6)

The tests written alongside the C-02 transport fix could not fail:

```python
src = inspect.getsource(_transport.client)
assert "trust_env" in src and "False" in src
```

That passes on `trust_env=True, verify=True, follow_redirects=False`, because
`"False"` appears elsewhere on the same line. It was the same source-grep theatre
deleted one round earlier, reintroduced by the person fixing the thing it was meant to
guard — which is the more useful finding than the test itself.

`tests/test_transport.py` replaces both with ten behavioural tests against a real HTTP
server, and the design point is the **control arm**:

| Arm | Assertion |
|---|---|
| Control | a client built with `trust_env=True` **fails** to reach the origin through a dead proxy in the environment |
| Subject | `_transport.client()` **succeeds** against the same origin under the same environment |

If the control ever stops failing, the test has gone toothless and says so; if the
subject starts failing, the transport has begun trusting the environment. Flipping
`trust_env` back to `True` fails the subject immediately.

Also covered behaviourally: a *named* `LLM_EGRESS_PROXY` is honoured (otherwise "ignores
proxies" could be satisfied by a transport that ignores all of them, breaking a
legitimate deployment); redirects are not followed, so an open redirect cannot forward a
request and its `Authorization` header elsewhere; and both adapters reach the network
only through the pinned transport — instrumented on both routes, so no network call is
made whichever path is taken.

The last remaining source-grep test, on constant-time comparison, is replaced by a spy on
`secrets.compare_digest`. A statistical timing test would be flaky; reading the source
would be the theatre being removed. **No test in the bundle now asserts on source text.**

### C2-06 closed (build 4.7.7)

Unit costs were moved to reference data two rounds ago; the **weights that combine them**
stayed in Python. `confidence.WEIGHTS`, `STAGE_CEILINGS`, `LEVER_STAGE_WEIGHT`,
`SIMULATED_BANDS`, the band floors and the inline `0.40 / 0.35 / 0.25` driver blend were
all code constants — the same defect the unit-cost fix was meant to close, relocated
rather than removed. A governed model whose inputs are governed and whose weights are not
is only half governed.

`domain/policy.py` introduces `ConfidencePolicy` and `CoveragePolicy`, loaded from
`reference.threshold` (versioned, with an approver). 37 governed values in total.

**There is no code default anywhere in the fix**, which is the part that matters: a
missing key raises `PolicyIncomplete` rather than falling back, because a fallback
constant is a code constant with extra steps. The seed is the single source; tests build
policies explicitly from the seeded values, so a seed change that breaks the model is
caught in the suite rather than in production.

Policies validate on construction, so a steward cannot commit:

| Rejected | Why it matters |
|---|---|
| Component weights not summing to 1 | The weighted score would silently exceed or undershoot its range |
| Driver blends not summing to 1 | Same, one level down |
| A simulated ceiling that *rises* with share | Inverts the control — more simulation would mean more confidence |
| Bands that stop below a share of 1 | Leaves a hole a real run can fall into |
| Band floors that do not descend | Produces incoherent labels |
| A coverage floor above the minimum | Nothing could ever publish PARTIAL |

Fourteen tests cover it, including a regression guard that fails if a `DEFAULTS`-style
constant reappears in either module — which is exactly what happened last time — and one
that shifts a weight and asserts the result moves, proving the policy is consumed rather
than shadowed. `/v1/health` reports policy usability, and an unusable policy is a 503 on
the estimate endpoint rather than a run on constants nobody approved.

### C2-07 and C2-08 closed (build 4.7.8)

One origin meant two different things. `ANALYST_ASSERTED_PRIOR` covered both *the analyst
typed a site count into the scope form* and *someone registered a known fact under
§0.1B*. On a default run the typed footprint drove primary access, overlay, SSE and
operations, so asserted share read **0.96** against a 0.25 trigger and the
asserted-baseline ceiling fired on every estimate ever produced — a constant wearing a
control's clothing. C2-08 was the mirror image: because asserted share read component
origins and known facts never became components, registering a known fact changed
confidence by exactly zero.

The two are one defect, so they are fixed together:

| Change | Effect |
|---|---|
| `ANALYST_ENTERED_SCOPE` split out | Typed scope is the perimeter of the question, not a claim about the world. It earns no evidenced credit — which depresses the baseline — but does not trigger the assertion ceiling |
| Known facts can supply a quantity | `footprint_known_fact_id` / `users_known_fact_id`. Naming the fact is the **only** way to claim that origin, so the caller cannot assert provenance and the link is recorded in the snapshot pins |
| Validated at use | Rights check (§2.4), fact class must match the driver, and a CONTRADICTED fact is refused |
| Corroboration supersedes | Per §0.1B a corroborated fact is superseded by the public fact that corroborated it, so it enters as `EVIDENCED_PUBLIC` and *raises* the baseline. Corroborating is now worth doing rather than merely recorded |

**A test found a defect in the model itself.** Asserting that typed scope depresses the
baseline failed — because stage ceilings were applied as a hard cap, and the V0 baseline
ceiling of 0.55 sits below the 0.65 a typed-scope run already derives. Every raw score
above the ceiling collapsed to the same number, so the evidence drivers had no effect at
V0 at all. Ceilings now **scale** rather than truncate: the ceiling is the most a stage
could ever justify and derived quality attains a fraction of it. Discrimination is
restored (typed 0.358, half-evidenced 0.454, fully evidenced 0.550), and the raw
pre-scaling score is reported so a weak analysis is distinguishable from a strong one the
stage does not yet permit to be confident.

### C2-07 and C2-08 closed (build 4.7.8)

One defect seen from two sides. `ANALYST_ASSERTED_PRIOR` meant both *"the analyst typed a
site count into the scope form"* and *"someone registered a known fact under §0.1B"*. On a
default run the typed footprint drove primary access, overlay, SSE and operations, so
asserted share read **0.96** against a 0.25 trigger — the ceiling fired on every estimate
ever produced, a constant wearing a control's clothing. And because the share was computed
from component origins alone, a registered fact that wasn't bound to anything moved
confidence by **exactly zero**.

The origins are now three distinct things, weakest to strongest:

| Origin | Meaning | Effect |
|---|---|---|
| `ANALYST_ENTERED_SCOPE` | typed into the form; no asserter, no date | earns no evidenced credit, so it depresses the baseline through the driver blend — but trips no ceiling. Declaring a perimeter is not the same act as relying on an unverified claim |
| `ANALYST_ASSERTED_PRIOR` | a registered, uncorroborated known fact | also trips the §0.6A asserted ceiling |
| `EVIDENCED_PUBLIC` | a *corroborated* known fact | superseded by the public fact that corroborated it (§0.1B.3 step 3), so it raises the evidenced share |

That last row is what makes known facts consequential: corroborating one moves its value
out of asserted share *and* into evidenced share, so it raises published confidence twice
over. Corroboration becomes worth doing rather than merely logged.

Facts bind to quantity drivers explicitly (`footprint_known_fact_id`,
`users_known_fact_id`). A binding is refused if the fact is on another case, is the wrong
class, has not passed the §2.4 rights check, is `CONTRADICTED`, or — for a quantity the
model already carries — disagrees with it beyond the governed
`known_fact_binding_tolerance`. Attribution you cannot reconcile is decorative.

**A design error surfaced while fixing this, and the suite caught it.** Operating cost was
initially bound as a quantity driver. It is a *rate*: the OPS quantity is sites, which
inherits the footprint's provenance. Binding it to `quantity_origin` would have misreported
what the fact influenced, since the §0.6A shares are quantity-weighted. Operating-cost
facts are now informational, and rate-level attribution (`unit_cost_origin`) is named as a
gap rather than faked.

Eight tests cover it, including one asserting the three shares sum to the whole estimate,
and one asserting the ceiling now *discriminates* between runs — which was the actual
complaint.

### C2-07 and C2-08 closed (build 4.7.8)

These were one problem. `ANALYST_ASSERTED_PRIOR` covered both a *registered known fact*
under §0.1B and *the footprint typed into the intake form*, so asserted share read ~0.96
on every default run and the 0.50 ceiling fired every time — a constant wearing a
control's clothing (C2-07). And because asserted share read component origins while known
facts set none, registering a known fact moved the published confidence by exactly zero
(C2-08). The overloading was the reason the register did nothing.

**Three origins, not two.** The distinction is that the scope frame is a *premise* — the
analyst telling the system what to estimate — while a known fact is a *claim about the
world* that could be wrong:

| Origin | What it is | Effect |
|---|---|---|
| `ANALYST_ENTERED_SCOPE` | 120 branches in GB, as declared at intake | Counts against evidenced share, so it lowers baseline confidence — but does not trip the assertion ceiling |
| `ANALYST_ASSERTED_PRIOR` | a registered, attributed, dated claim supplying that number | Trips the ceiling when it carries material share |
| `EVIDENCED_PUBLIC` | the same claim, once corroborated and superseded | Raises baseline confidence |

**Known facts now bind to the drivers they supply.** `known_facts.select_bindings()` maps
a registered fact onto `sites` or `users`, and the components it drives carry both its
origin and its `known_fact_id` — so a figure is traceable to the person who asserted the
number behind it. Binding is refused for a fact that is contradicted, or for a
`PRIOR_ENGAGEMENT` fact whose §2.4 rights check has not passed. Where several facts target
one driver the most recent assertion wins and the displaced ones are reported.

The incentive structure is the point: attributing what you know and then **checking** it
raises confidence, because the public fact supersedes the claim. Leaning on an unchecked
claim lowers it. Measured on an identical estate — same sites, same rates, differing only
in whether the number behind them was verified — the three paths produce different
confidence.

Eleven tests cover binding, rights refusal, contradiction refusal, recency precedence,
fact-versus-run disagreement, and the end-to-end confidence movement in both directions.

### C2-10 closed (build 4.7.9)

This was a genuine design limit rather than an oversight. The liveness proof compares the
provider's reported clock to ours and bounds the skew — but an interceptor returns
`Date: <now>` and passes. The clock check had no strength of its own: it rested entirely
on the transport being genuine, so an operator who could install a CA in the container
image defeated both controls at once. They were not two controls; they were one control
with two names.

**TLS pinning supplies the independence.** A pinned connection fails even when the trust
store has been subverted, because the peer certificate must match a value fixed out of
band. Three modes, via `TLS_PIN_MODE`:

| Mode | Behaviour |
|---|---|
| `OFF` | pins neither recorded nor checked |
| `OBSERVE` *(default)* | pin recorded on every call, never enforced |
| `ENFORCE` | a call whose pin is unknown, unreadable or unmatched **fails the run** |

`OBSERVE` is the default because **you cannot pin what you have never seen**. Run
normally, read the value from `make pins`, verify it against the provider's published
certificate, set `TLS_PINS`, then switch to `ENFORCE`. A host may carry several pins so a
certificate rotation does not take the system down.

The pin is read **in band**, from the connection the answer arrived on. A separate
handshake to the same host would be simpler, but an interceptor could serve a genuine
certificate to that probe and its own to the real request.

**Each run now records the strength of its own evidence** — `PINNED_AND_ENFORCED`,
`PINNED_OBSERVED` or `TRANSPORT_ONLY` — so a call made over an unpinned connection is not
presented as equally proven. Under `ENFORCE`, an unreadable certificate fails closed:
that is exactly the shape an interception takes.

**And one control remains deliberately out of band.** `make attest` produces a summary to
compare against the provider's own console — a different channel, on a different device,
not reachable by anything that has compromised this host. Everything else in the chain
arrives over the same connection and can be forged together, so the endpoint says so in
its own response rather than presenting its counts as proof.

Twenty-one transport tests, eleven of them covering the pin state machine across all
three modes, rotation, and fail-closed behaviour.

### C2-09 closed (build 4.7.10)

The README presented `provider_request_id` as part of the liveness proof. It was stored,
nullable, and never checked by anything — claimed as evidence, used as none.

Closing it required first being honest about what it is. **It is not a barrier to
forgery**: anyone controlling the endpoint mints both identifiers, so requiring a second
one stops nobody. Its real value is different — the transport-issued request identifier
is the value the provider's *own logs are indexed by*, which is what turns the out-of-band
attestation from "compare aggregate counts" into "confirm you served these specific
calls". That is a materially stronger question to be able to ask through a channel this
host does not control.

| Change | Detail |
|---|---|
| Uniqueness | A unique **index**, not a constraint — nullable, so absent identifiers do not collide with each other, and addable to an existing table on both SQLite and Postgres |
| Verifiability recorded | `externally_verifiable` per run. A call with no identifier cannot be spot-checked, and the record says so rather than leaving it to be assumed |
| Graded enforcement | `REQUIRE_PROVIDER_REQUEST_ID`, off by default: a provider or intermediary can legitimately omit the header, and failing genuine calls by default would be the wrong trade |
| Attestation sample | `make attest` now emits up to 20 `(request_id, response_id, timestamp, tokens)` tuples to quote to the provider, plus a count of runs that carry nothing to quote |

The nullable semantics are deliberate and were got wrong once before: absence is absence,
not sameness. That mistake is how the idempotency key ended up unenforced, and there is
now a test asserting three identifier-less runs coexist.

### C2-11 closed (build 4.7.11)

§16.1 stated that simulation is "asynchronous, cancellable and resumable". It was none of
those — a blocking endpoint that, at the permitted bounds, held a worker for around a
minute. Bounded is not the same as non-blocking, and a spec target the implementation
does not meet is a claim, not a target.

The ensemble made all three cheap, because pass *i* is a pure function of `seed + i`:

| Property | How |
|---|---|
| Asynchronous | `POST …/simulations:run` returns **202** with a run id; a bounded worker pool (`SIM_WORKERS`, `SIM_QUEUE_MAX`) does the work; poll `GET /v1/outside-in/simulations/{id}` |
| Cancellable | The worker checks a flag **between passes**, so cancellation is prompt without being violent and completed passes survive |
| Resumable | A checkpoint holds per-pass summaries every `SIM_CHECKPOINT_EVERY` passes; a cancelled or failed run continues from the next index |

**The property worth having is not that resuming works but that it is *identical*.**
Assembling an ensemble from two batches produces byte-identical output to running it
straight through, because no pass depends on any other. A cancelled-and-resumed estimate
is therefore the same estimate, not a similar one — which is what lets the §0.11
reproducibility guarantee survive cancellation. There is a test asserting exactly that,
comparing output hashes.

Two supporting details. Checkpoints store per-pass *summaries* rather than full node and
edge lists; the display sample is regenerated at aggregation time by re-running the one
pass it came from, which is free because that pass is deterministic. And the estimate
endpoint now refuses a partial ensemble with a 409 naming the status and progress, since
asynchronous simulation means a run can exist without an output.

Migration v6 backfills pre-existing runs as `SUCCEEDED` — they completed synchronously, so
they are finished by definition, and marking them `QUEUED` would offer a resume that
recomputed an already-stored result.

Thirteen job tests. `run_job` is called directly rather than through the executor, so they
exercise the real code path without depending on thread scheduling.

### C2-11 closed (build 4.7.11)

§16.1 stated that simulation is asynchronous, cancellable and resumable, and the
implementation was none of those — a blocking endpoint that, at the permitted bounds,
held a worker for about a minute. Bounded is not the same as non-blocking: a request that
long times out through most proxies and occupies a worker that could be serving someone
else.

`app/jobs.py` is a small in-process runner. The production architecture puts this on
Prefect, which is out of scope for a laptop bundle, so the three properties are
implemented directly:

| Property | How |
|---|---|
| Asynchronous | `POST …:run` returns **202** with a poll URL; work happens on a worker thread with its own session. The queue is bounded by `SIM_QUEUE_MAX` and returns **429** rather than backlogging — an unbounded queue turns a burst into an outage |
| Cancellable | Cooperative, checked between passes, so a cancelled run stops at a consistent checkpoint. No thread is killed mid-write, and completed work survives |
| Resumable | Checkpointed every `SIM_CHECKPOINT_EVERY` passes; `…:resume` continues from where it stopped, and a crashed process requeues its `RUNNING` rows at startup |

**Resumability is what makes cancellation safe to offer at all.** Because every pass is a
pure function of its seed, a resumed ensemble is byte-identical to one that ran straight
through — not merely similar. Without that, an interruption would quietly produce a
different estimate and §0.11 reproducibility would not survive it. Verified: interrupting
at pass 9 of 25 and resuming reproduces the same `output_hash`.

The estimate endpoint now refuses a run that has not reached `SUCCEEDED`, returning the
progress rather than crashing on a null output — async means a simulation can exist
without a result, and the caller has to be told which.

### C3-01a closed (build 4.7.12)

A third audit reported that `requeue_interrupted()` was never called. **That finding was
wrong** — it was called from the lifespan at `main.py:42`. The audit had grepped for
`recover|reclaim` against a function using neither word, and read the empty result as
proof. The correction is recorded in `Workbench_Red_Team_Audit_3.md` rather than removed.

Three real defects sat behind it and are fixed:

| Defect | Fix |
|---|---|
| Only `RUNNING` runs were reclaimed | `CANCELLING` and `QUEUED` orphans too — in a fresh process no worker exists for any of them |
| A cancelled run would be resurrected | `CANCELLING` now resolves to `CANCELLED`, honouring the request the dead process could not deliver. The checkpoint survives, so resume remains available |
| A deferred run stayed `RUNNING` | On a full pool it is left `QUEUED` — visible, recoverable, and distinguishable from a live job |

The more useful outcome is `tests/test_wiring.py`. Both the real defects and the false
positive had one cause: **a unit test on a control passes whether or not anything invokes
it, and a grep for the call site depends on guessing the name.** Ten tests now assert
invocation rather than implementation — that the lifespan runs migrations, seeds and
reclaims; that a failed reclaim does not stop the service while a refused schema does;
that the auth middleware runs on a real request; and that a unique index declared in the
model exists in a created database. Had the first of those existed, the false finding
would never have been written.

### C3-03 closed (build 4.7.13)

Pinning hashed the **leaf certificate**, so a provider renewing with the same key produced
a different pin and `ENFORCE` failed every call. Following the README's own instruction to
switch enforcement on bought a quarterly outage — and the README did not say so.

Two pins are now computed per connection, self-describing by prefix so they can never be
compared to the wrong thing:

| Pin | What it hashes | Renewal |
|---|---|---|
| `sha256/…` | the SubjectPublicKeyInfo (RFC 7469 form) | **survives** |
| `cert-sha256/…` | the whole leaf certificate | breaks |

Either matching satisfies enforcement, so an operator migrating between them is never
locked out mid-change. Verified: an SPKI pin passes across a renewal that a certificate
pin refuses, while a genuine **key rotation** is still refused by both — which is the
behaviour that makes pinning worth having.

**The more useful half is making the rotation visible before it bites.** A key rotation
still moves an SPKI pin, so each connection also records the leaf certificate's expiry.
`make pins` and `/v1/health` report it and warn inside `TLS_PIN_EXPIRY_WARN_DAYS`, which
turns the day enforcement would have broken into a date known three weeks ahead. A
mismatch message now also names renewal as the likely cause before it names interception,
because a renewal is what an operator will actually hit.

Two smaller fixes came with it. `make pins` suggests only the SPKI form — suggesting a
certificate hash would reinstate the defect the endpoint exists to prevent. And the pin
host is now derived from `ENDPOINT` rather than repeated by hand in each adapter (C3-10),
so an endpoint change cannot leave the pin checking a different host than the one being
called.

Migration v7 relabels pre-existing unprefixed pins as `cert-sha256/…` rather than
discarding them, so anyone who already configured one is not silently locked out.

### C3-04 closed (build 4.7.14)

Migration v5 added a uniqueness guarantee to a column that had never had one, by creating
the index directly. A legacy database holding two rows with the same
`provider_request_id` therefore **crash-looped the container at startup** with a bare
driver error, no diagnosis and no remedy — the schema stuck at v4 with no way forward
short of manual SQL.

The decision inside the fix matters more than the mechanics. A duplicate provider
identifier is **precisely the event the constraint exists to catch** — it can be the trace
of a replayed response presented as a fresh call. Deleting the offending rows to let the
migration proceed would destroy the evidence of the one thing most worth knowing about.
So nothing is deleted:

| Step | Behaviour |
|---|---|
| Detect | Duplicates are found before the index is attempted, not discovered by its failure |
| Preserve | Every displaced copy is written in full to `audit.quarantined_row` |
| Release | The identifier is cleared on the later copies only; the earliest keeps it |
| Report | A **P2 incident** records the values, the row kept and the rows released |
| Surface | `/v1/health` carries the open-incident count; `/v1/integrity/incidents` has the detail |

Verified end to end: four rows in, four rows out, both displaced copies preserved with
their token counts intact, one incident raised, and the index created.

Migration failures generally now raise `MigrationFailed`, naming the step, stating that no
partial change was committed, and pointing at `make reset` or a manual resolution — because
migrations are idempotent and resume from the last good version. A structural failure still
refuses to start; a *data* conflict is handled and reported, because an operator who cannot
start the service cannot investigate it either.

### C3-02 closed (build 4.7.15)

A known fact nominated as the source of a quantity was validated for rights, class and
contradiction — but never against the **figure it claimed to be the source of**. So a run
using 122 sites could be attributed to someone who had said 400, with the disagreement
recorded in a field nothing read.

That is worse than leaving the number unattributed: a reader following the attribution
arrives at a fact contradicting the figure it supposedly supports.

**The system does not resolve the disagreement, because it cannot.** Either the scope was
typed wrongly or the fact describes a different perimeter, and nothing in the code can
tell which. So it routes to review, on the same pattern §0.1B applies when a known fact
contradicts an approved public fact — retain both, credit neither.

| Case | Outcome |
|---|---|
| Fact agrees within tolerance | Credited: `ANALYST_ASSERTED_PRIOR`, or `EVIDENCED_PUBLIC` once corroborated |
| Fact disagrees | **409 with a conflict id.** Not credited, and the estimate is blocked |
| Fact carries no value | Refused — there is nothing to be the source of |
| Conflict resolved | Unblocked, and the quantity stays `ANALYST_ENTERED_SCOPE`. The fact still disagrees, so it is still not credited; the reason travels with the snapshot |

There is deliberately **one** resolution, `SCOPE_IS_CORRECT`, and it requires a reason and
a named person. Any other answer means the input is wrong, and the remedy for a wrong
input is to change it and re-run — not to file a note about it. A settled conflict is not
reopened by a re-run.

The tolerance is governed (`known_fact_policy.agreement_tolerance`, default 0.10) rather
than the module constant it was.

**Four unreachable implementations were deleted.** `bind_quantities`, `select_bindings`,
`resolve_binding` and `inventory` — 251 lines — none called by anything. The estimate
endpoint used `resolve_quantity_source`, and **seven tests were exercising the dead path
instead**, which is why this defect survived a test suite that appeared to cover it. Two
implementations existed and the tested one was the wrong one.

### C3-05 to C3-13 closed (build 4.7.16)

The remaining audit-3 findings, all medium or low.

| # | Defect | Fix |
|---|---|---|
| C3-05 | `resume()` committed `QUEUED` then let `QueueFull` propagate, leaving a row claiming to be queued with nothing scheduled | Status is restored when the pool refuses, so the row reflects reality and the caller gets an honest 429 |
| C3-06 | `aggregate([])` raised a bare `IndexError` with no context | A named error explaining that a cancelled run with no checkpoint has nothing to assemble |
| C3-07 | Identifier uniqueness was **global**, so two providers issuing the same string would fail a genuine run with a message accusing it of replay | Scoped to `(provider, identifier)`. The control is unchanged within a provider; only the false positive is gone |
| C3-08 | `/v1/health` ran a schema query and two full policy validations on every call, polled every 10s by the container | Shallow by default and touches no database; `?deep=true` adds the checks and is cached for `HEALTH_DEEP_TTL_SECONDS` |
| C3-09 | `superseded_by` was filtered on and **never written** — §0.1B's documented mechanism did not exist | Corroboration now records the agent run that superseded the fact |
| C3-10 | The pin host was repeated by hand in each adapter | Derived from `ENDPOINT` (closed during C3-03) |
| C3-11 | `SIM_QUEUE_MAX` was counted in an in-memory set, so each replica admitted a full queue and a restart forgot the backlog | Counted in the database; `_inflight` now only de-duplicates within a process |
| C3-12 | A cancel arriving during aggregation left `SUCCEEDED` with `cancel_requested` still set | The flag is cleared on completion and the late arrival logged. Completing is right — the work was already done — but the record must not contradict itself |
| C3-13 | A test mutated the module-global `jobs._inflight` | Rewritten against the database-backed depth, which is also the thing now worth testing |

Migration v9 carries the uniqueness change and reuses the C3-04 duplicate handling, so a
legacy database with a cross-provider collision is quarantined rather than crash-looped.

### C4-01 closed (build 4.7.17)

Two correct fixes disabled each other. C3-11 made the queue bound count database rows so
it would hold across replicas; C3-01 made startup reclaim interrupted runs. Reclaim sets
every orphan to `QUEUED` — which the bound then counts — so it was refused by its own
admission control. Measured: **40 orphans, `SIM_QUEUE_MAX=32`, 0 reclaimed.** The recovery
path could not run whenever there was a backlog, which is the only situation it exists for.

Investigating it showed C3-11 had bounded the wrong thing. `SIM_WORKERS` was declared,
reported on `/v1/health`, and **used nowhere**; thread creation was bounded only
indirectly, by database state. There are now two bounds measuring two different quantities:

| Bound | Measures | On exceeding |
|---|---|---|
| `SIM_WORKERS` | concurrent worker threads **in this process** — threads are a per-process resource, so per-process is the right scope | The run stays `QUEUED` for the next free worker. Not refused |
| `SIM_QUEUE_MAX` | total work that **exists anywhere**, counted in the database | New work is refused with 429. Accepting work nobody can get to is not a queue |

**Reclaim and drain are exempt from admission control**, because neither is new work: one
finishes something already accepted, the other starts something already queued.

The missing piece was a **drain**: a freed worker takes the next queued run, which is what
makes `QUEUED` a queue rather than a label. Without it a run deferred for want of a worker
waited for a restart. Verified at the scale that broke it — 40 orphans, 2 workers: all 40
complete, concurrency never exceeds 2, and new work is still refused while saturated.

Six tests added, and the point of them is the **scale**. Every earlier job test used a
single run, which is exactly why this interaction was invisible: a bound is only
interesting when something exceeds it.

### C4-02 closed (build 4.7.18)

The C3-02 agreement check shipped with its own opt-out:

```python
def resolve_quantity_source(..., value_used=None, tolerance=0.10):
```

Omitting `value_used` skipped the comparison entirely and credited the fact
unconditionally — the exact behaviour C3-02 was raised to remove. And `tolerance` had been
moved to governed reference data under C2-06, then given a default here, which is the same
defect with a longer path: a caller omitting it silently used a number nobody approved.

**A guard whose default is "off" is not a guard.** Both are required arguments now. And a
required argument can still be passed `None`, so the check also **fails closed**: a run
that supplied no usable figure is refused rather than waved through, because crediting a
fact as the source of an unknown quantity is precisely what the check exists to stop.

Auditing for the same shape found three more in `confidence.compute` —
`simulated_share=0`, `asserted_share=0` and `v0_status="COMPLETE"`, all defaulting to the
**unpenalised** state. A caller that forgot one published a higher confidence than the
evidence supported, which is the direction that matters. All three are now required; the
18 call sites state their case explicitly, which reads better anyway — a test asserting
"no simulation" should say so rather than rely on a default.

Six tests, in two forms: signature assertions that no default has crept back, and
behavioural ones that omission raises and an unusable comparand is refused. The test helper
now reads the **seeded** tolerance rather than carrying its own, so a seed change that
weakens the guard fails in the suite rather than in production.

### C4-03 closed (build 4.7.19)

Migration v9 passed `scope_column="provider"` into the duplicate release, and the scope
reached the `GROUP BY` and stopped there — the row-fetch selected by identifier alone. So
a migration written to **stop** treating a cross-provider collision as a replay did
exactly that while running: it found the right duplicate groups and then stripped the
wrong rows.

Demonstrated with four rows sharing one identifier, two per provider:

| Release | Stripped |
|---|---|
| Unscoped (old) | `a2`, **`o1`**, `o2` — `o1` is a legitimate OpenAI identifier |
| Scoped (new) | `a2`, `o2` — only the genuine within-provider duplicates |

The scope now reaches the fetch and the release predicate, and a `NULL` scope uses `IS
NULL` rather than an equality that would match nothing and leave the group unresolved.

**The audit missed half of it.** v5 runs before v9 and performed its own release to build a
single-column index that v9 then drops. That release was necessarily global — a
single-column unique index requires it — so the damage was done two steps before the
scoped code ran. v5 now adds its column and nothing else; all index work happens once, in
v9, with the correct scope.

Five tests, including one that runs v5 **in isolation** and asserts it neither indexes nor
releases anything. That one started as a `getsource` check for `CREATE UNIQUE INDEX` —
the same theatre removed twice already — and was rewritten behaviourally, because a grep
passes on any rewrite that spells the statement differently.

### C4-04 closed (build 4.7.20)

C3-08 was right that a schema query plus two policy validations every ten seconds is
waste — but it fixed the cost by deleting the signal. The container healthcheck still
polled the now-shallow default, so an API with an **unreachable database reported
healthy**, and `ui depends_on api: service_healthy` would start the interface against an
API that could not serve a request.

The real problem was three questions sharing one endpoint, where the cheap answer
displaced the useful one:

| Endpoint | Question | Properties |
|---|---|---|
| `/v1/health` | **Liveness** — is the process up? | No dependencies. Restarting will not fix a database outage |
| `/v1/ready` | **Readiness** — can it serve? | One `SELECT 1`, **never cached**, 503 on failure. The healthcheck and `depends_on` use this |
| `/v1/health?deep=true` | **Diagnostics** — schema, policy, pins, incidents | Cached, and for humans |

A cached readiness answer is not a readiness answer, so `/v1/ready` never caches. And the
deep check now caches **only clean results**: caching a failure keeps reporting it after
it is fixed, and a stale success is exactly the shape that let a dead database look
healthy in the first place.

`/v1/ready` is auth-exempt, because the container probe cannot send a header — requiring
one would mark the container unhealthy forever the moment `API_TOKEN` was set, and
`depends_on: service_healthy` would never release the UI.

Seven tests, one of which is the kind this bundle has repeatedly needed: it parses the
**Dockerfile's** healthcheck URL and asserts the app serves that path without a token.
The container config and the application's exempt set are in different files and nothing
else checks that they agree.

### C4-05 closed (build 4.7.21)

`resume()` set `status=QUEUED, error=None` and *then* attempted submission. On
`QueueFull` it restored the status and not the rest, so a refused resume of a failed run
left the operator told it had failed and no longer why.

Investigating it showed the rollback was treating a symptom. Two prior conclusions had not
been carried through:

- **A resume is not new work.** C4-01 established that reclaim is exempt from admission
  control because it finishes something already accepted. A resume is the identical case
  and was still passing `new_work=True`, so it could be refused on backlog at all. It now
  cannot: when every worker is busy the run stays `QUEUED` and the drain collects it.
- **`run_job` already clears `error`** when a run actually starts. Clearing it on
  submission was redundant, and harmful in exactly the case the finding describes — a
  resume that then sat queued lost the diagnosis for no benefit.

So the failure mode largely disappears rather than being handled. What remains is a guard
for any other reason submission might fail: the status is restored, because a row claiming
to be queued with nothing scheduled is the failure the ordering exists to avoid.

The endpoint's `QueueFull` → 429 handler is **removed** rather than left in place, since a
resume can no longer raise it. An unreachable handler is the same defect this bundle has
found three times, and a test now asserts a resume does not raise when the backlog is past
its bound — which is what would catch a future change back.

### C4-06 closed (build 4.7.22)

Two problems, one cause: **admission and scheduling were the same function.**

`submit()` both decided whether to accept work and started it, so every caller created the
run's row first and the candidate then counted itself — `SIM_QUEUE_MAX=3` admitted 2.
The same conflation had already produced C4-01 and C4-05, where reclaim and resume were
refused for exceeding a bound they should never have been measured against. Every internal
caller was passing `new_work=False` to opt out; a flag that exists for one call site is a
sign the split belongs in the design.

They are now separate. `admit()` is asked **once, before the run exists**, so the count is
genuinely of other work. `submit()` only schedules and can never refuse. The `new_work`
flag is gone, and a refused run is never created rather than being created and then failed.

**The atomicity claim was wrong and is corrected rather than engineered around.** The
README said the backlog bound "holds across replicas". It does not: the count and the
insert are not one operation, so two replicas can each read a depth below the bound and
both accept. A Postgres advisory lock would close that, and is deliberately not used —
over-admitting by a few under a burst costs nothing, because the resource that can actually
be exhausted is worker threads, and that bound is exact.

The two guarantees are now stated in the code and reported on `/v1/health`:

| Bound | Guards | Enforcement |
|---|---|---|
| `SIM_WORKERS` | worker threads | **exact**, under a lock, per process |
| `SIM_QUEUE_MAX` | how much new work is accepted | **advisory**, not atomic across replicas |

Five tests, including one asserting the bound admits exactly the number it names, and one
asserting only the worker bound claims to be exact — an honesty check on the docstrings,
since the previous overclaim lived in prose.

### C4-07 closed (build 4.7.23)

C3-09 made `superseded_by` written. Nothing read it and nothing displayed it, so a figure
labelled `EVIDENCED_PUBLIC` rested on a chain no reader could follow — the links existed
and the second one was a dead end.

The chain is now traversable in one call, `GET /v1/outside-in/known-facts/{id}/provenance`:

```
figure on a V0 estimate
  -> quantity_sources.footprint.origin = EVIDENCED_PUBLIC
  -> corroborated_by_agent_run
  -> provider_record.provider_request_id
  -> quoted to the provider via /v1/integrity/attestation
```

A quantity sourced from a corroborated fact now carries that reference in the estimate
response, because **a figure claiming public evidence should ship the link that makes the
claim checkable, not merely the label.** The known-facts list exposes it, and the UI shows
the corroborating provider call beside the fact.

Three cases are reported rather than assumed: a corroboration with **no provider record**
says it rests on nothing checkable; a corroborating run that is **no longer present** says
the corroboration cannot be substantiated; and an uncorroborated fact says it would enter
as an attributable assumption. Each is a state where the `EVIDENCED_PUBLIC` label would
otherwise have looked identical to a sound one.

**One honesty correction went with it.** §0.1B describes a known fact being superseded by
the *public fact* that corroborated it. This build creates no public-fact record — that is
V1+ work. What is stored is the agent run that established the corroboration, which is the
closest real reference available, and the docstring now says so rather than letting a
column name imply a record that does not exist.

### C4-08 verified closed, C4-09 closed (build 4.7.24)

**C4-08** — `submit()` no longer performs a database query while holding the thread lock.
The C4-06 refactor removed it: admission moved to `admit()`, which runs before the lock is
taken. Verified by walking every `with _lock:` block; none does database work, and
`_next_waiting` queries first and takes the lock only to read the in-flight set. Closed by
a fix aimed at something else, and confirmed rather than assumed.

**C4-09** — if `cryptography` failed to install, `_CRYPTO` was `False`, `spki_pin()`
returned `None` and `cert_not_after()` returned `None`. Pinning silently reverted to the
pre-C3-03 behaviour: certificate hashes that break on every renewal, with no expiry
warning because the expiry could not be read either. `pin_status()` reported
`spki_supported: false` and nothing acted on it.

The four combinations now behave distinctly:

| Mode | `cryptography` | Behaviour |
|---|---|---|
| OBSERVE | present | starts, no warning |
| OBSERVE | **absent** | starts, `WARNING` on `/v1/health` and at startup — degraded, not dangerous |
| ENFORCE | present | starts, no warning |
| ENFORCE | **absent** | **refuses to start**, `ERROR` |

Enforcement without SPKI support is either broken immediately — a configured `sha256/`
pin can never match a `cert-sha256/` observation — or a scheduled outage at the next
rotation with no advance warning. Both are worse than not starting, and a warning in a log
nobody reads is what "silently" means. `TLS_ALLOW_CERT_ONLY_PINNING=true` is the
deliberate override for an operator who has accepted the exposure.

A mismatch when an SPKI pin is configured but cannot be computed now **names that as the
cause**, because otherwise it reads like an interception and sends the reader somewhere
useless.

### C4-08 and C4-09 closed (build 4.7.24)

**C4-08 was already fixed** by the C4-06 split. Moving admission out of `submit()` took
the database query with it, so the lock section is now pure in-memory work and
`_next_waiting` queries before acquiring. Two regression tests pin it: `threading.Lock` is
not reentrant, so a failed non-blocking acquire from the same thread proves the lock was
held during a query.

**C4-09: a missing library must not quietly undo a fix.** If `cryptography` fails to
install, `_CRYPTO` is `False`, only certificate hashes can be computed, and — because
nothing can parse a certificate — there is no expiry to warn on either. Under `ENFORCE`
that is precisely the pre-C3-03 behaviour: the pin breaks on the provider's next renewal
and the first sign is every LIVE call failing.

The service now refuses to start in that combination, and states the override in the
refusal:

| Configuration | Outcome |
|---|---|
| No `cryptography`, `OBSERVE` | Starts, warns. There is no outage to cause |
| No `cryptography`, `ENFORCE` | **Refuses to start** |
| No `cryptography`, `ENFORCE`, `TLS_PIN_ALLOW_CERT_ONLY=true` | Starts, warns twice. The trade is available, deliberately |
| `ENFORCE` with no pins configured | **Refuses** — every LIVE call would fail |

Refusing by default is right; refusing absolutely is not, so the override exists and is
noisy. This is the same judgement as the migration split in C3-04: a *structural* problem
refuses to start, because a service that starts and is quietly unprotected is worse than
one that does not.

Writing it surfaced a smaller instance of the recurring pattern — `spki_warning()` already
existed and described degraded support, and the new check described it again. One
description now, and a test asserting the two agree.

### Compose duplicate key (build 4.7.25)

`docker compose up` failed on the first real run:

```
line 61: mapping key "environment" already defined at line 58
```

The `ui` service had two `environment:` blocks — the second added when the shared secret
was wired in C2-04, without noticing the first.

**The check that should have caught it was giving a false pass.** Every "compose ok"
reported during development used PyYAML's default loader, which silently keeps the *last*
of a duplicated key. Compose's Go parser rejects duplicates outright, so the file
validated locally and failed there.

The consequence was worse than the false pass: taking the last block meant `API_BASE_URL`
was being **dropped**, and the only reason the UI would have worked is that the client's
fallback happens to be the same string.

`tests/test_compose.py` now loads the file with a duplicate-rejecting loader — what
Compose actually does — and checks the properties that were only ever conventions: the UI
knows where the API is, holds no database or provider credentials, has no network route to
the database, and both services receive the shared secret. A sweep also removed
`TLS_ALLOW_CERT_ONLY_PINNING`, set in compose and read by nothing; a test now fails on any
variable that is configured and unused.

These six tests run without Docker, so they execute in the sandbox as well as the
container.

### Dockerfile COPY path, and a pre-build check (build 4.7.26)

The second launch failure: `COPY api_service/tests ./tests` — the tests live at the bundle
root. The path had been wrong since the build context moved to the root in C2-04, and
nothing noticed because nothing had ever built the image.

Both real failures were the same shape, and neither was catchable from inside the
container: **the test suite cannot validate the build that produces the container.** A
broken Dockerfile means the image never builds, so the test that would have caught it
never runs.

`tests/check_build_config.py` runs on the **host, before the build**, with no third-party
imports and no Docker. It checks for duplicate compose keys — using an indentation scan
rather than PyYAML, whose default loader is the thing that missed the first failure — and
that every `COPY` source exists in its build context. Verified against both actual
failures, reintroduced into a copy of the tree:

```
docker-compose.yml:61 duplicate key 'environment' (first at line 59)
api_service/Dockerfile: COPY api_service/tests - no such path in the build context
```

`make up` now depends on `make check`, so the configuration is validated before Docker is
invoked. The same properties are also asserted in `tests/test_compose.py` for the
in-container run, but the host check is the one that can catch a failure that prevents the
container existing.

### F-01 to F-05 closed (build 4.8.0)

The fifth review swept the whole bundle rather than the newest delta. These five were its
findings with consequences.

**F-01 — §7.2E reconciliation was a table, an endpoint and no implementation.** The table
was written by nothing and read by nothing; the endpoint returned `EXPECTED_PENDING`,
which reads as *the job has not run yet* when there was no job. §7.2C names this the
control of last resort — the one that catches fabrication the application cannot detect
about itself.

Writing an adapter against provider usage APIs I cannot reach would produce a
control-shaped object that has never run, so `domain/reconciliation.py` implements
everything that does not require the provider call: the comparison, tolerance by adapter
tier (A 2%, B 5%), the variance record, the P2 incident on breach, and the promotion block
§7.2C requires. Figures are submitted from the provider's own console — which is the
out-of-band channel the control depends on, and **stronger** than an API call from this
host, since a compromised host could fake the latter. `UsageSource` has no
implementations and `PROVIDER_API` is refused with a 501 rather than stubbed. The endpoint
now reports never-reconciled distinctly from reconciled-and-passing.

**F-02 — 24 of 36 routes returned 500 for a wrong identifier.** Nine `.one()` calls raised
`NoResultFound`, which FastAPI renders as a server fault. A single `LookupError → 404`
handler at the boundary plus hardened resolvers removes the class; the only `.one()` calls
left are internal, on identifiers just created.

**F-03 — six routes took a raw body.** `Body(...)` gives a `KeyError` and a 500 on a
malformed payload; one route indexed a caller-supplied list directly. All six now have
models and return a 422 naming the field.

**F-04 — the interface had zero tests.** 864 lines, and C2-04 (the API enforcing a header
the UI never sent) was exactly this gap. `tests/test_interface.py` covers the client's
token handling and misconfiguration probe, and asserts structural rules: no page reaches
past the API, case-scoped pages require a case, and every page handles the error shape the
client returns. **That last rule found a real defect** — page 7 treated five API failures
as empty results, so an unreachable API rendered as "no runs recorded" on the integrity
page, where the difference between *none* and *could not ask* is the entire point.

**F-05 — `preflight.py` and `entity_resolution.py` had no tests.** Pre-flight is the gate
whose failure mode is silent permissiveness; entity resolution exists to refuse
auto-selection. Both now have tests, including that a run cannot begin while a BLOCK is
open or without a named acknowledgement.

296 tests, up from 267.

Lows closed: non-root containers, healthchecks with `service_healthy` gating, optional
`API_TOKEN`, provider error bodies no longer echoed, `engagement_case` rename, lifespan
handler, PARTIAL penalty applies below the Indicative floor.

## Verification status — read this

I built this without network access and **could not run `docker compose up`**. What was
verified and what wasn't:

| Check | Status |
|---|---|
| Every Python file compiles | Verified (39 files) |
| 71 pure-logic tests pass | Verified (third-party stubbed) |
| 20 DB control tests | **Not executed** — SQLAlchemy unavailable in the build sandbox; run `make test` |
| 11 migration tests | **Not executed** — same reason; logic verified step-for-step against raw `sqlite3` |
| 12 auth tests | **Not executed** — needs FastAPI TestClient; run `make test` |
| 31 transport tests | **Not executed** — needs httpx; pin state machine and renewal survival verified with stdlib |
| 10 wiring tests | **Not executed** — needs TestClient; assert startup invokes what it claims |
| No test asserts on source text | Verified — swept all five test modules |
| Both images resolve one contract definition | Verified — api and ui layouts simulated |
| Legacy upgrade preserves cases, runs, thresholds | Verified against raw `sqlite3` |
| Both refusal paths fire | Verified — newer schema, half-applied rename |
| `assert_disposable` refuses non-SQLite engines | Verified — both branches exercised |
| `setdefault` vs assignment behaviour | Verified — reproduced the original no-op |
| SQLite attached-schema fixture works | Verified against raw `sqlite3`, including cross-schema UNIQUE enforcement |
| Memory bound: 10 × 50k sites | Verified — 1.5 MB peak, was unbounded |
| Simulation determinism and seed sensitivity | Verified |
| Coverage gate across all four branches | Verified |
| Confidence ceiling monotonicity | Verified |
| `docker compose` YAML parses | Verified |
| Image builds, container startup, DB migration | **Not verified** |
| Live provider calls end to end | **Not verified** |
| Streamlit page rendering | **Not verified** |

Expect to fix one or two things on first run — most likely a pinned dependency version
or a Postgres startup race. `make logs` first.

## Network posture

`docker-compose.yml` puts Postgres on an `internal: true` network with no external
route, and attaches Streamlit only to the frontend network, so **the UI container has no
route to the database** and holds no DB or provider credentials. This is the spec 2.1
boundary.

The residual gap: Streamlit still has general outbound internet via the frontend bridge.
Compose can't express "no egress except the API" while still publishing a port. In a real
deployment that's an egress firewall or network policy, and the spec's no-egress
requirement is not fully met by this file alone.

## Layout

```
docker-compose.yml          three services, two networks
db/init/001_schemas.sql     knowledge zones as schemas (2.2)
api_service/app/
  config.py                 server-side only; environment resolution
  db.py                     all tables in one metadata definition
  seed.py                   governed thresholds — no material value is a code constant
  domain/
    money.py                Decimal; cost increases stay negative
    entity_resolution.py    0.1A
    known_facts.py          0.1B
    preflight.py            0.1C
    dispositions.py         0.3A
    simulation.py           0.3B — seeded, hashed, reproducible
    coverage.py             0.3C
    confidence.py           0.6A + 13.2
    estimate.py             12.1
  llm/
    gateway.py              where the anti-fake controls live
    providers/              real HTTP adapters, no stub path
analyst_ui/streamlit_app/   HTTP-only client, 7 pages
tests/test_integrity.py     26 tests from spec section 16
```

## How the simulated share is derived

Earlier drafts hardcoded this. It is now computed, and the derivation is the
interesting part.

A component counts as simulated when the **simulation decided how many there are** —
not when its unit price came from a prior, which is true of every Stage 0 component.
So the question is which quantities the simulation actually determines:

| Component | Quantity driver | Origin |
|---|---|---|
| L0 primary access | one per site, from the supplied footprint | inherits `footprint_origin` |
| L0 backup access | **the seeded draw against the resilience prior** | `SIMULATED` |
| L2 overlay | sites | inherits `footprint_origin` |
| L4 SSE licences | users | inherits `users_origin` |
| OPS | sites | inherits `footprint_origin` |

Only the backup layer is the simulation's decision. The primary circuit count follows
deterministically from the footprint you typed in — run the simulation twice with
different seeds and you will see primary fixed while backup moves. Attributing the whole
underlay to `SIMULATED` would overstate what the simulation contributed and push
confidence down for the wrong reason.

For a 122-site estate with 55% dual access and 5,000 users, the derived share is about
**4.8%** — which trips no ceiling at all. The old hardcoded 0.70 forced the 0.50 ceiling
and pinned every V0 to *Indicative* regardless of evidence quality.

Two consequences worth knowing:

- **Share is computed per scenario, on the target rather than the baseline.** Scenario C
  strips L2 and L4, which are not simulated, so its target is proportionally *more*
  simulated than scenario A's. The published ceiling uses the highest scenario share,
  since that is the most simulation-dependent target on offer.
- **Setting `footprint_origin` to `SIMULATED` propagates correctly** to primary access,
  overlay and operations, and the share jumps above 50%. That is the path for a future
  build where the footprint is inferred rather than supplied.

This fix also required levers to apply **per cost layer** rather than to the whole
baseline. `reference.savings_lever.cost_layers` was already in the data and was being
ignored; an SSE consolidation lever was reducing access spend. That was a real
overstatement of savings, independent of the provenance work.

## Known gaps worth naming

- **The DB control tests have not been executed.** They are written and the fixture
  mechanism is proven, but SQLAlchemy was unavailable in the environment that built
  this. `make test` is now safe to run first — that was not true before C2-01 was fixed.
- **Three findings from the second audit remain open**, all medium or low: C2-09
  (`provider_request_id` is stored but no control requires it), C2-10 (the liveness
  timestamp and the transport pin are not independent — anyone controlling the endpoint
  returns a plausible `Date`, so certificate pinning is what would separate them), and
  C2-11 (simulation is synchronous while §16.1 claims it is asynchronous and cancellable).
  See `Workbench_Red_Team_Audit_2.md`.
- **Reconciliation is one-sided.** Claimed usage is aggregated from `audit.llm_run`;
  the provider-side figure needs a scheduled job per adapter. Status reads
  `EXPECTED_PENDING`, which is deliberately distinct from a pass.
- **Auth is opt-in and coarse.** Setting `API_TOKEN` now works end to end, but it is a
  single shared secret: there is still no per-user identity, no authorisation on
  `case_id`, and no audit of who acted. It ships open by default.
- **`created_by` is typed, not authenticated.** Named confirmation is only as strong as
  the identity behind it; wire OIDC at the gateway before this means anything.
- **MOCK, REPLAY and DETERMINISTIC_ONLY have no executors.** The registry advertises
  only LIVE, and the other modes are rejected before a run row exists. The spec requires
  all four; this build implements one and says so rather than pretending.
- **Reference priors are indicative,** not sourced. Replace `seed.py` before any real use.
