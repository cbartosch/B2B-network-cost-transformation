# Enterprise Network Cost Transformation Workbench

**Build 4.235.0** · schema 62 · `calc-1.14.0` · `sim-1.18.0` · 1,358 tests passing

An outside-in estimator for enterprise WAN and network cost. It takes a company
name and produces a defensible baseline, a savings range and a transformation
scenario — without access to the client's circuit inventory, and while saying
exactly how much of the answer it actually knows.

---

## 1. What this is for

A partner needs a number for a company they have never worked with, before any
data room exists. The honest version of that number has three properties, and
this system is built around them:

1. **It says what it does not know.** Unpriced scope is reported as unpriced,
   never quietly defaulted to zero or to an average.
2. **It refuses when it should.** An estimate priced on less than 40% of its
   own scope is not published, whatever the deadline.
3. **Every figure carries its provenance.** A rate is graded A to E, a site
   count names the fact it came from, and a converted amount records the
   exchange rate.

The system is deliberately unhelpful in one specific way: it will not produce a
plausible number when it does not have the evidence for one. Most of the design
follows from that.

---

## 2. Shape of the thing

```
  analyst_ui/          Streamlit interface, 10 pages, one per stage
  api_service/app/     FastAPI service, 70 modules, ~29,400 lines
    domain/            48 modules - all the reasoning lives here
    routers/api.py     110 HTTP endpoints
    llm/               provider gateway, prompts, response schemas
    db.py              43 tables across 7 Postgres schemas
    migrations.py      61 forward migrations, v2 to v62, no gaps
    seed.py            every governed default, as data
  tools/               22 command-line checks and utilities
  tests/               68 files, 1,358 tests
```

Nothing in `domain/` imports from `routers/`. The interface can be replaced
without touching the reasoning, and the reasoning can be tested without a web
server — which is how the offline test runner works at all.

### The seven schemas

| schema | tables | holds |
|---|--:|---|
| `outside_in` | 19 | cases, known facts, dispositions, footprints, estimates |
| `reference` | 13 | governed inputs: rates, thresholds, levers, regions, FX |
| `audit` | 4 | what ran, what it produced, what was rejected |
| `analysis` | 3 | derived outputs a person reads |
| `agent_runtime` | 2 | live agent runs and their provenance |
| `benchmark` | 1 | the observation vault |
| `engagement` | 1 | engagement-level record |

The split matters: `reference` is governed data a steward changes, `outside_in`
is one engagement's work, and `audit` is written and never edited.

---

## 3. The nine stages

The interface is a sequence because the work is. Each stage refuses to let you
skip the one before it when skipping would make the output dishonest.

| # | Stage | What happens |
|---|---|---|
| 1 | **Intake and entity resolution** | Name the company, resolve it to a legal entity, declare scope: countries, currency, price year, site-inclusion rule |
| 2 | **Known facts** | Register what is actually known — site counts, user counts, disclosed spend — each with a basis, a source and a rights status |
| 3 | **Pre-flight** | Nothing runs until the inputs are coherent. Produces a report that goes stale if the inputs change |
| 4 | **Domain dispositions** | 24 input domains, 17 researched by agents, each ending in a recorded disposition — including "searched and found nothing" |
| 5 | **Simulation** | Turn a site count into a circuit-level estate: archetypes, densities, bandwidths, dual access, serviceability |
| 6 | **Run V0** | Price it. Coverage gate decides whether it may be published |
| 7 | **Execution integrity** | What ran, what it cost, what was rejected and why |
| 8 | **Savings recommendation** | Levers, scenarios, transition cost, payback |
| 9 | **V1 questionnaire** | What to ask the client to move the estimate from grade E to grade A |
| 10 | **Benchmark vault** | Observations, their sources, and the bands derived from them |

---

## 4. The two estimation methods

**`BUILD_UP`** enumerates the estate and prices every circuit. It needs a
footprint.

**`ANCHOR`** starts from a disclosed spend line and a governed addressable
share, for the normal outside-in case where no site-level inventory is public.

Both run through the same levers, the same confidence model and the same
ceilings. **Neither is a fallback that fires on its own**, because a method that
switches itself produces a number whose basis nobody chose.

---

## 5. How a number is built

```
  footprint  ──►  simulation  ──►  serviceability  ──►  coverage
  (sites)         (circuits)       (can it be           (how much can
                                    delivered?)          we price?)
                                                             │
                     scenarios  ◄──  estimate  ◄─────────────┘
                     (levers)        (rates × counts)
                         │
                         └──►  transition cost  ──►  confidence
```

### Simulation

A footprint row says *80 sites in Germany*. That is not enough to price
anything: a store and a data centre are not the same circuit. Simulation
expands a site count into an estate using:

- **6 site archetypes** — `BRANCH`, `LARGE_OFFICE`, `WAREHOUSE`, `DC`,
  `STORE`, `CAMPUS`
- **estate shapes** per industry — `many-small`, `few-large`, `plant-centric`,
  `office-centric`, `network-centric`, `campus-centric`
- **density bands** — dense urban through rural, which drive what can actually
  be delivered
- **dual access probability** and **committed share** from the industry
  benchmark

It is an ensemble, seeded, and the median pass is the one that prices — so the
same case gives the same answer twice.

### Serviceability

170 rows saying which bearer is available in which country and density band. A
rural Ethernet tail that cannot be delivered is refused rather than priced; the
same site over PON is delivered. This is why coverage is not simply "do we have
a rate".

### Pricing

`match_prior` walks a scope ladder — the client's own invoiced rates first,
then country, then market band, then region:

```
  case rate  ►  GB  ►  EUROPE_WEST  ►  EMEA  ►  (refuse)
```

Each rung is a worse answer than the one above and the scope actually used is
recorded on every priced row. A committed service prices on its **CIR**, not its
bearer: a 1 Gbps port with a 300 Mbit CIR is a 300 Mbit circuit.

### Coverage — the gate

```
  effective coverage = min(value coverage, circuit coverage)

  ≥ 70%   publishable
  40-70%  publishable with a stated ceiling
  < 40%   REFUSED
```

Plus a **material country floor**: a country holding more than 10% of the
estate must itself be covered, so a well-covered aggregate cannot hide a
completely unpriced major market.

---

## 6. The rate card

**1,295 rates. 78 countries with their own card. 11 regional fallbacks.**

| source | rows | grade |
|---|--:|---|
| UK market survey, September 2026 | 6 | 5 at C, 1 at B |
| Supplied Global Access Pricing Workbook | 264 | C |
| Derived, interpolated or seeded | ~1,026 | E |

### Regions

242 countries — every ISO-3166-1 entry bar seven uninhabited — map to one of
eleven regions:

```
  EUROPE_WEST  EUROPE_CENTRAL  EUROPE_NORTH  EUROPE_SOUTH  EUROPE_EAST
  MIDDLE_EAST  AFRICA_NORTH    AFRICA_SSA    AMER          APAC
  EMEA  (the parent the eight EMEA bands fall through to)
```

A country with no card falls to its band; a band with no priced member falls to
its parent. The chain is recorded on the priced row, so a reader can see which
rung answered.

### Currency

Every seeded rate is USD. A case in another currency converts at a rate from
`reference.fx_rate`, chosen by the case's own `fx_convention` — `SPOT`,
`AVERAGE` or `BUDGET`. 17 rates, two of them sourced this month, one a currency
peg, fourteen indicative and labelled as such.

**A pair with no rate refuses.** Parity assumed would be invisible in the
result.

---

## 7. Evidence grading

Every figure carries a grade, and the grade is what the confidence model reads.

| grade | means |
|---|---|
| **A** | The client's own invoice or contract |
| **B** | A seller's published tariff — transactable |
| **C** | A benchmark somebody published and a person can check |
| **D** | A figure inferred from adjacent evidence |
| **E** | This repository's judgement |

The distinctions the system refuses to blur:

- **Absent is not zero.** Unpriced scope is reported by circuit count with its
  value marked unknown.
- **Budget exhausted is not "found nothing".** A domain that ran out of
  allowance is worth retrying; a domain that searched and found nothing is not.
- **Expired is not absent.** A rate that was true last year still prices and is
  reported as stale, because refusing would trade a stale number for unpriced
  scope.
- **A bound is not a point.** A source saying "over 100 sites" records
  `AT_LEAST`, and corroborating an asserted 340 against it succeeds rather than
  contradicting.

---

## 8. The research half

**24 input domains. 17 researched by agents, 7 analyst judgement by design.**

Each agent call carries a live web search plus an independent fetch of every
source it cites, so a domain takes one to three minutes and a full pass is most
of an hour.

Every call is:

- **Schema-enforced** — the response model is sent to the provider as a tool
  input schema, and the reply is validated on the way back
- **Bounded** — list and text limits keep a reply inside its token budget, and
  they *coerce* rather than reject, because a cap that throws away a complete
  answer is worse than the truncation it prevents
- **Recorded** — `agent_run` is committed before the call, so an in-flight run
  is visible while the interface is still blocked on it
- **Fail-closed** — a model that cannot produce a valid answer abstains, and
  abstention is a recorded disposition rather than an empty result

### The 24 domains

```
   1 Company and industry profile        13 Outage and performance evidence
   2 Location footprint                  14 Transformation announcements
   3 Site archetype assumptions          15 Site growth and shrinkage
   4 Bandwidth and traffic assumptions   16 Regulatory and sovereignty
   5 Remote-user population              17 Resilience assumptions
   6 Data-centre and cloud footprint     18 Market serviceability
   7 Current architecture hypothesis     19 Market unit prices
   8 Current vendor and product signals  20 Contract-duration assumptions
   9 Public cost evidence                21 Transformation costs
  10 IT spend proxy                      22 Currency, inflation and tax
  11 Operating-model cost                23 Northstar architecture scenarios
  12 Contract and sourcing events        24 Evidence and confidence metadata
```

---

## 9. Industry model

**49 BICS Level-3 industries**, each with a benchmark row: representative site
archetype, bandwidth, committed share, dual-access probability and criticality
tier.

This is what makes a pharmaceutical estate different from a supermarket one.
AstraZeneca and Henkel on an identical 120-site footprint differ by **2.76×**,
because one is half research campuses at 10 Gbps and the other is 80%
warehouses.

---

## 10. Running it

```powershell
docker compose up --build -d
docker compose exec api python -m app.seed --force
```

Interface on `:8501`, API on `:8000`.

### Behind a TLS-inspecting proxy

```powershell
.\make.ps1 bootstrap-ca      # exports the corporate CA, rebuilds without cache
.\make.ps1 tls-doctor-in-container
```

### Back up before you update

```powershell
python tools\backup_cases.py backup --out .\case-backups
docker compose exec -T db pg_dump -U workbench -d workbench > db-backup.sql
```

`bundle-in` now takes the case-level backup automatically. The `pg_dump` is
broader — it captures estimates and runs, which the case export deliberately
does not.

**Never use `docker compose down -v`.** It drops the volume and every case with
it.

### Overnight batches

```powershell
python tools\run_batch.py companies.csv --out results.csv
python tools\run_batch.py companies.csv --skip-research --out smoke.csv
```

Resumable, one company and one domain at a time, results written after each
company. Roughly six hours for ten companies.

---

## 11. Standing checks

All green at 4.235.0. Run them before believing anything.

| command | asserts |
|---|---|
| `python tools/run_tests_offline.py` | 1,358 tests, no database needed |
| `python tools/validate_flow.py` | every stage boundary agrees on what crosses it |
| `python tools/check_duplication.py` | no logic duplicated in seven known shapes |
| `python tools/verify_domains.py` | all 17 agent domains route, grade and store |
| `python tools/audit_reachability.py` | 8 dimensions: modules, routes, tables, columns, outputs, pages |
| `python tools/audit_framework_controls.py` | 16 governance controls |
| `python tools/audit_agent_formats.py` | prompt and schema agree, replies are bounded |
| `python tools/run_end_to_end.py` | one estimate through the whole chain |
| `python tests/check_build_config.py` | compose keys, COPY paths, undefined names |
| `make check-identity` | VERSION and `_version.py` agree |

`validate_flow` is the one that has caught the most: a dataclass decorator lost
in a refactor, a policy missing five class constants, a column name read from
memory rather than the schema, and a module shadowed by a local variable.

---

## 12. What this cannot do yet

Stated plainly, because a limitation you know about is a research task and one
you do not is a wrong number.

**No validation corpus.** Zero cases have been checked against an outturn. The
harness exists; the corpus is empty. This is the single largest gap.

**The card is mostly grade E.** 6 rates are sourced to a publication and 264
come from a supplied workbook. The rest are judgement. A German quote
corroborated the seeded DE rate to within a dollar; the UK card was found
overstated by about 1.5×. One check each way, on two of 78 countries.

**43 of 49 industry benchmarks are inert.** Each names a representative
archetype — `PLANT`, `DATA_CENTER`, `AUTONOMOUS_MINE` — that its estate shape
does not contain, so the criticality and committed share it carries are applied
to nothing. Two industries sharing a shape currently price identically however
different their benchmark rows. `campus-centric` was the first fix of this
class; the rest remain.

**No NPV.** Deliberate. Payback and annual saving only.

**Domain research is synchronous.** Seventeen domains block the interface for
most of an hour. The simulation already runs as a queued job with polling;
research does not, and it is the longer of the two.

**Authorisation is a shared bearer token.** No roles, no row-level security, no
OIDC. Acceptable on a laptop, wrong anywhere else.

**26 of 110 routes are named by no test.** They need a live database, and the
offline runner does not have one.

**No transitive dependency lock.** Requires a container to generate.

---

## 13. Design rules worth knowing before changing anything

These are the rules the codebase keeps re-learning. Every one is in the source
next to the thing it governs.

**Refuse rather than guess.** A missing rate, a missing FX pair, a coverage
floor breach — each refuses with a reason naming what to supply. The one
exception is an expired rate, which prices and says so.

**Report the degradation, never absorb it.** A substituted bandwidth tier, a
regional rather than national rate, a fallback convention — all recorded on the
row that used them.

**Governed data lives in tables, not code.** Thresholds, rates, levers, regions
and FX are seeded rows a steward can change without a release.

**A check that cries wolf gets switched off.** Several audits here were narrowed
after their first run: 54 findings became 12 when phantom classes were removed,
48 became 8 when the JSON schema was accounted for. Precision is what makes a
checker survive.

**Read the contract, do not remember it.** A column name, an enum member, a
field limit — every one of those has been got wrong from memory in this
codebase, and each mistake now has a static check.

---

*Generated at build 4.235.0. Figures in this document were read from the
repository, not recalled.*
