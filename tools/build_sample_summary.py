"""Roll the per-company sample runs up into summary.csv and HIGHLIGHTS.md.

Reads what tools/run_samples.py wrote and adds nothing of its own: every
figure here is lifted from a manifest, a simulation or an estimate, so a
number in the summary can always be traced to the file it came from.

    python tools/build_sample_summary.py --out samples/outside_in
"""
import argparse
import csv
import json
import pathlib

# What the estimate carries, and where. Kept as a table rather than inline
# so a key that moves is changed in one place.
FIELDS = [
    ("slug", lambda m, s, e, r: m["slug"]),
    ("build", lambda m, s, e, r: m.get("build")),
    ("company", lambda m, s, e, r: m["legal_name"]),
    ("industry", lambda m, s, e, r: m["industry"]["industry"]),
    ("industry_origin", lambda m, s, e, r: m["industry"]["origin"]),
    ("countries", lambda m, s, e, r: "|".join(m["in_scope_countries"])),
    ("currency", lambda m, s, e, r: m["base_currency"]),
    ("sites", lambda m, s, e, r: sum(int(x["sites"])
                                     for x in m["footprint_used"])),
    ("footprint_origin", lambda m, s, e, r: m["footprint_origin"]),
    ("v0_status", lambda m, s, e, r: e.get("v0_status")),
    ("baseline_base", lambda m, s, e, r: _g(e, "current_tco", "base")),
    ("baseline_low", lambda m, s, e, r: _g(e, "current_tco", "low")),
    ("baseline_high", lambda m, s, e, r: _g(e, "current_tco", "high")),
    ("best_scenario", lambda m, s, e, r: _best(e)[0]),
    ("best_saving_base", lambda m, s, e, r: _best(e)[1]),
    ("one_time_cost_base", lambda m, s, e, r: _trans(e, "one_time_cost")),
    ("payback_months_base", lambda m, s, e, r: _payback(e)),
    ("programme_months", lambda m, s, e, r: _prog(e)),
    # The number that says how much to trust the rest of the row.
    ("confidence_overall", lambda m, s, e, r: _g(e, "confidence", "overall")),
    ("confidence_band", lambda m, s, e, r: _g(e, "confidence", "band")),
    ("coverage_status", lambda m, s, e, r: _g(e, "coverage", "status")),
    ("simulated_share", lambda m, s, e, r: e.get("simulated_share")),
    ("asserted_share", lambda m, s, e, r: e.get("asserted_share")),
    # The research, counted rather than quoted.
    ("domains_requested", lambda m, s, e, r: len(m.get("domains_requested")
                                                or m.get("domains_researched") or [])),
    ("domains_researched", lambda m, s, e, r: len(m["domains_researched"])),
    ("resumed", lambda m, s, e, r: m.get("resumed_existing_case")),
    ("domains_evidenced", lambda m, s, e, r: _count(r, "EVIDENCED_PUBLIC")),
    ("domains_declared_unknown", lambda m, s, e, r: _count(r,
                                                           "DECLARED_UNKNOWN")),
    ("research_sources", lambda m, s, e, r: _sources(r)),
    ("research_minutes", lambda m, s, e, r: round(
        sum(r.get("timings_seconds", {}).values()) / 60, 1)),
]


def _g(d, *path):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _best(e):
    scen = e.get("scenarios") or {}
    best, val = None, None
    for code, sc in scen.items():
        v = _g(sc, "gross_run_rate_savings", "base")
        if v is None:
            continue
        if val is None or float(v) > float(val):
            best, val = code, v
    return best, val


def _trans(e, key):
    code, _ = _best(e)
    return _g((e.get("scenarios") or {}).get(code) or {},
              "transition", key, "base")


def _payback(e):
    code, _ = _best(e)
    return _g((e.get("scenarios") or {}).get(code) or {},
              "transition", "payback_months", "base")


def _prog(e):
    code, _ = _best(e)
    return _g((e.get("scenarios") or {}).get(code) or {},
              "transition", "programme_months")


def _count(r, disposition):
    return sum(1 for d in r.get("dispositions") or []
               if d.get("disposition") == disposition
               and d.get("agent_run_id"))


def _sources(r):
    seen = set()
    for h in (r.get("highlights") or {}).values():
        for u in h.get("sources") or []:
            if u:
                seen.add(u)
    return len(seen)


def _fmt(v):
    if v is None:
        return "not reported"
    return str(v)


def highlights_md(rows):
    """What the research found, per company, in the order a reader asks."""
    out = ["# What the research found",
           "",
           "One section per company. Everything here was produced by the "
           "agent-routed research domains against public sources; the "
           "`sources` count is distinct URLs the agents cited and had "
           "re-fetched independently. A domain that found nothing says so - "
           "`DECLARED_UNKNOWN` is a result, not a gap in this document.",
           ""]
    for m, s, e, r in rows:
        h = r.get("highlights") or {}
        out += [f"## {m['legal_name']}",
                "",
                f"- **Industry** {m['industry']['industry']} "
                f"({m['industry']['origin'].lower().replace('_', ' ')})",
                f"- **Scope** {', '.join(m['in_scope_countries'])}, "
                f"{m['base_currency']}, "
                f"{sum(int(x['sites']) for x in m['footprint_used']):,} sites "
                f"({m['footprint_origin'].lower().replace('_', ' ')})",
                f"- **Confidence** {_fmt(_g(e, 'confidence', 'overall'))} "
                f"({_fmt(_g(e, 'confidence', 'band'))}), coverage "
                f"{_fmt(_g(e, 'coverage', 'status'))}",
                ""]
        for key, label in (("profile", "Profile"),
                           ("locations", "Locations"),
                           ("data_centres", "Data centres and cloud"),
                           ("architecture", "Current architecture"),
                           ("vendors", "Current providers and products"),
                           ("contracts", "Contract and sourcing events"),
                           ("transformation", "Transformation announcements"),
                           ("serviceability", "Market serviceability")):
            d = h.get(key) or {}
            finding = d.get("finding")
            if not finding:
                out.append(f"**{label}** - {d.get('disposition') or 'not researched'}"
                           + (f": {d.get('reason')}" if d.get("reason") else ""))
                out.append("")
                continue
            out += [f"**{label}** ({d.get('disposition')}, "
                    f"{len(d.get('sources') or [])} source(s))",
                    "",
                    str(finding).strip(),
                    ""]
            qs = d.get("quantities") or []
            if qs:
                out.append("| value | unit | label | country |")
                out.append("| --- | --- | --- | --- |")
                for q in qs[:12]:
                    out.append(
                        f"| {q.get('value')} | {q.get('unit') or ''} "
                        f"| {q.get('label') or ''} | {q.get('country') or ''} |")
                out.append("")
        out.append("---")
        out.append("")
    return "\n".join(out)


def backfill_build(root, build):
    """Stamp the build onto manifests written before the driver could read it.

    Safe only because the build did not change during the run: these runs
    executed inside one container from one image. A manifest that already
    names a build is never overwritten.
    """
    touched = []
    for d in sorted(root.iterdir()):
        f = d / "manifest.json" if d.is_dir() else None
        if not f or not f.exists():
            continue
        m = json.loads(f.read_text("utf-8"))
        if m.get("build"):
            continue
        m["build"] = build
        m["build_backfilled"] = True
        f.write_text(json.dumps(m, indent=2, default=str,
                                ensure_ascii=False), encoding="utf-8")
        touched.append(d.name)
    return touched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--build", default="", help="stamp manifests missing one")
    args = ap.parse_args()
    root = pathlib.Path(args.out)

    if args.build:
        done = backfill_build(root, args.build)
        if done:
            print(f"stamped build {args.build} onto {len(done)} manifest(s)")

    rows = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not (d / "estimate_v0.json").exists():
            continue
        rows.append(tuple(
            json.loads((d / f"{n}.json").read_text("utf-8"))
            for n in ("manifest", "simulation", "estimate_v0", "research")))

    with (root / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([n for n, _ in FIELDS])
        for m, s, e, r in rows:
            w.writerow([fn(m, s, e, r) for _, fn in FIELDS])

    (root / "HIGHLIGHTS.md").write_text(highlights_md(rows), encoding="utf-8")
    print(f"{len(rows)} company(ies) -> summary.csv, HIGHLIGHTS.md")


if __name__ == "__main__":
    main()
