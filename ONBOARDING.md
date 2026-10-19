# Onboarding — Enterprise Network Cost Transformation Workbench

A Stage 0 **outside-in estimator** for enterprise network cost. Given a client's name and a
site footprint, it produces a defensible current-state TCO and a savings range — and
**refuses** to produce one when it cannot support the number. That refusal is the design.
Most of the codebase exists to make the refusal trustworthy: attributed evidence, a chain of
gates, provider-issued proof for every LLM call, and a Decimal cost engine.

> **The numbers are indicative, not sourced.** `seed.py` ships placeholder reference priors.
> The arithmetic, gates and provenance are real; the unit costs are not. Replace them before
> any figure leaves the building. (`README.md` → "What this is, and what it isn't".)

Build: see `VERSION` (currently 4.272.x). `python tests/check_build_config.py` prints it.

---

## Get it running

Stack is Docker Compose: **`api_service`** (FastAPI, port 8000), **`analyst_ui`** (Streamlit,
port 8501), **`db`** (Postgres). On Windows `make` isn't available — `make.ps1` mirrors every
Makefile target.

```powershell
.\make.ps1 check     # validate build config — no Docker needed
.\make.ps1 up        # build + start the stack
.\make.ps1 test      # run the suite inside the api container
```
Linux/macOS: `make check`, `make up`, `make test`. Then open **http://localhost:8501** (UI)
and **http://localhost:8000/docs** (API).

**On a managed corporate network (BCG laptops):** if the build stops at
`verify_tls_before_build.py`, that check is *working* — it caught HTTPS re-signing (Zscaler)
before pip failed opaquely. Run `.\make.ps1 bootstrap-ca` (reads the Windows machine store,
needs no network), which rebuilds `--no-cache`. `.\make.ps1 tls-doctor` diagnoses per
endpoint without Docker.

**Without a provider API key:** everything except LIVE agent calls works. On the pre-flight
page choose **`DETERMINISTIC_ONLY`**; `LIVE` will correctly BLOCK on provider availability
and refuse to unlock the simulation.

---

## How the product works — a chain of gates, not a menu

Each step refuses until the one before it is satisfied, and each refusal *names* the open
condition. UI pages (`analyst_ui/streamlit_app/pages/`) map to the gates:

1. **Intake / entity resolution** — subject confirmed by a *named* person
2. **Known facts** — attributed, rights-checked, corroborated
3. **Pre-flight** — every BLOCK condition cleared and acknowledged
4. **Simulation** — seeded topology, reproducible from one pinned integer
5. **Domain dispositions** — all 24 input domains disposed
6. **Run V0** — coverage gate: publishes COMPLETE, PARTIAL, or nothing
7. **Savings recommendation** — the model proposes; the Decimal engine decides
8. **V1 questionnaire / stage advance**

**What drives the estimate:** topology + geography. `footprint [{country, archetype, sites}]`
→ products per site → priced from `reference.unit_cost_prior` × 12 + platform/user +
ops/site. The low/base/high spread is a Monte Carlo draw over dual-access (the only thing the
sim *decides* — hence only the backup layer is `SIMULATED`). **Not driven by** industry
(stored, read by nothing in the cost engine) or bandwidth (`unit_cost_prior` has no speed
dimension — `bandwidth_is_priced: false`).

**The controls are the point** (`README.md` → "The controls are the point"): fail closed
never downgrade; provider-issued proof (DB-enforced uniqueness); named attribution never a
role; governed reference data in `reference.threshold`, not code constants; distinct evidence
classes (`EVIDENCED_PUBLIC`, `CLIENT_CONFIRMED`, `BENCHMARK_PRIOR`, `SIMULATED`, …).

---

## Layout

| Path | What |
|---|---|
| `api_service/app/domain/` | the model — ~50 modules, one concern each (`estimate.py`, `promotion.py`, `simulation.py`, `confidence.py`, `coverage.py`, `money.py`, `research_briefs.py`, …) |
| `api_service/app/llm/` | the gateway, provider transport, and pydantic `schemas.py` (v2) |
| `api_service/app/{db,migrations,seed,jobs}.py` | schema, numbered migrations (also run at startup), reference seed, async jobs |
| `analyst_ui/streamlit_app/` | the operator UI, one page per gate |
| `samples/outside_in/` | 41 worked companies — each has `manifest / research / estimate_v0 / simulation.json`; `summary.csv` + `HIGHLIGHTS.md` + `docs/sample-set-review.html` are rollups |
| `tests/`, `tools/` | the suite (~100 files) and offline runners/shims |
| `docs/`, `DOCUMENTATION.md` | deeper design notes |

---

## Testing

Two paths, and the distinction matters:

- **`make test` / `.\make.ps1 test`** — the real suite (pytest + real SQLAlchemy/pydantic)
  inside the api container. **This is authoritative.** Use it before claiming anything green.
- **`python tools/run_pure_tests.py`** — offline pure-logic runner for a locked-down env with
  *no* pytest/SQLAlchemy/pydantic installed. It imports shims from `tools/offline_shims/` and
  runs only zero-fixture logic tests for real; engine/DB tests are skipped or can't run.

**Gotchas with the offline runner** (learned the hard way — see git history for PR #20):
- It runs on **Python 3.14** locally, where PEP 649 defers annotations. The shims must stay in
  step with the product's library usage, or whole modules fail to import.
- It **exits early on any import error, before printing failures** — so one stale shim name can
  hide every real failure. If it looks like "no failures," check `IMPORT ERR` is 0 first.
- It **can't distinguish a real logic regression from an engine-can't-run failure** and exits 0
  regardless. A healthy run today is ~369 passed / 0 import errors; the ~98 "failures" are all
  engine/JSON-schema fidelity gaps that need `make test`. Treat only *non-engine* failures as
  signal.

Useful audit targets: `make validate-flow` (what each stage writes is read by the next),
`make verify-domains`, `make audit-contract` (every field's unit/period/currency),
`make check-duplication`, `make end-to-end` (one estimate through the whole chain, no DB).

---

## Contributing — workflow & conventions

- **One fix = one small branch → one PR.** Branch names `fix/<slug>` or `feat/<slug>`. PRs
  target `main`; merged with **merge commits** (not squash), matching `git log`.
- **Never commit to `main` directly.** It's the default branch; branch first.
- **Pushing hangs on Git Credential Manager** on these laptops. Push with gh's helper:
  `git -c credential.helper='!gh auth git-credential' push -u origin <branch>`. `gh` is
  authed; `gh pr create` / `gh pr merge --merge` work normally.
- **Commit messages:** imperative, explain the *why*. End with
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` when pairing.
- **Release identity:** `VERSION` and `api_service/app/_version.py` must agree —
  `make check-identity` enforces it; set both with `make set-release`.
- **Reference data / policy constants** go in `reference.threshold` (seeded via `make seed`),
  never as literals in Python. `make seed` is additive and safe; it won't touch existing rows.

---

## Traps worth knowing before you touch the model

- **A field's name is not its meaning.** Units, periods and currencies are explicit for a
  reason (`make audit-contract`). An "annual rental" is a *rate*, not a term; "36 months" is a
  *term*, not a rate. Check `promotion.py`'s `rate_period` / `is_monthly_rate_unit` before
  assuming a number is monthly.
- **The `samples/` artifacts are regenerated outputs.** They move when the model or briefs
  change, and a regeneration is a *full pipeline re-run* (fresh research, new timestamps) — not
  a surgical diff. When you change classification/pricing, regenerate and **audit the sample
  diff** against your intent before committing (research refresh, consumer declines, and
  coverage shifts all ride along). Don't commit samples ahead of the code that produces them.
- **`reference.unit_cost_prior` has no bandwidth dimension** — don't "fix" a 100 Mbps and a
  10 Gbps circuit pricing identically without reading `README.md` → "What the estimate is
  driven by" first; it's deliberate and disclosed.
- **Fail closed.** A missing provider makes a LIVE run *fail*, by design — never add a silent
  deterministic fallback. Deterministic is a separate, explicitly requested mode.

---

## First-day checklist

1. `python tests/check_build_config.py` — confirm your build number.
2. `.\make.ps1 check`, then `.\make.ps1 up` (bootstrap-ca first if on a managed network).
3. Open the UI (8501) and walk one case through the gates; open `/docs` (8000).
4. Read a worked example end-to-end: `samples/outside_in/tesco/` (manifest → research →
   estimate_v0 → simulation).
5. Skim `README.md` and `DOCUMENTATION.md`; the README's "controls are the point" and "what
   the estimate is driven by" sections are the mental model.
6. Run `python tools/run_pure_tests.py` once to see the offline baseline (and its caveats
   above); run `make test` for the authoritative result.
