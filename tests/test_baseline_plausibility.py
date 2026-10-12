"""CR-03: the plausibility gate, and what it refuses to do without a benchmark.

The thresholds are the owner's. These test everything around them: the
ratios, the flag logic once a range exists, the confidence cap, and - most
importantly - that an absent benchmark produces NOT_ASSESSABLE and never a
quietly-invented verdict.
"""
import pytest

from app.domain import baseline_plausibility as plausibility
from app.domain.money import D

BASE = dict(baseline="10000000", employees="50000", revenue="20000000000",
            sites="2000", industry="GROCERY_RETAIL")


def _bench(metric, low, high, industry="DEFAULT", **over):
    row = {"metric": metric, "industry": industry, "low": low, "high": high,
           "unit": "x", "source": "test", "as_of": "2026-01-01",
           "evidence_grade": "B"}
    row.update(over)
    return {(metric, industry): row}


# -------------------------------------------------- the shipped state

def test_with_no_benchmark_every_metric_is_not_assessable():
    """The state this ships in. Nothing is judged, and the output says why
    rather than leaving a reader to wonder whether OK meant checked."""
    out = plausibility.assess(**BASE, benchmarks={})
    assert out["flag"] == plausibility.NOT_ASSESSABLE
    assert out["benchmark_rows"] == 0
    for m in plausibility.METRICS:
        assert out["metrics"][m]["flag"] == plausibility.NOT_ASSESSABLE
    assert any("thresholds are the owner's" in n for n in out["notes"])


def test_the_ratios_are_published_even_with_no_benchmark():
    """The part that is useful without anybody setting a threshold. A reader
    can see 0.05% of revenue and form a view; before, they could not see it
    at all."""
    out = plausibility.assess(**BASE, benchmarks={})
    assert out["metrics"]["BASELINE_PER_EMPLOYEE"]["value"] == "200.00"
    assert out["metrics"]["BASELINE_PCT_OF_REVENUE"]["value"] == "0.05"
    assert out["metrics"]["BASELINE_PER_SITE"]["value"] == "5000.00"


def test_not_assessable_does_not_cap_confidence():
    """An unmeasured baseline is not a wrong one. Treating "nobody has said"
    as "this is wrong" would make the absence of a benchmark look like a
    finding about the company."""
    assert not plausibility.caps_confidence(plausibility.NOT_ASSESSABLE)


# ------------------------------------------------- once a range exists

@pytest.mark.parametrize("low,high,expect", [
    ("100", "300", plausibility.OK),
    ("250", "400", plausibility.LOW),
    ("50", "150", plausibility.HIGH),
])
def test_a_ratio_is_judged_against_its_band(low, high, expect):
    out = plausibility.assess(
        **BASE, benchmarks=_bench("BASELINE_PER_EMPLOYEE", low, high))
    assert out["metrics"]["BASELINE_PER_EMPLOYEE"]["flag"] == expect
    assert out["flag"] == expect


def test_the_worst_metric_governs_the_company_flag():
    """A company fine on one metric and wrong on another is flagged. The
    question is whether anything is wrong, not whether most of it is fine."""
    marks = {}
    marks.update(_bench("BASELINE_PER_EMPLOYEE", "100", "300"))      # OK
    marks.update(_bench("BASELINE_PER_SITE", "10", "50"))            # HIGH
    out = plausibility.assess(**BASE, benchmarks=marks)
    assert out["metrics"]["BASELINE_PER_EMPLOYEE"]["flag"] == plausibility.OK
    assert out["metrics"]["BASELINE_PER_SITE"]["flag"] == plausibility.HIGH
    assert out["flag"] == plausibility.HIGH


def test_an_industry_row_beats_the_default():
    marks = {}
    marks.update(_bench("BASELINE_PER_EMPLOYEE", "1", "5"))              # DEFAULT
    marks.update(_bench("BASELINE_PER_EMPLOYEE", "100", "300",
                        industry="GROCERY_RETAIL"))
    out = plausibility.assess(**BASE, benchmarks=marks)
    assert out["metrics"]["BASELINE_PER_EMPLOYEE"]["flag"] == plausibility.OK


def test_a_flagged_baseline_caps_confidence():
    """CR-03's second acceptance criterion."""
    assert plausibility.caps_confidence(plausibility.LOW)
    assert plausibility.caps_confidence(plausibility.HIGH)
    assert not plausibility.caps_confidence(plausibility.OK)


def test_the_benchmark_behind_a_judgement_is_published_with_it():
    """A flag nobody can trace to a source is the thing the benchmark table
    exists to prevent."""
    out = plausibility.assess(
        **BASE, benchmarks=_bench("BASELINE_PER_SITE", "10", "50",
                                  source="ACME 2026 survey p.12"))
    b = out["metrics"]["BASELINE_PER_SITE"]["benchmark"]
    assert b["source"] == "ACME 2026 survey p.12"
    assert b["as_of"] == "2026-01-01"


# ------------------------------------------------------- missing inputs

def test_a_metric_with_no_input_is_not_assessable_not_zero():
    out = plausibility.assess(
        baseline="10000000", employees=None, revenue="20000000000",
        sites="2000", benchmarks=_bench("BASELINE_PER_EMPLOYEE", "1", "9"))
    m = out["metrics"]["BASELINE_PER_EMPLOYEE"]
    assert m["flag"] == plausibility.NOT_ASSESSABLE
    assert m["value"] is None
    assert "not available" in m["note"]


def test_a_zero_denominator_does_not_divide():
    out = plausibility.assess(baseline="1000", employees="0", revenue="0",
                              sites="0", benchmarks={})
    for m in plausibility.METRICS:
        assert out["metrics"][m]["value"] is None


def test_the_provenance_of_each_input_is_carried():
    """A ratio whose numerator is dated 2026 and denominator 2019 is not a
    ratio, so CR-03 asks for the source and period of each input."""
    prov = {"employees": {"source": "AR 2025 p.4", "as_of": "2025-12-31"},
            "revenue": {"source": "AR 2025 p.9", "as_of": "2025-12-31"}}
    out = plausibility.assess(**BASE, benchmarks={}, inputs_provenance=prov)
    assert out["inputs"]["provenance"]["employees"]["as_of"] == "2025-12-31"


# --------------------------------------------- units, found the hard way

def test_a_figure_stated_in_millions_is_not_read_as_units():
    """Research states a figure in whatever unit its source used: "324700000000
    EUR", "5639 EUR million", "78 EUR billion". The first version of the
    extractor took the number and ignored the unit, so a company reporting in
    millions looked a million times cheaper - and because the largest raw
    number won, it also picked the wrong row wherever scales were mixed.

    Caught by computing the ratios across the twenty-company set and finding
    baseline-as-percent-of-revenue spanning 0.0009 to 179,059."""
    from app.routers.api import _scaled
    from app.domain.money import D

    assert _scaled("5639", "EUR million") == D("5639000000")
    assert _scaled("78", "EUR billion") == D("78000000000")
    assert _scaled("324700000000", "EUR") == D("324700000000")
    assert _scaled("12", "thousand sites") == D("12000")


def test_a_unit_with_no_scale_word_is_taken_as_stated():
    from app.routers.api import _scaled
    from app.domain.money import D

    assert _scaled("150", "sites") == D("150")
    assert _scaled("150", None) == D("150")


def test_a_currency_code_is_read_out_of_the_unit():
    from app.routers.api import _currency_of

    assert _currency_of("EUR million") == "EUR"
    assert _currency_of("USD") == "USD"
    assert _currency_of("sites") is None



# ------------------------------------- scope, and the ratio it invalidates

def test_a_partial_scope_suspends_the_group_wide_ratios():
    """Revenue and headcount are published group-wide. A baseline covering
    three countries divided by worldwide revenue is the scope mismatch
    expressed as a number, and it will always look absurdly low.

    This is not hypothetical. Reading the first version's output I concluded
    that half the sample was priced twenty to two hundred times too low and
    recommended hours of re-research to widen the country scope. The
    per-site figures said otherwise all along."""
    out = plausibility.assess(
        **BASE, scope_status="PARTIAL_COUNTRIES",
        benchmarks={**_bench("BASELINE_PER_EMPLOYEE", "1", "5"),
                    **_bench("BASELINE_PCT_OF_REVENUE", "1", "5")})
    for m in plausibility.SCOPE_SENSITIVE:
        assert out["metrics"][m]["flag"] == plausibility.NOT_ASSESSABLE
        assert "scope" in out["metrics"][m]["note"]
    assert any("only BASELINE_PER_SITE is judged" in n for n in out["notes"])


def test_per_site_survives_a_partial_scope():
    """It divides the cost of the estate by the size of the same estate, so
    it is unaffected by how much of the group that estate is."""
    out = plausibility.assess(
        **BASE, scope_status="PARTIAL_COUNTRIES",
        benchmarks=_bench("BASELINE_PER_SITE", "10", "50"))
    assert out["metrics"]["BASELINE_PER_SITE"]["flag"] == plausibility.HIGH
    assert out["flag"] == plausibility.HIGH


def test_the_scope_sensitive_values_are_still_published():
    """Suspended from judgement, not withheld. A reader can still see the
    figure and draw their own conclusion about the scope gap."""
    out = plausibility.assess(**BASE, scope_status="PARTIAL_COUNTRIES",
                              benchmarks={})
    assert out["metrics"]["BASELINE_PCT_OF_REVENUE"]["value"] == "0.05"


def test_a_full_group_scope_judges_everything():
    out = plausibility.assess(
        **BASE, scope_status="FULL_GROUP",
        benchmarks=_bench("BASELINE_PER_EMPLOYEE", "100", "300"))
    assert out["metrics"]["BASELINE_PER_EMPLOYEE"]["flag"] == plausibility.OK

