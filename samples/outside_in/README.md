# Outside-in sample estimates

Twenty large public companies, one per industry, run end to end through the
Stage 0 outside-in estimator: entity resolution, pre-flight, domain research,
simulation, and a published V0 estimate.

They exist so the estimator can be looked at working on more than one shape of
problem. A grocery chain, a parcel network, a branch bank, a plant-and-lab
estate and a remote mine site are different problems, and an estimator that
has only ever been exercised on stores is not one anybody has tested.

---

## What these are, and what they are not

**They are** modelled outside-in estimates built from public evidence by the
research agents in this repository, using the governed policies and seeded
reference data in this repository, on build `4.272.0`.

**They are not:**

- **Not client work.** No company named here is a client, was contacted, or
  supplied anything. Every case is created with
  `client_contact_status: NO_CONTACT`, which is what keeps `CLIENT_CONFIRMED`
  off every disposition in the set.
- **Not what these companies spend.** They are what this model estimates a
  network estate of the shape it could evidence would cost, at seeded
  benchmark rates. Nobody has checked a single one against an invoice.
- **Not advice**, about these companies or to them.
- **Not a benchmark.** Do not price a case from these numbers. The reference
  data they rest on is in `reference.*` and should be read there, where it
  carries its own provenance and approval state.

Every figure here is traceable to the file it came from, and every file
records what it rests on. If a number cannot be traced, treat it as wrong.

---

## Read the confidence before the number

Each estimate carries a confidence score and a band, and the band is the
headline, not the baseline. Governed in `reference.threshold`
(`confidence_policy`):

| band | floor | what it means |
| --- | --- | --- |
| A - Confirmed | 0.85 | — |
| B - Supported | 0.70 | — |
| C - Directional | 0.50 | — |
| D - Indicative | below 0.50 | the honest home for an estimate like these |

Expect **D**. An outside-in estimate with no client contact, a partly
researched footprint and benchmark pricing is indicative by construction, and
the model says so rather than rounding its own uncertainty away. A V0 estimate
is additionally capped by `stage_ceiling_V0_current_baseline = 0.55`, so no
run in this set can report a confident baseline however good the research is.

`coverage` is a separate axis and answers a different question: how much of
the declared scope got priced at all. A `COMPLETE` coverage with a `D` band
means everything in scope was priced, from assumptions.

---

## The footprint is a merge, and that is the biggest caveat

Site count is the single largest driver of the baseline, so it is worth
knowing exactly where it came from. Each `manifest.json` records every row
with an origin:

| origin | meaning |
| --- | --- |
| `RESEARCHED` | the agents found and sourced this count, and it was promoted |
| `SUPERSEDED_BY_RESEARCH` | a disclosed row research replaced; the research figure is recorded beside it |
| `PUBLIC_DISCLOSURE` | research did not reach this (country, archetype); the count is from public disclosure |

**Why not research alone.** The pilot run settled it. For Unilever the agents
returned seven rows totalling seventeen sites - five GB plants, four DE
plants, a couple of offices - every one a real sourced fact, and together not
an estate. It had no data centre and almost no offices, because nobody
publishes a list of them. Priced on its own it produced a baseline an order of
magnitude below the disclosed footprint. Next to a 3,900-site grocery estate
that reads as *"this company has a small network"*, which is not what the
research found. It is what the research could see.

**Why not disclosure alone.** That throws away the one part of the estate
anybody actually evidenced.

So a researched `(country, archetype)` replaces the disclosed row for that
pair, and pairs research did not reach keep theirs. Both are recorded. The
confidence model is unaffected by the merge - it reads evidence from the
dispositions, not from the footprint.

---

## Assumptions that are not research

Stated here because an estimate that hides its inputs cannot be checked. Both
are recorded in every `manifest.json` under `estimate_inputs`:

- **`ops_cost_per_site_base = 900`** (base currency, per site per month). A
  flat figure applied to all twenty. Nobody researched it.
- **`users`** is derived as `sites x 12`. A crude proxy, applied uniformly.

Neither is a finding, and the OPS layer of every baseline rests on the first
of them.

Seven of the twenty-four domains have no research agent routed to them -
3, 4, 5, 11, 17, 23 and 24 - so they are disposed `BENCHMARK_PRIOR`: this
estimate rests on the seeded priors for archetypes, bandwidth, remote users,
operating model, resilience, the northstar set and the confidence metadata.
`manifest.json` lists exactly which domains were researched and which were
benchmark-disposed, so the two are never confused.

---

## Layout

```
samples/outside_in/
  README.md          this file
  companies.json     the twenty specs: industry, scope, disclosed footprint
  summary.csv        one row per company - baseline, saving, payback,
                     confidence, coverage, research counts
  HIGHLIGHTS.md      what the research found, per company
  _cases.json        slug -> case_id, so a re-run resumes the same case
                     instead of re-buying research already paid for
  _run_log.json      which companies completed and which failed
  <slug>/
    manifest.json      inputs, footprint provenance, seed, build, mode
    simulation.json    the ensemble run and its pins
    estimate_v0.json   the published snapshot: current_tco, by_layer,
                       scenarios with transition, confidence, coverage
    research.json      per-domain dispositions, quantities, triangulated
                       bands, qualitative findings, conflicts, sources,
                       known facts, evidenced footprint
```

The manifest fields worth knowing:

| field | meaning |
| --- | --- |
| `domains_requested` | what the run asked for |
| `domains_researched` | what came back with an agent verdict — **the honest count** |
| `domains_fell_back_unanswered` | asked for, no verdict, disposed `BENCHMARK_PRIOR` so the case stays publishable |
| `footprint_provenance` | every footprint row, tagged `RESEARCHED` / `SUPERSEDED_BY_RESEARCH` / `PUBLIC_DISCLOSURE` |
| `mode` | `run`, `repair` or `repromote` — see below |

`domains_requested` and `domains_researched` are both recorded because the
first overstates coverage whenever a call fails, and a manifest that
overstates its own research is the thing this set is least allowed to do.

`estimate_v0.json` carries its own `pins`, so each snapshot is provenance for
itself rather than relying on this directory staying tidy.

---

## How this set was actually produced

Not in one pass, and the detours are part of what the artifacts mean.

**The provider went unreachable mid-run.** DNS inside the api container
stopped resolving `api.anthropic.com` for a stretch:

```
ProviderUnavailable: anthropic transport error:
  [Errno -2] Name or service not known
```

Every call in that window failed. The driver could not tell an unreachable
provider from an agent with nothing to say, so its safety net disposed the
affected domains `BENCHMARK_PRIOR` to keep each company publishable — and
because research skips any domain already carrying a disposition, that made
a transient fault permanent. Seven of twenty companies finished with zero
researched domains and the set averaged 6.7 of 17.

That became finding **P-14** and a fix: a failure now carries a typed
`failure_kind` and a boolean `retryable`, so a caller can tell
`PROVIDER_UNAVAILABLE` from `OUTPUT_INVALID` without parsing prose.

**A `--repair` pass recovered it**, re-researching only the domains the net
had disposed and keeping every domain an agent had actually answered.

**Research was reaching the estimates and being discarded.** The promotion
classifier routed a finding to the footprint only when its label was
*nothing but* an archetype name — while the research prompt asks the agent to
"say which mapping you chose and why". A well-behaved agent returning
`SERVICE_POINT - Iberdrola customer service and sales points` was classified
`unclassified` every time. Iberdrola: 103 findings, 0 classified, priced
entirely from public disclosure despite seventeen researched domains.

That became finding **P-15**. A `--repromote` pass then re-offered every
company's existing findings to the fixed classifier — no provider calls —
and re-ran the footprint merge, the simulation and the estimate.

**What this means for reading the set.** Coverage is uneven and each manifest
says exactly what its own is. A company with a low `domains_researched`
count is not a company with less to find; it is one whose run caught the
outage. The confidence score does not know that — it reads evidence from
dispositions, and a benchmark disposition is honestly weighted as a
benchmark — so a thin company reads as *indicative*, which is correct, for a
reason the score cannot state.

---

## Reproducing a run

The stack must be up and seeded, and `ANTHROPIC_API_KEY` must be set - these
are LIVE provider calls with hosted web search.

```
docker compose up -d
docker compose exec api python -m app.seed

docker compose cp samples/outside_in/companies.json api:/tmp/samples/companies.json
docker compose cp tools/run_samples.py api:/tmp/run_samples.py
docker compose exec api sh -c 'cd /app && PYTHONPATH=/app \
    python -u /tmp/run_samples.py --out /tmp/samples'

python tools/build_sample_summary.py --out samples/outside_in
```

`--only tesco,basf` runs a subset, `--domains 1,2,6` researches fewer domains
(everything else is disposed `BENCHMARK_PRIOR`), `--force` re-runs a company
that already has results. A company that fails is logged and skipped; the set
continues.

Three modes, and the difference is what they spend:

| mode | spends |
| --- | --- |
| *(default)* | researches domains with no disposition |
| `--repair` | re-researches **only** domains the fallback disposed, keeping every domain an agent answered |
| `--repromote` | **nothing** — re-offers findings already paid for, then re-merges the footprint, re-simulates, re-estimates |

`--repromote` refuses a company with no confirmed case in `_cases.json`
rather than quietly starting a fresh one, which would spend exactly the money
the mode exists to avoid.

`tools/finish_samples.sh` chains a full recovery: wait out a repair pass,
copy the artifacts to the host, restart the api to deploy a fix, copy them
back, re-promote. The copies are not optional — `/tmp` inside the container
does not survive a restart, and that is where the artifacts live.

**Determinism.** Seed `20260101`, ensemble 25, for every company - so a
difference between two of them is the company and not the draw. The
simulation reproduces exactly. **The research does not:** it is a live model
with live web search, and re-running it will find different pages, cite
different sources and sometimes reach different counts. `research.json` is a
record of one pass, not a repeatable fixture.

**Cost.** Seventeen agent-routed domains per company, each a search-carrying
call of roughly two to ten minutes. Twenty companies is around 340 such calls
and several hours of wall clock even run five-wide. Do not re-run the set
casually.

---

## Known limits in the model these runs inherit

- **Serviceability density is an open decision** in
  `docs/TEST_SUITE_FINDINGS.md` (D-1), and it affects estimate numbers. These
  runs are stamped with build `4.272.0` and will need regenerating when it is
  resolved.
- **`evidenced_value_share` reported `0.0000`** on the pilot despite a
  researched-and-promoted footprint, which suggests promoted evidence is not
  reaching the confidence model's origin accounting. If it is a defect, these
  confidence scores are understated rather than overstated - the safe
  direction, but not the correct one.
- **`count_source` is accepted by the footprint API and never read** by the
  domain layer, so per-row provenance could not be carried into the
  simulation and is recorded in the manifest instead.
- **A research call that fails for an environmental reason still settles the
  domain** unless the caller handles it. P-14 makes the reason legible
  (`failure_kind`, `retryable`); it does not change that a disposition, once
  written, suppresses re-research. That is what `--repair` is for, and a
  caller without one will quietly bake an outage into its results.
