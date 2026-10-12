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
| Owner sign-off | **not obtained** |
| Safe for internal review | yes |
| Safe for external use | **no**, until the table below is signed |

---

## CR-04 · one-time cost build

The per-site reference cost (400 / 900 / 1800) was already governed and is
unchanged. What is new is the split of it into work that scales with
circuits and work that scales with sites.

| parameter | value | class | rationale | sign-off |
| --- | --- | --- | --- | --- |
| `one_time_share_hardware` | 0.35 | ASSUMED | CPE and a switch port are per access circuit, not per site. Largest single component because it is the only one with a hardware bill. | ☐ |
| `one_time_share_migration` | 0.25 | ASSUMED | Cutover labour and test are per circuit: a dual-access site is cut over twice. | ☐ |
| `one_time_share_integration` | 0.20 | ASSUMED | Configuring and proving a site happens once however many circuits land in it. | ☐ |
| `one_time_share_project_management` | 0.20 | ASSUMED | Programme overhead of touching a site at all — survey, scheduling, acceptance. | ☐ |
| `one_time_reference_circuits_per_site` | 1.25 | ASSUMED | The density the reference cost is taken to assume. A seeded estate runs about 1.3; 1.25 is the round figure the four shares were set against. | ☐ |

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

| parameter | value | class | rationale | sign-off |
| --- | --- | --- | --- | --- |
| `widen_evidenced_public` | 1.00 | FIXED POINT | A fully evidenced estimate is reported at exactly the card's width. The scale has a fixed point rather than a floor somebody chose, and `validate` refuses any other value. | ☐ |
| `widen_client_confirmed` | 1.15 | ASSUMED | First-party and not independently checkable; internal records go stale and the person answering may not be the one who knows. | ☐ |
| `widen_derived_public` | 1.20 | ASSUMED | A figure computed from evidence carries the evidence's error plus the derivation's. | ☐ |
| `widen_analyst_entered_scope` | 1.35 | ASSUMED | A scoped figure nobody sourced. Wider than derived, narrower than a pure benchmark because somebody chose it for this estate. | ☐ |
| `widen_benchmark_prior` | 1.40 | ASSUMED | A governed rate for a population, applied to one company. The card's band describes dispersion *within* the benchmark, not whether the benchmark fits. | ☐ |
| `widen_analyst_asserted_prior` | 1.50 | ASSUMED | An unverified recollection. Weaker than a benchmark, which at least has a published basis. | ☐ |
| `widen_simulated` | 1.55 | ASSUMED | A drawn value. The widest, because nothing outside the model attests to it. | ☐ |
| `widen_unevidenced_domain_share` | 0.50 | ASSUMED | Coefficient on the unresearched-domain share. At 0.5, an estate with no domains evidenced is reported 50% wider than one fully evidenced, before the origin term. | ☐ |

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

## Open, and blocking

| item | needed from the owner |
| --- | --- |
| **CR-03** plausibility benchmark file | The thresholds and their sources. CR §5 makes these explicitly the owner's; inventing them would violate principle 1 and put a fabricated benchmark behind a flag that lowers confidence. |
| **CR-05** wave parameters | Delivery capacity, sites per wave, parallel waves. The current `sites_migrated_per_month = 120` is governed but is a single global rate. |
| **CR-01** coverage thresholds | The CR proposes ≥80% of domains and ≥70% of baseline for `COMPLETE`. Not yet applied — see the rescope note, which keeps `priced_scope_status` measuring priced scope and adds evidence columns beside it. |
| **CR-02b** country scope | Whether to widen the sample beyond 2–3 countries per company. Costs a full research re-run and changes every number. |
