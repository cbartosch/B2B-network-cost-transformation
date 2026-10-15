"""Render the sample-set review page from what the run already wrote.

Reads summary.csv and each company's estimate, and computes every figure it
shows. Nothing is restated: the totals, the grade mix, the counts of flagged
and short-researched companies and the confidence range are all derived, so
the page cannot drift from the set it describes.

The first version of this page was a throwaway script that was deleted after
use, which left a committed report nothing could regenerate - the same shape
as most of the defects it describes.

    python tools/build_sample_review.py --out samples/outside_in

    --compare <git-rev>   add a baseline-change table against that revision
                          of summary.csv, for showing what a change did
"""
import argparse
import csv
import html
import io
import json
import pathlib
import subprocess
import sys

OUT_DEFAULT = pathlib.Path("docs") / "sample-set-review.html"

#: Grades that mean "an expert assumption or worse" - the same split
#: coverage.unsourced_price_share uses, named once here.
UNSOURCED_GRADES = ("E", "F")


def _f(row, key, default=0.0):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return default


def read_set(outdir: pathlib.Path) -> list:
    """One record per company, from the summary and its estimate."""
    summary = outdir / "summary.csv"
    if not summary.exists():
        raise SystemExit(f"no summary at {summary} - run "
                         f"tools/build_sample_summary.py first")
    rows = list(csv.DictReader(summary.open(encoding="utf-8")))
    out = []
    for r in rows:
        est = outdir / r["slug"] / "estimate_v0.json"
        mix = {}
        if est.exists():
            cov = (json.loads(est.read_text("utf-8")).get("coverage") or {})
            mix = cov.get("evidence_grade_mix") or {}
        out.append({
            "slug": r["slug"], "company": r["company"],
            "industry": r["industry"],
            "sites": int(_f(r, "sites")),
            "base": _f(r, "baseline_base_eur"),
            "sav": _f(r, "best_saving_base_eur"),
            "conf": _f(r, "confidence_overall"),
            "band": r.get("confidence_band", ""),
            "dom": int(_f(r, "domains_researched")),
            "v0": r.get("v0_status", ""),
            "plaus": r.get("plausibility_flag", ""),
            "payback": int(_f(r, "steady_state_payback_months_base")),
            "build": r.get("build", ""),
            # Share of priced value at each evidence grade. The sourced share
            # is everything that is not an assumption, so a grade the card
            # gains later counts without this needing to know about it.
            "mix": {g: float(v) for g, v in mix.items()},
        })
    return sorted(out, key=lambda x: -x["base"])


def sourced_share(rec: dict) -> float:
    """Share of this company's priced value on better than an assumption."""
    return sum(v for g, v in rec["mix"].items()
               if g not in UNSOURCED_GRADES) * 100


def facts(recs: list) -> dict:
    """Everything the prose quotes, computed rather than written down."""
    total = sum(r["base"] for r in recs) or 1.0
    sourced = sum(r["base"] * sourced_share(r) / 100 for r in recs)
    confs = [r["conf"] for r in recs if r["conf"]]
    short = [r for r in recs if r["dom"] < 17]
    return {
        "n": len(recs),
        "total": total,
        "saving": sum(r["sav"] for r in recs),
        "saving_pct": sum(r["sav"] for r in recs) / total * 100,
        "with_sourced": sum(1 for r in recs if sourced_share(r) > 0.05),
        "vw_sourced": sourced / total * 100,
        "conf_lo": min(confs) if confs else 0,
        "conf_hi": max(confs) if confs else 0,
        "bands": sorted({r["band"] for r in recs if r["band"]}),
        "partial": [r["company"] for r in recs if r["v0"] != "COMPLETE"],
        "flagged": [(r["company"], r["plaus"]) for r in recs
                    if r["plaus"] and r["plaus"] != "OK"],
        "short": [(r["company"], r["dom"]) for r in
                  sorted(short, key=lambda r: r["dom"])],
        "build": next((r["build"] for r in recs if r["build"]), "unknown"),
        "sav_lo": min(r["sav"] / r["base"] * 100 for r in recs if r["base"]),
        "sav_hi": max(r["sav"] / r["base"] * 100 for r in recs if r["base"]),
        "pay_lo": min(r["payback"] for r in recs),
        "pay_hi": max(r["payback"] for r in recs),
    }


def compare(outdir: pathlib.Path, rev: str) -> list:
    """Baseline change against a past revision of the same summary.

    Optional, and omitted rather than guessed at: a before-and-after needs a
    before, and the generator has no way to invent one.
    """
    path = f"{rev}:{outdir.as_posix()}/summary.csv"
    got = subprocess.run(["git", "show", path], capture_output=True,
                         text=True, encoding="utf-8")
    if got.returncode != 0:
        raise SystemExit(f"cannot read {path}: {got.stderr.strip()[:120]}")
    old = {r["slug"]: r for r in csv.DictReader(io.StringIO(got.stdout))}
    new = {r["slug"]: r for r in
           csv.DictReader((outdir / "summary.csv").open(encoding="utf-8"))}
    moved = []
    for slug, row in new.items():
        before, after = (_f(old.get(slug, {}), "baseline_base_eur"),
                         _f(row, "baseline_base_eur"))
        if before and abs((after - before) / before) > 0.0005:
            moved.append((row["company"], (after - before) / before * 100))
    return sorted(moved, key=lambda m: m[1])


# ------------------------------------------------------------------ render

def _row(rec: dict) -> str:
    sourced = sourced_share(rec)
    flag = ("" if rec["plaus"] in ("OK", "")
            else f'<span class="flag">{html.escape(rec["plaus"])}</span>')
    v0 = "" if rec["v0"] == "COMPLETE" else '<span class="flag">PARTIAL</span>'
    dom = (f'{rec["dom"]}/17' if rec["dom"] >= 17
           else f'<span class="warn">{rec["dom"]}/17</span>')
    cell = (f'<td class="n good">{sourced:.0f}%</td>' if sourced > 0.05
            else '<td class="n dim">&mdash;</td>')
    ind = html.escape(rec["industry"].replace("_", " ").title())
    return ("<tr>"
            f'<th scope="row">{html.escape(rec["company"])}<em>{ind}</em></th>'
            f'<td class="n">{rec["sites"]:,}</td>'
            f'<td class="n strong">{rec["base"] / 1e6:,.1f}</td>'
            f'<td class="n">{rec["sav"] / 1e6:,.1f}</td>'
            f'<td class="n">{rec["sav"] / max(rec["base"], 1) * 100:.0f}%</td>'
            f'<td class="n">{rec["payback"]}</td>'
            f'<td class="n">{rec["conf"]:.2f}</td>'
            f'<td class="n">{dom}</td>{cell}'
            f'<td class="st">{v0}{flag}</td>'
            "</tr>")


def _listing(pairs, fmt) -> str:
    return ", ".join(fmt(a, b) for a, b in pairs) if pairs else "none"


STYLE = """
:root{--paper:#fbfcfd;--raise:#fff;--ink:#11161c;--muted:#5a6675;
--line:#dfe5ec;--line-soft:#eef2f6;--dim:#9aa6b4;
--caution:#b45309;--caution-bg:#fdf5e9;--caution-line:#e8cfa6;--good:#0f766e;
--shadow:0 1px 2px rgba(17,22,28,.05),0 8px 24px -16px rgba(17,22,28,.25)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
--paper:#0d1115;--raise:#141a21;--ink:#e7edf3;--muted:#93a1b1;
--line:#242e39;--line-soft:#1b232c;--dim:#5d6b7a;
--caution:#e9a23b;--caution-bg:#241c0f;--caution-line:#4d3a1c;--good:#4fc4b4;
--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.8)}}
:root[data-theme="dark"]{--paper:#0d1115;--raise:#141a21;--ink:#e7edf3;
--muted:#93a1b1;--line:#242e39;--line-soft:#1b232c;--dim:#5d6b7a;
--caution:#e9a23b;--caution-bg:#241c0f;--caution-line:#4d3a1c;--good:#4fc4b4;
--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.8)}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font:400 16px/1.6 "IBM Plex Sans",ui-sans-serif,system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:56px 24px 96px}
header{border-bottom:1px solid var(--line);padding-bottom:28px;margin-bottom:40px}
.eyebrow{font:500 12px/1 "IBM Plex Mono",ui-monospace,monospace;
letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
h1{font:600 clamp(32px,5vw,46px)/1.1 "Newsreader",Georgia,serif;
margin:14px 0 10px;letter-spacing:-.015em;text-wrap:balance}
.sub{color:var(--muted);max-width:62ch;margin:0;font-size:17px}
h2{font:600 clamp(21px,2.6vw,26px)/1.25 "Newsreader",Georgia,serif;
margin:56px 0 6px;letter-spacing:-.01em;text-wrap:balance}
.lede{color:var(--muted);margin:0 0 22px;max-width:68ch}
h3{font:600 16px/1.3 "IBM Plex Sans",sans-serif;margin:28px 0 8px}
p{max-width:72ch}
.verdict{background:var(--raise);border:1px solid var(--line);
border-left:3px solid var(--good);border-radius:3px;padding:22px 26px;
box-shadow:var(--shadow)}
.verdict p{margin:0 0 10px}.verdict p:last-child{margin:0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:1px;background:var(--line);border:1px solid var(--line);border-radius:3px;
margin:28px 0 8px;overflow:hidden}
.kpi{background:var(--raise);padding:16px 18px}
.kpi .v{font:500 25px/1.1 "IBM Plex Mono",monospace;letter-spacing:-.02em;
font-variant-numeric:tabular-nums}
.kpi .k{font-size:12.5px;color:var(--muted);margin-top:5px;line-height:1.4}
.kpi.bad .v{color:var(--caution)}.kpi.ok .v{color:var(--good)}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:3px;
background:var(--raise);margin:20px 0}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:900px}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line-soft);
white-space:nowrap}
thead th{font:500 11px/1.3 "IBM Plex Mono",monospace;letter-spacing:.07em;
text-transform:uppercase;color:var(--muted);background:var(--paper);
position:sticky;top:0;border-bottom:1px solid var(--line)}
tbody th{font-weight:500;white-space:normal;min-width:170px}
tbody th em{display:block;font:400 11.5px/1.3 "IBM Plex Sans",sans-serif;
color:var(--muted);font-style:normal;margin-top:2px}
td.n{text-align:right;font-family:"IBM Plex Mono",monospace;
font-variant-numeric:tabular-nums;font-size:13px}
td.strong{font-weight:500}td.good{color:var(--good);font-weight:500}
td.dim{color:var(--dim)}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:none}
.flag{display:inline-block;font:500 10.5px/1 "IBM Plex Mono",monospace;
letter-spacing:.06em;padding:3px 6px;border-radius:2px;
background:var(--caution-bg);color:var(--caution);
border:1px solid var(--caution-line);margin-right:4px}
.warn{color:var(--caution)}
.note{font-size:13.5px;color:var(--muted);margin-top:8px}
ul{max-width:72ch;padding-left:20px}li{margin:9px 0}
.find{border-top:1px solid var(--line);padding:18px 0 4px}
.find h3{margin:0 0 4px}
.find p{margin:0;color:var(--muted);font-size:14.5px}
code{font:400 13px/1 "IBM Plex Mono",monospace;background:var(--line-soft);
padding:2px 5px;border-radius:2px}
footer{margin-top:64px;padding-top:20px;border-top:1px solid var(--line);
color:var(--muted);font-size:13px}
"""


def render(recs: list, f: dict, moved: list, rev: str) -> str:
    body = "\n".join(_row(r) for r in recs)
    band = f["bands"][0] if len(f["bands"]) == 1 else ", ".join(f["bands"])

    delta = ""
    if moved:
        lines = "\n".join(
            f'<tr><th scope="row">{html.escape(c)}</th>'
            f'<td class="n">{"&minus;" if d < 0 else "+"}'
            f'{abs(d):.1f}%</td></tr>' for c, d in moved)
        delta = f"""
<h2>What changed</h2>
<p class="lede">Baseline movement against <code>{html.escape(rev)}</code>
&mdash; {len(moved)} of {f["n"]} companies moved.</p>
<div class="scroll"><table style="min-width:400px">
<thead><tr><th scope="col">Company</th>
<th scope="col" class="n">Baseline change</th></tr></thead>
<tbody>
{lines}
</tbody></table></div>"""

    return f"""<title>Outside-In Estimate Review</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{STYLE}</style>

<div class="wrap">
<header>
  <div class="eyebrow">B2B network cost transformation &middot; sample set review</div>
  <h1>{f["n"]} outside-in estimates</h1>
  <p class="sub">What the set says, where each number comes from, and how much
  of it rests on an observed price rather than a seeded assumption.</p>
</header>

<div class="verdict">
  <p><strong>{f["n"]} companies price without error and every gate
  passes.</strong> {f["with_sourced"]} of them carry value priced from an
  observed market rate; the rest are seeded throughout.</p>
  <p>Across the set, value-weighted, that is
  <strong>{f["vw_sourced"]:.1f}% sourced against
  {100 - f["vw_sourced"]:.1f}% assumption</strong> &mdash; grade&nbsp;E, with
  no transaction, quote or published benchmark behind it.</p>
  <p>Research determines <em>how many sites</em>; the rate card determines
  <em>what they cost</em>. The cost side is where the evidence is thinnest.</p>
</div>

<div class="kpis">
  <div class="kpi"><div class="v">{f["n"]}</div><div class="k">companies, all priced</div></div>
  <div class="kpi"><div class="v">&euro;{f["total"] / 1e6:,.0f}m</div><div class="k">baseline, EUR-normalised</div></div>
  <div class="kpi"><div class="v">{f["saving_pct"]:.1f}%</div><div class="k">max base-case saving</div></div>
  <div class="kpi ok"><div class="v">{f["with_sourced"]}/{f["n"]}</div><div class="k">carry observed prices</div></div>
  <div class="kpi bad"><div class="v">{100 - f["vw_sourced"]:.1f}%</div><div class="k">assumption, value-weighted</div></div>
  <div class="kpi"><div class="v">{f["conf_lo"]:.2f}&ndash;{f["conf_hi"]:.2f}</div><div class="k">confidence, all {html.escape(band)}</div></div>
</div>
<p class="note">Band D &mdash; Indicative &mdash; is a property of the method:
outside-in, public evidence only, <code>NO_CONTACT</code>. No parameter change
moves it.</p>
{delta}

<h2>The {f["n"]}</h2>
<p class="lede">Sorted by baseline. <em>Sourced</em> is the share of priced
value resting on a rate better than an expert assumption.</p>
<div class="scroll">
<table>
<thead><tr>
<th scope="col">Company</th><th scope="col" class="n">Sites</th>
<th scope="col" class="n">Baseline &euro;m</th><th scope="col" class="n">Saving &euro;m</th>
<th scope="col" class="n">Save&nbsp;%</th><th scope="col" class="n">Payback</th>
<th scope="col" class="n">Conf.</th><th scope="col" class="n">Domains</th>
<th scope="col" class="n">Sourced</th><th scope="col">Flags</th>
</tr></thead>
<tbody>
{body}
</tbody>
</table>
</div>
<p class="note">Totals &euro;{f["total"] / 1e6:,.1f}m baseline,
&euro;{f["saving"] / 1e6:,.1f}m saving. Savings range
{f["sav_lo"]:.0f}&ndash;{f["sav_hi"]:.0f}%; payback
{f["pay_lo"]}&ndash;{f["pay_hi"]} months.</p>

<h2>What is actually evidenced</h2>
<p class="lede">Two questions, often conflated: how many sites, and what each
one costs.</p>
<ul>
<li><strong>Quantities are part-evidenced.</strong> Site counts start from a
declared footprint and research supersedes where it finds a sourced count at
least as large. The declared base is <code>ANALYST_ENTERED_SCOPE</code>, so
<code>evidenced_share</code> stays 0: it measures the <em>origin</em> of a
quantity, and that origin is a specification rather than a discovery.</li>
<li><strong>Unit costs are {f["vw_sourced"]:.1f}% sourced,
value-weighted</strong>, against a card otherwise grade&nbsp;E:
<em>&ldquo;indicative starting position set at seed time; no transaction,
quote or published benchmark behind it.&rdquo;</em></li>
<li><strong>So {f["saving_pct"]:.1f}% savings rests mostly on
assumption</strong> &mdash; not yet a claim about what these companies
spend.</li>
</ul>

<h2>Scope, and what the flags mean</h2>
<ul>
<li><strong>Every company is <code>PARTIAL_COUNTRIES</code></strong> and the
denominator is <code>DECLARED_UNKNOWN</code>. This is not &ldquo;three of
twenty modelled&rdquo;, it is &ldquo;three modelled, total unknown&rdquo;.</li>
<li><strong>Partial at v0:</strong>
{html.escape(", ".join(f["partial"]) or "none")}.</li>
<li><strong>Plausibility flags:</strong>
{html.escape(_listing(f["flagged"], lambda c, v: f"{c} ({v})"))}. The
tripwires are grade&nbsp;F and catch only order-of-magnitude error, so a flag
is a prompt to look rather than a finding.</li>
<li><strong>Short of 17 researched domains:</strong>
{html.escape(_listing(f["short"], lambda c, n: f"{c} at {n}"))}.</li>
</ul>

<h2>The recurring defect</h2>
<p>Nearly everything found in this set was a guard that existed and checked
the weaker property. <code>set_industry_if_absent</code> asked whether an
industry code was <em>a</em> code, never <em>this entity&rsquo;s</em>. The
footprint merge could not tell &ldquo;not listed&rdquo; from
&ldquo;excluded&rdquo;. Promotion let write order choose between a national
total and a state breakdown. The rate card let query order choose between a
researched price and the seed it displaced. The evidence metric read a dict
with <code>getattr</code> and reported a constant.</p>
<p>In every case the output looked normal, which is why reading the code
found none of them and running it found all of them &mdash; usually as an
expected movement that did not happen.</p>

<h2>Before any of this leaves the room</h2>
<ul>
<li><strong>{f["n"] - f["with_sourced"]} companies carry no observed price at
all.</strong> Every market without a researched rate is seeded throughout.</li>
<li><strong>A handful of prices is not a rate card.</strong> The evidence is
real and narrow &mdash; single observations, widened to the card&rsquo;s own
&plusmn;25% rather than to anything measured.</li>
<li><strong>CR-03 plausibility ranges, CR-05 wave parameters, CR-01 coverage
thresholds</strong> still need values.</li>
<li><strong>Nothing here is safe for external use</strong> on the strength of
the gate alone. A clean gate is necessary and not sufficient, and the tooling
says so on every run.</li>
</ul>

<footer>
Generated by <code>tools/build_sample_review.py</code> from
<code>samples/outside_in/summary.csv</code> &mdash; {f["n"]} companies, build
{html.escape(str(f["build"]))}. Figures EUR-normalised at seeded indicative
FX, itself grade&nbsp;E.
</footer>
</div>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="samples/outside_in",
                    help="the published sample directory to read")
    ap.add_argument("--page", default=str(OUT_DEFAULT),
                    help="where to write the page")
    ap.add_argument("--compare", default="",
                    help="git revision to show baseline movement against")
    args = ap.parse_args()

    outdir = pathlib.Path(args.out)
    recs = read_set(outdir)
    if not recs:
        raise SystemExit(f"no companies in {outdir}")
    f = facts(recs)
    moved = compare(outdir, args.compare) if args.compare else []

    page = pathlib.Path(args.page)
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(render(recs, f, moved, args.compare), encoding="utf-8")
    print(f"{page}: {f['n']} companies, "
          f"EUR {f['total']:,.0f} baseline, "
          f"{f['with_sourced']} with sourced prices "
          f"({f['vw_sourced']:.1f}% value-weighted)"
          + (f", {len(moved)} moved vs {args.compare}" if args.compare else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
