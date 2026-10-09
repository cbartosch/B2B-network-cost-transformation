# Findings register — test suite remediation

**Build 4.272.0** · branch `fix/test-suite-trustworthy`

Under `make test`, the project's own entry point:
**138 failed / 2,315 passed → 0 failed / 2,602 passed.**
Zero regressions. Every commit checked by set-difference against the previous
complete run, not by reading output.

The suite is green. The one remaining question was a decision rather than a
defect and has been answered by the owner — see §3.

---

## 0. Read this first: the numbers in the earlier versions of this file were wrong

Every count I reported before commit `fc5fd7f` came from pointing pytest at
`/src/tests` with the repo bind-mounted. **That is not how this project runs its
suite.** `make test` runs `/app/tests` inside the api image, and the image is
built from a Dockerfile that copies `api_service/app`, `tests` and `contract` —
and not `analyst_ui`. So roughly a hundred tests that read the Streamlit source
died on

```
FileNotFoundError: '/app/analyst_ui/streamlit_app/api_client.py'
```

before asserting anything. Under the project's own entry point the suite was at
**138** failures, not the 36 this file previously claimed.

The Dockerfile already said what it intended — *"Tests live at the bundle root,
beside the two services they exercise"* — and copied one of the two. Adding
`analyst_ui`, `make.ps1`, `docker-compose.yml` and the api `Dockerfile` took it
138 → 47 without touching a line of application code.

Everything below is measured the way `make test` measures.

---

## 1. The pattern, which is the actual finding

**Twenty-one guards were found silenced rather than absent.** This repository
writes unusually good checks and then loses them — to a missing file, a moved
phrase, a renamed section, a fixture that stopped describing the system. A
suite carrying known failures cannot report a new one, so each loss is also
cover for the next.

The forms it took here, with examples:

| form | instances | worst example |
|---|---|---|
| the file the test reads is not in the image | ~105 | five backup checks on `make.ps1` |
| a byte window that counted prose | 3 | a comment pushed the `archetype_prior` scan's target out of a 900-char window |
| the documentation defeating its own check | 2 | `_one_or_404`'s docstring explains "404, not 403"; the test asserts `"403" not in source` |
| a phrase that moved or got rewrapped | 3 | `"...a figure and its\nprovenance"` |
| a fixture modelling a retired rule | 7 | a corroboration reply asserting `state: CORROBORATED` — the register's own P0 |
| a test asserting a withdrawn behaviour | 2 | a 422 the system deliberately replaced with disclosure |

Two of these had happened before and been fixed before, each leaving a comment
saying so, and then happened again:

- `inspect.cleandoc` on function source — fixed in `test_migrations`, then in
  `test_footprint_resolution`, both carrying the note. Found a third time.
- A rejection reason added without guidance — the `GUIDANCE` map carries a
  comment about the last two. Found two more.

---

## 2. PRODUCT — defects found and fixed

### P-1 · A case delete left eleven tables orphaned — **FIXED**
`DEPENDENTS` listed 12 of 23 case-scoped tables. A deleted case left its
assumptions, rates, data requests, locations, providers and calibration behind.
For a client asking to have their data removed, that is the control failing
rather than a tidiness problem. The test that catches it could not run until
the client fixture was fixed.

### P-2 · The governed sweep budget — **FIXED**
`_sweep_budget` called a class that does not exist under that name.

### P-3 · The cross-case guard was never reached — **FIXED**

### P-4 · The committed-rate seam — **FIXED, and I broke it first**
`committed_fraction` was seeded per archetype and never loaded, so
`access.pair_for` priced on the bearer rather than the committed rate — up to
3.3× on priced bandwidth for an IPVPN or ETHERNET site. My fix passed the raw
`Numeric`, which is a `Decimal`, into a dict pinned as JSON: **`POST
/simulations:run` then raised `TypeError` — a 500 on the main simulation
route.** I reported that commit as having no regressions. It did. My check was
a set difference over failing test ids, and both tests it broke were already
failing on an unrelated setup error, so the id was on both lists and the diff
was empty. *A set difference over names cannot see a test that fails for a new
reason.*

### P-5 · `TransitionPolicy` could not be constructed — **FIXED**
```python
@dataclass(frozen=True)
@dataclass
class TransitionPolicy:
```
Stacked, the inner decorator installs an `__init__` that assigns with
`self.x = ...`; the outer `frozen=True` installs the raising `__setattr__` but
will not replace an `__init__` already in the class `__dict__`. Every
construction raised `FrozenInstanceError`.

`estimate.py` emits the transition block only `if transition_policy is not
None`, so **every scenario had been reporting a gross run-rate saving with no
payback and no one-time cost** — word for word the defect the class was written
for: *"P3: none of this existed, so every scenario reported a gross saving as
though it were the answer."* Now wired — see P-13.

### P-6 · A case export could not be imported — **FIXED**
`_plain()` writes dates as ISO strings so the export stays readable JSON;
`import_case` put the strings straight back into the insert and the driver
refused them. A restore died on the first `known_fact` carrying an
`assertion_date`. **This is the recovery path** — an export that cannot be
imported is not a backup, and the failure arrives at the worst possible moment.

### P-7 · Every gate-rejected agent run was stranded — **FIXED**
`structured_call` raised after exhausting retries without touching the
`agent_run` row, so any run whose reply was refused three times stayed `QUEUED`
permanently. In the gateway, so every caller. A queue advertising work nothing
will pick up, and an audit trail saying "queued" about a call that ended.

### P-8 · Two retryable rejections could not say what to fix — **FIXED**
`ANSWER_NOT_ACTIONABLE` and `OPTION_NOT_SUPPLIED` had no `GUIDANCE` entry, so a
retry re-sent the prompt unchanged — resampling, which is the one thing the map
exists to prevent.

### P-9 · The serviceability read-out stopped reporting its own finding — **FIXED**
`summarise()` counts substitutions and ignores `access_technology`. Once the
resolver moved to bearers, 600 rural stores on PON instead of fibre became
`DELIVERED` rather than `SUBSTITUTED`, the count went to zero, and a
4,000-store estate read as uniform. It reports the bearer mix now.

### P-10 · An error that named the wrong mistake — **FIXED**
The ops-cost check ran before the method was validated and branched on
`payload.method`, so a request naming method `"ANCOHR"` was told to supply a
per-site operating cost.

### P-11 · Four offline tools dead on a stub — **FIXED**
The stubs' module-level `__getattr__` answered *any* attribute including
`__path__`, so the import machinery took the stub for a package and died on
`TypeError: 'A' object is not iterable` — naming neither the stub nor the
import. `check_lever_reach.py` has been unable to start; its docstring lists
three features this repository shipped inert.

### P-12 · The suite made real, billable provider calls — **FIXED**
`conftest.py` opens with the last time an ambient variable turned the harness
into a hazard: `setdefault("DATABASE_URL", ...)` meant `make test` *"dropped
every table in the live database, once per test."* The same shape, one live
resource over — `ANTHROPIC_API_KEY` reached the suite and `config.py` reads it
at import.

`test_entity_resolution_fails_closed_without_a_provider` calls itself *"the
single most important behaviour in the bundle: no provider means no output, not
fabricated output."* With a key present it got a 200 carrying 22,431 input
tokens and 51 seconds of latency — a real answer from a real model, which is
exactly the fabricated output it forbids. Whether it passed depended on whose
machine ran it.

**Treat the key as worth rotating.** I did not read it; it was in the
environment of every container this work ran in.

---

### P-13 · The transition model was complete and unreachable — **WIRED**
Every piece existed and was correct: `transition.net`, `TransitionPolicy`, the
seeded thresholds, page 8's renderer, and `validation_capture`'s extraction of
`scenario["transition"]["one_time_cost"]["base"]`. Nothing built a policy and
handed it to `scenarios()`, so the feature was absent end to end and **nothing
failed** — the domain tests call `transition.net` directly, and no endpoint
test looked for the block.

Three gaps, all at seams:

1. no call site constructed a `TransitionPolicy` (P-5 made that impossible
   anyway);
2. `scenarios()` needs a site count and a *monthly* run rate, and neither was
   available at the call sites as such;
3. the recommendation row has no `transition` column, so page 8 could never
   have rendered one even with the scenarios fixed. It has shown its fallback
   — *"No transition cost is modelled for this recommendation"* — to every
   reader since 4.165.

What was added: `_transition_policy(s)` beside its eight sibling loaders;
`estimate.site_count()` and `estimate.monthly_run_rate()`, both reading back
from the components rather than taking a number that could disagree with them;
and `_with_transition()`, which attaches the block to a recommendation from its
snapshot at read time rather than copying it onto the row, where it would be
free to drift.

**This changes what every estimate reports.** A scenario now carries its
one-time cost, dual running, first-year net, payback band and programme
duration. On a 4,000-site estate at the seeded 400/900/1800 band: £3.6m
one-time, 19-month payback at base against a 34-month programme, and a
first-year net of −£1.3m against a £2.4m gross saving. That is the number the
gross figure was standing in for.

Two things worth knowing about the shape:

- **It is a 503 if the policy will not build**, like every other governed
  policy, rather than silently omitting the block. `scenarios()` keeps its
  optional contract for other callers — *"a missing payback is honest, and one
  computed from no assumptions is not"* — but omitting it silently on the
  publishing route is how it went missing in the first place.
- **The site count is maxed across site-driven layers, not summed.** Both the
  OPS line and the L2 overlay are driven by it and each is split across origins
  by `_split()`, so a flat sum would report 8,000 sites for a 4,000-site estate
  — doubling every one-time cost and halving every payback. Pinned by a test.

Eight tests added, at the seam the domain and the endpoint met at.

---

## 3. DECISION — answered

### D-1 · Is a degraded or undeliverable second path a second path? · **ANSWERED: no**

`test_a_substitution_onto_a_genuinely_different_product_is_resilient` asked a
rural DC with an ETHERNET primary for a backup and expected broadband,
`resilient=True`. The resolver reports no second path and models the site with
one.

**Owner's decision: a backup must carry the primary's load. The resolver
stands.** The tests now assert the single-path outcome.

Investigating it to write those tests corrected my own framing, which is worth
recording because the register had it wrong:

- I filed this as a *bandwidth* question — nothing in DE RURAL reaches the
  10 Gbps the test asked for. That was a red herring. `carriers_for("ETHERNET")`
  is `(ETHERNET_FIBRE, DARK_FIBRE)` and the seed marks **both unavailable in DE
  RURAL**, so the ask is refused at 100 Mbps for the same reason it is refused
  at 10,000. It is a bearer question, not a capacity one.
- **The real behavioural change is that the backup resolver no longer
  substitutes across service classes.** The product-keyed resolver walked
  `FALLBACK_ORDER` and would hand a dedicated backup a broadband circuit; the
  bearer resolver only considers carriers of the class asked for. A rural site
  whose archetype names an ETHERNET backup now gets none, where before it got
  broadband.

That is the decision as taken, and it is the conservative reading: a circuit
the site cannot be given is not resilience. Both rules are now pinned, with the
converse — a `BROADBAND_HFC` backup behind an ETHERNET primary in the same
rural town **is** a second path, delivered on PON — so the rule cannot be
satisfied by a resolver that simply refuses every rural backup.

## 4. Not failures, but worth the owner's attention

1. **Both `requirements.lock` files are missing.** `check_lockfile.py`:
   *"9 direct pin(s) and no record of the transitive versions that ran"*, and 3
   for the UI. Producing them is a `pip freeze` against a chosen environment and
   a call about reproducibility policy.
2. **`DOCUMENTATION.md` line 3 claims "1,835 tests passing."** The suite
   collects ~2,600, and 138 were failing when this started.
3. **`products_present` is a misnomer.** It now holds `field=value` pairs across
   whatever dimensions a lever constrained. Renaming it is a response-contract
   change; nothing in `analyst_ui` reads it today.
4. **`FALLBACK_ORDER` is live only on a path nothing ships.** It is used in
   `resolve()`'s product-keyed branch, reached when `service_class is None`;
   `simulation.py` always passes a class. It is still covered by
   `test_the_substitute_is_chosen_for_reliability_not_price`, which therefore
   tests a path the service does not take. Harmless today, and it is the
   cross-class substitution that D-1 just confirmed should not happen — so it
   reads as a live rule and is not one.
5. **A runtime image carries its own test suite, the UI source and the
   bundle-root files.** That is the established choice here and I have extended
   it rather than reversed it, because it is the only way these guards run at
   all. Whether that is the right shape for a production image is a separate
   question.

---

## 5. Method

Every commit was verified by capturing the complete `FAILED`/`ERROR` list before
and after and taking the set difference both ways — fixed, and newly broken. The
"newly broken" direction is the one that matters and is reported in every commit
message.

Two cautions, both learned the hard way here:

- **A set difference over test ids cannot see a test that fails for a new
  reason.** That is how P-4's regression passed a clean check. Where a test was
  already failing, the new failure has to be read, not diffed.
- **`docker compose build … | tail -1` hides a failed build.** Three times I read
  a stale image's results as new ones, once concluding a correct fix had not
  worked. Builds are grepped for the `Built` marker now.

---

## 6. Closed

- **Density no longer differentiates a footprint** — *resolved, not a defect.*
  `carriers_for("DIA")` is `(ETHERNET_FIBRE, DARK_FIBRE, PON, FWA)`; in DE RURAL
  both fibres are unavailable and PON reaches 100 Mbps, so a rural store gets
  DIA over PON while urban takes ETHERNET_FIBRE. The finding survives as a
  different bearer rather than a different product name — which is what the
  vocabulary split was for — and it is still priced differently, because
  `unit_cost_prior` is keyed on `access_technology` as well as `service_class`.
  What *was* broken is P-9, the read-out.
- **A degraded second path** — closed by the owner's decision, §3.
- A CONTRADICTED fact suppressing a good one — no longer failing.
- Lever eligibility and right-sizing — no longer failing.
- The certificate test, `acknowledge()`'s `case_id`, the retired lever
  vocabulary, and 126 mechanical fixture repairs.
