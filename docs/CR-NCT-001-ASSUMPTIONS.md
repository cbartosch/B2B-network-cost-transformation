# CR-NCT-001 · assumptions register

Every value introduced by this change request that is **not** sourced, with
what it is, why it was set where it was, and whose signature it needs before
the output goes outside.

CR-NCT-001 §4 principle 1: nothing here is invented to fill a gap. Each line
is either a decomposition of a value that was already governed, or a
`DECLARED_UNKNOWN` that was deliberately not modelled.

## Status

| | |
| --- | --- |
| Owner sign-off | **obtained** — Christian Bartosch, 2026-10-12 |
| Assumed parameters signed | 13 of 13 |
| Safe for internal review | yes |
| Safe for external use | see below — signing the assumptions does not clear the set on its own |

**What the signature covers.** The thirteen values in the tables below:
the one-time cost component shares and reference density (CR-04), the
savings-accrual and cost-spread conventions in the rollout (CR-05), and the
per-evidence-class range multipliers and the unresearched-domain
coefficient (CR-06). Each is a judgement with no source, which is why it
needed a name against it.

**What it does not cover**, and what still stands between this set and an
external reader:

| | |
| --- | --- |
| **CR-03 is not implemented** | There is no plausibility check on any baseline. The validation gate reports this as NOT CHECKED HERE rather than passing it. A signature on the assumptions does not create the benchmark file. |
| **Every estimate is band D — Indicative** | Outside-in, from public evidence, `NO_CONTACT`. That is a property of the method, not of the parameters, and no signature changes it. |
| **The four open items below** | These need *values*, not approval. They are unaffected by this sign-off. |

Signing a parameter is attesting that the value is a reasonable judgement
to publish under, not that it is measured. Each remains `ASSUMED` in the
output and is reported as such.

---

## CR-04 · one-time cost build

The per-site reference cost (400 / 900 / 1800) was already governed and is
unchanged. What is new is the split of it into work that scales with
circuits and work that scales with sites.

| parameter | value | class | rationale | signed |
| --- | --- | --- | --- | --- |
| `one_time_share_hardware` | 0.35 | ASSUMED | CPE and a switch port are per access circuit, not per site. Largest single component because it is the only one with a hardware bill. | ☑ CB 2026-10-12 |
| `one_time_share_migration` | 0.25 | ASSUMED | Cutover labour and test are per circuit: a dual-access site is cut over twice. | ☑ CB 2026-10-12 |
| `one_time_share_integration` | 0.20 | ASSUMED | Configuring and proving a site happens once however many circuits land in it. | ☑ CB 2026-10-12 |
| `one_time_share_project_management` | 0.20 | ASSUMED | Programme overhead of touching a site at all — survey, scheduling, acceptance. | ☑ CB 2026-10-12 |
| `one_time_reference_circuits_per_site` | 1.25 | ASSUMED | The density the reference cost is taken to assume. A seeded estate runs about 1.3; 1.25 is the round figure the four shares were set against. | ☑ CB 2026-10-12 |

**The shares must sum to 1.0** and `TransitionPolicy.validate` refuses a set
that does not. They divide a reference cost; a set summing to anything else
is losing money or inventing it, and every individual value would still look
reasonable.

**Level-preserving by construction.** At the reference density the build
reproduces the reference cost exactly — a 400-site estate drawing 500
circuits still costs 400 × 900. This adds structure without moving the
governed level, which is the difference between decomposing a number and
re-tuning one. Pinned by
`test_the_build_reproduces_the_reference_cost_at_the_reference_density`.

### Deliberately not modelled

| dimension | treatment | why |
| --- | --- | --- |
| Country | `DECLARED_UNKNOWN` | No sourced per-country transition cost exists here. A factor invented to vary it would read as evidence. |
| Target architecture | `DECLARED_UNKNOWN` | Same. The scenario already differs in what it saves; making it differ in what it costs would need a source nobody has. |

Both are reported in `one_time_cost_build.not_varied_by` on every estimate,
so the absence is visible rather than implied.

### What is *not* assumed

`circuits` come from the simulated estate — whether each site drew a backup
product — and carry origin `SIMULATED`. Site counts come from the footprint
and carry its own provenance. Neither is a judgement introduced here.

One caveat recorded in the code and worth repeating: the simulation
publishes at most 5,000 estate rows, so for larger estates the circuit
**density** is measured on a sample and applied to the full footprint.
`circuit_density_sampled_sites` reports how many sites of that archetype the
density was measured on. A density from 1,000 of 16,000 stores is a weaker
claim than one measured on all of them, and the field says which.

---

## CR-05 · programme and payback

No new assumed parameters. The wave model reuses CR-04's reference density
and the governed `sites_migrated_per_month`; what changed is the unit
capacity is expressed in.

| decision | class | rationale |
| --- | --- | --- |
| Capacity in **circuits** where the estate mix is known | DERIVED | A cutover is per circuit: a dual-access site is cut over twice. Converted at the reference density, so at that density it reproduces the governed site rate exactly. |
| Capacity in **sites** where no mix is known | GOVERNED | Converting without circuit information would assert the estate runs at the reference density. That is a claim, not a default, so a caller without a mix still gets `ceil(sites / 120)`. |
| Savings earned on circuits live **at the start** of the month | ASSUMED | The month a site is cut over is the month it is disrupted, not the month it pays. The conservative reading. |
| One-time and dual-running spread **pro-rata with migration** | ASSUMED | Cost lands when the work happens. The alternative — all cost in month one — would understate payback. |

**A consequence worth stating.** Expressing capacity in circuits means a
simple estate migrates faster than the governed site rate: McDonald's 16,406
stores draw about 1.04 circuits each, below the 1.25 reference, so the
programme falls from 137 months to 114. That is the model's claim and it
follows from the unit change — it is not a tuning. An owner who believes
capacity is genuinely per *site visit* rather than per circuit should say so,
and the `in_circuits` switch already exists to express it.

### Deliberately not modelled

`pilot_wave`, `capacity_ramp` and `site_dependencies`. CR-NCT-001 §9 lists
wave parameters as owner inputs and none is sourced. `parallel_waves`
defaults to 1 and is the parameter a delivery plan drops into without code
changes. All three are named in `programme.not_modelled` on every estimate.

---

## CR-06 · evidence-based ranges

The rate card's own band is real and is kept. These widen it for what the
card cannot see. All are judgements with no source — the CR asks for them
documented with rationale, which is what this table is.

| parameter | value | class | rationale | signed |
| --- | --- | --- | --- | --- |
| `widen_evidenced_public` | 1.00 | FIXED POINT | A fully evidenced estimate is reported at exactly the card's width. The scale has a fixed point rather than a floor somebody chose, and `validate` refuses any other value. | ☑ CB 2026-10-12 |
| `widen_client_confirmed` | 1.15 | ASSUMED | First-party and not independently checkable; internal records go stale and the person answering may not be the one who knows. | ☑ CB 2026-10-12 |
| `widen_derived_public` | 1.20 | ASSUMED | A figure computed from evidence carries the evidence's error plus the derivation's. | ☑ CB 2026-10-12 |
| `widen_analyst_entered_scope` | 1.35 | ASSUMED | A scoped figure nobody sourced. Wider than derived, narrower than a pure benchmark because somebody chose it for this estate. | ☑ CB 2026-10-12 |
| `widen_benchmark_prior` | 1.40 | ASSUMED | A governed rate for a population, applied to one company. The card's band describes dispersion *within* the benchmark, not whether the benchmark fits. | ☑ CB 2026-10-12 |
| `widen_analyst_asserted_prior` | 1.50 | ASSUMED | An unverified recollection. Weaker than a benchmark, which at least has a published basis. | ☑ CB 2026-10-12 |
| `widen_simulated` | 1.55 | ASSUMED | A drawn value. The widest, because nothing outside the model attests to it. | ☑ CB 2026-10-12 |
| `widen_unevidenced_domain_share` | 0.50 | ASSUMED | Coefficient on the unresearched-domain share. At 0.5, an estate with no domains evidenced is reported 50% wider than one fully evidenced, before the origin term. | ☑ CB 2026-10-12 |

**Two terms, because they are two different ignorances.** The value-weighted
origin mix takes the *weaker* of each component's quantity and unit-cost
origin — a perfectly evidenced site count priced off a benchmark is only as
good as the benchmark. The coverage term is scaled by the share of
agent-routed domains that returned no evidence, which no component origin can
see: price and quantity may both be benchmark-solid while the estate they
describe was never checked.

**The base never moves.** Widening spreads the band about it. A version that
moved the base would be re-forecasting under the name of honesty, and a test
pins it.

**An origin nobody mapped takes the widest multiplier**, not 1.0. An
unrecognised origin is one this policy has never been asked about, and
treating it as evidenced would let a new origin silently narrow every band
that used it.

### What this does to the sample

`low/base` spread went from 0.688–0.735 to 0.543–0.629 — roughly double the
variation, with the 14-domain companies clearly widest. It remains somewhat
clustered because all twenty genuinely *are* similarly evidenced: every one
is ~85% `ANALYST_ENTERED_SCOPE` quantity on 100% `BENCHMARK_PRIOR` pricing.
That residual clustering is a true property of the set, not a defect in the
widening.

---

## CR-07 · savings build

**No new assumed parameters.** The compounding build was already correct and
the four invariants pass on it unchanged — they confirm behaviour rather
than repair it. What was missing was attribution and reporting.

| added | why |
| --- | --- |
| Per-lever `saving_low` / `saving_high` | The scenario published a band and the levers underneath it published a point, so the band could not be traced to the levers that produced it. |
| `saving_on_evidenced_baseline` / `saving_on_unevidenced_baseline`, per lever and per scenario | A saving on drawn value is not one anybody can bank. On small campus estates `SIMULATED` is a quarter to a third of the baseline — Siemens 0.375, Volkswagen 0.261 — so the headline was substantially a saving on drawn value, reported as though measured. |
| `best_scenario_reason` | The choice was made in the summary builder by largest base saving and recorded nowhere. |

**Unevidenced is taken on either axis:** a drawn quantity priced from a real
card is still drawn, and a counted site priced from a drawn rate is still
drawn. Same "weaker input governs" rule as CR-06.

### F9 — documented, not removed

CR-07 asks that a size relationship in saving percentage be removed or
explained. It is real (Unilever 21.6% at 48 sites against Shell 15.1% at
5,995) and the cause is **lever mix, not evidence**: small campus estates
carry proportionally more platform and overlay value (L2/L4) where the
seeded levers bite hardest, while branch-heavy estates are dominated by
access circuits (L0) with lower lever reach.

It is a property of the lever set against the estate shape. Treating it as a
defect and flattening it would be tuning the model to a expectation about
its own output, which §4 principle 2 forbids.

---

## CR-08 · confidence breakdown

**No new assumed parameters.** F10 says the breakdown is missing; it is not.
`confidence.compute` has always published the three components, the ceilings
it applied and the weighted figure. Two real gaps remained:

| gap | fix |
| --- | --- |
| The **weights** were not published, so `overall` could be read but not reproduced | `weights`, `component_cap_headroom`, `band_floors` and a one-line `arithmetic` string are now in the output. A reader holding the JSON and nothing else can check the score. |
| `summary.csv` carried only `overall` and `band` | The three components, the weighted figure, the weights and the ceilings applied are now columns. |

**What the breakdown immediately shows.** `realization` is the binding weak
component on every company in the set (0.174–0.196), not the baseline
(0.346–0.358). A reader comparing two companies previously saw two scores
and no way to tell which part of either was weak — and the part that is weak
is the same part every time, which is a fact about the model rather than
about any company.

**Process is not evidence**, and that is now pinned rather than assumed:
neither `research_minutes`, `research_sources`, `queries_used` nor
`captures_used` appears anywhere in the confidence module, and
`compute`'s signature is asserted to take only evidence and scope. An agent
that searched for an hour and found nothing has not made an estimate more
certain, and a model that rewarded effort would reward the wrong thing.

Reproduction is tested across 54 parameterised cases — three baselines,
three target costs, three realizations, two simulated shares — recomputed
from the output dict rather than by calling the engine's own helper, which
would pass whatever the helper did.

---

## CR-09 · currency comparability

**No assumed parameters.** Every rate comes from `reference.fx_rate`.

`fx_rate_to_eur`, `fx_date`, `fx_evidence_grade` and EUR columns for
baseline, saving and one-time cost were already in the summary. What was
missing was that `reference.fx_rate` is **USD-quoted** — every row is
`USD->X` — so only USD had a direct line to EUR. CHF, GBP and anything else
went out as `DECLARED_UNKNOWN` while `USD->CHF`, `USD->GBP` and `USD->EUR`
all sat in the table, one division apart. Three of twenty companies could
not be compared.

A cross-rate is arithmetic on two governed rates, not a new number, and it
is reported as derived:

| | |
| --- | --- |
| `basis` | `cross-rate via USD` |
| `legs` | both source rates with their own dates |
| `as_of` | the **older** of the two — a rate is only as fresh as its stalest leg |
| `evidence_grade` | the **weaker** of the two — a derived rate must not read as better evidenced than either half |

So Swiss francs convert at `1.088875` dated `2026-01-01` and grade E, not at
the EUR leg's `2026-09-17` and grade B. A currency with no path to EUR is
still `DECLARED_UNKNOWN`.

**Local currency remains the source of truth.** The EUR column is derived
and the gate checks it: `local x rate = eur` for baseline, saving and
one-time cost on every row, within 0.01. Verified by mutation — a wrong
conversion fails the gate.

---

## Sample-run inputs · **not covered by the sign-off above**

Added to this register after it was signed, so they carry no signature. They
were documented in `samples/outside_in/README.md` from the start but never
listed here, which meant the register was not the single place it claims to
be — and the 2026-10-12 signature was given against a table that did not
contain them.

Both are inputs to the sample run rather than to the model, and both are
material: the OPS layer of every one of the twenty baselines rests entirely
on the first.

| parameter | value | class | rationale | signed |
| --- | --- | --- | --- | --- |
| `ops_cost_per_site_base` | **900 per site per YEAR** | ASSUMED | A flat figure applied to all twenty companies in the base currency. Nobody researched it; no domain produces it. **Corrected 2026-10-12:** this register previously said *per month*, which overstated the OPS layer twelvefold in anybody reading it. The model is right and page 6 labels the field "Ops cost per site per YEAR (not per month)" — somebody had been caught by this before. The register was the thing that was wrong. | ☐ |
| `users` | `sites x 12` | ASSUMED | A uniform proxy for headcount per site, used where the research returned no user count. Crude, and applied to a retail store and a data centre alike. | ☐ |

Neither is a finding. If either is wrong, every OPS baseline in the set
moves with it.

---

## Open, and blocking

**Unaffected by the sign-off above.** These need values or a decision, not
approval of a value already chosen.

| item | needed from the owner |
| --- | --- |
| **CR-03** sourced plausibility ranges | **Per-site tripwires are now seeded (21 rows), at your request.** They are **not a benchmark**: `source` says so in words, `evidence_grade` is `F`, `approved_by` is null, and the brackets span 5-30x so they can only catch an order-of-magnitude error. All 20 pass; verified by mutation that a grocery estate priced like a refinery flags HIGH and a chemical group priced like a kiosk flags LOW, and that either caps confidence. **Still needed:** a sourced range per metric. The two scope-sensitive metrics stay unassessable for any partial-scope estimate regardless. |
| ~~original CR-03 blocker~~ | **The machinery is built; only the numbers are missing.** `reference.plausibility_benchmark` ships empty, with columns for `low`, `high`, `unit`, `source`, `as_of` and `evidence_grade` — the source and date are not nullable. Insert a row per metric (and optionally per industry) and every estimate starts judging itself against it. Until then all three ratios are computed and published and the flag is `NOT_ASSESSABLE`. Inventing ranges would violate principle 1 and put a fabricated benchmark behind a flag that lowers confidence. |
| **promotion yield: 4.5%, and the funnel is now measured** | Of 1,012 quantities research produced across the twenty companies, **46 changed a priced footprint** (was 39). The losses, in order: **821 findings have no destination at all** — their label leads with neither an archetype nor a product because they are not footprint or price findings (revenue, carrier counts, FTTH coverage); **44 were found and then discarded** by the disclosure comparison as lower than the declared count; **~26 deduped** on `(country, archetype)`. ~~The `price` bucket has never fired~~ — **that measurement was wrong**: it covered only the 8 domains `HIGHLIGHT_DOMAINS` writes into `research.json`, which exclude domain 19, the pricing domain. Across all 17 researched domains there are **2,210 quantities, not 1,012**, and the price bucket now holds **33 candidates (was 10 before the classifier fix), 29 of them promotable**, covering 8 (country, bandwidth) pairs in ES, GB, NL and US from published Eurofiber, Virgin Media, BT and Lightyear figures. They land at `evidence_grade: C` against grade-E seed, `approved=False`, so a steward accepts them before anything prices. The `archetype` bucket is still genuinely empty. Qualitative findings are not wasted: they set each domain's disposition, which drives `evidenced_domain_share` → CR-06 widening. They move the uncertainty, not the level. |
| **`known_fact` is a live channel this workflow never uses** | `known_facts.register` writes rows and is reachable only through an API route — an analyst action. The sample driver *reads* `known_fact` into `research.json` and never writes one, so it is zero across all 20. It is the designed home for findings like "France FTTH premises coverage 95%", and nothing routes them there. |
| **the seeded rate card looks calibrated to US prices** | **The first observed evidence under it, and it disagrees.** 18 researched prices staged into `unit_cost_prior` at grade C, `approved=False`, collapsing to 10 distinct (country, product, tier) rows. Six are comparable to a seeded row; converted to USD at the seeded FX, **five European rows sit 26–73% below the seed and the one US row agrees within 5%** — GB MPLS 100 Mbps $268 against $1,000, ES DIA 1 Gbps $515 against $1,300, GB DIA 100 Mbps $248 against $335. Median gap −40%. Four are new coverage: ES DIA 100, NL DIA 200, US DIA 10G, US MPLS 1G. **Three caveats before acting.** Several sources are published list or entry prices, not negotiated enterprise rates — an entry price compared to a mid-band seed overstates the gap, while a list price compared to what a large buyer pays understates it. A single observed price is a point: `promote` stores low=base=high and a steward must widen it. And the FX used for this comparison is itself grade E, "indicative only". **Nothing prices on these yet** — the pricing query filters `approved=True`. Approving them would cut European L0 materially. |
| ~~the resolver names the sector and nothing reads it~~ | **Built.** `case.industry_as_resolved` (v69) carries the resolving agent's sector description, `entity_resolution.confirm` writes it, and `bics.industry_text_agrees` compares it to the taxonomy code — reporting only, never deciding, because free text cannot settle a taxonomy and the code drives bandwidth, resilience and the estate shape. Measured across the 27 comparable cases: **25 agree, 2 disagree.** One is the real error (UNFI's orphaned `WAREHOUSING` case; the corrected `WHOLESALE_DISTRIBUTION` one passes). One is a false alarm that cannot be fixed with tokens — Unilever's `HOUSEHOLD_PERSONAL_CARE` against *"Consumer Goods — FMCG"*, synonyms in two vocabularies sharing no word. One false alarm in 27 is the price of catching the one that mattered. The original finding follows. **A real finding, found by getting it wrong.** UNFI was specified as `WAREHOUSING` — third-party storage — when it is a wholesale grocery distributor. The two codes share a shape (`distribution-led`) so nothing downstream differed, but they disagree on the archetype that *is* UNFI's estate: warehouse bandwidth **100 Mbps vs 1,000**, dual-access **0.81 vs 0.45**. <br><br>**The system had the right answer and discarded it.** `entity_candidate.industry` holds a sector description the resolving agent wrote — for UNFI, *"Grocery and Food Wholesale Distribution"*. `entity_resolution.confirm` copies seven fields onto the case and not that one, so `set_industry_if_absent` sees nothing from resolution, logs `SPEC_FALLBACK`, and its `resolution_said` field — the one put there to surface this — reports empty because the text never arrived. The spec's code is then checked only for membership in `archetype_bandwidth`: that it is *a* code, never that it is *this entity's* code. <br><br>**The evidence that a check would work.** Across the six new companies, five candidate strings agree with the spec code (*"Retail pharmacy / health & beauty"*→`DRUG_RETAIL`, *"Offices of Bank Holding Companies"*→`RETAIL_BANKING`, *"Package Delivery & Logistics"*→`PARCEL_LOGISTICS`) and the one that disagrees is the one that was wrong. <br><br>**Proposed:** carry `candidate.industry` onto the case as `industry_as_resolved`, and have `set_industry_if_absent` report it beside the code it chose. Free text against a taxonomy cannot decide anything automatically and should not try — surfacing the disagreement for a person is all it needed to do here. |
| ~~promotion keeps one row per (country, archetype), arbitrarily~~ | **Fixed: largest wins, never the sum.** Measured first — across 26 companies, 25 pairs carry several rows, and in **every one** the largest is right and the sum is wrong (Simmons 222 not 459; DHL 81 not 165; Tesco 3,829 not 4,680). Research returns a total alongside illustrative subsets, not a disjoint partition. Displaced rows are reported as `superseded_within_pair`. Five estates gained real evidence that write order had been discarding: BASF's German plants 40→54 and US 30→60, Siemens' German plants 35→95 — in each case a sourced total had lost to a one-site example that happened to be written after it. The one shape where largest undercounts, several regions with no total, is flagged via `parts_exceed_kept` rather than handled: nothing in the sample resembles it (closest 1.07×) and a rule for a case that has not occurred would be guessing twice. |
| **standalone ATMs are a site type nothing can supply** | `absolute_counts.ADDITIVE_ONLY` says a standalone ATM is its own site needing its own connectivity, arriving "as an explicit count from the analyst or from research" — and no such count could reach the footprint, because the unit gate rejects every ATM unit there is. The channel the design assumes did not exist. **Now it does**, narrowly: an ATM count promotes only when the label says standalone, off-premise, remote or non-branch, so a bare "total ATM estate" still stays out — most cash machines are inside a branch already counted. **No company in the set has such a count.** Simmons Bank returned zero ATM findings across all 17 domains, so its estate is understated by however many off-premise machines it runs, and no figure was invented to close that. |
| *(original finding)* | Research returns the same estate at several granularities. Simmons Bank's locations domain gave a 222-branch national total **and** a six-state breakdown — Arkansas 65, Texas 57, Missouri 47, Tennessee 45, Oklahoma 19, Kansas 4 — all typed `STORE`. `promote` deletes and reinserts by `(case, country, archetype)`, so the last one written wins: the estate kept **Kansas's 4** and discarded the 222. Summing them instead would have double-counted the same branches. Neither is right, and nothing reported the choice. **Mitigated** for this company by an `excluded` rule, since those branches are already declared as `BRANCH`; the general case — prefer the most complete row, or refuse a set that mixes a total with its parts — is open. |
| ~~the rate card must be one currency, which blocks the price channel~~ | **Fixed.** `currency.rate_table` builds a factor per source currency and `convert_prior` moves each row at its own; `assert_single_currency` stays for the case it was written for. A second blocker surfaced behind it: `fx_rate` is a star — every row USD→X — so EUR→CHF is a pair it will never hold, and refusing it blocked Novartis and Nestlé. Pairs absent from the table are now crossed through its pivot (read off the rows, not hardcoded), with **both legs recorded and the weaker evidence grade taken** — a chain is as good as its worst link. All 26 companies price from a card holding EUR and USD; `pins.fx` carries one entry per currency so a rerun reproduces. **Effect so far: Fresenius −3.9%**, its 150 Spanish circuits moving to the observed €159.99 DIA tariff. The remaining six promoted prices — four GBP, `US/DIA 100`, `ES/DIA 1000` — are now approvable and displace seeded figures rather than adding coverage, so each is a judgement about which number is right. |
| *(original finding)* | **Found by approving.** `promote` stores a researched price in the currency its source quoted — deliberately, because stamping every price USD put a EUR tariff into the card as dollars, a 7–8% error before anything else. But the estimate refuses a mixed-currency card: *"these figures are in ['EUR', 'USD'] and no conversion has been applied."* Approving two EUR rows broke **11 of 26 companies**; both were revoked and the set is whole. **Only USD prices are approvable today**, and the observed evidence that matters is not in USD: the GB and ES rows showing the seeded card 26–73% high are all EUR or GBP. The whole non-US price channel is blocked behind single-currency reconciliation. |
| **two prices approved, and they change nothing yet** | `US/DIA 10000` at $1,987 and `US/MPLS 1000` at $1,439, grade C, attributed, at the card's own ±25% band. No circuit in the 26-company set reaches either tier, so the set baseline is unmoved — these are coverage for circuits that do not currently exist. Eight promoted rows remain unapproved: four GBP, two EUR, and `US/DIA 100` (+5% against seed) and `ES/DIA 1000` (−60%), both of which displace a seeded figure rather than adding coverage. |
| **approving a point price would defeat evidence widening** | `promote` writes `low = base = high` for a single observation, correctly refusing to invent a spread. `estimate.widen` spreads a band by scaling the existing gap, so a zero-width range stays zero-width through every widening — an approved point price is immune to CR-06 entirely, a grade C observation presented as exact inside an outside-in estimate. **Approval is now where the band is set**: `approve_price` inherits `CARD_BAND_SHARE` (±25%, measured off the card — 280 DIA rows, 89 MPLS, 356 Ethernet all sit at exactly that) unless a band is stated. A zero-width band remains reachable and must be asked for. |
| **external audit, 2026-10-13: labels that over-claim** | An audit of the six newest companies raised `EVIDENCE_LABEL_CONTRADICTION` on **6 of 6 rows** — the export reported millions of saving on an *evidenced* baseline while every value-evidence share on the same row was zero. It was right: `UNEVIDENCED_ORIGINS` holds `SIMULATED` and `DECLARED_UNKNOWN` and nothing else, so an analyst-typed footprint and a grade-E rate both counted as evidenced, and UPS reported €6.0m of saving on an "evidenced" baseline that was a declared site count priced from a seeded card. **Fixed by renaming** to `saving_on_specified_baseline` / `saving_on_simulated_baseline` — the split is useful and the word was wrong. Also fixed: `RESEARCH_TELEMETRY_ZERO` on 5 of 6 rows, where a `--repromote` run exported 0 minutes beside 48 sources because timings measured the session rather than the case; prior timings now carry forward. |
| **external audit: labels still over-claiming** | **Not fixed, and each is a naming decision rather than a bug.** `COMPLETE_LABEL_WITH_PARTIAL_ENTERPRISE_SCOPE` (6/6) — `v0_status=COMPLETE` sits beside `scope_status=PARTIAL_COUNTRIES`; the audit asks it be qualified as declared-scope complete. `COMPLETE_WITH_PARTIAL_PRICED_SPEND` (3) — `priced_scope_status=COMPLETE` at 77–91% priced spend. `PAYBACK_BEFORE_PROGRAMME_COMPLETION` (UPS) — payback 8 months against an 11-month programme, because payback is steady-state rather than a period-by-period migration cash flow. `SCENARIO_SELECTION_OBJECTIVE_LIMITED` — `best_scenario` selects on maximum base-case gross saving, not client value, and the audit asks for `max_base_savings_scenario` or a risk-adjusted selection. |
| ~~external audit: no verification register~~ | **Added, and it reports the gap rather than closing it.** `samples/verification_register.csv` carries a dated entry per checked change — as-of date, site definition, evidence reference, named verifier — and `tools/check_footprint_verification.py` compares it against every footprint change in the published set. **15 of 61 changes carry an entry.** That is the true state and the useful output: the other 46 are explained by `footprint_provenance` and not independently checkable. `--strict` exits 1 on any gap, for a pipeline that wants the stronger rule. Verifying them removed **€5.3m of baseline across six companies**, and every removal was the same failure: research correctly counted something that is not the company's estate, wrote the disqualification into the finding's own label, and promotion carried only `(country, archetype, sites)` — so the words were discarded. Saint-Gobain's 820 divested merchants, BNP's 182 Fintro franchises, BASF's all-site-types total promoted as PLANT, UNFI's 4 DC *closures* added as sites, Siemens' 2016 pre-spin-off lower bound, UPS's 5,603 franchised Stores and UNFI's 60,000 *customer* locations. |
| *(original finding)* | `FOOTPRINT_CHANGE_WITHOUT_VERIFICATION_RECORD` on 5 rows, HIGH for Douglas (+266 sites, 24.8%). Research superseding a declared count is recorded in `footprint_provenance` with both figures and the source URLs, but there is no **dated verification register** with an as-of date, evidence reference and site definition — which is what makes a changed count auditable rather than merely explained. Douglas was verified by hand this session (the 432 is Douglas's own *Segment France (FR+Monaco)* across two FY publications, against a declared 170 that missed Nocibé) and that verification lives in a commit message, not a register. |
| **a site count records when it was true, and nothing reads it** | A price carries `expires` and `coverage.expired_price_share` reports how much of the estate is priced on a rate past it. A site count carries `as_of` and has **no equivalent** — it is written on every promoted row and read by nothing, so a count from 2002 enters the estate weighted exactly like one from this year and no output distinguishes them. `check_footprint_verification.py` now reports age against a 3-year cutoff: **8 of 61 changes are priced on evidence 3–24 years old.** The oldest found a real defect — Nestlé's German DC entered on a 2002 finding labelled an *IBM-era regional DC*, whose Swiss sibling carries the same date and the words *sold to Orllati*, and a third finding records no Nestlé-owned DC in France at all; that company's DC evidence describes an outsourcing estate since disposed of, and DE/DC is now excluded. The report is a question for a reader rather than a verdict: Shell's Amsterdam campus flagged at four years because its `as_of` is when the campus *opened*, not when somebody last counted — VERIFIED, not stale. **Still open:** three changes (Tesco IE/WAREHOUSE 2017, Nestlé FR/LARGE_OFFICE and FR/WAREHOUSE 2021) are old, single-source and unverified — though each now names the one page it was read from, which is what the next entry fixed. |
| ~~a row cited its domain's reading list, not its evidence~~ | **Fixed.** `promote` wrote `evidence.sources` — everything the research domain read across *all* of its findings — onto every row it produced, so a site count and a revenue figure from one domain carried the same seven or eight URLs. Nestlé's French office row cited a swissinfo piece about a German factory closing; its nine footprint rows shared 2 distinct citations between them. The list was never wrong, it just did not answer the question asked of it: *which document says this number?* Each quantity already carried the `candidates` it was triangulated from, each naming its own `source_url`, and `promotion._quantity_sources` now reads those. **Mean citation 8.0 URLs per row → 1.9, and Nestlé's nine rows now carry 8 distinct citations.** The Swiss DC rows cite the datacenterdynamics piece on Nestlé *selling* that data centre — the disqualifying evidence, finally attached to the row it disqualifies. Two rows cite nothing and should: Inditex DE/DC and FR/DC are the explicit negatives (*"no public evidence of an Inditex DC in Germany"*), 0 sites each. Lending those the pool would have made a dead end look sourced. The baseline does not move — a citation prices nothing — but verification stops being a search. |
| **a row with no date cannot be flagged at all** | Found by writing the check above. Comparing a missing `as_of` against a cutoff silently passes, so the first version reported a clean bill on the one row it could say least about. Undated rows are now listed separately: **Tesco IE/DC**, 1 site, no `as_of` of any kind. The same first attempt also read the first four characters as a year, which called `FY2025` and `FY2026 (Aug 2025 – Aug 2026)` undated — two real dates buried in the list of rows that have none. Dates are now matched as a four-digit year anywhere in the string. |
| **CR-05** wave parameters | Delivery capacity, sites per wave, parallel waves. The current `sites_migrated_per_month = 120` is governed but is a single global rate. |
| **CR-01** coverage thresholds | The CR proposes ≥80% of domains and ≥70% of baseline for `COMPLETE`. Not yet applied — see the rescope note, which keeps `priced_scope_status` measuring priced scope and adds evidence columns beside it. |
| **density now reaches the price — on 24 unsourced numbers** | `reference.density_cost_multiplier` scales the rate card by (product, band), and `unit_cost_prior.density_band` lets an observed band-specific rate outrank it. **93% of L0 spend across the sample now prices through a multiplier, and the set baseline rose 4.7%, 19 of 20 companies.** The directions are defensible and asserted in tests: cost follows the local loop, so dedicated products (Ethernet rural ×2.00, DIA ×1.80, MPLS ×1.70) vary sharply while shared ones barely do (mobile ×1.05, PON ×1.12); URBAN is pinned at 1.00 as the anchor; bands are monotonic. **The magnitudes are seed judgement with nothing behind them**, and they now move real money — Nestlé's baseline rose 60.9%. Replace them with quoted rates per engagement before any number leaves the room. |
| ~~tier substitution compounds with the rural multiplier~~ | **Closed.** The card jumped 1,000 Mbps to 10,000 with nothing between, so a 1,650 Mbps circuit paid the 10 Gbps rate — then ×2.00 for rural on top. 2 Gbps and 5 Gbps tiers are now interpolated from each country's own 1,000 and 10,000 anchors, geometric in both axes. **Nestlé −48.8%**, set −1.9%. 107 circuits move from a 6× overshoot to a 1.2× one. A 5 Gbps tier was added alongside and **removed on review**: it priced only the 31 circuits at 3,000 Mbps, which now round to 10,000 again. 54 circuits — at 3,000, 5,500 and 9,500 Mbps — still take the 10 Gbps rate, a 1.1–3.3× overshoot on 0.1% of the estate. Re-add by appending `(5000, 1000, 10000)` to `_INTERPOLATED_TIERS`; everything downstream reads that tuple. |
| **the interpolated tiers are derived, not sourced** | `price_basis = INTERPOLATED` on 178 rows, same `evidence_grade` as the anchors they sit between — a derivation is not worth more than its inputs. The *method* is checkable rather than asserted: predicting tiers the card already holds reproduces the seeded 250 within 0.7% median and the 500 within 1.3%, so it reproduces how the card was authored. The one tier it predicts badly is DIA's 300 at 14%, a real kink in that product, and nothing is interpolated there. Nothing is extrapolated past the top of a product's card: DIA and the broadband products stop at 1 Gbps, so a circuit above that stays visibly unpriced rather than resting on a tier with nothing holding it down. |
| **density barely reaches the economics** (superseded) | **Worth knowing before commissioning more work on bands.** No pricing table is keyed on density: `unit_cost_prior` keys on (country, scope_kind, product, cost_layer, bandwidth_mbps), and `platform_unit_cost`, `archetype_bandwidth` and `archetype_prior` carry no density column either. A rural site and a dense-urban site of the same type, country and bandwidth are priced identically. The band's only economic path is serviceability forcing a different bearer, and that fires on 575 of 50,369 sites — so authoring four sector-specific shapes and moving 2,315 sites into RURAL moved the baseline by **0.1%** on three companies and nothing on the rest. The estate is now geographically truthful and the model is largely indifferent to it. If rural access is genuinely more expensive, that belongs in `unit_cost_prior` as a density dimension; until then, band accuracy buys serviceability realism and almost no pricing accuracy. |
| **the four authored shapes** | `forecourt-network`, `clinic-network`, `merchant-network` and `agency-network` (industries.SHAPES) are **this repository's judgement, not sourced** — same standing as every other shape, and `approved_by` is `seed`. The shares are invented; what is defensible is the ordering each encodes: forecourts follow the road network, trade counters need yard space and sit off the high street, clinics follow the population, tied agencies follow it most closely. `agency-network` assumes a **tied-agent** insurer — a broker or direct insurer has no agency layer and belongs on office-centric. `clinic-network` makes a healthcare estate 78% small sites, right for a dialysis or outpatient operator and an overstatement for a pure acute-hospital group. Retune per engagement. |
| **density_mix** band quality | **Coverage is closed — 13,847 unbanded down to 23 — but the bands are template defaults, and the fill barely moved the pricing.** `BAND_LAYER_SYNONYM` resolves the nine `(industry, archetype)` pairs where research and the mix name one estate layer differently (Allianz's agencies as `STORE`, `INSURANCE`'s mix as `BRANCH`), and a legacy-code fallback routes `PARCEL_LOGISTICS` to `POSTAL_AND_PARCEL_NETWORK`. **The caveat:** of the nine, only `UNIVERSAL_BANKING→BRANCH` and `DIVERSIFIED_MINING→REMOTE_SITE` point at a layer authored for that sector. The other seven point at a generic template slice, so Shell's 2,578 forecourts now carry an office-centric branch distribution — urban-weighted, when a real forecourt network is road-weighted and far more rural. That is why closing 13,805 sites moved `SUBSTITUTED` by only 15. Carried as `basis: SECTOR_LAYER_SYNONYM` with `via_layer`, so it is distinguishable downstream. **Needed:** a real band profile for forecourts, clinics, builders' merchants and tied agencies — the four that are genuinely their own kind of site. |
| **density_mix** is nine templates | Separately, and worth knowing before trusting any of it: **73 industries resolve to 9 distinct share-vectors, and all 532 rows are `approved_by='seed'`.** `PARCEL_LOGISTICS` shares its vector with `GROCERY_RETAIL` and `HOTELS`; `HOSPITAL` shares with `AIRPORT` and `E_COMMERCE`; `INTEGRATED_OIL_GAS` is identical to `INSURANCE`. The industry dimension is close to decorative. This limits `propose_split` as much as the band fill, and the row `note` already says "seed starting position; retune per engagement" — nothing is mislabelled, but nothing is sector-specific either. |
| **CR-02b** country scope | **Done for the six global industrials** (BASF, Nestlé, Novartis, Siemens, Unilever, Volkswagen), widened to 8–10 countries each. The other fourteen are left alone deliberately: Tesco is GB/IE and Deutsche Bahn is DE, and those scopes *are* the business. The per-country split of each group total is an apportionment, not a published per-country figure — same `PUBLIC_DISCLOSURE` class the footprint already carried, and research supersedes any pair where it finds a sourced count at least as large. **Unsigned**, added after the 2026-10-12 signature. |
