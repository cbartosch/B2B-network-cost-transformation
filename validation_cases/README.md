# Validation cases

Empty. That is the finding, not an oversight.

**The estimator has not been empirically validated against actual enterprise
network portfolios.** No statistic computed anywhere in this repository changes
that, and `make validate-cases` says so rather than reporting a number that
would read as reassurance.

## Adding a case

One JSON file per case. The name becomes the case id.

```json
{
  "evidence_tier": "HISTORICAL_ACTUAL",
  "geography": "GB",
  "site_count_band": "1000-2500",
  "actual": {
    "site_count": 1840,
    "circuit_count": 2210,
    "bandwidth_mbps_total": 96500,
    "current_annual_cost": 8400000,
    "target_annual_cost": 6900000,
    "one_time_cost": 1200000,
    "feasible_annual_savings": 1500000
  },
  "estimated": {
    "site_count": 1840,
    "circuit_count": 2410,
    "current_annual_cost": 9100000
  }
}
```

Any measure may be omitted from either side; it is reported `NOT_COMPARABLE`
rather than scored as zero error.

## Evidence tiers

In the order an auditor prefers them:

| tier | meaning |
|---|---|
| `HISTORICAL_ACTUAL` | a completed engagement with known outturn |
| `VALIDATED_INVENTORY` | inventory and spend confirmed against invoices |
| `COMPLETED_SOURCING` | a finished sourcing exercise |
| `CARRIER_QUOTED` | a quoted target design |
| `EXPERT_SYNTHETIC` | reviewed, and invented |

**Synthetic cases are excluded from the statistics.** They are useful for
exercising the harness and they are not evidence: an error computed over cases
somebody invented measures the inventor. Reporting one beside a real case as
though they were the same number is the failure the tier exists to prevent.

## What the harness tests for

Bias, not magnitude. An outside-in estimate is not expected to be accurate; it
is expected to be **unbiased**. Being 20% wrong in both directions is the
advertised behaviour. Being 20% high in every case is a defect, and the
mean signed error with the over/under split is what shows it.

Six bias questions cannot be answered without cases and are listed as
`NOT_ASSESSED` rather than guessed at - whether the model oversizes warehouse
bandwidth, misprices small sites or data centres, understates rural access
cost, overstates sourcing savings, or understates managed-service scope.
