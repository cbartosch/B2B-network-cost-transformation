# CR-NCT-001 · rescope and implementation plan

Follows the CR-00 root-cause note. Changes to the CR as written are listed
first with the reason; the plan then implements the rescoped set.

## Changes to the CR

| item | change | reason |
| --- | --- | --- |
| **F3 / CR-05 reconciliation** | Dropped as a defect. `payback_simple_months` redefined as `total_transition_cost ÷ run_rate_saving × 12` | Payback already reconciles; the CR's formula omits dual-running cost and would report a false gap on every small-estate company |
| **CR-08** | From "output the components" to "publish the components that exist, and pin that process metrics cannot raise confidence" | `confidence.drivers` already carries ten fields and is already reproducible; only `summary.csv` is thin |
| **CR-01** | From "redefine `coverage_status` from evidence" to "rename it `priced_scope_status` and add evidence columns beside it" | Coverage measures priced scope across 27 fields; evidence lives in `confidence`. Merging them destroys the question coverage answers |
| **CR-02** | Split: **CR-02a** scope flags (workflow), **CR-02b** wider country scope (sample input) | The small footprints are `companies.json` declaring 2–3 countries, not an engine defect. Different owner, different cost |
| **F8 / CR-06** | Premise corrected from "fixed band" to "evidence-insensitive band" | Ratios vary 0.688–0.735; the conclusion stands, the premise does not |
| **F5** | Reclassified as designed behaviour, no change | `asserted_share = 0` is correct under `NO_CONTACT`; `simulated_share` rises as estates shrink by arithmetic |
| **F9** | Reclassified from defect to documented property | Saving % tracks lever/layer mix against estate shape, not evidence |
| **CR-03** | Blocked pending owner | Thresholds and the benchmark file are explicitly the owner's to set; inventing them violates principle 1 |

## Build order

Reporting first, because it makes every later change legible; then the two
figures that are presently mechanical; then ranges, then the gate.

1. **CR-01** evidence columns, `priced_scope_status`, real `domains_declared_unknown`
2. **CR-08** confidence components in the summary + process-metric test
3. **CR-09** FX columns
4. **CR-02a** scope status and site-type origin
5. **CR-04** one-time cost by component and site type
6. **CR-05** wave-based programme, payback basis, reconciliation
7. **CR-06** evidence-weighted ranges
8. **CR-07** additivity, monotonicity, perturbation, scenario identity — as tests first
9. **§6** validation gate
10. Rerun, delta report, assumptions register

## Standing rules for this work

- Anything unsourced is `ASSUMED` in one register with a rationale, or
  `DECLARED_UNKNOWN`. Nothing is invented to fill a gap.
- No parameter is tuned toward a headline. Figures are expected to move and
  some to fall.
- Per-country and per-architecture transition cost is **not** sourced and
  will be declared unknown rather than modelled, until someone sources it.
