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

## Open, and blocking

| item | needed from the owner |
| --- | --- |
| **CR-03** plausibility benchmark file | The thresholds and their sources. CR §5 makes these explicitly the owner's; inventing them would violate principle 1 and put a fabricated benchmark behind a flag that lowers confidence. |
| **CR-05** wave parameters | Delivery capacity, sites per wave, parallel waves. The current `sites_migrated_per_month = 120` is governed but is a single global rate. |
| **CR-01** coverage thresholds | The CR proposes ≥80% of domains and ≥70% of baseline for `COMPLETE`. Not yet applied — see the rescope note, which keeps `priced_scope_status` measuring priced scope and adds evidence columns beside it. |
| **CR-02b** country scope | Whether to widen the sample beyond 2–3 countries per company. Costs a full research re-run and changes every number. |
