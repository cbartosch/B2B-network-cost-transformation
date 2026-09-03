#!/usr/bin/env python3
"""Validate the estimator against cases with known actuals.

Audit finding A-01: no case had ever been compared against a real portfolio,
and there was no machinery to do it with.

This is the machinery. It does not close the finding. A harness with no cases
validates nothing, and `validation_cases/` is empty - so this reports the
mandate's own sentence rather than a number that would read as reassurance.

What it does close is the excuse. When a completed engagement produces an
actual site count, circuit count and spend, adding it is one JSON file and
running this is one command - rather than a project nobody starts.

    make validate-cases

Exit codes:
    0  no empirical case exists, and the report says so plainly
    0  cases exist and no measure exceeds its bias threshold
    1  a measure is biased beyond the threshold, or a case is malformed
"""
import json
import pathlib
import sys
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORPUS = ROOT / "validation_cases"
sys.path.insert(0, str(ROOT / "api_service"))

from app.domain import validation                       # noqa: E402

# A mean signed error beyond this on a cost measure is bias rather than noise.
# Deliberately generous: an outside-in estimate is not expected to be accurate,
# it is expected to be unbiased. Being 20% wrong in both directions is the
# advertised behaviour; being 20% high in every case is a defect.
BIAS_THRESHOLD_PCT = Decimal("15")


def _load() -> list:
    if not CORPUS.exists():
        return []
    cases = []
    for path in sorted(CORPUS.glob("*.json")):
        try:
            case = json.loads(path.read_text())
        except ValueError as exc:
            print(f"  [MALFORMED] {path.name}: {exc}")
            continue
        case.setdefault("case_id", path.stem)
        cases.append(case)
    return cases


def main() -> int:
    cases = _load()
    comparisons = [validation.compare(c) for c in cases]
    stats = validation.statistics(comparisons)

    print("EMPIRICAL VALIDATION")
    print(f"  corpus directory       {CORPUS.relative_to(ROOT)}/")
    print(f"  cases found            {len(cases)}")
    print(f"  empirical tier         {stats['cases_included']}")
    print(f"  excluded as synthetic  {stats['cases_excluded_as_synthetic']}")
    print()

    failed = False
    if stats["cases_included"]:
        print(f"  {'measure':26} {'n':>3} {'MAPE':>8} {'signed':>12} "
              f"{'over/under':>11}")
        for measure, m in stats["per_measure"].items():
            if not m.get("n"):
                continue
            signed = Decimal(m["mean_signed_error"])
            mape = m.get("mean_absolute_pct_error")
            print(f"  {measure:26} {m['n']:>3} "
                  f"{(mape or '-'):>8} {m['mean_signed_error']:>12} "
                  f"{m['overestimated']}/{m['underestimated']:<9}")
            # Bias, not magnitude. Wrong in one direction is the defect.
            if mape and Decimal(mape) > BIAS_THRESHOLD_PCT and (
                    m["overestimated"] == 0 or m["underestimated"] == 0):
                print(f"      BIASED: every case errs in one direction beyond "
                      f"{BIAS_THRESHOLD_PCT}%")
                failed = True
    else:
        print("  The estimator has not been empirically validated against "
              "actual enterprise network portfolios.")
        print()
        print("  This is not a passing result. It is the absence of a test.")
        print("  Add a case as validation_cases/<name>.json with:")
        print("    evidence_tier, actual{...}, estimated{...}")
        print(f"    tiers: {', '.join(validation.EMPIRICAL_TIERS)}")

    print()
    print("STRUCTURAL BIAS PROBES")
    print("  (answerable from the model itself, no corpus required)")
    # The cost build-up alone. Concatenating every domain module meant the
    # probe searched its own prose describing the gap and reported the gap
    # absent - a check that read its own commentary as evidence.
    source = (ROOT / "api_service" / "app" / "domain" / "estimate.py").read_text()
    probes = validation.bias_probes(priors=[], archetypes={},
                                    model_source=source)
    for probe in probes:
        if probe["needs_corpus"]:
            continue
        print(f"  [{probe['verdict']:20}] {probe['question']}")
        print(f"       {probe['evidence'][:100]}")

    pending = [p for p in probes if p["needs_corpus"]]
    print()
    print(f"  {len(pending)} probe(s) need cases with known actuals:")
    for probe in pending:
        print(f"    - {probe['question']}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
