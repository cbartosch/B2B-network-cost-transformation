# Red-team audit #2 — Network Cost Transformation Workbench, build 4.7.1

**Target:** the remediated bundle (61 files, 39 Python modules)
**Method:** adversarial, against the *new* code. The failure mode of a re-audit is
confirming that the previous fixes landed; the objective here was to break what the
fixes introduced.
**Result:** 1 critical, 4 high, 6 medium, 5 low. **Two are regressions — defects the
remediation created, not ones it missed.**

---

## Verdict

The three original criticals are genuinely closed. The liveness proof now rests on
provider-issued evidence, the transport is pinned, and confidence components are derived.
Those fixes hold under attack.

But the remediation introduced a defect worse than one it fixed, and shipped a test
harness that destroys data. Specifically:

- **`make test` drops every table in the running Postgres database.** The command the
  README tells you to run first is the most destructive thing in the bundle.
- **The coverage fix replaced a caller-controlled bypass with a silent one.** Scope that
  cannot be priced anywhere is now sized at zero, so the exact circuits you have no
  prior for are invisible to the denominator that is supposed to count them against you.

Neither was reachable in 4.7.0. Both were created by the fixes.

---

## CRITICAL

### C2-01 — `make test` destroys the production database

`tests/conftest.py`:

```python
os.environ.setdefault("DATABASE_URL", "sqlite://")
```

`setdefault` is a no-op when the variable already exists — and `docker-compose.yml`
sets `DATABASE_URL` to Postgres on the `api` container, which is where `make test`
executes. So `db.engine` binds to the live database and the session fixture runs:

```python
db.metadata.drop_all(db.engine)
db.metadata.create_all(db.engine)
```

against it, once per test, seventeen times. Every case, known fact, estimate snapshot,
agent run and provider record is destroyed, silently, by the command the README
recommends running first.

Verified: with `DATABASE_URL` pre-set to the Postgres URL, `setdefault` leaves it
unchanged.

**Fix:** assign unconditionally rather than defaulting, and refuse to run if the URL is
not SQLite:

```python
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["WORKBENCH_ENVIRONMENT"] = "TEST"
...
assert db.engine.url.get_backend_name() == "sqlite", \
    "control tests must never bind to a non-SQLite database"
```

The assertion matters more than the assignment: it is the thing that survives someone
later "improving" the fixture.

---

## HIGH

### C2-02 — Unpriced scope with no prior anywhere is sized at zero (regression)

`coverage._fallback_rates` builds a cross-country median per product so unpriced scope
can be sized into the denominator. If a product has **no approved prior in any in-scope
country**, there is no median, `annual_value` becomes `"0.00"`, and `rate_basis` is
`UNSIZED`.

Demonstrated — an estate that is DIA in GB and MPLS in Brazil and India, with no MPLS
prior anywhere:

| Row | Priced | Basis | Value |
|---|---|---|---|
| GB / DIA (800) | yes | APPROVED_PRIOR | 4,992,000 |
| BR / MPLS (300) | no | UNSIZED | **0.00** |
| IN / MPLS (200) | no | UNSIZED | **0.00** |

Result: **`COMPLETE`, coverage 1.000, no material-country breach.** Five hundred circuits
in two countries vanish from the gate that exists to catch exactly this.

The material-country floor cannot help either: it skips any country where
`c_total == 0`, which is precisely the wholly-unsized case.

This is worse than the bypass it replaced. In 4.7.0 the caller had to actively omit
markets; here the system omits them on its own, and the output says `COMPLETE`.

**Fix:** an unsizable row is not zero-valued scope, it is scope of unknown size. Size it
by circuit count against a global default rate, or — better — treat any `UNSIZED` row as
an automatic `PARTIAL` with the product named, and remove the `c_total == 0` skip so a
wholly-unsized country always breaches.

### C2-03 — No migration path; upgrading a 4.7.0 volume corrupts silently

There is no Alembic, and `metadata.create_all()` creates missing *tables* only — it never
adds columns. Against an existing `db_data` volume, 4.7.1:

- adds five columns to `audit.llm_run` → every `INSERT` fails at runtime, so **no LIVE
  run can record its proof**
- adds `reference.lever.earliest_supported_stage` → seed insert fails
- renames `engagement.case` → `engagement_case`, so a new empty table is created and
  **every existing case is orphaned and invisible**
- `seed(force=False)` sees thresholds present and skips, so `platform_unit_cost` stays
  empty and overlay and SSE are **permanently unpriced**

The last one is the nastiest: it produces a working system that silently omits ~40% of
TCO. `make reset` fixes everything by destroying the volume, but nothing tells you that
is required.

**Fix:** add Alembic, or at minimum a startup schema-version check that refuses to boot
against an older schema with a clear message pointing at `make reset`.

### C2-04 — The `API_TOKEN` feature is unusable as shipped

`main.py` requires `X-API-Token` on every route bar `/v1/health` when `API_TOKEN` is set.
`analyst_ui/streamlit_app/api_client.py` sends **no headers at all**. `docker-compose.yml`
passes `API_TOKEN` into the `ui` container, where nothing reads it.

Setting the variable therefore breaks the entire interface with 401s. The only
authentication control in the bundle cannot be switched on.

**Fix:** read `API_TOKEN` in `api_client._req` and attach the header. Also replace
`!=` with `secrets.compare_digest` — the current comparison is not constant-time.

### C2-05 — The two new transport tests cannot fail

I deleted a source-grep test as theatre in the last round and then added two more.

```python
src = inspect.getsource(_transport.client)
assert "trust_env" in src and "False" in src
```

Verified: this assertion passes just as happily on `trust_env=True, verify=True,
follow_redirects=False`, because `"False"` appears elsewhere in the same line. The test
is incapable of detecting the defect it names.

`test_no_adapter_builds_a_raw_httpx_client` is narrower and slightly better, but still a
string search — `getattr(httpx, "Client")(...)` evades it.

**Fix:** assert on the constructed object, not the source. `c = _transport.client(1.0);
assert c.trust_env is False`. If httpx does not expose it, set a bogus `HTTPS_PROXY` and
assert the client has no proxy mounts.

---

## MEDIUM

### C2-06 — Confidence weights and stage ceilings are code constants
`confidence.WEIGHTS`, `STAGE_CEILINGS`, `LEVER_STAGE_WEIGHT` and `SIMULATED_BANDS` are
module-level Python constants, and `derive_components` hardcodes `0.40/0.35/0.25` and
`0.55/0.45` inline. This is the same defect class as M-01 in the first audit — material
priors living only in code, which spec §18.1 forbids — moved rather than fixed. Unit
costs were relocated to reference data; the weights that combine them were not.

### C2-07 — `ANALYST_ASSERTED_PRIOR` is overloaded, and the asserted ceiling now always fires
The origin is used for two different things: a *registered known fact* under §0.1B, and
*the footprint the analyst typed into the form*. On a default run the typed footprint
drives primary access, overlay, SSE and operations, so measured **asserted share = 0.96**
against a 0.25 trigger. The `asserted_baseline_confidence_ceiling` of 0.50 therefore
applies to every estimate the system will ever produce, which makes it a constant rather
than a control.

**Fix:** separate the origins — `ANALYST_ENTERED_SCOPE` for form input,
`ANALYST_ASSERTED_PRIOR` for registered known facts — and trigger the ceiling on the
latter only.

### C2-08 — Registered known facts no longer affect confidence at all (regression)
Making asserted share value-weighted (M-07) moved it onto component
`quantity_origin`. `known_facts.uncorroborated_count()` is computed, returned in the API
response, and consumed by nothing. Registering ten uncorroborated known facts now changes
the published confidence by zero. Before the fix it did — crudely, but it did.

### C2-09 — `provider_request_id` is decorative
The README presents the transport-issued request identifier as part of the liveness
proof. It is stored, nullable, and never checked: no control requires it to be present,
unique or consistent with the body identifier. Claimed as evidence, used as none.

### C2-10 — The liveness proof and the transport pin are not independent
C-01's fix bounds the skew between the provider's clock and ours. Anyone controlling the
endpoint returns `Date: <now>`, which is trivially inside tolerance. The timestamp
control therefore has no strength of its own — it is entirely dependent on C-02's
transport pinning holding. That is defence in depth and worth having, but the README
describes it as though a forged response must independently defeat both, and it must not.

Certificate pinning would make them independent. Absent that, an operator who can install
a CA in the container image defeats both at once.

### C2-11 — Simulation is synchronous; §16.1 claims otherwise
`run_simulation` is a plain synchronous endpoint. At the permitted bounds
(`ensemble_size=100`, 50,000 sites) it occupies a worker for roughly a minute — measured
5.4s for 10 × 50k. The spec's §16.1 target says simulation is "asynchronous, cancellable
and resumable"; it is none of those. Bounded is not the same as non-blocking.

---

## LOW

| # | Finding |
|---|---|
| C2-12 | `X-API-Token` compared with `!=` rather than `secrets.compare_digest` — non-constant-time |
| C2-13 | `prior_coverage` in the endpoint is pair-count-weighted while every other share is value-weighted |
| C2-14 | An empty `lever_stage_mix` yields realization 0, which caps overall confidence at 0.15 through the §13.2 headroom rule — a cliff rather than a curve |
| C2-15 | `_transport.EGRESS_PROXY` is read at import, so changing it requires a restart; not wrong, but undocumented |
| C2-16 | A caching proxy or a provider returning a stale `Date` header will fail the skew check and mark a genuine call as fabricated — a false-positive path with no operator guidance |

---

## What held up under attack

- **C-01, C-02 and C-03 are genuinely closed.** The forgery from audit #1 no longer
  works: a fabricated `ProviderCall` with a locally generated timestamp is rejected, and
  a response with no provider timestamp fails the run.
- **The coverage denominator is no longer caller-controlled.** The declared figure is
  reconciled and reported; the bypass test reproduces the original attack and passes.
- **Per-(country, product) assessment works** — an all-MPLS country holding only a
  broadband prior is now `REFUSED`, where it previously passed.
- **`seed()` is non-destructive** and the analyst-edit preservation test covers it.
- **Mode rejection leaves no orphan run**, verified before and after the row would be
  written.
- **Memory is bounded** — 10 × 50k sites peaks at 1.5 MB against previously unbounded.
- **Simulation determinism survived** the primary/backup refactor and the sampling
  change.
- **45 pure-logic tests pass**, including the ones that reproduce the audit-#1 attacks.

---

## Remediation order

**Before anyone runs `make test`:** C2-01. It is one line, and the current state
destroys data on the first command the README recommends.

**Before any figure is quoted:** C2-02. A gate that reports `COMPLETE` on an estate it
cannot price is worse than no gate, because it is believed.

**Before a second deployment exists:** C2-03. The first upgrade is the one that corrupts.

**Before the integrity story is presented:** C2-04, C2-05, C2-09, C2-10 — three of these
are claims in the README that the code does not support.

The rest is ordinary hardening.

---

## A note on the pattern

Two of the four highs are regressions, and two of the mediums (C2-06, C2-08) are the
previous round's fixes relocating a defect rather than removing it. The lesson is not
that the fixes were careless — they were tested — but that **the tests were written by
whoever wrote the fix, against the failure they had just been shown**. C2-01 and C2-05
in particular are defects *in the test harness itself*, which is the one place nobody
was auditing.
