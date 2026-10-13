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
import sys

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
    # CR-07 / F11: why that one. It was picked here as the largest base
    # saving and the reason was recorded nowhere, so a reader comparing two
    # companies could not tell whether the choice meant anything.
    ("best_scenario_reason", lambda m, s, e, r: _best_reason(e)),
    ("best_saving_base", lambda m, s, e, r: _best(e)[1]),
    # The headline split by what it rests on. A saving on drawn value is
    # reported, never mixed into the figure a reader takes as the answer.
    ("saving_on_specified_baseline",
     lambda m, s, e, r: _scen(e, "saving_on_specified_baseline")),
    ("saving_on_simulated_baseline",
     lambda m, s, e, r: _scen(e, "saving_on_simulated_baseline")),
    ("one_time_cost_base", lambda m, s, e, r: _trans(e, "one_time_cost")),
    ("payback_months_base", lambda m, s, e, r: _payback(e)),
    ("programme_months", lambda m, s, e, r: _prog(e)),
    # The number that says how much to trust the rest of the row.
    ("confidence_overall", lambda m, s, e, r: _g(e, "confidence", "overall")),
    ("confidence_band", lambda m, s, e, r: _g(e, "confidence", "band")),
    # CR-08 / F10. The three components, the weighted figure and the
    # ceilings are already published below as conf_* - CR-01 surfaced them.
    # Only the weights were genuinely missing, and without them the score
    # could be read but not reproduced, which is the acceptance criterion.
    #
    # The first version of this added confidence_current_baseline,
    # confidence_target_cost, confidence_realization, confidence_weighted
    # and confidence_ceilings_applied beside identical conf_* columns. Two
    # names for one number in one row is how a reader ends up asking which
    # is authoritative.
    # CR-03. The flag, what drove it, and the grade of the benchmark behind
    # it - a reader seeing OK is entitled to know whether that came from a
    # sourced range or from an unsourced tripwire.
    ("plausibility_flag", lambda m, s, e, r: _g(e, "baseline_plausibility",
                                                "flag")),
    ("plausibility_per_site",
     lambda m, s, e, r: _g(e, "baseline_plausibility", "metrics",
                           "BASELINE_PER_SITE", "value")),
    ("plausibility_per_site_flag",
     lambda m, s, e, r: _g(e, "baseline_plausibility", "metrics",
                           "BASELINE_PER_SITE", "flag")),
    ("plausibility_benchmark_grade",
     lambda m, s, e, r: _g(e, "baseline_plausibility", "metrics",
                           "BASELINE_PER_SITE", "benchmark",
                           "evidence_grade")),
    ("confidence_weights", lambda m, s, e, r: _pipe(
        f"{k}={v}" for k, v in sorted(
            (_g(e, "confidence", "weights") or {}).items()))),
    ("confidence_cap_headroom",
     lambda m, s, e, r: _g(e, "confidence", "component_cap_headroom")),
    # Renamed, not redefined. It measures how much of the declared scope was
    # priced - 27 published fields' worth - and says nothing about evidence.
    # Beside a domain count in one row, "coverage COMPLETE" read as "we know
    # a lot about this company". The evidence columns below are the other
    # axis, and they are the ones that were missing.
    ("priced_scope_status", lambda m, s, e, r: _g(e, "coverage", "status")),
    ("priced_spend_pct", lambda m, s, e, r: _g(e, "coverage", "priced_spend_pct")),
    ("unsourced_price_share",
     lambda m, s, e, r: _g(e, "coverage", "unsourced_price_share")),
    # CR-01: where the baseline's value actually comes from.
    ("evidenced_share", lambda m, s, e, r: evidence_shares(e)[0]["evidenced_share"]),
    ("derived_share", lambda m, s, e, r: evidence_shares(e)[0]["derived_share"]),
    ("client_confirmed_share",
     lambda m, s, e, r: evidence_shares(e)[0]["client_confirmed_share"]),
    ("assumed_share", lambda m, s, e, r: evidence_shares(e)[0]["assumed_share"]),
    ("simulated_value_share",
     lambda m, s, e, r: evidence_shares(e)[0]["simulated_share"]),
    ("unknown_share", lambda m, s, e, r: evidence_shares(e)[0]["unknown_share"]),
    ("shares_sum", lambda m, s, e, r: f"{evidence_shares(e)[1]:.4f}"),
    # CR-02a: what the baseline covers.
    ("scope_status", lambda m, s, e, r: m.get("scope_status")),
    ("scope_countries_modelled",
     lambda m, s, e, r: "|".join(m.get("scope_countries_modelled") or [])),
    ("scope_countries_company_total",
     lambda m, s, e, r: m.get("scope_countries_company_total")),
    # CR-08: the components confidence is built from, which already existed.
    ("conf_current_baseline",
     lambda m, s, e, r: _g(e, "confidence", "current_baseline")),
    ("conf_target_cost", lambda m, s, e, r: _g(e, "confidence", "target_cost")),
    ("conf_realization", lambda m, s, e, r: _g(e, "confidence", "realization")),
    ("conf_weighted", lambda m, s, e, r: _g(e, "confidence", "weighted")),
    ("conf_ceilings_applied",
     lambda m, s, e, r: "|".join(_g(e, "confidence", "ceilings_applied") or [])),
    ("conf_evidenced_value_share",
     lambda m, s, e, r: _g(e, "confidence", "drivers", "evidenced_value_share")),
    ("conf_domain_completeness",
     lambda m, s, e, r: _g(e, "confidence", "drivers", "domain_completeness")),
    ("conf_prior_recency",
     lambda m, s, e, r: _g(e, "confidence", "drivers", "prior_recency")),
    # CR-09: local currency stays the source of truth.
    ("fx_rate_to_eur", lambda m, s, e, r: (m.get("fx_to_eur") or {}).get("rate")),
    ("fx_date", lambda m, s, e, r: (m.get("fx_to_eur") or {}).get("as_of")),
    ("fx_evidence_grade",
     lambda m, s, e, r: (m.get("fx_to_eur") or {}).get("evidence_grade")),
    ("baseline_base_eur", lambda m, s, e, r: _eur(m, _g(e, "current_tco", "base"))),
    ("best_saving_base_eur", lambda m, s, e, r: _eur(m, _best(e)[1])),
    ("one_time_cost_base_eur",
     lambda m, s, e, r: _eur(m, _trans(e, "one_time_cost"))),
    ("simulated_share", lambda m, s, e, r: e.get("simulated_share")),
    ("asserted_share", lambda m, s, e, r: e.get("asserted_share")),
    # The research, counted rather than quoted.
    ("domains_requested", lambda m, s, e, r: len(m.get("domains_requested")
                                                or m.get("domains_researched") or [])),
    ("domains_researched", lambda m, s, e, r: len(m["domains_researched"])),
    ("resumed", lambda m, s, e, r: m.get("resumed_existing_case")),
    ("domains_evidenced", lambda m, s, e, r: _count(r, "EVIDENCED_PUBLIC")),
    # Two different things, both worth having: a domain the agent answered
    # with "nothing found" is a result; a domain with no evidence at all is
    # a gap. The summary reported only the first and called it the second.
    ("domains_agent_declared_unknown",
     lambda m, s, e, r: _count(r, "DECLARED_UNKNOWN")),
    ("domains_no_evidence",
     lambda m, s, e, r: len(m.get("domains_declared_unknown") or [])),
    ("domains_no_evidence_list",
     lambda m, s, e, r: "|".join(
         str(x) for x in (m.get("domains_declared_unknown") or []))),
    ("research_sources", lambda m, s, e, r: _sources(r)),
    ("research_minutes", lambda m, s, e, r: round(
        sum(r.get("timings_seconds", {}).values()) / 60, 1)),
]




# --------------------------------------------------------------- CR-01 shares
# A component is only as evidenced as its weakest axis.
#
# Two origins govern each component: where its quantity came from and where
# its unit cost came from. A sourced site count priced from a seeded
# benchmark is not evidenced - it is an evidenced count carrying an assumed
# price, and reporting it as evidenced is how an estimate comes to look
# better sourced than it is. So the class is the weaker of the two.
_QUANTITY_CLASS = {
    "EVIDENCED_PUBLIC": "evidenced",
    "DERIVED_PUBLIC": "derived",
    "CLIENT_CONFIRMED": "client_confirmed",
    "ANALYST_ENTERED_SCOPE": "assumed",
    "ANALYST_ASSERTED_PRIOR": "assumed",
    "SIMULATED": "simulated",
}
_PRICE_CLASS = {
    "EVIDENCED_PUBLIC": "evidenced",
    "DERIVED_PUBLIC": "derived",
    "CLIENT_CONFIRMED": "client_confirmed",
    "BENCHMARK_PRIOR": "assumed",
    "SIMULATED": "simulated",
}
# Weakest first: the class a component lands in is the lowest of its two.
_RANK = ["unknown", "simulated", "assumed", "derived", "client_confirmed",
         "evidenced"]


def evidence_shares(e):
    """Baseline value by evidence class, summing to 1.0."""
    comps = e.get("components") or []
    tot = sum(float(_g(c, "value", "base") or 0) for c in comps)
    agg = {k: 0.0 for k in _RANK}
    for c in comps:
        q = _QUANTITY_CLASS.get(c.get("quantity_origin"), "unknown")
        u = _PRICE_CLASS.get(c.get("unit_cost_origin"), "unknown")
        cls = min(q, u, key=_RANK.index)
        agg[cls] += float(_g(c, "value", "base") or 0)
    if tot <= 0:
        return {f"{k}_share": "0.0000" for k in _RANK}, 0.0
    out = {f"{k}_share": f"{agg[k] / tot:.4f}" for k in _RANK}
    return out, sum(agg.values()) / tot

def _g(d, *path):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _eur(m, value):
    """Derived, and only where a dated rate exists. A missing rate yields
    DECLARED_UNKNOWN rather than the local figure relabelled."""
    fx = (m.get("fx_to_eur") or {}).get("rate")
    if value in (None, "") or not fx:
        return "DECLARED_UNKNOWN"
    return f"{float(value) * float(fx):.2f}"


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


def _pipe(items):
    """Pipe-delimited, because a CSV cell cannot hold a list and a comma
    would split the column."""
    return "|".join(str(x) for x in items) or None


def _scen(e, key):
    """A field off the scenario the summary selected."""
    code, _ = _best(e)
    return ((e.get("scenarios") or {}).get(code) or {}).get(key)


def _best_reason(e):
    """Why this scenario and not another, in the summary's own terms.

    The engine already publishes each scenario's label, levers, ceiling and
    non-applicable levers with reasons; what was missing was the comparison
    the summary itself makes. Written here because the choice is made here -
    recording it anywhere else would be recording a different decision.
    """
    scen = e.get("scenarios") or {}
    code, val = _best(e)
    if not code:
        return None
    ranked = sorted(
        ((c, _g(sc, "gross_run_rate_savings", "base")) for c, sc in scen.items()),
        key=lambda kv: float(kv[1] or 0), reverse=True)
    label = (scen.get(code) or {}).get("label") or code
    if len(ranked) < 2 or not ranked[1][1]:
        return f"{label}: only scenario with a saving"
    runner, second = ranked[1]
    margin = float(val or 0) - float(second or 0)
    pct = (margin / float(second)) * 100 if float(second) else 0
    unev = _scen(e, "saving_on_simulated_baseline")
    tail = ""
    if unev and float(unev) > 0 and float(val or 0):
        tail = (f"; {float(unev) / float(val) * 100:.0f}% of it rests on "
                f"unevidenced baseline")
    return (f"{label}: largest base saving, {margin:,.0f} ({pct:.0f}%) above "
            f"{runner}{tail}")


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


def backfill_fx(root, rates):
    """Fill in an FX rate a manifest could not find when it ran.

    CR-09. reference.fx_rate is USD-quoted - every row is USD->X - so only
    USD had a direct line to EUR and CHF, GBP and anything else went out as
    DECLARED_UNKNOWN. The rates were in the table the whole time, one
    division apart. Three of twenty companies could not be compared.

    Only a manifest with no rate is touched; one that found its own is never
    overwritten. Marked, because a rate read after the fact is not the rate
    the run read, even when it is the same number.
    """
    touched = []
    for d in sorted(root.iterdir()):
        f = d / "manifest.json" if d.is_dir() else None
        if not f or not f.exists():
            continue
        m = json.loads(f.read_text("utf-8"))
        fx = m.get("fx_to_eur") or {}
        if fx.get("rate"):
            continue
        fresh = rates.get((m.get("base_currency") or "").upper())
        if not fresh or not fresh.get("rate"):
            continue
        m["fx_to_eur"] = {**fresh, "backfilled": True}
        f.write_text(json.dumps(m, indent=2, default=str,
                                ensure_ascii=False), encoding="utf-8")
        touched.append(d.name)
    return touched


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
    ap.add_argument("--no-gate", action="store_true",
                    help="publish without running the validation gate")
    ap.add_argument("--fx", default="",
                    help="JSON of currency -> fx_to_eur, to fill in a rate a "
                         "manifest could not find when it ran")
    args = ap.parse_args()
    root = pathlib.Path(args.out)

    if args.build:
        done = backfill_build(root, args.build)
        if done:
            print(f"stamped build {args.build} onto {len(done)} manifest(s)")

    if args.fx:
        rates = json.loads(pathlib.Path(args.fx).read_text("utf-8"))
        done = backfill_fx(root, {k.upper(): v for k, v in rates.items()})
        if done:
            print(f"backfilled an FX rate onto {len(done)} manifest(s): "
                  f"{', '.join(done)}")

    rows = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not (d / "estimate_v0.json").exists():
            continue
        rows.append(tuple(
            json.loads((d / f"{n}.json").read_text("utf-8"))
            for n in ("manifest", "simulation", "estimate_v0", "research")))

    # CR-NCT-001 section 6: the gate runs before the summary is published.
    #
    # Written to a staging name, gated, and only then promoted. The gate
    # reads a summary - most of its checks are on the rolled-up row - so
    # "before it is written" has to mean "before the published one is",
    # not "before any file exists". A set that fails leaves summary.csv as
    # it was and the staging file on disk to look at, which is more use
    # than no file and a stack trace.
    staged = root / "summary.staged.csv"
    with staged.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([n for n, _ in FIELDS])
        for m, s, e, r in rows:
            w.writerow([fn(m, s, e, r) for _, fn in FIELDS])

    if not args.no_gate:
        import shutil
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            # The gate wants a directory shaped like a sample set. Linking
            # the company folders rather than copying keeps a 16MB set from
            # being duplicated on every build.
            stage_dir = pathlib.Path(td) / "staged"
            stage_dir.mkdir()
            shutil.copy(staged, stage_dir / "summary.csv")
            for d in root.iterdir():
                if d.is_dir():
                    (stage_dir / d.name).symlink_to(d.resolve(),
                                                    target_is_directory=True)
            gate = subprocess.run(
                [sys.executable,
                 str(pathlib.Path(__file__).with_name("validation_gate.py")),
                 "--out", str(stage_dir)])
        if gate.returncode != 0:
            print()
            print(f"summary NOT published. The staged rows are at "
                  f"{staged} if you want to look at what failed.")
            return 1

    staged.replace(root / "summary.csv")
    (root / "HIGHLIGHTS.md").write_text(highlights_md(rows), encoding="utf-8")
    print(f"{len(rows)} company(ies) -> summary.csv, HIGHLIGHTS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
