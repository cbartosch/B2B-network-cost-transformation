# CR-NCT-001 · rerun delta report

Build `4.272.0` → `4.273.0`, the same twenty companies. The re-estimate itself made no provider calls - it re-ran promotion, the footprint merge, the simulation and the estimate over research already paid for. Research coverage did change between the two builds though, because the domain fill ran in between, and the next section says for which companies and what that means for attribution.

**These are not corrections toward a target.** CR-NCT-001 §4 principle 2 forbids tuning, and §8 says several figures are expected to move materially and some should drop. They did.

## A confound, named

Research coverage also changed between these two runs for **11 of 20** companies - the domain fill ran between them. For those, a baseline or saving movement is the estate changing as well as the model, and this report does not pretend to separate them. Figures that do not depend on the estate - one-time cost per site, programme length, payback - are attributable to the CR items named.

| company | domains researched before | after |
| --- | ---: | ---: |
| accor | 8 | 14 |
| deutsche-bahn | 7 | 14 |
| fresenius | 12 | 15 |
| inditex | 15 | 16 |
| lufthansa | 16 | 17 |
| mcdonalds | 11 | 17 |
| shell | 14 | 17 |
| siemens | 9 | 17 |
| tesco | 16 | 17 |
| unilever | 15 | 17 |
| volkswagen | 8 | 17 |

## What moved, across the set

| figure | companies changed | median change | cause |
| --- | --- | --- | --- |
| `baseline_base` | 1 of 20 | +0.0% | **CR-06** band widened for evidence; the base is untouched |
| `baseline_low` | 20 of 20 | -16.6% | **CR-06** band widened for evidence |
| `baseline_high` | 20 of 20 | +11.5% | **CR-06** band widened for evidence |
| `best_saving_base` | 1 of 20 | +0.1% | **CR-07** savings split by evidenced and unevidenced baseline |
| `one_time_cost_base` | 20 of 20 | +10.1% | **CR-04** built over the estate by component instead of a flat per-site charge |
| `programme_months` | 17 of 20 | +10.5% | **CR-05** capacity in circuits where the estate mix is known, instead of ceil(sites / 120) |
| `payback_months_base` | 20 of 20 | +76.5% | **CR-05** first month cumulative net turns positive against the rollout, instead of cost divided by the full-year saving; **CR-04** the one-time cost it is measured against changed |

## Per company

### Accor SA

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 5,942,227.41 | 4,595,847.93 | -22.7% | CR-06 |
| `baseline_high` | 12,098,729.17 | 14,030,528.37 | +16.0% | CR-06 |
| `one_time_cost_base` | 2,029,500 | 2,124,216 | +4.7% | CR-04 |
| `programme_months` | 19 | 21 | +10.5% | CR-05 |
| `payback_months_base` | 22 | 34 | +54.5% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Allianz SE

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 26,265,195.68 | 21,993,459.36 | -16.3% | CR-06 |
| `baseline_high` | 51,127,857.44 | 56,955,744.14 | +11.4% | CR-06 |
| `one_time_cost_base` | 5,897,700 | 6,327,864 | +7.3% | CR-04 |
| `programme_months` | 55 | 62 | +12.7% | CR-05 |
| `payback_months_base` | 11 | 24 | +118.2% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### BASF SE

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 1,766,567.98 | 1,486,009.13 | -15.9% | CR-06 |
| `baseline_high` | 3,216,736.33 | 3,549,583.43 | +10.3% | CR-06 |
| `one_time_cost_base` | 91,800 | 117,936 | +28.5% | CR-04 |
| `programme_months` | 1 | 2 | +100.0% | CR-05 |
| `payback_months_base` | 15 | 17 | +13.3% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### BNP Paribas SA

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 28,085,659.45 | 23,881,571.64 | -15.0% | CR-06 |
| `baseline_high` | 51,427,518.23 | 56,701,213.68 | +10.3% | CR-06 |
| `one_time_cost_base` | 3,963,600 | 4,393,872 | +10.9% | CR-04 |
| `programme_months` | 37 | 44 | +18.9% | CR-05 |
| `payback_months_base` | 7 | 15 | +114.3% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Deutsche Bahn AG

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 17,850,405.23 | 14,082,227.01 | -21.1% | CR-06 |
| `baseline_high` | 34,077,697.37 | 39,036,904.26 | +14.6% | CR-06 |
| `one_time_cost_base` | 5,027,400 | 5,153,328 | +2.5% | CR-04 |
| `programme_months` | 47 | 49 | +4.3% | CR-05 |
| `payback_months_base` | 16 | 33 | +106.2% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Deutsche Post AG

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 12,223,011.94 | 10,187,438.43 | -16.7% | CR-06 |
| `baseline_high` | 24,188,888.86 | 26,991,284.57 | +11.6% | CR-06 |
| `one_time_cost_base` | 3,564,900 | 3,492,216 | -2.0% | CR-04 |
| `programme_months` | 34 | 32 | -5.9% | CR-05 |
| `payback_months_base` | 17 | 33 | +94.1% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Fresenius SE & Co. KGaA

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 27,967,432.51 | 22,773,592.87 | -18.6% | CR-06 |
| `baseline_high` | 52,594,384.17 | 59,493,818.40 | +13.1% | CR-06 |
| `one_time_cost_base` | 5,153,400 | 5,672,880 | +10.1% | CR-04 |
| `programme_months` | 48 | 56 | +16.7% | CR-05 |
| `payback_months_base` | 9 | 20 | +122.2% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Iberdrola SA

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 8,819,751.88 | 7,423,974.04 | -15.8% | CR-06 |
| `baseline_high` | 16,606,687.18 | 18,373,858.82 | +10.6% | CR-06 |
| `one_time_cost_base` | 2,500,200 | 2,571,696 | +2.9% | CR-04 |
| `programme_months` | 24 | 25 | +4.2% | CR-05 |
| `payback_months_base` | 17 | 30 | +76.5% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Industria de Diseno Textil SA

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 6,689,160.04 | 5,599,880.39 | -16.3% | CR-06 |
| `baseline_high` | 12,163,194.07 | 13,492,392.40 | +10.9% | CR-06 |
| `one_time_cost_base` | 1,525,500 | 1,597,752 | +4.7% | CR-04 |
| `programme_months` | 15 | 16 | +6.7% | CR-05 |
| `payback_months_base` | 13 | 22 | +69.2% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Deutsche Lufthansa AG

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 1,578,458.79 | 1,300,311.70 | -17.6% | CR-06 |
| `baseline_high` | 3,063,453.09 | 3,428,439.30 | +11.9% | CR-06 |
| `one_time_cost_base` | 200,700 | 244,872 | +22.0% | CR-04 |
| `programme_months` | 2 | 3 | +50.0% | CR-05 |
| `payback_months_base` | 14 | 17 | +21.4% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### McDonald's Corporation

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_base` | 85,356,000 | 85,386,384 | +0.0% | CR-06 + research coverage changed |
| `baseline_low` | 62,735,856 | 53,702,678.09 | -14.4% | CR-06 |
| `baseline_high` | 112,805,196 | 123,833,744.42 | +9.8% | CR-06 |
| `best_saving_base` | 15,282,721.29 | 15,290,643.14 | +0.1% | CR-07 + research coverage changed |
| `one_time_cost_base` | 14,765,400 | 15,490,440 | +4.9% | CR-04 |
| `programme_months` | 137 | 148 | +8.0% | CR-05 |
| `payback_months_base` | 12 | 26 | +116.7% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Nestle SA

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 3,041,740.80 | 2,586,674.12 | -15.0% | CR-06 |
| `baseline_high` | 5,457,574.80 | 5,987,878.18 | +9.7% | CR-06 |
| `one_time_cost_base` | 85,500 | 107,208 | +25.4% | CR-04 |
| `programme_months` | 1 | 2 | +100.0% | CR-05 |
| `payback_months_base` | 13 | 15 | +15.4% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Novartis AG

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 1,878,758.40 | 1,545,521.55 | -17.7% | CR-06 |
| `baseline_high` | 3,673,026 | 4,103,561.05 | +11.7% | CR-06 |
| `one_time_cost_base` | 60,300 | 76,392 | +26.7% | CR-04 |
| `payback_months_base` | 15 | 16 | +6.7% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Rio Tinto plc

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 954,984 | 759,526.65 | -20.5% | CR-06 |
| `baseline_high` | 2,027,502 | 2,316,777.69 | +14.3% | CR-06 |
| `one_time_cost_base` | 87,300 | 104,904 | +20.2% | CR-04 |
| `programme_months` | 1 | 2 | +100.0% | CR-05 |
| `payback_months_base` | 16 | 18 | +12.5% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Compagnie de Saint-Gobain SA

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 19,267,900.60 | 15,963,621.29 | -17.1% | CR-06 |
| `baseline_high` | 38,290,542.85 | 42,727,843.13 | +11.6% | CR-06 |
| `one_time_cost_base` | 4,216,500 | 4,509,288 | +6.9% | CR-04 |
| `programme_months` | 40 | 44 | +10.0% | CR-05 |
| `payback_months_base` | 11 | 24 | +118.2% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Shell plc

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 16,713,612 | 13,779,448.50 | -17.6% | CR-06 |
| `baseline_high` | 34,372,866 | 38,612,222.51 | +12.3% | CR-06 |
| `one_time_cost_base` | 5,395,500 | 5,431,032 | +0.7% | CR-04 |
| `programme_months` | 50 | 51 | +2.0% | CR-05 |
| `payback_months_base` | 19 | 38 | +100.0% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Siemens AG

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 3,941,595.54 | 3,286,072.46 | -16.6% | CR-06 |
| `baseline_high` | 7,121,240.61 | 7,902,904.48 | +11.0% | CR-06 |
| `one_time_cost_base` | 177,300 | 226,008 | +27.5% | CR-04 |
| `programme_months` | 2 | 3 | +50.0% | CR-05 |
| `payback_months_base` | 9 | 12 | +33.3% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Tesco PLC

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 12,973,104.59 | 10,922,838.65 | -15.8% | CR-06 |
| `baseline_high` | 24,417,064.54 | 26,950,832.11 | +10.4% | CR-06 |
| `one_time_cost_base` | 3,517,200 | 3,683,520 | +4.7% | CR-04 |
| `programme_months` | 33 | 36 | +9.1% | CR-05 |
| `payback_months_base` | 15 | 31 | +106.7% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Unilever PLC

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 875,397.34 | 709,442.47 | -19.0% | CR-06 |
| `baseline_high` | 1,755,400.84 | 1,957,192.87 | +11.5% | CR-06 |
| `one_time_cost_base` | 43,200 | 54,000 | +25.0% | CR-04 |
| `payback_months_base` | 16 | 18 | +12.5% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.

### Volkswagen AG

| figure | before | after | change | CR |
| --- | ---: | ---: | ---: | --- |
| `baseline_low` | 2,102,489.68 | 1,758,029.74 | -16.4% | CR-06 |
| `baseline_high` | 3,858,732.67 | 4,276,099.85 | +10.8% | CR-06 |
| `one_time_cost_base` | 77,400 | 94,896 | +22.6% | CR-04 |
| `payback_months_base` | 14 | 15 | +7.1% | CR-05, CR-04 |

Newly reported: `saving_on_evidenced_baseline`, `saving_on_unevidenced_baseline`, `confidence_weights`, `best_scenario_reason`.
