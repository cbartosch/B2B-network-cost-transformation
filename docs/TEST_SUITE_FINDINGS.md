# Findings register — test suite remediation

**Build 4.272.0** · branch `fix/test-suite-trustworthy` · PR #4
Suite: **162 failed / 2408 passed → 47 failed / 2547 passed**, 13 commits, no regressions at any step.

`DOCUMENTATION.md` line 3 claims "1,835 tests passing". It was 162 failing when this
started, and the suite collects ~2,600 tests rather than 1,835.

---

## How to read this

Every remaining failure is listed. Each is classified by **who is wrong**, because
that is the only question that decides what to do:

| class | meaning | action |
|---|---|---|
| **PRODUCT** | the test is right and the code is wrong | fix the code |
| **DECISION** | behaviour changed deliberately; the test encodes the old intent | confirm the new intent, then update the test |
| **TEST** | the code is right and the test is wrong | fix the test |
| **UNTRIAGED** | not yet investigated | triage |

Nothing here is a fixture repair. Those are done — 115 of the original 162 were
mechanical and are fixed in this PR.

---

## 1. The pattern worth reading first

Six guards in this codebase were found **silenced rather than absent**. In each case
somebody wrote the check, and something unrelated stopped it reporting:

| guard | silenced by |
|---|---|
| `test_anchor_runs_end_to_end` — written to catch a `current_tco` KeyError | three Postgres-only migrations stopping the app from starting under SQLite |
| v66's `estimate_snapshot_never_refused` constraint | a schema-name mismatch; the migration stamped success and did nothing |
| `test_every_table_carrying_a_case_id_is_in_the_delete_list` | a missing `client` fixture — the test never ran |
| `_sweep_budget`'s governed budget | `except Exception: return 6000` |
| `committed_fraction` reaching the rate card | one key missing from a dict literal |
| `test_every_resolver_branch_returns_the_same_keys` | `cleandoc` on source → `IndentationError` |

This is the most actionable conclusion of the exercise. The repo's instinct for
writing guards is good; the failure mode is that guards stop reporting and nobody
notices, because a suite with 162 known failures cannot tell you that one more
appeared.

**Recommendation:** get the suite to zero and keep it there. Until then no guard in
it can be relied on, including the ones that pass.

---

## 2. PRODUCT — the test is right

### P-1 · A case delete leaves eleven tables orphaned
`test_case_admin.py:120`

```
assumption_register, case_rate, data_request, estimate_delta,
evidenced_anchor, evidenced_archetype, location,
outside_in_tco_calibration, product, provider, validation_case
```

The test's own words: *"A table added later that nobody adds here leaves orphans
behind."* It could not run until the `client` fixture was fixed in this PR, so these
eleven accumulated unseen.

**Not a mechanical fix.** `product`, `provider` and `location` read like reference
data that merely carries a `case_id`; adding them to a delete list would destroy rows
other cases depend on. Someone who knows the schema must split case-owned from
shared.

**Severity: high.** Deleting a case is the control a client exercises when they ask
for their data to be removed.

### P-2 · `ResearchBudgetProfile` has never existed
`test_prompt_registry.py:744`

`known_facts._sweep_budget` calls `policy_module.ResearchBudgetProfile.from_rows(...)`
inside `except Exception: return 6000`. The class is defined nowhere, and **no commit
in this repository ever defined it** (checked with `git log -S`). The seed does not
carry `max_output_tokens_per_sweep_call` either.

So every sweep has always used the hardcoded 6000, the governed
`research_budget_profile` rows have never been read, and an operator changing that
value would see no effect. The docstring calls it *"The governed output budget"* and
adds *"the fallback matches the seeded value"* — which is how a constant passed for a
policy.

**Decide:** write the class and seed the key, or drop the pretence and name it a
constant. Either is defensible; the present state is not.

### P-3 · `llm01.public_evidence.extract` is cut off at its budget
`test_research.py:698`, `test_prompt_registry.py:309`

> *"was cut off at 16000 tokens, so its reply is incomplete rather than empty. Raise
> the budget for this call, or ask it for less at a time — retrying an identical
> request will be cut off in the same place."*

The system's own error text states the fix and the futility of retrying. Related:
`test_prompt_registry.py:309` reports the same prompt *"has no call site"*.

### P-4 · A cross-case simulation is refused for the wrong reason
`test_case_admin.py:163`

Audit finding C-04 is that case A must not consume case B's simulation. The test
expects **404** — *"whether a simulation exists on another case is not something a
caller without access to that case should be able to learn"* — and now gets **409 no
pre-flight report**.

The request is still refused, so there is no data leak today. But it is refused by a
different guard, and the one that exists for this threat is no longer demonstrably
reached. A pre-flight that later passes would expose whether the ordering is the only
thing protecting it.

---

## 3. DECISION — behaviour changed; confirm the intent

### D-1 · Density no longer differentiates a footprint
`test_serviceability.py:69, 119, 269`

Serviceability moved from "is this product sold here" to "does a bearer reach this
site that can carry this service". `resolve()` argues it: *"An IPVPN in a rural town
is deliverable if VDSL reaches it — true, and the product-keyed table could not say
so."*

The consequence, for the module's own worked example — a BRANCH asking DIA at
100 Mbps on the seeded DE table:

```
DENSE_URBAN  DELIVERED  DIA @ 100
URBAN        DELIVERED  DIA @ 100
SUBURBAN     DELIVERED  DIA @ 100
RURAL        DELIVERED  DIA @ 100
```

`test_serviceability.py` opens by saying the module exists because *"a 4,000-store
estate was priced as though every store could take the same product"*. At this
bandwidth that is again what happens. Substitution still occurs, but it caps
bandwidth rather than changing product, and only above what the bearer carries.

**Decide:** should density differentiation return as a bandwidth or price effect, or
does the seeded table understate rural constraint? The bearer model is the more
truthful answer to "can it be delivered"; it may have cost the module its purpose.

### D-2 · A CONTRADICTED fact suppresses a good one
`footprint.py` — pinned, not failing

Two registered totals with no analyst choice resolve to nothing. That is deliberate
and well argued: *"on a Boots UK case picks 12,028 (the Walgreens Boots Alliance
group figure) over 1,840 (GB stores)... an estimate that looks finished and is about
a different company."*

But a `CONTRADICTED` fact carries standing 0 — somebody disputed it — and still counts
as a competitor. One disputed total beside one good one yields a placeholder, the same
outcome as two credible rivals. Refusing is the safe direction; whether a disputed
number should suppress an undisputed one is a different question.

### D-3 · Lever eligibility and right-sizing
`test_savings_advisory.py:511, 571, 581`

- MPLS substitution books a saving against an estate with no MPLS
- a shared best-effort circuit is right-sized, which the test says must not happen
- `LEV-REPRICE-001 has no applies_to_products slot`

These sit on the lever vocabulary split (`product` → service class + access
technology, migration v44). Whether a lever should declare products, service classes,
or both is a modelling decision.

---

## 4. TEST — the code is right

### T-1 · The certificate test checks the wrong thing
`test_compose.py:186`

Reports *"certificates committed: [...]"*. **No certificate is committed.**
`git ls-files` returns none, and `.gitignore:2` carries `certs/*.crt`. The test
inspects the `certs/` directory on disk, where the corporate CA bundle legitimately
lives for building behind the TLS-inspecting proxy.

A test named `test_no_corporate_certificate_is_committed` that fails on an ignored
local file is worse than no test: it reports a leak that has not happened, and the
habit of dismissing it is what will hide a real one. Should assert against
`git ls-files`.

### T-2 · `acknowledge()` gained a required `case_id`
`test_controls_db.py:731` — signature drift, same class as the `max_tokens` and
`assertion_date` batches already fixed.

### T-3 · Assorted
`test_location_structure_agent.py:33` (`'tuple' object has no attribute 'name'`),
`test_progress_reporting.py:58` (`IndexError`), `test_savings_band.py:114`
(`KeyError: 'low'`), `test_integrity.py:1170` (`KeyError: 'components'`).
Shapes moved; the tests kept the old one.

---

## 5. UNTRIAGED

| test | reported |
|---|---|
| `test_llm_call_audit.py:231` | `[ok] every name a module uses is bound` |
| `test_llm_call_audit.py:277` | `assert 7431 < 2594` |
| `test_wiring.py:261` | `assert 6 == 2` |
| `test_quality_gate.py:97` | `['ANSWER_NOT_ACTIONABLE', 'OPTION_NOT_SUPPLIED']` |
| `test_reliability.py:204` | prompt text assertion |
| `test_promotion.py:47, 165` | `'DE'` vs `None`; `0 == 1` |
| `test_research.py:237, 736` | empty result; archetype definitions |
| `test_lever_reach.py:34` | bare assertion |
| `test_logic_audit.py:789` | `_one_or_404` source assertion |
| `test_end_to_end_flow.py:81` | agent-run payload |
| `test_prompt_registry.py:73, 418` | prompt text; `basis=` in source |
| `test_estimate_endpoint.py` ×5 | refusal messages, QUEUED status |
| `test_case_export.py` ×2 | — |
| `test_savings_advisory.py:469, 538` | rejected shape leaves run QUEUED |

---

## 6. Things worth fixing that are not failures

**A 3.3× pricing move broke no test.** `committed_fraction` never reached the rate
card, so every IPVPN and ETHERNET site was priced on its bearer — a DC at 1000 Mbps
instead of 300. Fixed in this PR, and nothing in the suite noticed in either
direction. Now pinned by `test_priced_rate_reaches_the_card.py`.

**Four recurrences of one migration defect.** v9 documented that a migration must
guard a table that may not exist. v31/v38/v66 reintroduced it as Postgres-only DDL;
v44–v48 reintroduced it as unguarded raw SQL. Each time the guard went into the helper
and not the call sites around it.

**Three recurrences of `cleandoc` on source.** `inspect.cleandoc` is for docstrings;
on a function's source it de-indents the body and leaves `def` at column 0, raising
`IndentationError` before any assertion runs. Two fixed here;
`test_prompt_registry.py:715` still uses it.

**Tests import each other through `/app`.** `conftest.py` does
`sys.path.insert(0, "/app")`, so `from tests.x import y` resolves to the image's baked
copy, not the mounted `/src`. A helper edited in the working tree is not what a
cross-file import gets. This cost two debugging cycles during this work.

**`make test` is not what it claims.** Its comment says 26 tests skip as "not present
in this image"; it produces 267 failures. `tools/run_tests_offline.py`, documented as
the locked-down path, dies on Windows at `signal.SIGALRM`.

---

## 7. Suggested order

1. **P-1** — a case delete that leaves orphans is a client-facing control.
2. **T-1** — a false security alarm trains people to ignore security alarms.
3. **D-1** — decide whether serviceability still does its job, before anyone quotes a
   density-differentiated estimate.
4. **P-2, P-3** — governance that cannot bite, and a prompt that cannot complete.
5. The remaining TEST and UNTRIAGED rows, to reach zero and stay there.
