# Red-team audit #4 — Network Cost Transformation Workbench, build 4.7.16

**Target:** the bundle after all three prior audits were closed (72 files, 49 Python
modules, 200 tests)
**Method:** adversarial, against the last round's fixes and — deliberately — against the
places where two fixes *meet*. Audit #3 found that the newest code carries the risk;
this round assumed the newest **interactions** do.
**Result:** 2 high, 4 medium, 4 low. **No criticals.**

---

## Verdict

That assumption paid. **The two most serious findings are fixes that break each other or
themselves**, and neither is visible when either change is reviewed alone:

- **C3-11 disabled C3-01.** Making the queue bound global means the recovery function sets
  every orphan to `QUEUED` and is then refused by its own bound. Measured: 40 interrupted
  runs, `SIM_QUEUE_MAX=32` → **0 reclaimed, 40 deferred**. The recovery path fixed two
  rounds ago now recovers nothing whenever there is a backlog, which is the only situation
  it exists for.
- **C3-02's fix contains its own bypass.** `resolve_quantity_source(..., value_used=None,
  tolerance=0.10)` — omit the argument and the agreement check is skipped entirely and the
  fact is credited unconditionally, and the tolerance I moved to governed reference data
  has a code constant sitting in the signature behind it.

Everything the earlier audits confirmed still holds: the audit-1 forgery fails, the
audit-2 coverage bypass fails, the harness is safe, SPKI pins survive renewal, duplicate
legacy data no longer crash-loops. The integrity spine is not the problem. Composition is.

---

## HIGH

### C4-01 — The global queue bound defeats interrupted-run recovery

`reclaim_interrupted()` walks orphaned rows, setting each to `QUEUED` and submitting it.
`queue_depth()` counts `QUEUED + RUNNING + CANCELLING` rows. At startup every orphan is
already in one of those states, so the depth is the full backlog before the first submit.

Measured with 40 orphans and the default `SIM_QUEUE_MAX=32`:

```
requeued 0, deferred 40
```

Each fix is correct in isolation. C3-11 was right that an in-memory bound is per-replica
and forgets a restart. C3-01 was right that orphans need reclaiming. Together they produce
a recovery that cannot run precisely when there is something to recover — a small backlog
is fine, and a large one, which is the case that matters, is not.

**Fix:** reclaim should not be subject to the admission bound at all — it is not new work,
it is work already admitted. Either exclude the run being reclaimed from the depth count,
submit through a path that bypasses admission control, or process reclaim in batches of
`SIM_QUEUE_MAX` as workers free up. Whichever, there must be a test with a backlog larger
than the bound; the current test uses one orphan.

### C4-02 — The C3-02 agreement check can be skipped by omitting an argument

```python
def resolve_quantity_source(session, *, case_id, known_fact_id, driver,
                            value_used=None, tolerance=0.10) -> dict:
```

Two defects in one signature:

- **`value_used=None` skips the check.** The body only compares `if value_used:`. A caller
  that omits it credits the fact unconditionally — exactly the behaviour C3-02 was raised
  to remove. The wired endpoint does pass it, so the defect is latent rather than live,
  but the guard is opt-in and the opt-out is the default.
- **`tolerance=0.10` is a code constant.** It was moved to
  `known_fact_policy.agreement_tolerance` under C2-06 and then given a default here, which
  is the same defect with a longer path: a caller omitting the argument silently uses a
  number nobody approved.

**Fix:** make both required keyword arguments. A caller that cannot supply the figure the
run uses has no business crediting a fact as its source.

---

## MEDIUM

### C4-03 — The duplicate release groups by provider but releases across providers

Migration v9 calls `_release_duplicate_identifiers(..., scope_column="provider")`. The
scope reaches the `GROUP BY` and stops there — the row-fetch is unscoped:

```sql
SELECT * FROM audit.llm_run WHERE provider_response_id = :v ORDER BY created_at
```

Demonstrated with three rows sharing an identifier, two from Anthropic and one from
OpenAI:

| Row | Provider | Outcome |
|---|---|---|
| `a1` | anthropic | kept |
| `o1` | **openai** | **released and quarantined** — legitimate, different provider |
| `a2` | anthropic | released and quarantined — correct |

So a migration written to *stop* treating a cross-provider collision as a replay does
exactly that while running. Nothing is lost — the quarantine preserves the row — but a
legitimate identifier is stripped and an incident raised against an innocent call.

**Fix:** carry `scope_column` into the row-fetch and the release predicate, not just the
grouping.

### C4-04 — Making `/v1/health` cheap removed the signal it existed to give

C3-08 was correct that a schema query plus two full policy validations every ten seconds
is waste. The fix made the default shallow — and the container healthcheck still polls the
default, so **it no longer touches the database at all**. An API whose database is
unreachable now reports healthy, and `ui depends_on api: service_healthy` will start the
interface against an API that cannot serve a single request.

The cost was fixed by deleting the signal. Since the deep path is now cached for 30
seconds, pointing the healthcheck at `?deep=true` costs one check per TTL and restores
readiness detection.

**Fix:** healthcheck hits `/v1/health?deep=true`; keep the shallow default for the UI's
frequent polling.

### C4-05 — `resume()` restores the status but not the rest of the row

```python
_set(session, run_id, cancel_requested=False, status=QUEUED, error=None)
try:
    submit(run_id)
except QueueFull:
    _set(session, run_id, status=previous)   # error and cancel_requested not restored
```

A refused resume of a `FAILED` run leaves the status correct and the diagnosis gone —
`error` was cleared on the way in and is not put back. The operator is told the run failed
and no longer why.

### C4-06 — `queue_depth()` counts the run it is admitting

Every caller sets or inserts the row as `QUEUED` *before* calling `submit()`, so the depth
includes the candidate. `SIM_QUEUE_MAX=32` therefore admits 31 concurrent others. An
off-by-one rather than a defect, but the configured number does not mean what it says.

Related and worth stating plainly: the README claims the bound "holds across replicas". It
does not. `queue_depth()` and the subsequent insert are not atomic, so two replicas can
each read a depth below the limit and both admit. It is materially better than an
in-memory set and it is still advisory.

---

## LOW

| # | Finding |
|---|---|
| C4-07 | `superseded_by` is now written (C3-09) and read by nothing and shown nowhere. Recording it satisfies §0.1B, but a reader still cannot follow a corroborated fact to the evidence that superseded it |
| C4-08 | `submit()` performs a database query while holding `_lock`, serialising all submissions behind DB latency |
| C4-09 | If `cryptography` fails to install, `_CRYPTO` is `False`, `spki_pin()` returns `None` and `cert_not_after()` returns `None` — silently restoring the pre-C3-03 behaviour with no expiry warning. `pin_status()` reports `spki_supported: false`, but nothing warns on it |
| C4-10 | `_deep_health()`'s cache is module-level with no lock and no invalidation. After `make seed` fixes a policy, health reports the old state for up to 30s. `test_health_deep_is_cached` also depends on test ordering, since a neighbouring test can populate the cache |

---

## What held up under attack

- **The audit-1 forgery still fails**; the audit-2 coverage bypass still fails.
- **SPKI pins survive a certificate renewal** that a certificate pin refuses, and a genuine
  key rotation is still refused by both.
- **Duplicate legacy data no longer crash-loops** the container; rows are preserved, not
  repaired away.
- **Cancel-then-resume remains byte-identical** through the C3-05/C3-12 changes.
- **The test harness is still safe** — `assert_disposable` guards the operation.
- **No governed constant** in `confidence.py`, `coverage.py` or `policy.py`, and no test
  asserts on source text.
- **The wiring tests work.** `test_startup_reclaims_interrupted_simulations` passes, which
  is what proves C4-01 is a *behavioural* failure under load rather than another missing
  call site — the wiring is right, the interaction is not.

---

## Remediation order

**Before relying on restart recovery:** C4-01. The path exists, is wired, is tested with
one orphan, and fails with forty.

**Before a figure carries a person's name:** C4-02. The guard is one keyword argument away
from being off.

**Before an upgrade on a multi-provider database:** C4-03.

**Before trusting the healthcheck:** C4-04.

---

## The pattern, four audits running

| Audit | Shape |
|---|---|
| #1 | Control written, documented, unreachable (grep-based test that could not fail) |
| #2 | Control written, documented, unread (`provider_request_id` checked by nothing) |
| #3 | Two implementations, the tested one not the wired one (`select_bindings` vs `resolve_quantity_source`) |
| #4 | **Two correct fixes that disable each other** (C3-11 vs C3-01), and a fix carrying its own opt-out (C4-02) |

The shape has moved each round, and it has moved in a consistent direction: from *is this
code reached?* to *is this the code that runs?* to *do these controls still work together?*

Unit tests answer the first. The wiring tests added in round three answer the second. **The
third has no test in this suite at all** — every job test uses a single run, every policy
test a single policy, every migration test a clean legacy database. C4-01 needs forty
orphans and C4-03 needs two providers, and no existing test supplies either.

The generalisable guard this round is **adversarial fixtures**: exercise a control at the
scale and multiplicity where its neighbours become relevant, not at the minimum that
demonstrates it functions. A bound is only interesting when something exceeds it.
