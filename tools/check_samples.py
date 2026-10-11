"""Refuse to commit a sample set that is worse than the one already in.

    python tools/check_samples.py --out _samples_backup [--baseline samples/outside_in]

Exit 0 if the set is fit to commit, 1 with reasons otherwise.

Written after a gate that only asked "more than zero researched domains?"
passed a repair which had produced four of seventeen and two of seventeen,
because 98 of its 106 agent runs had failed against an unreachable provider.
"More than nothing" is not a standard.
"""
import argparse
import csv
import json
import pathlib
import sys

# The set's own mean when it was last whole. A repaired company that lands
# below this did not get its research; it got a handful of calls through a
# bad window. Absolute rather than relative because the failure it exists to
# catch - an outage - depresses every company at once, so a relative floor
# would move down with the damage.
MIN_RESEARCHED = 12
TOTAL_AGENT_DOMAINS = 17


def load(root: pathlib.Path):
    rows = {r["slug"]: r for r in csv.DictReader(
        (root / "summary.csv").open(encoding="utf-8"))}
    return rows


def manifest(root: pathlib.Path, slug: str):
    f = root / slug / "manifest.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def check(out: pathlib.Path, baseline: pathlib.Path | None,
          repaired: list[str]):
    fails, notes = [], []
    rows = load(out)
    base = load(baseline) if baseline and (
        baseline / "summary.csv").exists() else {}

    for slug, r in sorted(rows.items()):
        researched = int(r["domains_researched"])
        sites = int(r["sites"])
        baseline_cost = float(r["baseline_base"])

        if sites <= 0 or baseline_cost <= 0:
            fails.append(f"{slug}: empty estate or baseline")

        # The summary is derived from the manifest; if they disagree, one of
        # them is describing a run that did not happen. This is the check
        # that would have caught a footprint the merge silently shrank.
        m = manifest(out, slug)
        if m is None:
            fails.append(f"{slug}: no manifest")
        else:
            used = sum(int(x["sites"]) for x in m["footprint_used"])
            if used != sites:
                fails.append(
                    f"{slug}: summary says {sites} sites, manifest says {used}")

        # Nothing may go backwards against what is already committed. An
        # outage depresses research, and a re-run that lands lower than the
        # set it replaces is a worse set however it reads on its own.
        was = base.get(slug)
        if was:
            before = int(was["domains_researched"])
            if researched < before:
                fails.append(
                    f"{slug}: {before} -> {researched} researched domains, "
                    f"a regression against the committed set")
            elif researched > before:
                notes.append(f"{slug}: {before} -> {researched} researched")

        if slug in repaired and researched < MIN_RESEARCHED:
            fails.append(
                f"{slug}: {researched} of {TOTAL_AGENT_DOMAINS} researched, "
                f"below the floor of {MIN_RESEARCHED} - this is a repair that "
                f"did not take, not a repaired company")

    return rows, fails, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline", default="")
    ap.add_argument("--repaired", default="",
                    help="comma-separated slugs held to the floor")
    args = ap.parse_args()

    repaired = [s for s in args.repaired.split(",") if s]
    rows, fails, notes = check(
        pathlib.Path(args.out),
        pathlib.Path(args.baseline) if args.baseline else None,
        repaired)

    for slug in repaired:
        r = rows.get(slug)
        if r:
            print(f"  {slug}: {r['domains_researched']} researched, "
                  f"{r['sites']} sites, {r['footprint_origin']}")
    for n in notes:
        print(f"  improved: {n}")
    print(f"  {len(rows)} companies checked, floor {MIN_RESEARCHED} "
          f"on {repaired or 'nothing'}")

    if fails:
        for f in fails:
            print(f"  FAIL: {f}")
        return 1
    print("  gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
