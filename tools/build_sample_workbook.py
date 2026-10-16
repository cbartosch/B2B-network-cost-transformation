#!/usr/bin/env python3
"""An Excel summary of the sample set, one row per company in the spec.

Every company in samples/companies.json gets a row, whether or not it has
been modelled yet - a set of 41 companies where 28 carry figures is the
true state, and a workbook showing only the 28 would quietly answer a
different question.

Totals and shares are written as FORMULAS over the visible rows, not as
numbers this script computed. A reader who filters or deletes a row sees
the totals move, which is the point of putting it in Excel rather than
sending a CSV.

    python tools/build_sample_workbook.py
    python tools/build_sample_workbook.py --out docs/sample-set.xlsx
"""
import argparse
import csv
import json
import pathlib

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "Arial"
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(name=FONT, size=10, bold=True, color="FFFFFF")
BODY = Font(name=FONT, size=10)
BODY_DIM = Font(name=FONT, size=10, color="808080")
BOLD = Font(name=FONT, size=10, bold=True)
TITLE = Font(name=FONT, size=14, bold=True, color="1F3864")
NOTE = Font(name=FONT, size=9, color="595959", italic=True)
PENDING_FILL = PatternFill("solid", fgColor="FFF2CC")
TOTAL_FILL = PatternFill("solid", fgColor="D9E2F3")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)

MONEY = '#,##0;(#,##0);-'
MONEY2 = '#,##0.0;(#,##0.0);-'
PCT = '0.0%'
NUM = '#,##0;(#,##0);-'


def _f(row, key):
    """A float from the summary, or None when the cell is empty."""
    v = (row or {}).get(key)
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _header(ws, headers, row=1):
    for col, (text, width) in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col, value=text)
        c.font = HEAD_FONT
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center",
                                wrap_text=True)
        c.border = BOX
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[row].height = 30
    ws.freeze_panes = ws.cell(row=row + 1, column=3)


def build(spec_path, summary_path, out_path):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))["companies"]
    modelled = {r["slug"]: r for r in
                csv.DictReader(summary_path.open(encoding="utf-8"))}

    wb = Workbook()

    # ------------------------------------------------------ 1. Summary
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "Outside-in network cost estimates"
    ws["A1"].font = TITLE
    ws["A2"] = (f"{len(spec)} companies in the specification; "
                f"{len(modelled)} modelled. Rows shaded amber are still in "
                f"research and carry no figures.")
    ws["A2"].font = NOTE

    headers = [
        ("Company", 34), ("Slug", 16), ("Industry", 22), ("Domicile", 9),
        ("Ccy", 6), ("Countries", 9), ("Sites", 10),
        ("Baseline (EUR)", 16), ("Saving (EUR)", 15), ("Saving %", 10),
        ("One-time (EUR)", 15), ("Payback (mo)", 12),
        ("Programme (mo)", 13), ("Confidence", 11), ("Band", 8),
        ("Sourced %", 11), ("Domains", 10), ("Status", 24),
    ]
    _header(ws, headers, row=4)

    first = 5
    r = first
    for company in sorted(spec, key=lambda c: c["legal_name"]):
        slug = company["slug"]
        m = modelled.get(slug)
        declared = sum(x["sites"] for x in company["declared_footprint"])

        ws.cell(row=r, column=1, value=company["legal_name"])
        ws.cell(row=r, column=2, value=slug)
        ws.cell(row=r, column=3, value=(m or {}).get("industry")
                or company["industry"])
        ws.cell(row=r, column=4, value=company["domicile"])
        ws.cell(row=r, column=5, value=company["currency"])
        ws.cell(row=r, column=6, value=len(company["countries"]))

        if m:
            ws.cell(row=r, column=7, value=int(_f(m, "sites") or 0))
            ws.cell(row=r, column=8, value=_f(m, "baseline_base_eur"))
            ws.cell(row=r, column=9, value=_f(m, "best_saving_base_eur"))
            # Saving share, computed in the sheet so it tracks its inputs.
            ws.cell(row=r, column=10,
                    value=f"=IF(H{r}=0,\"\",I{r}/H{r})")
            ws.cell(row=r, column=11, value=_f(m, "one_time_cost_base_eur"))
            ws.cell(row=r, column=12,
                    value=_f(m, "steady_state_payback_months_base"))
            ws.cell(row=r, column=13, value=_f(m, "programme_months"))
            ws.cell(row=r, column=14, value=_f(m, "confidence_overall"))
            ws.cell(row=r, column=15, value=m.get("confidence_band"))
            unsourced = _f(m, "unsourced_price_share")
            ws.cell(row=r, column=16,
                    value=(1 - unsourced) if unsourced is not None else None)
            ws.cell(row=r, column=17, value=_f(m, "domains_researched"))
            ws.cell(row=r, column=18, value=m.get("v0_status"))
        else:
            ws.cell(row=r, column=7, value=declared)
            ws.cell(row=r, column=18, value="RESEARCH IN PROGRESS")
            for col in range(1, 19):
                ws.cell(row=r, column=col).fill = PENDING_FILL

        for col in range(1, 19):
            c = ws.cell(row=r, column=col)
            c.font = BODY if m else BODY_DIM
            c.border = BOX
            if col == 7:
                c.number_format = NUM
            elif col in (8, 9, 11):
                c.number_format = MONEY
            elif col in (10, 16):
                c.number_format = PCT
            elif col in (12, 13):
                c.number_format = MONEY2
            elif col == 14:
                c.number_format = '0.00'
        r += 1

    last = r - 1
    ws.cell(row=r, column=1, value="TOTAL / weighted").font = BOLD
    for col, formula in (
            (7, f"=SUM(G{first}:G{last})"),
            (8, f"=SUM(H{first}:H{last})"),
            (9, f"=SUM(I{first}:I{last})"),
            (10, f"=IF(H{r}=0,\"\",I{r}/H{r})"),
            (11, f"=SUM(K{first}:K{last})"),
            # Value-weighted, not a mean of the column: a 16,000-store
            # estate and a 40-site one must not count equally.
            (14, f"=IF(SUM(H{first}:H{last})=0,\"\","
                 f"SUMPRODUCT(N{first}:N{last},H{first}:H{last})"
                 f"/SUM(H{first}:H{last}))"),
            (16, f"=IF(SUM(H{first}:H{last})=0,\"\","
                 f"SUMPRODUCT(P{first}:P{last},H{first}:H{last})"
                 f"/SUM(H{first}:H{last}))"),
    ):
        c = ws.cell(row=r, column=col, value=formula)
        c.font = BOLD
    for col in range(1, 19):
        c = ws.cell(row=r, column=col)
        c.fill = TOTAL_FILL
        c.border = BOX
        if col == 7:
            c.number_format = NUM
        elif col in (8, 9, 11):
            c.number_format = MONEY
        elif col in (10, 16):
            c.number_format = PCT
        elif col == 14:
            c.number_format = '0.00'
    ws.cell(row=r, column=14).comment = Comment(
        "Value-weighted by baseline, not a simple average of the column. "
        "An unweighted mean would let a 40-site airport operator move the "
        "headline as much as a 16,000-restaurant estate.", "model")
    ws.cell(row=r, column=16).comment = Comment(
        "Share of priced value resting on a rate better than an expert "
        "assumption. 1 minus unsourced_price_share, value-weighted.", "model")

    note = r + 2
    ws.cell(row=note, column=1, value=(
        "Sites for a modelled company is the estate the simulation priced. "
        "For a company still in research it is the DECLARED total from the "
        "specification, which is why those rows carry a figure but no "
        "baseline.")).font = NOTE
    ws.cell(row=note + 1, column=1, value=(
        "Every estimate is band D - Indicative: outside-in, public evidence "
        "only, NO_CONTACT. That is a property of the method and no parameter "
        "changes it.")).font = NOTE

    # --------------------------------------------------- 2. Evidence
    ev = wb.create_sheet("Evidence")
    ev["A1"] = "What each baseline rests on"
    ev["A1"].font = TITLE
    ev["A2"] = ("Shares are of priced value. Assumed is the share with no "
                "transaction, quote or published benchmark behind it.")
    ev["A2"].font = NOTE
    ev_headers = [
        ("Company", 34), ("Baseline (EUR)", 16), ("Priced spend %", 13),
        ("Sourced %", 11), ("Assumed %", 11), ("Evidenced %", 12),
        ("Derived %", 11), ("Simulated %", 12), ("Unknown %", 11),
        ("Domains researched", 17), ("Sources", 10), ("Scope", 20),
    ]
    _header(ev, ev_headers, row=4)
    er = 5
    for company in sorted(spec, key=lambda c: c["legal_name"]):
        m = modelled.get(company["slug"])
        if not m:
            continue
        unsourced = _f(m, "unsourced_price_share")
        vals = [
            company["legal_name"], _f(m, "baseline_base_eur"),
            (_f(m, "priced_spend_pct") or 0) / 100
            if _f(m, "priced_spend_pct") is not None else None,
            (1 - unsourced) if unsourced is not None else None,
            _f(m, "assumed_share"), _f(m, "evidenced_share"),
            _f(m, "derived_share"), _f(m, "simulated_value_share"),
            _f(m, "unknown_share"), _f(m, "domains_researched"),
            _f(m, "research_sources"), m.get("scope_status"),
        ]
        for col, v in enumerate(vals, start=1):
            c = ev.cell(row=er, column=col, value=v)
            c.font = BODY
            c.border = BOX
            if col == 2:
                c.number_format = MONEY
            elif 3 <= col <= 9:
                c.number_format = PCT
        er += 1
    ev.cell(row=er + 1, column=1, value=(
        "Shares sum to 1 by construction; the model refuses an estimate "
        "whose evidence shares do not.")).font = NOTE

    # ---------------------------------------------- 3. Declared scope
    sc = wb.create_sheet("Declared scope")
    sc["A1"] = "What the specification declares, before research"
    sc["A1"].font = TITLE
    sc["A2"] = ("One row per company per archetype. This is the analyst's "
                "declaration, not a measured count - see the note column.")
    sc["A2"].font = NOTE
    sc_headers = [("Company", 34), ("Slug", 16), ("Country", 9),
                  ("Archetype", 18), ("Declared sites", 14),
                  ("Density", 12), ("Per-country basis", 46)]
    _header(sc, sc_headers, row=4)
    sr = 5
    for company in sorted(spec, key=lambda c: c["legal_name"]):
        apportioned = bool(company.get("scope_note_cr02b"))
        basis = ("Apportionment of a published group total - not a published "
                 "per-country figure" if apportioned
                 else "Declared per country")
        for row in company["declared_footprint"]:
            vals = [company["legal_name"], company["slug"], row["country"],
                    row["archetype"], row["sites"], row.get("density"), basis]
            for col, v in enumerate(vals, start=1):
                c = sc.cell(row=sr, column=col, value=v)
                c.font = BODY if not apportioned else BODY_DIM
                c.border = BOX
                if col == 5:
                    c.number_format = NUM
            sr += 1
    sc.cell(row=sr + 1, column=1, value=(
        "An apportioned figure is the one the estimate prices when research "
        "finds nothing larger. Rows marked so are the ones most worth "
        "challenging.")).font = NOTE

    # ------------------------------------------------------ 4. Method
    me = wb.create_sheet("Method and caveats")
    me["A1"] = "How to read this workbook"
    me["A1"].font = TITLE
    me.column_dimensions["A"].width = 110
    lines = [
        "",
        "SCOPE",
        f"  {len(spec)} companies in the specification; {len(modelled)} "
        f"carry modelled figures. The rest are still in research and are "
        f"shaded amber on the Summary tab.",
        "",
        "WHAT THE BASELINE IS",
        "  An outside-in estimate of annual network cost, built from public "
        "evidence only, with no client contact. Every estimate is "
        "confidence band D - Indicative - which is a property of the method "
        "rather than of any parameter.",
        "",
        "THE LARGEST CAVEAT",
        "  Most priced value rests on an expert assumption rather than an "
        "observed rate. Research establishes HOW MANY SITES a company has; "
        "the seeded rate card establishes WHAT THEY COST, and the cost side "
        "is where the evidence is thinnest. The Sourced % column is the "
        "share resting on something better than an assumption.",
        "",
        "DECLARED VERSUS RESEARCHED SITE COUNTS",
        "  A declared count is the analyst's figure. Where it is an "
        "apportionment of a published group total rather than a published "
        "per-country number, the Declared scope tab says so. Research "
        "supersedes a declaration only where it finds a sourced count at "
        "least as large, so an apportioned figure can stand above every "
        "source that looked at it.",
        "",
        "SAVING",
        "  The saving shown is the maximum base-case GROSS saving across "
        "scenarios: not net of one-time cost, not risk-adjusted, and not a "
        "recommendation. Payback is steady-state - one-time cost divided by "
        "the full run-rate saving - so it answers how long to repay once "
        "the programme is done, not when cumulative cash turns positive.",
        "",
        "PROVENANCE",
        "  Generated by tools/build_sample_workbook.py from "
        "samples/outside_in/summary.csv and samples/companies.json. Every "
        "figure traces to a committed estimate; nothing here is typed by "
        "hand.",
    ]
    for i, text in enumerate(lines, start=2):
        c = me.cell(row=i, column=1, value=text)
        c.font = BOLD if text and not text.startswith("  ") else BODY
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if text.startswith("  "):
            me.row_dimensions[i].height = 48

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return len(spec), len(modelled), out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="samples/companies.json")
    ap.add_argument("--summary", default="samples/outside_in/summary.csv")
    ap.add_argument("--out", default="docs/sample-set-summary.xlsx")
    a = ap.parse_args()
    n, m, p = build(pathlib.Path(a.spec), pathlib.Path(a.summary),
                    pathlib.Path(a.out))
    print(f"{p}: {n} companies, {m} modelled, {n - m} still in research")
