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
    # A room of equipment inside a building the company already occupies.
    # Tesco's Irish DC was one: "Smart Hands call-outs to satellite IT rooms
    # in Slough, Dundee, and Dublin", promoted as a site at DC bandwidth.
    # The unit gate cannot catch these - the unit says "sites" and the
    # disqualification is in the label, which is the same shape as DIVESTED.
    # Matched as "it room" rather than "room" or "satellite", both of which
    # have legitimate premises in this set: Accor counts hotel rooms and
    # Simmons Bank has a West Little Rock satellite OFFICE.
    "it room",
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


#: Leading token of a finding's label, which is how an archetype is named.
_ARCH = re.compile(r"^([A-Z_]+)")


def priced_above_research(outdir: pathlib.Path, spec_path: pathlib.Path) -> list:
    """Pairs where the estate's figure exceeds every count research found.

    The opposite failure to a changed count, and invisible to the register
    because nothing changed. Research is refused or superseded, the
    declared figure stands unchallenged, and nobody sees that every source
    which looked said something smaller.

    Nestle's French plants are the case. Three sources - the Office
    francais de la biodiversite at 18, nestle.fr at 13, an aggregator at
    12 - and the estate prices 28, which is an apportionment of a
    published group factory total across ten countries, not a figure
    anybody published about France.

    Two separate things kept all three out, and only one is a defect. The
    18 and the 13 were banded together at a 38% spread and refused as a
    conflict, which is correct - promoting the midpoint would settle a
    disagreement by arithmetic. The 12 never reached that gate at all:
    its label reads "FR production sites (PLANT-type)", and archetype_of
    takes the leading token, so it resolved to "FR" and was never
    classified as a footprint. That narrow read is mostly a filter rather
    than a miss - see test_a_mid_label_archetype_is_still_not_a_footprint
    _count for what a wider one would admit - so the 28 stands on a
    correct refusal and a deliberate one, and the referral in the
    register is the only honest resolution.

    Mostly this reports research being incomplete rather than a
    declaration being wrong - one office found against twelve declared is
    research's limit, not the company's estate. The ratio and the CR-02b
    marker are what separate the two.
    """
    spec = {c["slug"]: c for c in
            json.loads(spec_path.read_text("utf-8"))["companies"]}
    out = []
    for d in sorted(outdir.iterdir()):
        f = d / "research.json"
        if not (d.is_dir() and f.exists()):
            continue
        r = json.loads(f.read_text("utf-8"))
        man = json.loads((d / "manifest.json").read_text("utf-8"))
        used = {}
        for row in (man.get("footprint_used") or []):
            key = (row["country"], row["archetype"])
            used[key] = used.get(key, 0) + row["sites"]
        # Two tiers, because reporting every pair the estate prices above
        # research gives 58 rows and buries the signal: Allianz's 800
        # declared German branches against the 3 research found is a 267x
        # ratio that says nothing except that research stopped at three.
        #
        #   NOTHING_SURVIVED   - research produced no usable row at all,
        #                        so the declared figure stands unexamined.
        #   APPORTIONED_BEATEN - research produced one and lost to a
        #                        declaration that is itself an
        #                        apportionment of a group total.
        #
        # The second tier exists because the delta-and-closure gate moved
        # Nestle's French plants from the first into it: the aggregator's
        # 12 now classifies and promotes, and then loses to the declared
        # 28. Same question, different origin, and dropping it when the
        # row started being promoted would have quietly retired the case
        # this check was written for.
        apportioned = bool(spec.get(d.name, {}).get("scope_note_cr02b"))
        promoted = {(e["country"], e["archetype"])
                    for e in (r.get("evidenced_footprint") or [])}
        highest = {}
        for disp in (r.get("dispositions") or []):
            for t in ((disp.get("evidence") or {}).get("triangulated") or []):
                country, label = t.get("country"), str(t.get("label") or "")
                match = _ARCH.match(label)
                if not country or not match:
                    continue
                key = (country, match.group(1))
                if key not in used or (key in promoted and not apportioned):
                    continue
                try:
                    value = float(t["high"])
                except (TypeError, ValueError, KeyError):
                    continue
                highest[key] = max(highest.get(key, 0.0), value)
        for key, found in highest.items():
            if found and used[key] > found:
                out.append({
                    "slug": d.name, "country": key[0], "archetype": key[1],
                    "used": used[key], "highest_found": int(found),
                    "apportioned": apportioned,
                    "kind": ("APPORTIONED_BEATEN" if key in promoted
                             else "NOTHING_SURVIVED")})
    return sorted(out, key=lambda c: -(c["used"] / max(c["highest_found"], 1)))


#: Archetype pairs that name the same premises under two words.
#:
#: Not a general synonym table - a warehouse is not a shop. Each pair is
#: here because the sample set shows one network counted both ways:
#:
#:   STORE/BRANCH         a bank branch and a "financial centre" (Simmons
#:                        Bank), a retail branch (BNP), a dialysis clinic
#:                        that the filing calls a clinic and the
#:                        declaration calls a branch (Fresenius).
#:   STORE/SERVICE_POINT  a fuel forecourt (Shell, DE and NL).
#:   STORE/WAREHOUSE      a builders' merchant, which is a trade counter
#:                        and a yard at one address (Saint-Gobain, in
#:                        three countries independently).
SAME_PREMISES = (frozenset({"STORE", "BRANCH"}),
                 frozenset({"STORE", "SERVICE_POINT"}),
                 frozenset({"STORE", "WAREHOUSE"}))

#: How far two counts of one network may differ and still be one network.
#: Saint-Gobain's French merchants are the widest real case at 2.2x - the
#: declaration says 900 and the company's own site says over 2,000 - and
#: the gap is the finding rather than a reason to call them different.
COLLISION_RATIO = 2.5


def archetype_collisions(outdir: pathlib.Path, spec_path: pathlib.Path) -> list:
    """One network counted twice under two archetype names.

    The merge keys on (country, archetype), so research typing a network
    differently from the declaration adds it instead of reconciling it.
    Simmons Bank's 222 "financial centres" beside its 230 declared
    branches was caught by hand; this is the same shape and it is not
    rare. Across the set it accounts for more phantom sites than every
    other footprint defect together.
    """
    spec = {c["slug"]: c for c in
            json.loads(spec_path.read_text("utf-8"))["companies"]}
    out = []
    for d in sorted(outdir.iterdir()):
        f = d / "research.json"
        if not (d.is_dir() and f.exists()) or d.name not in spec:
            continue
        declared = {}
        for row in spec[d.name]["declared_footprint"]:
            declared.setdefault(row["country"], {})[row["archetype"]] = \
                row["sites"]
        for e in (json.loads(f.read_text("utf-8")).get(
                "evidenced_footprint") or []):
            country, arch, found = e["country"], e["archetype"], e["sites"]
            here = declared.get(country, {})
            # Same archetype is an ordinary merge, not a collision.
            if found <= 0 or arch in here:
                continue
            for darch, dn in here.items():
                if dn <= 0 or frozenset({arch, darch}) not in SAME_PREMISES:
                    continue
                if max(found, dn) / min(found, dn) <= COLLISION_RATIO:
                    out.append({"slug": d.name, "country": country,
                                "archetype": arch, "found": found,
                                "declared_as": darch, "declared": dn})
    return sorted(out, key=lambda c: -c["found"])


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
            tail = {
                # Declining is a decision about evidence that did not win,
                # so there is nothing in the change list by design.
                "DECLINED": "the declared figure stands",
                # Likewise a referral about a figure research never moved:
                # Nestle's French plants are declared at an apportioned 28
                # against three sources between 12 and 18.
                "REFERRED": "awaiting an owner's ruling",
            }.get(e["disposition"],
                  "VERIFIED with nothing to verify - stale?")
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

    collisions = archetype_collisions(pathlib.Path(args.out),
                                      pathlib.Path(args.spec))
    if collisions:
        live = [c for c in collisions
                if (c["slug"], c["country"], c["archetype"]) not in register]
        print(f"\none network counted twice under two archetypes "
              f"({len(collisions)}, {len(live)} with no register entry):")
        for c in collisions:
            mark = "" if (c["slug"], c["country"],
                          c["archetype"]) in register else "  <- UNADDRESSED"
            print(f"  {c['slug']:<16}{c['country']}  researched "
                  f"{c['archetype']} {c['found']:,} beside declared "
                  f"{c['declared_as']} {c['declared']:,}{mark}")

    over = priced_above_research(pathlib.Path(args.out),
                                 pathlib.Path(args.spec))
    if over:
        apportioned = [c for c in over if c["apportioned"]]
        print(f"\npriced above every count research found ({len(over)}, "
              f"{len(apportioned)} on an apportioned declaration):")
        for c in over:
            mark = (" <- apportioned, research promoted and lost"
                    if c["kind"] == "APPORTIONED_BEATEN"
                    else " <- apportioned, not published"
                    if c["apportioned"] else "")
            print(f"  {c['slug']:<16}{c['country']}/{c['archetype']:<14}"
                  f"{c['used']:>7,} in estate, {c['highest_found']:>6,} "
                  f"found  {c['used']/max(c['highest_found'],1):>4.1f}x{mark}")

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
