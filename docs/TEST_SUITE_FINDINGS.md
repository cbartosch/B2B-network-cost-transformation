# Findings register — test suite remediation

**Build 4.272.0** · branch `fix/test-suite-trustworthy`

Under `make test`, the project's own entry point:
**138 failed / 2,315 passed → 1 failed / 2,592 passed.**
Zero regressions. Every commit checked by set-difference against the previous
complete run, not by reading output.

One test remains, and it is a decision rather than a defect. It is §3.

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
None`, so **every scenario has been reporting a gross run-rate saving with no
payback and no one-time cost** — word for word the defect the class was written
for: *"P3: none of this existed, so every scenario reported a gross saving as
though it were the answer."* See §4 for what is still needed.

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

## 3. DECISION — the one remaining failure

### D-1 · Is a degraded second path a second path?

`test_a_substitution_onto_a_genuinely_different_product_is_resilient` asks a
rural DC with a **10 Gbps** ETHERNET primary for a backup. Nothing in DE RURAL
reaches 10 Gbps — PON 100, HFC 200, VDSL 40, FWA 100, 5G 100, SATELLITE 50 — so
the resolver returns `UNSERVICEABLE` and the site is modelled with **one path**.

The test expects a broadband backup and `resilient=True`, on the grounds that a
different failure domain is a real second path.

| if you answer | then |
|---|---|
| a backup must carry the primary's bandwidth | the resolver is right; the test asserts a rule the model does not hold, and should assert the single-path outcome |
| a degraded second path still counts | the resolver is over-strict; backups should substitute down in capacity, and rural resilience is currently understated |

Both are defensible and they produce **different resilience numbers for
clients**, so this is not mine to pick.

*The rest of what was filed here as D-1 is resolved and closed — see §6.*

---

## 4. Not failures, but worth the owner's attention

1. **Nothing constructs a `TransitionPolicy`.** The thresholds are seeded,
   `from_rows` works and is tested, `estimate.py` is wired to use it — and no
   call site builds one. So the payback block stays absent even with P-5 fixed.
   Wiring it changes what every scenario reports, so it is a decision.
2. **Both `requirements.lock` files are missing.** `check_lockfile.py`:
   *"9 direct pin(s) and no record of the transitive versions that ran"*, and 3
   for the UI. Producing them is a `pip freeze` against a chosen environment and
   a call about reproducibility policy.
3. **`DOCUMENTATION.md` line 3 claims "1,835 tests passing."** The suite
   collects ~2,600, and 138 were failing when this started.
4. **`products_present` is a misnomer.** It now holds `field=value` pairs across
   whatever dimensions a lever constrained. Renaming it is a response-contract
   change; nothing in `analyst_ui` reads it today.
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
- A CONTRADICTED fact suppressing a good one — no longer failing.
- Lever eligibility and right-sizing — no longer failing.
- The certificate test, `acknowledge()`'s `case_id`, the retired lever
  vocabulary, and 126 mechanical fixture repairs.
