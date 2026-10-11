# CR-NCT-001 · CR-00 root-cause note

Against build `4.272.0`, the committed sample set, and the code that produced
it. Every claim below is checked against the artifacts or the source, and the
check is named so it can be repeated.

CR-00 asks me to say where the CR's inferences are wrong. **Three are, one
materially**, and one more attributes a real problem to the wrong component.
Acting on them as written would add a reconciliation field that reports a
false gap on half the set, and rebuild a breakdown that already exists.

| # | Verdict | Where it actually comes from |
| --- | --- | --- |
| F1 | **Confirmed** | `transition.one_time()` × governed threshold, not a code constant |
| F2 | **Confirmed** | `transition.programme_months()` = `ceil(sites / 120)` |
| F3 | **Wrong** | Payback reconciles; the CR's check omits dual-running cost |
| F4 | **Valid complaint, wrong target** | `coverage` measures priced scope, not evidence |
| F5 | **Confirmed, different cause** | Arithmetic of estate size, not evidence |
| F6 | **Confirmed, wrong component** | The sample spec, not the workflow |
| F7 | **Follows from F6** | Same |
| F8 | **Overstated but substantively right** | Bands come from price priors, not evidence |
| F9 | **Confirmed, cause is lever mix** | Not evidence-driven; worth documenting |
| F10 | **Wrong** | The breakdown exists and is published |
| F11 | **Confirmed** | Omission in the summary builder |
| F12 | **Confirmed** | Omission in the summary builder |

---

## F3 — wrong, and CR-05 would institutionalise the error

**The CR's check:** `one_time_cost / best_saving × 12` gives 1–3 months where
the stated payback is 9–16.

**What the engine computes** (`transition.net`): payback is
`total_transition_cost / annual_saving × 12`, where total transition cost is
one-time **plus dual-running** — both circuits billed while each site is cut
over.

Recomputed from the committed artifacts:

| company | stated | CR's formula | incl. dual-running |
| --- | --- | --- | --- |
| BASF | 15 | 1.9 | **14.7** |
| Nestlé | 13 | 1.0 | **12.8** |
| Novartis | 15 | 1.2 | **14.6** |
| Volkswagen | 14 | 1.3 | **13.6** |
| McDonald's | 12 | 11.6 | **11.7** |
| Allianz | 11 | 10.4 | **10.7** |

Every row reconciles within rounding. **The payback figures are correct.**

The CR's own observation explains it: *"branch-heavy rows roughly match"*.
`dual_running` charges `min(sites, sites_migrated_per_month)` sites for
`dual_running_months`. A 16,000-site estate caps in-flight sites at 120, so
dual-running is small beside one-time cost and the CR's formula is nearly
right. A 100-site estate migrates everything at once, so dual-running
dominates. The pattern the CR spotted is the cap, not a defect.

**Consequence if implemented as written.** CR-05 adds
`payback_simple_months = one_time ÷ run_rate_saving × 12` and demands a note
wherever it differs from `payback_months_base` by more than 25%. On this set
that fires for every small-estate company — a mandatory explanation of a gap
that is simply the omitted cost term. The reconciliation field should be
`total_transition_cost ÷ run_rate_saving × 12`, which is a genuine identity
check on the published components.

**F2 stands regardless.** `programme_months = ceil(sites / 120)` is confirmed
on all 20 rows, and a single global migration rate is a real weakness. The
wave model in CR-05 is worth building. But it should be built knowing the
payback arithmetic is currently sound, not to repair it.

---

## F10 — wrong: the breakdown already exists

`estimate_v0.json → confidence` publishes:

```
overall, band, weighted, policy_set, ceilings_applied,
current_baseline, target_cost, realization,
simulated_share, asserted_share,
drivers{ priced_spend_pct, evidenced_value_share,
         client_confirmed_value_share, client_confirmed_evidence_weight,
         domain_completeness, prior_coverage, prior_recency,
         lever_stage_mix, raw_before_stage_scaling, stage_ceilings }
```

CR-08's acceptance — *"every confidence score can be reproduced from the
published components"* — is **already met in the engine**. What is missing is
that `summary.csv` carries only `confidence_overall` and `confidence_band`.

CR-08 should be rescoped from "output the components" to "surface the
components that already exist in the summary", which is a schema change, not
a model change. The one substantive part worth keeping: the CR's requirement
that process metrics must not raise confidence on their own. Worth verifying
explicitly — `research_minutes` and `research_sources` are in my summary and
are **not** confidence inputs, but a test should pin that.

---

## F4 — valid complaint, wrong target

`coverage` is not a measure of evidence. It answers *"how much of the declared
scope got priced at all"*, across 27 published fields including
`priced_spend_pct`, `unpriced_layers`, `unpriced_countries`,
`evidence_grade_mix`, `unsourced_price_share` and `material_country_breaches`.
Evidence lives on the other axis, in `confidence`.

So `COMPLETE` next to 2-of-17 researched domains is not a lie: everything in
scope was priced. It is a **presentation failure** — put beside a domain count
in one row, it reads as "we know a lot about this company".

Redefining `coverage_status` from evidence, as CR-01 proposes, merges two axes
the system separates deliberately, and would destroy the question coverage
currently answers — which is the one that tells you whether a baseline is
missing whole cost layers.

**Recommended instead:** keep `coverage_status` as-is, rename it in the
summary to `priced_scope_status` so it cannot be read as evidential, and add
the evidence-grade fields CR-01 wants as their own columns. `evidence_grade_mix`
and `unsourced_price_share` already exist and are unpublished in the summary.

The rest of CR-01 is sound and needed: `domains_declared_unknown` is genuinely
wrong at 0, and the share fields do not exist.

---

## F6 / F7 — confirmed, but it is the sample spec, not the workflow

The small footprints are not an engine defect. `companies.json` declares two
or three countries per company, and the engine priced exactly what it was
given:

| company | spec countries | declared footprint | summary |
| --- | --- | --- | --- |
| Volkswagen | DE, ES, CZ | 86 | 86 |
| BASF | DE, BE, US | 101 | 102 |
| Siemens | DE, AT, US | 195 | 197 |
| Nestlé | CH, DE, FR | 73 | 95 |
| Novartis | CH, DE, US | 63 | 67 |
| Unilever | GB, NL, DE | 43 | 48 |

CR-02's acceptance — *"a substantially expanded sourced site count"* — is a
change to the **sample input**, not to the workflow. No code change produces
it. Worth separating, because the two have different owners and different
risks: widening the spec costs research calls and changes every number;
adding a scope flag costs neither.

The workflow change in CR-02 that **is** real and should be built: nothing in
the output states that a baseline covers three countries of a group operating
in thirty. `scope_status` and `scope_countries_modelled` do not exist, and a
reader cannot tell a deliberate three-country scope from a failed enumeration.

---

## F8 — overstated, substantively right

Not fixed: `low/base` ranges 0.688–0.735 and `high/base` 1.313–1.461 across
the twenty. But the variation comes from the seeded price priors' own bands,
which differ by product and country — **not** from how much was evidenced.

So the CR's premise ("a fixed band") is inaccurate and its conclusion is
correct: a company with 2 of 17 domains evidenced shows the same range width
as one with 17. CR-06 should proceed, with the premise corrected, or the first
engineer to check will find the ratios vary and conclude the finding was wrong.

---

## F9 — confirmed; the cause is lever mix, not evidence

| company | sites | saving % |
| --- | --- | --- |
| Unilever | 48 | 21.6 |
| Novartis | 67 | 22.5 |
| Nestlé | 95 | 25.3 |
| Fresenius | 5,726 | 20.0 |
| Allianz | 6,553 | 18.5 |
| Shell | 5,995 | 15.1 |

Real, and inversely related to size. The cause is which cost layers dominate:
small campus estates carry proportionally more platform and overlay value
(L2/L4) where the seeded levers bite hardest, while branch-heavy estates are
dominated by access circuits (L0) with lower lever reach. It is a property of
the lever set against the estate shape, not of evidence.

CR-07's requirement to *document* the relationship is right. Treating it as a
defect to remove would be wrong.

---

## F5 — confirmed, cause is arithmetic

`simulated_share` is simulated **value** over total value, not a count. Small
estates carry proportionally more platform components drawn from the seeded
distributions, so the share rises as the estate shrinks:

```
siemens    197 sites  0.3748        mcdonalds  16,406 sites  0.0012
volkswagen  86 sites  0.2614        tesco       3,908 sites  0.0045
```

`asserted_share = 0` everywhere is correct and expected: these cases are
`NO_CONTACT`, so no client has asserted anything. The CR lists it as a finding;
it is the designed outcome of the sample design.

---

## F1, F2, F11, F12 — confirmed

**F1.** `transition.one_time()` multiplies site count by
`transition_policy.one_time_cost_per_site_base`. Confirmed: 900.00 per site in
all 20 rows. One correction to CR-04 — a band already exists (400 / 900 /
1800) and `one_time_cost_low/base/high` are already published per scenario;
they are absent only from `summary.csv`. The defect is that cost per site is
flat across site types, countries and architectures, not that it lacks a band.

**F2.** `programme_months = ceil(sites / sites_migrated_per_month)`, with 120
governed. Confirmed on all 20 rows, no exceptions.

**F11.** `best_scenario` is chosen by the summary builder as the scenario with
the largest base saving, and the reason is not recorded. The engine does
better than the summary: each scenario publishes `label`, `levers`,
`levers_not_applicable` with reasons, `savings_pct_base` and `ceiling`, and
`savings_advisory` produces a `basis` sentence. CR-07's per-scenario table is
mostly a matter of publishing what exists.

**F12.** Confirmed — CHF, EUR, GBP, USD with no rate or date. Note the engine
has `fx_rate` reference data and the case carries `fx_convention`, so this is
a summary omission, not missing capability.

---

## What I recommend changing in the CR before implementation

1. **Drop F3.** Payback is correct. Change CR-05's reconciliation field to
   `total_transition_cost ÷ run_rate_saving × 12`, or it will report a false
   gap on every small-estate company.
2. **Rescope CR-08** to publishing existing confidence components, plus a test
   that process metrics cannot raise confidence.
3. **Split CR-02** into a workflow item (scope flags — real, small) and a
   sample-input item (wider country scope — real, costs a full re-run).
4. **Rescope CR-01** to add evidence columns rather than redefine
   `coverage_status`; rename it `priced_scope_status` in the summary.
5. **Correct F8's premise** from "fixed band" to "evidence-insensitive band".
6. **Reclassify F5** as designed behaviour and F9 as a property to document.

CR-04, CR-05's wave model, CR-06, CR-07's additivity tests, CR-09 and the
section-6 validation gate I have no objection to and would build as written.

One caveat on the gate: CR §6 already says a clean run does not prove the
output is right. Worth stating more strongly from this set's own history —
every defect found in it so far passed a green run, and the three worst were
visible only by reading the output table. The gate should be assumed to be
necessary and insufficient, and the independent reconciliation kept manual.

## Status of the set this review was run against

The review's evidence for F4 (*"Unilever 2 of 17 domains researched,
Lufthansa 4"*) describes a known, in-flight condition rather than a steady
state: both companies lost their research to a provider outage
(`ProviderUnavailable` on 98 of 106 agent runs), and a repair is running now.
Their coverage numbers will change. The finding stands — the reporting is
still wrong — but those two companies are not good examples of it.
