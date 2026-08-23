# Red-team audit — Network Workbench Docker bundle

**Target:** `network-workbench-docker-bundle.zip` (35 Python modules, 3 services)
**Method:** adversarial. Every claim made in the README was treated as a hypothesis to
falsify, starting with the ones stated most confidently.
**Result:** 15 attacks attempted, **13 landed**. 3 critical, 8 high, 6 medium.

---

## Verdict

The bundle divides cleanly, and not in a flattering way.

**The deterministic domain layer is sound.** `money.py`, `simulation.py`,
`confidence.py`, `coverage.py`, `dispositions.py` and `estimate.py` are pure functions
that do what they say. Determinism holds, ceilings compose downward, the coverage ladder
behaves across all four branches, provenance propagates correctly. These survived
attack.

**The integration layer is where every defect lives.** The endpoint that assembles those
functions into a published V0 contains five hardcoded values, three ineffective gates and
one tautological check. I fixed `simulated_share = 0.70` in the previous turn and
described it as "the real gap." It was not the gap; it was one instance of the gap.
Within twenty lines of the line I fixed there were four more hardcoded inputs, including
**all three confidence components**.

**The headline claim is roughly 60% true.** "Faking has to be structurally impossible"
holds for everything backed by provider-attested data and fails for one control I
described specifically and incorrectly.

---

## CRITICAL

### R-01 — The liveness timestamp check is tautological
`app/llm/providers/*.py`, `gateway._verify_liveness`

I claimed a LIVE run requires "a `provider_request_at` inside the run's own window."
The adapter sets that field itself:

```python
request_at = datetime.now(timezone.utc)     # our clock
resp = client.post(ENDPOINT, ...)
```

`_verify_liveness` then checks our clock against our own run window. **The assertion
cannot fail.** No provider-attested time is ever read, though both providers return a
`Date` response header and a request-id header.

Of the three elements of the liveness proof, two are provider-attested and real
(`provider_response_id`, token counts). The third is decorative. The README states it as
though all three carry equal weight.

*Fix:* read the `Date` response header and compare that to the run window; treat a
missing header as a liveness failure, not a pass.

### R-02 — The entire confidence model is a constant
`routers/api.py`

```python
conf = confidence.compute(current_baseline="0.42", target_cost="0.68",
                          realization="0.35", ...)
```

Coverage, corroboration state, disposition counts, unpriced scope, evidence quality —
none of it feeds the score. The 0.6A ceiling machinery is correct and tested, and it caps
a literal. Every V0 for every client returns the same three components.

This is the same defect I claimed to have fixed, one line below the line I fixed.

### R-03 — The rights gate does not gate anything
`domain/known_facts.py::asserted_share`

Pre-flight BLOCKs on an un-rights-cleared `PRIOR_ENGAGEMENT` fact, and the README says
such a fact "cannot influence an estimate." The query that computes its influence:

```python
db.known_fact.c.corroboration_state.in_(["PENDING", "UNCORROBORATED"])
```

`rights_cleared` is **not in the filter**. An uncleared fact — one that may carry another
client's confidential information — moves `asserted_share`, which moves the published
confidence. The advertised control is absent at the only place it matters.

---

## HIGH

### R-04 — The material-country floor is defeated by typing a smaller number
`routers/api.py`, UI page 6

`spend_by_country` is a free-text field in the analyst's own data editor. Verified:

| Input | Result |
|---|---|
| BR = 1,500,000 (honest) | `PARTIAL`, breach on BR |
| BR = 1 | `COMPLETE`, no breach |

The gate designed to catch an unpriced major market is bypassed by understating that
market. My own spec §0.3C.1 requires the spend distribution to be **derived** from an
initial footprint and archetype pass and then pinned. I implemented it as user input.

### R-05 — The layer-coverage test can never fail
`routers/api.py`: `layers_priced={"L0", "L2", "L4", "OPS"}` — a hardcoded full set,
passed regardless of which priors exist. `v0_product_coverage_min` is dead.

### R-06 — `asserted_share` denominator is invented
`material_input_count=24` is a literal. The result is (uncorroborated fact count) / 24 —
a share of nothing. Seven registered facts trip the 0.25 trigger and cap baseline
confidence at 0.50, so **confidence is degradable by spamming trivial facts**.

### R-07 — Pre-flight is a stale snapshot (TOCTOU)
`domain/preflight.py::assert_clear_to_run` reads the most recent stored report and
re-validates nothing. Working bypass:

1. Run pre-flight with no known facts → PASS. Acknowledge.
2. Register a `PRIOR_ENGAGEMENT` fact, leave rights uncleared.
3. Run the V0 — the gate reads the stale clean report.

Chained with R-03, this is a complete bypass of the rights control built from two
independent defects, neither of which looks serious alone.

### R-08 — Savings ranges manufacture negative savings
`money.Range.__sub__` pairs `current.low` against `target.high` — two different states of
the world. Verified on a pure-saving lever:

```
current  {low 100, base 200, high 300}
target   {low  82, base 176, high 282}
savings  {low -182, base 24, high 218}      <-- a cost-only lever "might cost 182 more"
```

Spec §12.1 wants negative deltas preserved for *real* cost increases. This fabricates
them, and the wider the input range the worse it gets. The bounds need to be computed
within a consistent world-state, not cross-paired.

### R-09 — No authentication, authorization or tenancy
Every endpoint is open on port 8000. `/v1/outside-in/cases` returns every case to
anyone. `confirmed_by`, `acknowledged_by` and `asserted_by` are free-text strings, so the
named-confirmation trail that §0.1A is built on is **unauthenticated self-assertion**.
Spec §4.3 requires RLS; there is none. I disclosed "no auth" in the README but understated
what it costs: it makes the entire audit trail decorative.

### R-10 — MOCK and REPLAY are advertised but unimplemented
`registry.AGENTS` lists `["LIVE", "MOCK", "REPLAY"]` for every agent.
`gateway.execute()` raises `ModeNotPermitted` for anything but LIVE. A MOCK run is
therefore **created, set to QUEUED, and abandoned** — it never executes and never fails.
No REPLAY path exists at all, and the simulation replay endpoint I wrote into spec §6.1
was never built.

### R-11 — Reference data and its version history are destroyed on every restart
`main.py` calls `seed()` on startup; `seed()` does `delete(threshold)` then reinserts at
`version=1`. Any operator change to a governed threshold is silently wiped on restart,
and the version/owner/approval history §0.2E requires is fiction.

---

## MEDIUM

### R-12 — The provenance taxonomy is unenforced at the database
`execution_mode`, `environment`, `status`, `quantity_origin` are bare `String` columns
with **no CHECK constraints**. The enums exist only in Python. Nothing at the storage
layer prevents `quantity_origin='EVIDENCED'` on a simulated component — which is the
precise laundering §7.2D prohibits. Response-id uniqueness *is* a real constraint; that
claim holds. The rest of the taxonomy does not.

### R-13 — Model output is coerced without a schema
`entity_resolution.py`: `float(c.get("match_score") or 0)` and `(c.get("domicile") or "")[:2]`.
Verified crashes (HTTP 500) on `match_score="high"`, `match_score=[0.9]`,
`domicile=44`. `parse_json_strict` validates that the reply is JSON, never that it has the
expected shape — despite §7.3 requiring structured-output validation.

### R-14 — Money is typed `float` at the API boundary
`EstimateIn.ops_cost_per_site_base: float`, and the endpoint computes `ops * 0.8` /
`ops * 1.3` in float before Decimal conversion. Intermittent, which is worse than
consistent: `900.0` is exact, `1234.56 * 1.3 = 1604.9279999999999` is not. Passes casual
testing, corrupts specific values.

### R-15 — Dead columns
`produced_without_llm` is never set true. `DEGRADED` is never set. Both are controls I
wrote into spec §7.2C and then failed to implement — the same spec-versus-code gap I
flagged as a defect when auditing v4.6.

### R-16 — No prompt fencing or input cap
`name_hint` and `fact.subject` are interpolated straight into prompts with no length cap
and no data-position fencing, against §7.3. Injection impact is bounded by mandatory human
confirmation, but an unbounded `name_hint` is an unmetered token-spend vector.

### R-17 — Simulation replay endpoint absent
Specified in §6.1, never built. `output_hash` is stored but never verified on rerun, so
the determinism guarantee is untested at runtime.

---

## The test suite is the worst finding

37 green tests created more confidence than they earned.

### R-18 — Two tests are vacuous
```python
assert "EVIDENCED" not in simulation.output_hash(_sim(7))
```
A SHA-256 hexdigest contains only `[0-9a-f]`. This passes for every possible input.

```python
for smell in ("FAKE_RESPONSE", "STUB_TEXT", "canned_response", "sample_output"):
    assert smell not in src
```
A grep for four identifier names I invented. Any real stub would be named something
else. This is a comment with an `assert` around it.

### R-19 — Zero coverage of every stateful control

| Control | Tested |
|---|---|
| `gateway.execute` — the real LIVE path | **no** |
| MOCK rejection at run creation | **no** |
| Proof-before-SUCCEEDED | **no** |
| Response-id uniqueness constraint | **no** |
| `preflight.assert_clear_to_run` | **no** |
| The estimate endpoint end to end | **no** |

The suite tests pure functions, because pure functions run without a database. **Not one
test exercises an anti-fake control end to end.** And R-01 is the sharpest case: the
timestamp test passes, while the property it appears to protect does not exist in the
running system. A green test guarding an absent property is worse than no test.

---

## What survived

Recorded so it is not re-litigated:

- **No stub path in the adapters.** Confirmed by reading both files: one code path each,
  and it is an HTTPS call.
- **Fail-closed with no key.** `_fail()` then raise; no fallback.
- **Response-id uniqueness is a genuine database constraint**, not a code check.
- **`succeed()` refuses SUCCEEDED without a persisted provider row.**
- **Environment is server-resolved** and never read from a request.
- **Simulation determinism** — byte-identical on rerun, seed-sensitive, order-independent.
- **Confidence ceilings** — monotonic, compose downward, cannot inflate.
- **Coverage ladder** — correct across COMPLETE / PARTIAL / REFUSED / country-floor.
- **Provenance decomposition** — primary inherits footprint origin, only backup is
  `SIMULATED`; propagation verified.
- **No SQL injection** — SQLAlchemy Core with bound parameters throughout.
- **Compose network posture** — Postgres on an `internal: true` network; the UI container
  genuinely has no route to it.

---

## Not audited

No runtime was available: no Docker, no database, no network. Therefore **unaudited**:
concurrency and transaction isolation, whether constraints are actually created by
`create_all`, container build and startup, real provider behaviour and error shapes,
Streamlit rendering, and any timing or race condition.

---

## Recommended order

1. **R-02, R-03, R-06** — one file, `routers/api.py` plus one query. These three make
   the published confidence meaningless and the rights gate ineffective.
2. **R-01** — read the provider `Date` header, or delete the claim from the README.
   Leaving it as-is is the only finding here that is actively misleading.
3. **R-18, R-19** — delete the two vacuous tests and add database-backed tests for the
   five stateful controls. Until then the suite's green is not evidence.
4. **R-04, R-05, R-08** — derive spend and priced layers; fix the range pairing.
5. **R-07, R-11, R-12** — re-validate at the gate rather than trusting the snapshot;
   stop reseeding on startup; add CHECK constraints.
6. **R-09** — before this leaves a laptop.

The structural lesson: I fixed one hardcoded value and called it "the real gap." The
class of defect — an untested integration layer assembling well-tested pure functions
with invented constants — was the gap, and it is still there.
