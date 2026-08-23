# Full audit — Network Cost Transformation Workbench, build 4.7.26

**Target:** the whole bundle. 30 application modules (5,378 lines), 9 interface modules
(864), 10 test modules (3,672). 36 routes, 19 tables, 267 tests.
**Method:** systematic sweep rather than an attack on the newest delta. The four prior
audits each went after recent changes; this one asks what was never looked at.
**Result:** 2 high, 7 medium, 6 low, plus a coverage gap that matters more than any
individual finding.

> **F-01 to F-05 closed in build 4.8.0.** Reconciliation is implemented as far as it can
> be without a provider integration and says plainly where it stops; identifier lookups
> return 404 rather than 500; six raw-body routes have validation models; the interface
> and the two untested domain modules now have tests. F-06 to F-15 remain open.

---

## The limit of this audit, stated first

**180 of the 267 tests have never executed.** Neither has the application. I can audit
structure, logic, consistency and claims. I cannot audit behaviour. Everything below is
derived from reading and analysing the code, and the two defects found by *running*
anything — the compose duplicate key and the bad `COPY` path — were both invisible to
four rounds of this kind of review.

That is the finding to weigh above the others: the review method is exhausted, and the
next real information comes from `make test`.

---

## HIGH

### F-01 — §7.2E provider usage reconciliation is a table, an endpoint, and no implementation

`audit.usage_reconciliation` is **written by nothing and read by nothing** — the only
table in the schema with neither. `GET /v1/integrity/reconciliation` aggregates
`audit.llm_run` and returns `status: EXPECTED_PENDING`, which reads as "the scheduled job
has not run yet". There is no scheduled job. There is no code that would ever write a
reconciliation row or move that status.

This matters more than an unused table because of what the control was for. §7.2C names
provider-side reconciliation as **the control of last resort** — the one that detects
fabrication the application cannot detect about itself, because it compares against a
record the application does not control. C2-09's fix explicitly leaned on it: the request
identifier was justified as the handle that makes attestation a spot check. The handle
exists; the check does not.

Nothing in the bundle is *wrong* as a result — the attestation endpoint is honest that its
counts are the system's own claim. But an integrity story that rests on an unimplemented
control should say so at the point of the claim, and `EXPECTED_PENDING` implies pending
work rather than absent work.

**Fix:** either implement the scheduled comparison against each provider's usage API, or
change the status to `NOT_IMPLEMENTED` and remove the table. Leaving a plausible
placeholder is how §7.2E ends up believed.

### F-02 — 24 of 36 routes return HTTP 500 for a bad identifier

Nine `.one()` calls resolve caller-supplied identifiers. SQLAlchemy's `.one()` raises
`NoResultFound` on a miss, which FastAPI renders as a 500. So:

```
GET /v1/outside-in/simulations/does-not-exist   -> 500
POST /v1/outside-in/cases/{unknown}/estimates:run -> 500
```

A 500 tells a caller the server is broken. A 404 tells them their identifier is wrong.
Both the Streamlit client and any future integration will treat these differently, and the
client currently surfaces a 500 as an opaque error string.

More broadly, **24 of 36 routes touch the database with no error handling at all**. Most
are reads where the failure mode is this same shape.

**Fix:** a small dependency that resolves a case, run or fact by id and raises 404, used
by every route that takes one. Roughly twenty lines, and it removes the whole class.

---

## MEDIUM

### F-03 — Six routes accept a raw body with no validation model
`clear-rights`, `resolve` (conflicts), `corroborate`, `preflight:run`,
`preflight:acknowledge` and `domain-dispositions` take `Body(...)` directly. The typed
`…In` models used elsewhere give length limits, enum constraints and a 422 with a field
path; these give a `KeyError` and a 500. `set_dispositions` in particular indexes
`r["domain_no"]` on a caller-supplied list.

### F-04 — The entire Streamlit interface is untested
Eight interface modules, 864 lines, **zero test references**. The client wraps every API
call and interprets error shapes, and the pages gate one another — page 6 depends on
simulation state, page 3 on pre-flight acknowledgement. None of that is exercised. C2-04
(the API enforcing a header the UI never sent) was precisely this gap, and only the
contract test now guards the one instance found.

### F-05 — `domain/preflight.py` and `domain/entity_resolution.py` have no tests
Two application modules with no test reference at all. Pre-flight is the gate that
prevents a V0 running before intake is complete — a control whose failure mode is silent
permissiveness — and entity resolution is the step whose whole purpose is refusing to
auto-select.

### F-06 — One session is opened outside a context manager
35 of 36 routes use `with S() as s:`. One does not, and `api.py` has one `SessionLocal()`
with no matching `close()`. Under load that leaks a connection per call.

### F-07 — 18 `except Exception` handlers, one of which swallows silently
Broad handlers are defensible at a boundary and are used deliberately in several places
(reclaim, health, pin reading). But 18 is enough that a genuine error is likely to be
absorbed somewhere, and the four audits found three separate controls that failed
silently. One handler discards the exception entirely.

### F-08 — Three functions are defined and never called
`config.is_production()`, `db.init_db()` and `estimate.known_fact_refs()`. Small, but this
is the fifth round in which unreferenced code has appeared, and two prior rounds found
that the unreferenced version was the one being *tested*.

### F-09 — `config.VALID_ENVIRONMENTS` is read only by the module that defines it
The tuple constrains `environment()` internally and is exposed as though it were the
canonical list. Nothing else consults it, so a caller comparing against environments has
no shared definition — the shape that produced C2-04.

---

## LOW

| # | Finding |
|---|---|
| F-10 | `README.md` is 71 KB of accumulated change log. The operational instructions a first-time reader needs are buried behind twenty build notes; the audit trail belongs in `docs/` |
| F-11 | No `.dockerignore`, so the whole tree including `.git` and `tests` enters both build contexts. Harmless at this size, wasteful, and it puts files in the UI image that have no business there |
| F-12 | `_version.py` carries a build number that `VERSION` also carries. Two sources, already diverging in principle |
| F-13 | Money is `Decimal` throughout the engine, but several API responses cast to `float` for JSON. Display-only today; a float that re-enters a calculation would not be |
| F-14 | No index on `simulation_run.status`, which `backlog()` and `_next_waiting()` scan on every submission |
| F-15 | The four audit documents are in the repository at `docs/` with all findings closed, but no document states the *current* posture — a reader has to reconstruct it from four rounds |

---

## What holds up

- **The integrity spine is sound.** Liveness proof, transport pinning, execution-mode
  binding, the promotion bar on simulated values, the coverage gate and the governed
  policy layer all survive re-examination.
- **No governed constant remains** in the domain layer; the policy validator rejects
  incoherent weights, inverted bands and impossible floors.
- **No test asserts on source text** — checked again across all ten modules.
- **Decimal arithmetic is correct** in the engine, including the conservative range pairing
  and per-layer lever compounding.
- **Simulation determinism holds**, including byte-identical resumption from a checkpoint.
- **Secrets hygiene is clean**: no key-shaped strings anywhere, `.env` gitignored,
  `.env.example` carries empty values.
- **Build configuration is now checked before the build**, which is the only reason the
  last two failures cannot recur.

---

## Remediation order

**Before anyone relies on the integrity story:** F-01. An unimplemented control that
reports `EXPECTED_PENDING` will be read as implemented.

**Before any non-Streamlit client:** F-02 and F-03. A 500 for a wrong identifier is
indistinguishable from a broken server.

**Before trusting the interface:** F-04. 864 lines, zero tests, and the one defect found
there was found by a user running it.

---

## What five rounds have shown

| Round | Shape of the worst finding |
|---|---|
| 1 | Controls that could not fail (source-grep tests, forgeable liveness) |
| 2 | Controls written and never read; a test harness that destroyed data |
| 3 | Two implementations, the tested one not the wired one |
| 4 | Two correct fixes that disabled each other |
| 5 | **A control that is a table, an endpoint and no implementation** — and a review method that has stopped finding new kinds of defect |

The first four rounds each found a *new* shape. This one mostly found more of the fourth
and second, plus scope that had never been examined at all — the interface, the error
paths, the routes.

That is the signal to stop reviewing. Reading the code has produced 67 findings across
five rounds; running it produced two more in ten minutes, both in configuration that
static review had passed dozens of times. **`make test` is the next audit**, and it will
be a better one.
