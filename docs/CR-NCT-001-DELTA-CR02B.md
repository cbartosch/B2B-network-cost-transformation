# CR-NCT-001 · rerun delta report

Build `4.272.0` → `4.273.0`, the same twenty companies. The re-estimate itself made no provider calls - it re-ran promotion, the footprint merge, the simulation and the estimate over research already paid for. Research coverage did change between the two builds though, because the domain fill ran in between, and the next section says for which companies and what that means for attribution.

**These are not corrections toward a target.** CR-NCT-001 §4 principle 2 forbids tuning, and §8 says several figures are expected to move materially and some should drop. They did.

## Re-scoped companies (CR-02b)

**6 of 20** companies had their in-scope countries widened. Every figure that scales with the estate moved for that reason and is attributed to CR-02b below, not to a model change.

The measure worth reading is cost per site, which divides the estate's cost by the same estate's size and should therefore barely move. It did not: the economics held while the estate grew, which is what a scope change should look like.

| company | sites before | after | per site before | after |
| --- | ---: | ---: | ---: | ---: |
| basf | 102 | 219 | 23,822 | 24,024 |
| nestle | 95 | 310 | 43,762 | 42,861 |
| novartis | 67 | 125 | 39,725 | 31,838 |
| siemens | 197 | 497 | 27,370 | 25,526 |
| unilever | 48 | 216 | 26,511 | 21,297 |
| volkswagen | 86 | 183 | 33,681 | 33,123 |

## What moved, across the set

| figure | companies changed | median change | cause |
| --- | --- | --- | --- |
| `baseline_base` | 6 of 20 | +135.3% | **CR-06** band widened for evidence; the base is untouched |
| `baseline_low` | 6 of 20 | +131.8% | **CR-06** band widened for evidence |
| `baseline_high` | 6 of 20 | +136.0% | **CR-06** band widened for evidence |
| `best_saving_base` | 6 of 20 | +135.4% | **CR-07** savings split by evidenced and unevidenced baseline |
| `one_time_cost_base` | 6 of 20 | +156.7% | **CR-04** built over the estate by component instead of a flat per-site charge |
| `programme_months` | 6 of 20 | +133.3% | **CR-05** capacity in circuits where the estate mix is known, instead of ceil(sites / 120) |
| `payback_months_base` | 5 of 20 | -29.4% | **CR-05** first month cumulative net turns positive against the rollout, instead of cost divided by the full-year saving; **CR-04** the one-time cost it is measured against changed |

## Per company

### Accor SA

Unchanged on every reported figure.

### Allianz SE

Unchanged on every reported figure.

### BASF SE

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_base` | 2,429,844.18 | 5,261,324.01 | +116.5% | CR-02b (scope widened) |
| `baseline_low` | 1,486,009.13 | 3,176,530.27 | +113.8% | CR-02b (scope widened) |
| `baseline_high` | 3,549,583.43 | 7,808,783.86 | +120.0% | CR-02b (scope widened) |
| `best_saving_base` | 568,925.49 | 1,241,653.86 | +118.2% | CR-02b (scope widened) |
| `one_time_cost_base` | 117,936 | 251,640 | +113.4% | CR-02b (scope widened) |
| `programme_months` | 2 | 3 | +50.0% | CR-02b (scope widened), CR-05 |
| `payback_months_base` | 17 | 12 | -29.4% | CR-02b (scope widened) |

### BNP Paribas SA

Unchanged on every reported figure.

### Deutsche Bahn AG

Unchanged on every reported figure.

### Deutsche Post AG

Unchanged on every reported figure.

### Fresenius SE & Co. KGaA

Unchanged on every reported figure.

### Iberdrola SA

Unchanged on every reported figure.

### Industria de Diseno Textil SA

Unchanged on every reported figure.

### Deutsche Lufthansa AG

Unchanged on every reported figure.

### McDonald's Corporation

Unchanged on every reported figure.

### Nestle SA

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_base` | 4,157,428.80 | 13,287,043.20 | +219.6% | CR-02b (scope widened) |
| `baseline_low` | 2,586,674.12 | 8,078,735.10 | +212.3% | CR-02b (scope widened) |
| `baseline_high` | 5,987,878.18 | 19,369,431.55 | +223.5% | CR-02b (scope widened) |
| `best_saving_base` | 1,052,092.20 | 3,422,933.66 | +225.3% | CR-02b (scope widened) |
| `one_time_cost_base` | 107,208 | 355,680 | +231.8% | CR-02b (scope widened) |
| `programme_months` | 2 | 4 | +100.0% | CR-02b (scope widened), CR-05 |
| `payback_months_base` | 15 | 9 | -40.0% | CR-02b (scope widened) |

### Novartis AG

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_base` | 2,661,604.80 | 3,979,761.60 | +49.5% | CR-02b (scope widened) |
| `baseline_low` | 1,545,521.55 | 2,372,558.09 | +53.5% | CR-02b (scope widened) |
| `baseline_high` | 4,103,561.05 | 5,988,121.97 | +45.9% | CR-02b (scope widened) |
| `best_saving_base` | 597,909.14 | 934,090.22 | +56.2% | CR-02b (scope widened) |
| `one_time_cost_base` | 76,392 | 139,176 | +82.2% | CR-02b (scope widened) |
| `programme_months` | 1 | 2 | +100.0% | CR-02b (scope widened), CR-05 |

### Rio Tinto plc

Unchanged on every reported figure.

### Compagnie de Saint-Gobain SA

Unchanged on every reported figure.

### Shell plc

Unchanged on every reported figure.

### Siemens AG

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_base` | 5,391,880.58 | 12,686,519.85 | +135.3% | CR-02b (scope widened) |
| `baseline_low` | 3,286,072.46 | 7,615,966.65 | +131.8% | CR-02b (scope widened) |
| `baseline_high` | 7,902,904.48 | 18,651,841.90 | +136.0% | CR-02b (scope widened) |
| `best_saving_base` | 1,342,475.97 | 3,160,344.95 | +135.4% | CR-02b (scope widened) |
| `one_time_cost_base` | 226,008 | 580,248 | +156.7% | CR-02b (scope widened) |
| `programme_months` | 3 | 7 | +133.3% | CR-02b (scope widened), CR-05 |
| `payback_months_base` | 12 | 9 | -25.0% | CR-02b (scope widened) |

### Tesco PLC

Unchanged on every reported figure.

### Unilever PLC

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_base` | 1,272,520.66 | 4,600,235.90 | +261.5% | CR-02b (scope widened) |
| `baseline_low` | 709,442.47 | 2,693,608.03 | +279.7% | CR-02b (scope widened) |
| `baseline_high` | 1,957,192.87 | 6,964,646.42 | +255.8% | CR-02b (scope widened) |
| `best_saving_base` | 275,340.75 | 1,059,674.04 | +284.9% | CR-02b (scope widened) |
| `one_time_cost_base` | 54,000 | 245,376 | +354.4% | CR-02b (scope widened) |
| `programme_months` | 1 | 3 | +200.0% | CR-02b (scope widened), CR-05 |
| `payback_months_base` | 18 | 12 | -33.3% | CR-02b (scope widened) |

### Volkswagen AG

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_base` | 2,896,574.50 | 6,061,539.05 | +109.3% | CR-02b (scope widened) |
| `baseline_low` | 1,758,029.74 | 3,649,490.93 | +107.6% | CR-02b (scope widened) |
| `baseline_high` | 4,276,099.85 | 9,152,093.62 | +114.0% | CR-02b (scope widened) |
| `best_saving_base` | 706,693.76 | 1,482,252.39 | +109.7% | CR-02b (scope widened) |
| `one_time_cost_base` | 94,896 | 208,440 | +119.7% | CR-02b (scope widened) |
| `programme_months` | 1 | 3 | +200.0% | CR-02b (scope widened), CR-05 |
| `payback_months_base` | 15 | 12 | -20.0% | CR-02b (scope widened) |
