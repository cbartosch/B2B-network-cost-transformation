# Red-team audit #3 — Network Cost Transformation Workbench, build 4.7.11

**Target:** the bundle after both prior audits were closed (71 files, 48 Python modules,
164 tests)
**Method:** adversarial, against the code the last six fixes introduced. The prior round
found that two of four highs were regressions and two were defects in the test harness —
so the newest code is where the risk sits, not the oldest.
**Result:** 6 medium, 7 low. **No criticals, no highs.**

> ### Correction (issued after remediation began)
>
> **C3-01 was a false positive and has been withdrawn.** It claimed that
> `requeue_interrupted()` was never called. It was called, from `main.py:42`, in the
> application lifespan.
>
> The error was in the audit method, not the reading of the result. Two greps were run:
> `recover|reclaim` across the app — against a function named `requeue_interrupted`, so
> the words never appear — and `RUNNING|CANCELLING` against `main.py`, which contains
> neither literal because it calls the function rather than querying statuses itself.
> Both returned nothing, and the absence was treated as confirmation rather than as a
> weak signal from two searches that could each have missed.
>
> What survives from C3-01 is narrower and is re-filed below as **C3-01a (medium)**: the
> function handled `RUNNING` only, left a deferred run indistinguishable from a live one,
> and had no test — which is the reason a grep was being used to answer the question at
> all.
>
> The finding is retained here rather than deleted. An audit that quietly removes its own
> errors is less trustworthy than one that shows them.

---

## Verdict

The integrity spine holds. The forgery from audit #1 still fails, the coverage bypass from
audit #2 still fails, the test harness no longer destroys data, and every governed number
is loaded from reference data with no code fallback. Those fixes survive attack.

The concentration this time is in the **job runner** — the newest and least-exercised
module — and in one recurring pattern that has now appeared three audits running:

> Something is written, documented as a control, and never wired up.

Audit #1: the anti-stub test grepped for self-chosen strings.
Audit #2: `provider_request_id` was stored and never checked.
Audit #3: `requeue_interrupted()` has the docstring *"Called at startup"* and **nothing
calls it**.

That is the finding worth acting on beyond the individual defects: plausible-looking
machinery keeps shipping in an unreachable state, and each time it was documented as
working.

---

## WITHDRAWN

### ~~C3-01 — Interrupted simulations are never recovered; the recovery function is dead code~~

**Withdrawn.** See the correction above. `jobs.requeue_interrupted()` was called from the
lifespan at `main.py:42`. The claim that no call site existed was produced by searching
for identifiers the code does not use.

---

## MEDIUM

### C3-01a — Interrupted-run recovery was incomplete and untested

The real defects behind the withdrawn finding, all verified:

- **`RUNNING` only.** A run interrupted while `CANCELLING` was not reclaimed, and neither
  was one left `QUEUED` by a full pool — in a fresh process no worker exists for any of
  them.
- **A deferred run stayed `RUNNING`.** On `QueueFull` the function logged and moved on,
  leaving a row that no later restart would distinguish from a live job.
- **No test.** `requeue_interrupted` was the only function in `jobs.py` absent from
  `test_jobs.py`. That absence is why the audit was reduced to grepping for a call site,
  and therefore the proximate cause of the false positive as well as of the real gaps.

**Fixed in 4.7.12.** Renamed `reclaim_interrupted`; `CANCELLING` orphans now honour the
cancellation the dead process could not deliver rather than being resurrected; `RUNNING`
and `QUEUED` orphans resume from checkpoint; a deferred run is left `QUEUED`, which is
visible and recoverable. Ten wiring tests added, including one asserting that the lifespan
invokes it.

## MEDIUM

### C3-02 — A known fact binds to a quantity it disagrees with

Demonstrated: Jane asserts 400 sites, the run uses 122, `agrees_with_run` is correctly
`False` — and the binding is applied anyway. Every site-driven component is then labelled
`ANALYST_ASSERTED_PRIOR` with `source_ref = kf-1`, attributing 122 sites to a person who
said 400.

That is worse than not binding. A reader following the attribution reaches a fact that
contradicts the figure it is supposed to support, and the disagreement is recorded in a
field nothing acts on.

Three defensible resolutions, in increasing order of ambition: refuse to bind on
disagreement and surface a conflict; bind but mark the component `DISPUTED`; or let the
fact drive the value, which is what §0.1B's *"set a prior where no approved public fact
exists"* actually implies. The current behaviour — bind, mislabel, record the
contradiction, act on nothing — is the one option that is not defensible.

### C3-03 — Certificate pinning breaks on renewal, and the README does not say so

`peer_pin()` hashes the **leaf certificate DER**. A provider renewing its certificate with
the *same key pair* produces a different DER, so the pin changes and `ENFORCE` fails every
call until an operator updates `TLS_PINS`.

Public-key (SPKI) pinning survives renewal, which is why it is the standard choice. The
README presents multi-pin rotation as the answer, but you cannot pre-load the next pin
unless the provider publishes its next certificate — which neither does.

As shipped this is latent, because the default is `OBSERVE`. Anyone who follows the
README's instruction to switch to `ENFORCE` acquires a quarterly outage.

**Fix:** hash the SPKI rather than the whole certificate, or state the renewal exposure
plainly and recommend `ENFORCE` only with monitoring on pin drift, which is already logged.

### C3-04 — Migration v5 fails irrecoverably on duplicate legacy data

`_migrate_v5` runs `CREATE UNIQUE INDEX` on `provider_request_id`. Verified against
SQLite: if the existing table holds two rows sharing a request id, the statement raises
and the migration aborts.

Because migrations run in the lifespan and a failure re-raises, the container **crash-loops
at startup** with a raw `IntegrityError` and no indication of the cause or the remedy. The
schema stays at v4 and there is no path forward short of manual SQL.

Duplicates should not exist — but the whole reason for adding the constraint was that
nothing previously prevented them.

**Fix:** detect duplicates before creating the index, and either fail with a message naming
the offending rows or quarantine them, rather than surfacing a bare database error.

### C3-05 — `resume()` can leave a run queued with nothing scheduled

```python
_set(session, run_id, cancel_requested=False, status=QUEUED, error=None)
submit(run_id)          # may raise QueueFull
```

The status is committed before `submit` is attempted. On `QueueFull` the API returns 429,
but the row is left `QUEUED` with no worker — a second class of zombie, and one that
`requeue_interrupted()` would not catch even if it were wired up, because it selects
`RUNNING`.

**Fix:** submit first, or roll the status back on failure.

### C3-06 — `aggregate([])` raises `IndexError`

Verified. An empty summary list reaches `sorted(...)[len(passes) // 2]` and fails with a
bare `IndexError` carrying no context. Not reachable through the API today —
`ensemble_size` is `ge=1` — but `aggregate` is a public function on a checkpoint-driven
path, and the failure mode is a stack trace rather than a diagnosis.

### C3-07 — Identifier uniqueness is global, not per provider

`UniqueConstraint("provider_response_id")` and the new unique index on
`provider_request_id` are both global. Two providers issuing the same identifier string
would raise a false integrity incident and fail a genuine run — and the failure message
says *"a stored response was presented as a fresh LIVE call"*, which would be actively
misleading.

Unlikely with `msg_…` and `chatcmpl-…` prefixes, but the correct key is
`(provider, identifier)` and the cost of using it is nil.

---

## LOW

| # | Finding |
|---|---|
| C3-08 | `/v1/health` performs a schema query plus two policy loads with full validation on every call, and the container healthcheck polls it every 10s — a validation pass every ten seconds forever. Cache it, or split the deep check onto `/v1/health?deep=true` |
| C3-09 | `superseded_by` is filtered on in `bind_quantities` and **never written by anything**. `asserted_share`'s docstring states that a corroborated fact "is superseded by the public fact", but no code performs the supersession. The effect is right (`BINDING_ORIGIN` maps `CORROBORATED → EVIDENCED_PUBLIC`); the documented mechanism does not exist |
| C3-10 | The pin host is hardcoded in each adapter (`check_pin("api.anthropic.com", …)`) rather than derived from `ENDPOINT`. Currently in sync, kept so by hand |
| C3-11 | `_inflight` and `SIM_QUEUE_MAX` are per-process, so the bound is per-replica rather than global. Fine for a laptop bundle, wrong the moment there are two API containers |
| C3-12 | A cancel arriving after the pass loop but during `aggregate()` leaves the run `SUCCEEDED` with `cancel_requested = True` — a contradictory record, harmless today |
| C3-13 | `test_the_queue_is_bounded` mutates and clears the module-global `jobs._inflight`; under `pytest-xdist` that is shared-state contamination |

---

## What held up under attack

- **Cancel-then-resume is byte-identical.** Verified independently: assembling an ensemble
  from two batches reproduces the straight-through output hash exactly. The property the
  async design rests on is real.
- **The audit #1 forgery still fails** — a fabricated `ProviderCall` with a locally
  generated timestamp is rejected.
- **The audit #2 coverage bypass still fails** — omitting unpriced markets no longer moves
  the gate, and unsizable scope cannot vanish from a circuit count.
- **No test asserts on source text.** Swept all six modules; the only `getsource` reference
  is a docstring quoting the deleted grep test.
- **No governed constant remains** in `confidence.py`, `coverage.py` or `policy.py`, and
  the policy validator refuses incoherent weights, inverted bands and impossible floors.
- **The test harness is safe.** `assert_disposable` guards the destructive path at the
  operation rather than the caller, and refuses any non-SQLite engine by name.
- **Legacy upgrade preserves data** through v2–v6, with both refusal paths intact.

---

## Remediation order

**Before relying on the job runner:** C3-01. The recovery path exists and is unreachable;
it is one line and a test.

**Before switching pinning to `ENFORCE`:** C3-03. Following the README as written buys a
quarterly outage.

**Before any second deployment:** C3-04. Same shape as C2-03 — the failure that only
appears on an upgrade.

**Before a figure is attributed to a named person:** C3-02. Mislabelling a number with the
name of someone who said something different is worse than leaving it unattributed.

The rest is ordinary hardening.

---

## The pattern, three audits running

| Audit | Written, documented, unreachable |
|---|---|
| #1 | Anti-stub test grepped four self-chosen identifiers — could not fail |
| #2 | `provider_request_id` stored, nullable, checked by nothing |
| #3 | *(withdrawn — the wiring was present; the audit searched for the wrong name)* |

Two confirmed instances, not three. The third was the auditor making the same class of
mistake as the code: reaching a confident conclusion through a check that could not have
produced the opposite answer. A grep for `recover|reclaim` against a function named
`requeue_interrupted` cannot find it, exactly as an assertion that four self-chosen strings
are absent cannot fail.

Both have one remedy. **A test that exercises the real path and asserts the control fired
settles the question in either direction** — it catches a control that is genuinely
unreachable, and it refutes a claim that a reachable one is not. Had
`test_startup_reclaims_interrupted_simulations` existed, C3-01 would never have been
written.

That is the generalisable guard, and it is now in `tests/test_wiring.py`: the lifespan
calls what it claims to, the middleware runs on a real request, and a constraint declared
in a model exists in a created database. It is worth more than any individual finding in
this document.
