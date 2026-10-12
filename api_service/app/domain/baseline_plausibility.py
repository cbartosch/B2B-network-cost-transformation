"""CR-03: is this baseline a sane size for this company?

Not to be confused with `estate_plausibility`, which asks whether the
FOOTPRINT is possible - nobody has 3,800 data centres in Germany. This asks
whether the COST is the right order of magnitude for the company it
describes, against its own headcount, revenue and site count. An estate can
be entirely possible and priced at ten times what such a company spends,
and the other module would pass it.

Three cross-checks on a published baseline, from figures the research
already found: cost per employee, cost as a share of revenue, and cost per
site. Each is computed and published whether or not anybody has said what
the right range is - a reader can see "0.031% of revenue" and form a view
without a benchmark, and could not see it at all before.

**The thresholds are not here and are not invented.** CR-NCT-001 section 5
makes them the owner's and section 4 principle 1 forbids filling the gap.
They live in reference.plausibility_benchmark, which ships with no rows. A
fabricated range would be worse than none: the flag lowers confidence, so a
made-up threshold would quietly change what every estimate reports about
itself, with a citation on it.

With no rows, every metric is NOT_ASSESSABLE and says so. That is a result.
"""
from decimal import Decimal, InvalidOperation

from .money import D, as_str

OK = "OK"
LOW = "LOW"
HIGH = "HIGH"
NOT_ASSESSABLE = "NOT_ASSESSABLE"

# Worst-first. A company flagged HIGH on one metric and OK on another is
# flagged, because the question is "is anything wrong with this number",
# not "is most of it fine".
_SEVERITY = {NOT_ASSESSABLE: 0, OK: 1, LOW: 2, HIGH: 3}

METRICS = ("BASELINE_PER_EMPLOYEE", "BASELINE_PCT_OF_REVENUE",
           "BASELINE_PER_SITE")

# Which metrics survive an estimate that covers part of the group.
#
# Revenue and headcount are published group-wide. A baseline covering three
# countries divided by worldwide revenue is not a ratio anybody can judge -
# it is the scope mismatch, expressed as a number, and it will always look
# absurdly low.
#
# This was not hypothetical. The first version judged all three regardless,
# and reading the output I concluded that half the sample was priced twenty
# to two hundred times too low and that the fix was to widen the country
# scope - hours of research on the strength of a comparison that could not
# have come out any other way. The per-site figures said otherwise all
# along: 3,756 to 5,846 per site for retail and branch estates, 14,304 to
# 43,762 for plants and R&D campuses, which is the gradient a network cost
# model should produce.
#
# Per site is scope-independent: it divides the cost of the estate by the
# size of the same estate. It stays assessable whatever the scope.
SCOPE_SENSITIVE = ("BASELINE_PER_EMPLOYEE", "BASELINE_PCT_OF_REVENUE")
PARTIAL_SCOPES = ("PARTIAL_COUNTRIES", "PARTIAL_SITE_TYPES", "UNKNOWN")


def _d(value):
    if value in (None, ""):
        return None
    try:
        out = D(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out


def _band_for(benchmarks, metric, industry):
    """The industry's own row, else DEFAULT, else nothing."""
    for key in ((metric, (industry or "").upper()), (metric, "DEFAULT")):
        row = benchmarks.get(key)
        if row:
            return row
    return None


def _judge(value, row):
    if value is None:
        return NOT_ASSESSABLE, "the input figure is not available"
    if not row:
        return NOT_ASSESSABLE, "no benchmark row for this metric"
    low, high = _d(row.get("low")), _d(row.get("high"))
    if low is None or high is None:
        return NOT_ASSESSABLE, "the benchmark row has no range"
    if value < low:
        return LOW, f"{value} is below the benchmark low of {low}"
    if value > high:
        return HIGH, f"{value} is above the benchmark high of {high}"
    return OK, f"{value} is within {low}-{high}"


def assess(*, baseline, employees=None, revenue=None, sites=None,
           industry=None, benchmarks=None, inputs_provenance=None,
           scope_status=None) -> dict:
    """Three ratios, each judged where a benchmark exists.

    `benchmarks` is {(metric, industry): row} from
    reference.plausibility_benchmark. Empty is the shipped state.

    `inputs_provenance` is {"employees": {...}, "revenue": {...}} carrying
    where each figure came from and for what period - CR-03 asks for the
    source and period recorded, and a ratio whose numerator is dated 2026
    and denominator 2019 is not a ratio.
    """
    base = _d(baseline)
    benchmarks = benchmarks or {}
    prov = inputs_provenance or {}

    emp, rev, n_sites = _d(employees), _d(revenue), _d(sites)
    values = {
        "BASELINE_PER_EMPLOYEE": (base / emp) if base is not None and emp
        else None,
        # As a percentage, because that is how anybody states it. A network
        # baseline is tenths of a percent of revenue, and a fraction here
        # would be read as a percentage by somebody eventually.
        "BASELINE_PCT_OF_REVENUE": (base / rev * D(100))
        if base is not None and rev else None,
        "BASELINE_PER_SITE": (base / n_sites) if base is not None and n_sites
        else None,
    }

    partial = str(scope_status or "").upper() in PARTIAL_SCOPES

    metrics, worst = {}, NOT_ASSESSABLE
    for metric in METRICS:
        value = values[metric]
        row = _band_for(benchmarks, metric, industry)
        if partial and metric in SCOPE_SENSITIVE:
            # Computed and published, because the figure is still worth
            # seeing - but not judged, because the denominator covers more
            # of the company than the numerator does.
            flag = NOT_ASSESSABLE
            why = (f"scope is {scope_status}: this baseline covers part of "
                   f"the group and the denominator is group-wide, so the "
                   f"ratio measures the scope gap rather than the estimate")
        else:
            flag, why = _judge(value, row)
        metrics[metric] = {
            "value": as_str(value) if value is not None else None,
            "flag": flag,
            "note": why,
            "benchmark": ({"low": as_str(_d(row.get("low"))),
                           "high": as_str(_d(row.get("high"))),
                           "unit": row.get("unit"),
                           "source": row.get("source"),
                           "as_of": row.get("as_of"),
                           "evidence_grade": row.get("evidence_grade")}
                          if row else None),
        }
        if _SEVERITY[flag] > _SEVERITY[worst]:
            worst = flag

    notes = [f"{m}: {d['note']}" for m, d in metrics.items()]
    if worst == NOT_ASSESSABLE and not benchmarks:
        notes.append(
            "reference.plausibility_benchmark has no rows. The thresholds "
            "are the owner's under CR-NCT-001 section 9 and are not "
            "invented here, so the ratios above are reported and not "
            "judged.")

    if partial:
        notes.append(
            f"scope is {scope_status}, so only BASELINE_PER_SITE is judged. "
            f"Per-site divides the cost of the estate by the size of the "
            f"same estate and is unaffected by how much of the group that "
            f"estate is.")

    return {
        "flag": worst,
        "scope_status": scope_status,
        "metrics": metrics,
        "inputs": {
            "employees": as_str(emp) if emp is not None else None,
            "revenue": as_str(rev) if rev is not None else None,
            "sites": as_str(n_sites) if n_sites is not None else None,
            "provenance": prov,
        },
        "notes": notes,
        "benchmark_rows": len(benchmarks),
    }


def caps_confidence(flag) -> bool:
    """A flagged baseline cannot be reported above D - Indicative.

    CR-03's second acceptance criterion. NOT_ASSESSABLE does not cap: an
    unmeasured baseline is not a wrong one, and treating "nobody has said"
    as "this is wrong" would make the absence of a benchmark look like a
    finding about the company.
    """
    return flag in (LOW, HIGH)


def load_benchmarks(session, table) -> dict:
    """{(metric, industry): row}. Empty where the table is empty."""
    from sqlalchemy import select

    rows = session.execute(select(table)).all()
    return {(r.metric, (r.industry or "DEFAULT").upper()): dict(r._mapping)
            for r in rows}
