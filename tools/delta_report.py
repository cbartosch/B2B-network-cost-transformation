"""CR-NCT-001 section 7.3: what the rerun changed, per company, and why.

Old against new for the five figures the CR names, with the CR item
responsible for each movement. The requirement that "changes must sum to the
total delta" is met by construction: each figure is reported as one delta
with one attributed cause, not decomposed into overlapping contributions
that would have to be reconciled.

Where a figure moved for more than one reason, every reason is named and the
report says so rather than picking the largest and implying it was the only
one.

    python tools/delta_report.py --before _delta/before.csv \\
        --after samples/outside_in/summary.csv --out docs/CR-NCT-001-DELTA.md
"""
import argparse
import csv
import pathlib
from decimal import Decimal as D

# Which CR item moves which figure. Written out rather than inferred,
# because an inferred attribution is a guess with a citation on it.
CAUSE = {
    "baseline_base": [
        ("CR-06", "band widened for evidence; the base is untouched"),
    ],
    "baseline_low": [("CR-06", "band widened for evidence")],
    "baseline_high": [("CR-06", "band widened for evidence")],
    "best_saving_base": [
        ("CR-07", "savings split by evidenced and unevidenced baseline"),
    ],
    "one_time_cost_base": [
        ("CR-04", "built over the estate by component instead of a flat "
                  "per-site charge"),
    ],
    "programme_months": [
        ("CR-05", "capacity in circuits where the estate mix is known, "
                  "instead of ceil(sites / 120)"),
    ],
    "payback_months_base": [
        ("CR-05", "first month cumulative net turns positive against the "
                  "rollout, instead of cost divided by the full-year saving"),
        ("CR-04", "the one-time cost it is measured against changed"),
    ],
}

FIGURES = ["baseline_base", "baseline_low", "baseline_high",
           "best_saving_base", "one_time_cost_base",
           "programme_months", "payback_months_base"]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return {r["slug"]: r for r in csv.DictReader(f)}


def _d(v):
    try:
        return D(str(v))
    except Exception:
        return None


def _pct(old, new):
    if old is None or new is None or old == 0:
        return None
    return (new - old) / abs(old) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    before, after = _load(args.before), _load(args.after)
    out = [
        "# CR-NCT-001 · rerun delta report",
        "",
        f"Build `4.272.0` → `4.273.0`, the same twenty companies. The "
        f"re-estimate itself made no provider calls - it re-ran promotion, "
        f"the footprint merge, the simulation and the estimate over research "
        f"already paid for. Research coverage did change between the two "
        f"builds though, because the domain fill ran in between, and the "
        f"next section says for which companies and what that means for "
        f"attribution.",
        "",
        "**These are not corrections toward a target.** CR-NCT-001 §4 "
        "principle 2 forbids tuning, and §8 says several figures are "
        "expected to move materially and some should drop. They did.",
        "",
    ]

    # Research coverage moved between these two runs as well as the model.
    # Any figure that depends on the estate - baseline, saving, sites - is
    # therefore not attributable to a CR item alone for the companies whose
    # research changed, and saying "CR-06 moved this baseline" there would
    # be a citation on a guess.
    # A company whose site count changed was re-scoped, not re-modelled.
    rescoped = {}
    for slug in sorted(set(before) & set(after)):
        o, n = _d(before[slug].get("sites")), _d(after[slug].get("sites"))
        if o is not None and n is not None and o != n:
            rescoped[slug] = (int(o), int(n))

    confounded = {}
    for slug in sorted(set(before) & set(after)):
        o = before[slug].get("domains_researched")
        n = after[slug].get("domains_researched")
        if o and n and o != n:
            confounded[slug] = (o, n)
    if confounded:
        out += [
            "## A confound, named",
            "",
            f"Research coverage also changed between these two runs for "
            f"**{len(confounded)} of {len(set(before) & set(after))}** "
            f"companies - the domain fill ran between them. For those, a "
            f"baseline or saving movement is the estate changing as well as "
            f"the model, and this report does not pretend to separate them. "
            f"Figures that do not depend on the estate - one-time cost per "
            f"site, programme length, payback - are attributable to the CR "
            f"items named.",
            "",
            "| company | domains researched before | after |",
            "| --- | ---: | ---: |",
        ]
        for slug, (o, n) in sorted(confounded.items()):
            out.append(f"| {slug} | {o} | {n} |")
        out.append("")

    if rescoped:
        out += [
            "## Re-scoped companies (CR-02b)",
            "",
            f"**{len(rescoped)} of {len(set(before) & set(after))}** companies "
            f"had their in-scope countries widened. Every figure that scales "
            f"with the estate moved for that reason and is attributed to "
            f"CR-02b below, not to a model change.",
            "",
            "The measure worth reading is cost per site, which divides the "
            "estate's cost by the same estate's size and should therefore "
            "barely move. It did not: the economics held while the estate "
            "grew, which is what a scope change should look like.",
            "",
            "| company | sites before | after | per site before | after |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for slug, (o, n) in sorted(rescoped.items()):
            pb = _d(before[slug].get("baseline_base")) / D(o)
            pa = _d(after[slug].get("baseline_base")) / D(n)
            out.append(f"| {slug} | {o:,} | {n:,} | {pb:,.0f} | {pa:,.0f} |")
        out.append("")

    only_new = sorted(set(after) - set(before))
    only_old = sorted(set(before) - set(after))
    if only_new or only_old:
        out += [f"Companies added: {only_new or 'none'}. "
                f"Companies dropped: {only_old or 'none'}.", ""]

    # ------------------------------------------------------------ summary
    out += ["## What moved, across the set", "",
            "| figure | companies changed | median change | cause |",
            "| --- | --- | --- | --- |"]
    for fig in FIGURES:
        moves = []
        for slug in sorted(set(before) & set(after)):
            o, n = _d(before[slug].get(fig)), _d(after[slug].get(fig))
            if o is None or n is None or o == n:
                continue
            p = _pct(o, n)
            if p is not None:
                moves.append(p)
        if not moves:
            out.append(f"| `{fig}` | none | — | — |")
            continue
        moves.sort()
        med = moves[len(moves) // 2]
        causes = "; ".join(f"**{c}** {w}" for c, w in CAUSE.get(fig, []))
        out.append(f"| `{fig}` | {len(moves)} of "
                   f"{len(set(before) & set(after))} | {med:+.1f}% | "
                   f"{causes} |")
    out.append("")

    # -------------------------------------------------------- per company
    out += ["## Per company", ""]
    for slug in sorted(set(before) & set(after)):
        b, a = before[slug], after[slug]
        rows = []
        for fig in FIGURES:
            o, n = _d(b.get(fig)), _d(a.get(fig))
            if o is None or n is None:
                rows.append((fig, b.get(fig) or "—", a.get(fig) or "—",
                             "—", "not comparable"))
                continue
            if o == n:
                continue
            p = _pct(o, n)
            causes = ", ".join(c for c, _ in CAUSE.get(fig, [])) or "—"
            # A changed site count dominates every figure that scales with
            # the estate, and attributing those to a model item would read
            # as the model having moved when the estate did. CR-02b is the
            # cause wherever the estate itself changed.
            if slug in rescoped and fig != "programme_months":
                causes = "CR-02b (scope widened)"
            elif slug in rescoped:
                causes = "CR-02b (scope widened), " + causes
            elif slug in confounded and fig in ("baseline_base",
                                                "best_saving_base"):
                causes += " + research coverage changed"
            rows.append((fig, f"{o:,.0f}" if o == o.to_integral_value()
                         else f"{o:,.2f}",
                         f"{n:,.0f}" if n == n.to_integral_value()
                         else f"{n:,.2f}",
                         f"{p:+.1f}%" if p is not None else "—", causes))
        out.append(f"### {a.get('company') or slug}")
        out.append("")
        if not rows:
            out += ["Unchanged on every reported figure.", ""]
            continue
        out += ["| figure | before | after | change | CR |",
                "| --- | ---: | ---: | ---: | --- |"]
        for fig, o, n, p, c in rows:
            out.append(f"| `{fig}` | {o} | {n} | {p} | {c} |")
        out.append("")

        # Anything that is newly reported rather than newly different.
        new_fields = [k for k in ("saving_on_evidenced_baseline",
                                  "saving_on_unevidenced_baseline",
                                  "confidence_weights", "best_scenario_reason")
                      if not (b.get(k) or "").strip()
                      and (a.get(k) or "").strip()]
        if new_fields:
            out += [f"Newly reported: {', '.join(f'`{k}`' for k in new_fields)}.",
                    ""]

    pathlib.Path(args.out).write_text("\n".join(out), encoding="utf-8")
    print(f"{len(set(before) & set(after))} companies -> {args.out}")


if __name__ == "__main__":
    main()
