"""Which footprint changes carry a dated verification entry, and which do not.

An external audit raised FOOTPRINT_CHANGE_WITHOUT_VERIFICATION_RECORD on
five rows: a site count that moved away from what the spec declared, with no
register entry carrying an as-of date, an evidence reference and a site
definition.

`footprint_provenance` already records what changed and why, with both
figures and the source URLs. That makes a change EXPLAINED. It does not make
it AUDITABLE: an explanation lives in the output of the run that made it,
and a reader checking the work has only the run's own word for it. A
register is a separate, dated statement a person signed.

So this reports the gap rather than closing it. Most changes in the set have
no entry, which is the true state and the useful thing to see.

    python tools/check_footprint_verification.py
    python tools/check_footprint_verification.py --strict   # exit 1 on gaps
"""
import argparse
import csv
import datetime
import json
import pathlib
import re
import sys

REGISTER = pathlib.Path("samples") / "verification_register.csv"
SPEC = pathlib.Path("samples") / "companies.json"

#: A disposition says what a person concluded, not what the model did.
DISPOSITIONS = {
    # The changed count was checked against the evidence and stands.
    "VERIFIED",
    # The research is correct and the sites are not this company's estate.
    "EXCLUDED",
    # The evidence was too inconsistent to accept; the declared figure holds.
    "DECLINED",
    # The count is sound and whether these sites are the company's estate is
    # a scope judgement for the owner, not a fact to be checked. A dealer-
    # operated forecourt and a drop-off counter inside somebody else's shop
    # are real sites that may or may not be this company's cost, and
    # deciding either way from a label would be inventing a policy.
    "REFERRED",
}


def load_register(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        disposition = (row.get("disposition") or "").strip().upper()
        if disposition not in DISPOSITIONS:
            raise SystemExit(
                f"{path}: {row.get('slug')} {row.get('country')}/"
                f"{row.get('archetype')} has disposition "
                f"{disposition or '(blank)'}; expected one of "
                f"{sorted(DISPOSITIONS)}")
        for field in ("as_of", "site_definition", "verified_by"):
            if not (row.get(field) or "").strip():
                raise SystemExit(
                    f"{path}: {row.get('slug')} {row.get('country')}/"
                    f"{row.get('archetype')} has no {field}. An entry without "
                    f"one is not a verification record.")
        out[(row["slug"], row["country"], row["archetype"])] = row
    return out


def changes(outdir: pathlib.Path, spec_path: pathlib.Path) -> list:
    """Every (country, archetype) whose count differs from the declaration."""
    spec = {c["slug"]: c for c in
            json.loads(spec_path.read_text("utf-8"))["companies"]}
    found = []
    for slug, company in sorted(spec.items()):
        manifest = outdir / slug / "manifest.json"
        if not manifest.exists():
            continue
        man = json.loads(manifest.read_text("utf-8"))
        declared = {(r["country"], r["archetype"]): r["sites"]
                    for r in company["declared_footprint"]}
        used = {}
        for r in (man.get("footprint_used") or []):
            key = (r["country"], r["archetype"])
            used[key] = used.get(key, 0) + r["sites"]
        for key, count in used.items():
            if declared.get(key, 0) != count:
                found.append({"slug": slug, "country": key[0],
                              "archetype": key[1],
                              "declared": declared.get(key, 0),
                              "used": count, "kind": "CHANGED"})
        # An exclusion is a change too: research found sites and a scope rule
        # kept them out. Silently dropping evidence needs a record as much as
        # silently accepting it does.
        for p in (man.get("footprint_provenance") or []):
            if p.get("origin") == "EXCLUDED_BY_SCOPE":
                found.append({"slug": slug, "country": p["country"],
                              "archetype": p["archetype"],
                              "declared": declared.get(
                                  (p["country"], p["archetype"]), 0),
                              "used": p["sites"], "kind": "EXCLUDED"})
    return found


#: Words in a finding's own label that disqualify it as this company's estate.
#:
#: Research writes the disqualification down and promotion carries only
#: (country, archetype, sites), so the words are discarded. Saint-Gobain's
#: German and UK merchants were labelled "DIVESTED to STARK Group" in 2019
#: and 2023 and were priced as its estate anyway - 820 sites. BNP's Belgian
#: row said "Fintro franchise branches". Both read like the UPS Store
#: network, which took a person noticing.
#:
#: Reported, never acted on. "Closed" in a label can mean a sub-unit of a
#: site that still exists, and "customer" can be a legitimate site type, so
#: this surfaces rows for a reader rather than dropping them.
DISQUALIFYING = (
    "divest", "sold to", "disposed", "no longer", "franchis", "licensee",
    "partner-operated", "third-party", "not operated", "customer location",
)


def label_warnings(outdir: pathlib.Path) -> list:
    """Promoted pairs whose originating finding label disqualifies them."""
    out = []
    for d in sorted(outdir.iterdir()):
        f = d / "research.json"
        if not (d.is_dir() and f.exists()):
            continue
        r = json.loads(f.read_text("utf-8"))
        # Only pairs where the researched figure actually WON.
        #
        # A disqualified finding that was promoted and then lost to the
        # declared count is not priced, so warning about it trains a reader
        # to skim. BNP's Fintro franchise lost to its own 420 Belgian
        # branches; Nestle's sold Bussigny DC lost to a declared 3.
        man = json.loads((d / "manifest.json").read_text("utf-8"))
        promoted = {
            (p.get("country"), p.get("archetype"))
            for p in (man.get("footprint_provenance") or [])
            if p.get("origin") in ("RESEARCHED", "SUPERSEDED_BY_RESEARCH",
                                   "EXCLUDED_BY_SCOPE")}
        seen = set()
        for disp in (r.get("dispositions") or []):
            for q in ((disp.get("evidence") or {}).get("quantities") or []):
                label = str(q.get("label") or "")
                if not label:
                    continue
                hit = next((w for w in DISQUALIFYING
                            if w in label.lower()), None)
                if not hit:
                    continue
                key = (q.get("country"), label.split()[0].upper())
                if key in promoted and (d.name, key) not in seen:
                    seen.add((d.name, key))
                    out.append({"slug": d.name, "country": key[0],
                                "archetype": key[1], "marker": hit,
                                "label": label})
    return out


#: How old a footprint figure can be before its age is worth reporting.
#:
#: There is no equivalent of a price's `expires` for a site count: as_of is
#: recorded on every promoted row and nothing reads it, so a count from 2002
#: contributes exactly as one from 2026 and the estimate says nothing. Three
#: years is one reporting cycle plus a margin - old enough that a restructure
#: or a disposal would usually have happened, recent enough not to flag a
#: stable estate every run.
STALE_YEARS = 3


def dated_changes(outdir: pathlib.Path, spec_path: pathlib.Path,
                  as_of_year: int) -> tuple:
    """(stale, undated) - changes too old to trust, and changes with no date.

    An undated row is the worse of the two and the easier to miss: with no
    as_of there is no age to compare, so a staleness check that skipped it
    would report a clean bill on the one row it could say least about.
    """
    stale, undated = [], []
    for change in changes(outdir, spec_path):
        res = outdir / change["slug"] / "research.json"
        if not res.exists():
            continue
        r = json.loads(res.read_text("utf-8"))
        row = next((e for e in (r.get("evidenced_footprint") or [])
                    if e.get("country") == change["country"]
                    and e.get("archetype") == change["archetype"]), None)
        raw = str((row or {}).get("as_of") or "")
        # Not every date is an ISO date. Research writes fiscal years too -
        # "FY2025", "FY2026 (Aug 2025 - Aug 2026)" - and reading the first
        # four characters called both of those undated, which would have
        # buried two real dates in the list of rows that have none.
        year = re.search(r"(19|20)\d{2}", raw)
        if not year:
            if row is not None:
                undated.append({**change, "as_of": raw or "(none)"})
            continue
        age = as_of_year - int(year.group(0))
        if age >= STALE_YEARS:
            stale.append({**change, "as_of": raw[:10], "age": age})
    return (sorted(stale, key=lambda c: -c["age"]),
            sorted(undated, key=lambda c: (c["slug"], c["country"])))


def stale_evidence(outdir: pathlib.Path, spec_path: pathlib.Path,
                   as_of_year: int) -> list:
    """Changes priced on evidence older than STALE_YEARS."""
    return dated_changes(outdir, spec_path, as_of_year)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="samples/outside_in")
    ap.add_argument("--register", default=str(REGISTER))
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any change has no register entry")
    args = ap.parse_args()

    register = load_register(pathlib.Path(args.register))
    found = changes(pathlib.Path(args.out), pathlib.Path(args.spec))

    covered, bare = [], []
    for change in found:
        key = (change["slug"], change["country"], change["archetype"])
        (covered if key in register else bare).append((change,
                                                       register.get(key)))

    if covered:
        print(f"verified ({len(covered)}):")
        for change, entry in sorted(covered, key=lambda c: c[0]["slug"]):
            print(f"  {change['slug']:<16}{change['country']}/"
                  f"{change['archetype']:<14}"
                  f"{change['declared']:>7,} -> {change['used']:>7,}  "
                  f"{entry['disposition']:<9}as of {entry['as_of']}")
    if bare:
        print(f"\nno verification entry ({len(bare)}):")
        by_company = {}
        for change, _ in bare:
            by_company.setdefault(change["slug"], []).append(change)
        for slug, items in sorted(by_company.items()):
            moved = sum(c["used"] - c["declared"] for c in items)
            pairs = ", ".join(f"{c['country']}/{c['archetype']}"
                              for c in items[:3])
            more = f" +{len(items) - 3} more" if len(items) > 3 else ""
            print(f"  {slug:<16}{len(items):>2} row(s), {moved:>+7,} sites  "
                  f"{pairs}{more}")

    # Entries matching no change. A DECLINED row is the common case: it
    # records that a figure was examined and left alone, which is a decision
    # worth keeping and invisible in a list of changes. A VERIFIED row with
    # nothing behind it is the other case, and means the register has gone
    # stale against a re-run.
    changed_keys = {(c["slug"], c["country"], c["archetype"]) for c in found}
    standing = [e for key, e in register.items() if key not in changed_keys]
    if standing:
        print(f"\nrecorded, no change in the set ({len(standing)}):")
        for e in sorted(standing, key=lambda e: e["slug"]):
            tail = ("the declared figure stands"
                    if e["disposition"] == "DECLINED"
                    else "VERIFIED with nothing to verify - stale?")
            print(f"  {e['slug']:<16}{e['country']}/{e['archetype']:<14}"
                  f"{e['disposition']:<9}{tail}")

    print(f"\n{len(covered)} of {len(found)} footprint changes carry a dated "
          f"verification entry.")
    if bare:
        print("A change without one is explained by footprint_provenance and "
              "not independently checkable.")
    stale, undated = dated_changes(pathlib.Path(args.out),
                                   pathlib.Path(args.spec),
                                   datetime.date.today().year)
    if undated:
        print(f"\nno as_of on the promoted row ({len(undated)}) - age cannot "
              f"be judged at all:")
        for c in undated:
            print(f"  {c['slug']:<16}{c['country']}/{c['archetype']:<14}"
                  f"{c['used']:>7,} sites  as_of {c['as_of']}")
    if stale:
        unaddressed = [c for c in stale if (c["slug"], c["country"],
                                            c["archetype"]) not in register]
        print(f"\nevidence older than {STALE_YEARS} years "
              f"({len(stale)}, {len(unaddressed)} with no register entry):")
        for c in stale:
            mark = "" if (c["slug"], c["country"],
                          c["archetype"]) in register else "  <- UNADDRESSED"
            print(f"  {c['slug']:<16}{c['country']}/{c['archetype']:<14}"
                  f"{c['used']:>7,} sites  as of {c['as_of']}  "
                  f"{c['age']:>2}y{mark}")

    warnings = label_warnings(pathlib.Path(args.out))
    live = [w for w in warnings
            if (w["slug"], w["country"], w["archetype"]) not in register]
    if warnings:
        print(f"\nfinding labels that disqualify a promoted pair "
              f"({len(warnings)}, {len(live)} with no register entry):")
        for w in warnings:
            mark = "" if (w["slug"], w["country"],
                          w["archetype"]) in register else "  <- UNADDRESSED"
            print(f"  {w['slug']:<16}{w['country']}/{w['archetype']:<13}"
                  f"[{w['marker']}] {w['label'][:46]}{mark}")

    if args.strict and (bare or live):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
