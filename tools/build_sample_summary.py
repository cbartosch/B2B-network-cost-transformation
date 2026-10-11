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
    """Distinct source URLs across every researched domain.

    sources became a list of dicts when the harvest started keeping the
    publisher and the vintage alongside the URL; adding a dict to a set
    raises, and counting one would have been wrong anyway.
    """
    seen = set()
    for h in (r.get("highlights") or {}).values():
        for sc in h.get("sources") or []:
            url = sc.get("url") if isinstance(sc, dict) else sc
            if url:
                seen.add(url)
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
            disp = d.get("disposition")
            srcs = d.get("sources") or []
            tri = d.get("triangulated") or []
            qty = d.get("quantities") or []
            qual = d.get("qualitative") or []

            if not disp:
                out += [f"**{label}** - not researched", ""]
                continue
            if not (tri or qty or qual or srcs):
                # A real outcome: the agent looked and reported nothing.
                out += [f"**{label}** - {disp}"
                        + (f": {d['reason']}" if d.get("reason") else ""), ""]
                continue

            out += [f"**{label}** - {disp}, {len(srcs)} source(s)", ""]

            # Prose first where there is any. It is the half of a finding
            # that is not a number, and it is where an architecture or a
            # vendor relationship actually gets described.
            for item in qual[:6]:
                lab = str(item.get("label") or "").strip()
                val = str(item.get("value") or "").strip()
                if lab or val:
                    out.append(f"- {lab}{': ' if lab and val else ''}{val}")
            if qual[:6]:
                out.append("")

            # Then the numbers, as bands where triangulation produced one -
            # a band with a vintage is a figure someone can argue with, a
            # bare value is not.
            rows = tri or qty
            if rows:
                banded = bool(tri)
                # The separator must have as many cells as the header or
                # the table renders as a paragraph.
                cols = (["what", "country", "low", "base", "high", "as of"]
                        if banded else
                        ["what", "country", "value", "unit", "as of"])
                out.append("| " + " | ".join(cols) + " |")
                out.append("| " + " | ".join(["---"] * len(cols)) + " |")
                for r in rows[:14]:
                    lab = str(r.get("label") or "")[:60]
                    ctry = r.get("country") or ""
                    if banded:
                        out.append(
                            f"| {lab} | {ctry} | {r.get('low')} | "
                            f"{r.get('base')} | {r.get('high')} | "
                            f"{r.get('newest_year') or ''} |")
                    else:
                        out.append(
                            f"| {lab} | {ctry} | {r.get('value')} | "
                            f"{r.get('unit') or ''} | {r.get('as_of') or ''} |")
                if len(rows) > 14:
                    out.append("| " + f"... {len(rows) - 14} more"
                               + " |" * len(cols))
                out.append("")

            # Conflicts are a result, not noise: two sources disagreeing is
            # information, and the model says so rather than averaging.
            conf = d.get("conflicts") or []
            if conf:
                out.append(f"*{len(conf)} conflict(s) flagged: "
                           + ", ".join(sorted({str(c.get('label') or '?')
                                               for c in conf})[:6]) + "*")
                out.append("")

            if srcs:
                # Both shapes. A source was a bare URL string before the
                # harvest started keeping the publisher and the vintage with
                # it, and a set written by an older run should still render.
                pairs = []
                for c in srcs:
                    if isinstance(c, dict) and c.get("url"):
                        pairs.append((c.get("publisher") or c["url"], c["url"]))
                    elif isinstance(c, str) and c:
                        pairs.append((c, c))
                shown = pairs[:4]
                if shown:
                    out.append("Sources: " + "; ".join(
                        f"[{name[:48]}]({url})" for name, url in shown)
                        + (f" and {len(pairs) - len(shown)} more"
                           if len(pairs) > len(shown) else ""))
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
