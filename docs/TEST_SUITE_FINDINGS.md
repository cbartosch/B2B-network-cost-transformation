# Findings register — test suite remediation

**Build 4.272.0** · branch `fix/test-suite-trustworthy` · PR #4
Suite: **162 failed / 2408 passed → 36 failed / 2559 passed**, 19 commits, zero
regressions — every commit checked by set-difference against the previous complete
run, not by reading output.

Updated after the four PRODUCT findings were worked; two of them turned out not to be
product defects, which is recorded in §2 rather than quietly amended.

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

Nothing here is a fixture repair. Those are done — 126 of the original 162 were
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

## 2. PRODUCT — worked, and two reclassified

All four are closed. Two were product defects and are fixed. **Two were not product
defects at all**, and I had classified them before confirming which side was wrong.
That error is left visible here because it is the same mistake this register warns
about everywhere else: a failing test proves a claim and its subject disagree, not
which of them is mistaken.

### P-1 · A case delete left eleven tables orphaned — **FIXED**
`case_admin.py`, `test_case_admin.py` · commit `9ff9280`

I flagged this as needing judgement because `product`, `provider` and `location` read
like shared reference data. They are not, and the codebase already said so —
`case_rate`'s comment states the rule: *"outside_in, not reference: the schema is the
boundary."*

Checking the rule holds: **no `reference` table carries a `case_id` at all**, and all
eleven sit in `outside_in` or `analysis` beside the twelve already listed. There was
no shared-data exception to weigh — which was the thing that made it look risky.

All eleven added, with the schema rule recorded above the tuple so the next table
does not repeat it.

Two fixture defects were hiding the proof. `test_deletion_leaves_no_orphans` — the
test that shows a delete *removes rows* rather than that the list merely names them —
inserted `agent_run` with a renamed column and two missing NOT NULLs, and raised
before deleting anything. Fixed, so the delete is now demonstrated.

### P-2 · The governed sweep budget — **FIXED, and my framing was wrong**
`known_facts.py`, `test_prompt_registry.py` · commit `9ff9280`

This register said: *"Decide: write the class and seed the key, or drop the pretence."*
Neither was needed. **`ResearchPolicy` already carries
`max_output_tokens_per_sweep_call`**, with 6000 as its own default and a `from_rows`
keyed on `research_budget_profile`. `_sweep_budget` asked for
`policy.ResearchBudgetProfile`, a name no commit here has ever defined, inside
`except Exception: return 6000`.

So the capability existed and the call named the wrong thing. Because the seeded value
is *also* 6000, the governed path and the fallback were indistinguishable from
outside — the only way to tell them apart is to raise the row. A new test does
exactly that: seed the profile, assert 6000, update to 9000, assert 9000. **That
assertion could not have passed at any point in this repository's history.**

### P-3 · The extract prompt — **NOT a product defect**
`test_prompt_registry.py`, `gateway.py` · commits `91f64b7`, `9e7ddc5`

Filed here as *"has no call site"* and a 16,000-token truncation. Both halves were
tests looking in the wrong place.

**The call site exists** (`research.py:1058`) and passes a search tool. The test
searched for the literal `prompt_id="..."`, but the id arrives through a ternary; and
it scanned 700 characters forward for `web_search`, which is declared twenty lines
*above* as `tools = _web_search_tool(...)`. Both now resolve the enclosing function
with `ast`, because "its call site" means the function making the call.

**The truncation test never exercised the budget.** It installs a fake adapter that
forces `stop_reason: "max_tokens"` on every reply, so it truncates at any ceiling. It
asserts the *message*, which said "Raise the budget for this call" without naming
which budget — `research_budget_profile` governs two token settings separately. The
message now names them.

**The 16,000 was not raised.** It was already raised to that from the gateway's 1,500
default for a documented reason, and no run here shows it binding. Raising a governed
per-call cost on the strength of a simulated truncation would be changing a number to
make a test pass. Still open as a margin decision if anyone wants it.

### P-4 · The cross-case guard was never reached — **FIXED**
`test_case_admin.py` · commit `9ff9280`

`estimates:run` calls `preflight.assert_clear_to_run` first, so the request was refused
with *409 no pre-flight report* and audit finding C-04's ownership check never ran.
Refused by the wrong guard is not the same as protected.

The test now gives case A a clear acknowledged pre-flight report, reaches the ownership
check, and gets the **404** it was written for — 404 rather than 403 being the point:
whether a simulation exists on another case is not something a caller without access
should be able to learn.

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

### T-1 · The certificate test checked the wrong thing — **FIXED**
`test_compose.py` · commit `1327003`

Reported *"certificates committed: [...]"*. **No certificate was committed.**
`git ls-files` returns none, and `.gitignore:2` carries `certs/*.crt`. The test
inspects the `certs/` directory on disk, where the corporate CA bundle legitimately
lives for building behind the TLS-inspecting proxy.

A test named `test_no_corporate_certificate_is_committed` that fails on an ignored
local file is worse than no test: it reports a leak that has not happened, and the
habit of dismissing it is what will hide a real one.

It asks `git ls-files` now, and skips where git is unavailable — a test that cannot
ask its question should say so rather than answer it from somewhere else.

### T-2 · `acknowledge()` gained a required `case_id` — **FIXED**
`test_controls_db.py` · commit `1327003`. Signature drift, same class as the
`max_tokens` and `assertion_date` batches. `acknowledge` is scoped to one case
deliberately, so a report cannot be acknowledged from another case's route.

### T-4 · Levers were constrained in a retired vocabulary — **FIXED**
`test_savings_advisory.py` · commit `1327003`

Three tests declared `LEV-MPLS-001` as `["MPLS"]` through a helper that built
`applies_to_products` — a field `estimate.py` deliberately does not read: *"falling
back to it would silently disable a lever rather than fail loudly."* The column
survives only so a pre-4.170 row stays readable.

So the constraint matched nothing and **the lever was unconstrained in practice,
which is the defect those tests exist to catch** — reported as though the product
code were at fault. The matcher is correct and the seed is correct
(`LEV-MPLS-001 → ['IPVPN']`, `LEV-BANDWIDTH-001` excludes `BEST_EFFORT`).

The fixtures also built components with no `service_class` at all, so every one of
these tests was passing or failing for the wrong reason. Both fixed.

This is the fifth place in this PR where the v44 / 4.166 vocabulary split left a test
behind — after the serviceability table, the sweep schema, the archetype row width,
and lever eligibility's row shape.

### T-3 · Assorted
`test_location_structure_agent.py:33` (`'tuple' object has no attribute 'name'`),
`test_progress_reporting.py:58` (`IndexError`), `test_savings_band.py:114`
(`KeyError: 'low'`), `test_integrity.py:1170` (`KeyError: 'components'`).
Shapes moved; the tests kept the old one.

---

## 5. UNTRIAGED — the remaining 36

| test | count | reported |
|---|---|---|
| `test_estimate_endpoint.py` | 5 | refusal messages; QUEUED status |
| `test_serviceability.py` | 3 | D-1, above |
| `test_prompt_registry.py` | 3 | prompt text (`AUTHORITY`); `basis=` in source; one class per call |
| `test_promotion.py` | 3 | `'DE'` vs `None`; `0 == 1` |
| `test_savings_advisory.py` | 2 | rejected shape leaves run QUEUED; inapplicable lever not reported |
| `test_research.py` | 2 | empty result; archetype definitions |
| `test_llm_call_audit.py` | 2 | `every name a module uses is bound`; `7431 < 2594` |
| `test_case_export.py` | 2 | — |
| `test_controls_db.py` | 1 | `known_fact.corroborate` rejected after 3 attempts |
| `test_integrity.py` | 1 | `KeyError: 'components'` |
| `test_savings_band.py` | 1 | `KeyError: 'low'` |
| `test_location_structure_agent.py` | 1 | `'tuple' object has no attribute 'name'` |
| `test_progress_reporting.py` | 1 | `IndexError` |
| `test_wiring.py` | 1 | `assert 6 == 2` |
| `test_quality_gate.py` | 1 | `['ANSWER_NOT_ACTIONABLE', 'OPTION_NOT_SUPPLIED']` |
| `test_reliability.py` | 1 | prompt text |
| `test_lever_reach.py` | 1 | bare assertion |
| `test_logic_audit.py` | 1 | `_one_or_404` source assertion |
| `test_policy_construction.py` | 1 | — |
| `test_research_briefs.py` | 1 | — |
| `test_stage_and_questionnaire.py` | 1 | — |
| `test_end_to_end_flow.py` | 1 | agent-run payload |

**Clear:** `test_case_admin.py`, `test_compose.py`, `test_footprint_resolution.py`,
`test_migrations.py`, `test_known_facts.py`, `test_preflight_freshness.py`,
`test_transport.py`, `test_case_rates.py`.

Several are shapes already met three or four times here: source-text assertions on
prose that moved, fixtures missing a column that became required, stubs that stopped
matching a signature, and the v44 vocabulary split. They are listed rather than
guessed at — classifying before confirming is what produced the two reclassifications
in §2.

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

1. **D-1** — decide whether serviceability still does its job, before anyone quotes a
   density-differentiated estimate. It is the only open item that could put a wrong
   number in front of a client.
2. **D-3, D-2** — the lever vocabulary and the CONTRADICTED rule, both modelling
   calls rather than repairs.
3. The 36 UNTRIAGED, to reach zero and hold it. Most should go quickly. The value is
   not in any one of them: it is that a suite at zero can report a *new* failure,
   and a suite at 36 cannot. Six guards in this codebase were found silenced rather
   than absent (§1), and that is the mechanism.
4. **P-3's margin** — raise `max_output_tokens_per_call` above 16,000 if the cost is
   acceptable. No evidence it binds today; a buffer decision, not a defect.

### Closed in this PR

C-02's `current_tco` KeyError · v66's schema mismatch · five unguarded migrations ·
the shared `client` fixture · the eleven orphaned tables · the cross-case guard ·
the governed sweep budget · the committed-rate seam · the certificate false alarm ·
lever eligibility · three `cleandoc`-on-source parses · three batches of
`assertion_date` · two of `max_tokens`.
