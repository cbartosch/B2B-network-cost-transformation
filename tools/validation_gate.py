"""CR-NCT-001 §6: the gate that runs before summary.csv is published.

Eight checks. The run fails and lists every violation rather than stopping
at the first, because a set with three problems should be fixed once.

**A clean run does not prove the output is right.** §6 says so and it is
worth repeating here, where someone reading a PASS will be tempted to take
it as a verdict. Every check below is necessary and none is sufficient:
they test that the arithmetic closes and the provenance is present, not that
the numbers describe any real company.

Two of the eight cannot be answered from published artifacts, and this
reports them as NOT CHECKED HERE rather than passing them silently:

* monotonic addition and perturbation independence (part of §6.6) need the
  model re-run with altered inputs. They live in
  tests/test_savings_invariants.py and run in the suite.
* plausibility (§6.3) needs the benchmark file CR-03 makes the owner's.
  Nothing here invents one.

Usage:
    python tools/validation_gate.py --out samples/outside_in
"""
import argparse
import csv
import json
import pathlib
import sys
from decimal import Decimal as D

TOL = D("0.01")
SHARE_TOL = D("0.001")


class Result:
    def __init__(self, num, name):
        self.num, self.name = num, name
        self.fails: list[str] = []
        self.skipped: str | None = None

    def fail(self, msg):
        self.fails.append(msg)

    @property
    def status(self):
        if self.skipped:
            return "NOT CHECKED HERE"
        return "FAIL" if self.fails else "pass"


def _rows(out: pathlib.Path):
    f = out / "summary.csv"
    if not f.exists():
        raise SystemExit(f"no summary at {f}")
    with f.open(encoding="utf-8") as fh:
        return {r["slug"]: r for r in csv.DictReader(fh)}


def _estimate(out: pathlib.Path, slug):
    f = out / slug / "estimate_v0.json"
    return json.loads(f.read_text("utf-8")) if f.exists() else {}


def _num(v):
    try:
        return D(str(v))
    except Exception:
        return None


# ------------------------------------------------------------------ checks

def c1_shares(rows, out):
    """Evidence shares sum to 1.0 per company."""
    r = Result(1, "evidence shares sum to 1.0 (CR-01)")
    for slug, row in rows.items():
        total = _num(row.get("shares_sum"))
        if total is None:
            r.fail(f"{slug}: no shares_sum")
        elif abs(total - D(1)) > SHARE_TOL:
            r.fail(f"{slug}: shares sum to {total}, not 1.0")
    return r


def c2_scope(rows, out):
    """scope_status populated, and no partial scope left unflagged."""
    r = Result(2, "scope_status populated, partial scope flagged (CR-02)")
    for slug, row in rows.items():
        status = (row.get("scope_status") or "").strip()
        if not status:
            r.fail(f"{slug}: no scope_status")
            continue
        if status not in ("FULL_GROUP", "PARTIAL_COUNTRIES",
                          "PARTIAL_SITE_TYPES", "UNKNOWN"):
            r.fail(f"{slug}: scope_status {status!r} is not a known value")
    return r


def c3_plausibility(rows, out):
    """CR-03. Blocked on the owner's benchmark file."""
    r = Result(3, "plausibility_flag populated (CR-03)")
    if not any((row.get("plausibility_flag") or "").strip()
               for row in rows.values()):
        r.skipped = (
            "CR-03 is not implemented. Its thresholds are the owner's by "
            "CR-NCT-001 section 9, and inventing them would put a fabricated "
            "benchmark behind a flag that lowers confidence.")
        return r
    for slug, row in rows.items():
        if not (row.get("plausibility_flag") or "").strip():
            r.fail(f"{slug}: no plausibility_flag")
    return r


def c4_one_time(rows, out):
    """One-time cost per site is not constant across companies."""
    r = Result(4, "one-time cost per site varies (CR-04)")
    per_site = {}
    for slug, row in rows.items():
        cost, sites = _num(row.get("one_time_cost_base")), _num(row.get("sites"))
        if cost is None or not sites:
            r.fail(f"{slug}: no one-time cost or no sites")
            continue
        per_site[slug] = (cost / sites).quantize(D("0.01"))
    if len(set(per_site.values())) <= 1 and len(per_site) > 1:
        r.fail(f"every company reports {next(iter(per_site.values()))} per "
               f"site - the flat charge CR-04 removed has come back")
    return r


def c5_payback(rows, out):
    """Programme and payback reconcile, or carry a note."""
    r = Result(5, "programme and payback reconcile or explain (CR-05)")
    for slug in rows:
        est = _estimate(out, slug)
        for code, sc in (est.get("scenarios") or {}).items():
            t = sc.get("transition")
            if not t:
                continue
            ramped = t.get("payback_months", {}).get("base")
            simple = t.get("payback_simple_months")
            if ramped is None or simple is None:
                continue
            if simple and abs(D(ramped) - D(simple)) / D(simple) > D("0.25") \
                    and not t.get("payback_reconciliation_note"):
                r.fail(f"{slug}/{code}: payback {ramped} against simple "
                       f"{simple} with no reconciliation note")
            # The ramp can only ever delay payback, never bring it forward.
            if ramped is not None and simple is not None and D(ramped) < D(simple):
                r.fail(f"{slug}/{code}: ramped payback {ramped} is faster "
                       f"than the day-one payback {simple}")
    return r


def c6_additivity(rows, out):
    """Lever savings sum to the scenario total, on every bound."""
    r = Result(6, "savings additivity on every bound (CR-07)")
    r.skipped = None
    for slug in rows:
        est = _estimate(out, slug)
        for code, sc in (est.get("scenarios") or {}).items():
            levers = sc.get("levers") or []
            if not levers:
                continue
            for bound in ("low", "base", "high"):
                key = f"saving_{bound}"
                if any(key not in lev for lev in levers):
                    continue
                got = sum((D(lev[key]) for lev in levers), D(0))
                want = _num((sc.get("gross_run_rate_savings_unwidened")
                             or sc.get("gross_run_rate_savings")
                             or {}).get(bound))
                if want is None:
                    continue
                if abs(got - want) > TOL:
                    r.fail(f"{slug}/{code}/{bound}: levers sum to {got}, "
                           f"scenario says {want}")
    return r


def c7_confidence(rows, out):
    """Confidence reproduces from its published components."""
    r = Result(7, "confidence reproducible from components (CR-08)")
    confs = {slug: (_estimate(out, slug).get("confidence") or {})
             for slug in rows}
    # None of them carrying weights means the artifacts predate CR-08, not
    # that twenty estimates each lost them. Some of them missing is a
    # defect, and is reported as one. The regression case - a build that
    # stops publishing weights at all - is caught by
    # test_the_output_carries_everything_needed_to_check_it, which fails on
    # the engine rather than waiting for a set to be produced from it.
    if not any(c.get("weights") for c in confs.values()):
        r.skipped = ("the weights are published by the engine as of CR-08; "
                     "these artifacts predate it and need a re-run. The "
                     "engine side is covered by "
                     "tests/test_confidence_reproducible.py")
        return r
    for slug in rows:
        conf = confs[slug]
        weights = conf.get("weights")
        headroom = conf.get("component_cap_headroom")
        if not weights or headroom is None:
            r.fail(f"{slug}: confidence publishes no weights or headroom, so "
                   f"the score cannot be reproduced")
            continue
        comps = {k: _num(conf.get(k)) for k in
                 ("current_baseline", "target_cost", "realization")}
        if any(v is None for v in comps.values()):
            r.fail(f"{slug}: a confidence component is missing")
            continue
        weighted = sum(v * D(weights[k]) for k, v in comps.items())
        capped = min(weighted, min(comps.values()) + D(headroom))
        overall = _num(conf.get("overall"))
        if overall is None or abs(capped - overall) > D("0.002"):
            r.fail(f"{slug}: published overall {overall} but the components "
                   f"give {capped}")
    return r


def c8_headline(rows, out):
    """No headline saving includes unevidenced baseline."""
    r = Result(8, "headline excludes unevidenced baseline (CR-07)")
    missing = 0
    for slug, row in rows.items():
        unev = row.get("saving_on_unevidenced_baseline")
        if unev in (None, ""):
            missing += 1
            continue
        if _num(unev) is None:
            r.fail(f"{slug}: saving_on_unevidenced_baseline is {unev!r}")
            continue
        headline, ev = _num(row.get("best_saving_base")), _num(
            row.get("saving_on_evidenced_baseline"))
        if headline is None or ev is None:
            continue
        if abs((ev + _num(unev)) - headline) > TOL:
            r.fail(f"{slug}: evidenced {ev} + unevidenced {unev} != headline "
                   f"{headline}")
    if missing == len(rows):
        r.skipped = ("the split is published by the engine as of CR-07; "
                     "these artifacts predate it and need a re-run")
    return r


CHECKS = [c1_shares, c2_scope, c3_plausibility, c4_one_time,
          c5_payback, c6_additivity, c7_confidence, c8_headline]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    rows = _rows(out)

    results = [fn(rows, out) for fn in CHECKS]

    print(f"validation gate: {len(rows)} companies\n")
    for res in results:
        print(f"  [{res.status:>16}]  {res.num}. {res.name}")
        if res.skipped:
            print(f"                      {res.skipped}")
        for f in res.fails[:6]:
            print(f"                      - {f}")
        if len(res.fails) > 6:
            print(f"                      - and {len(res.fails) - 6} more")

    print()
    print("  [NOT CHECKED HERE]  6b. monotonic addition, perturbation "
          "independence,")
    print("                      scenario identity - these need the model "
          "re-run with")
    print("                      altered inputs and live in "
          "tests/test_savings_invariants.py")
    print()

    failed = [r for r in results if r.fails]
    skipped = [r for r in results if r.skipped]
    if failed:
        print(f"GATE FAILED: {sum(len(r.fails) for r in failed)} violation(s) "
              f"across {len(failed)} check(s)")
        return 1
    print("gate passed.", end=" ")
    if skipped:
        print(f"{len(skipped)} check(s) could not run here - see above.")
    else:
        print()
    print("A clean gate does not prove the output is right: these checks are "
          "necessary, not sufficient.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
