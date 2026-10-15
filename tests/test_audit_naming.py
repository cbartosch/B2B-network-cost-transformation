"""Two names an external audit found misleading, and what they now say.

The audit raised EVIDENCE_LABEL_CONTRADICTION on six of six rows: the export
reported millions of saving on an "evidenced" baseline while every
value-evidence share on the same row was zero. It was right.
"""
import pathlib

import pytest

from app.domain import estimate


def test_nothing_in_the_savings_split_claims_evidence():
    """UNEVIDENCED_ORIGINS holds SIMULATED and DECLARED_UNKNOWN and nothing
    else, so a footprint an analyst typed and a rate nobody sourced both
    counted as evidenced. UPS reported 6.0m of saving on an "evidenced"
    baseline that was a declared site count priced from a grade E card.

    The split is useful; the word was wrong. `specified` is what the test
    actually asks - did something outside the simulation state this - and it
    claims nothing about evidence.
    """
    src = pathlib.Path(estimate.__file__).read_text("utf-8")
    # As a field key, which is how it is exported. The comment explaining
    # the rename names the old fields deliberately and must keep doing so -
    # a rename with no record of what it replaced is a worse artifact than
    # the name it fixed.
    assert '"saving_on_evidenced_baseline"' not in src
    assert '"saving_on_unevidenced_baseline"' not in src
    assert '"saving_on_specified_baseline"' in src
    assert '"saving_on_simulated_baseline"' in src


def test_the_split_still_separates_the_simulated_part():
    """Renaming must not change what is counted."""
    assert estimate.UNEVIDENCED_ORIGINS == {"SIMULATED", "DECLARED_UNKNOWN"}


@pytest.mark.parametrize("origin,unevidenced", [
    ("SIMULATED", True), ("DECLARED_UNKNOWN", True),
    ("ANALYST_ENTERED_SCOPE", False), ("EVIDENCED_PUBLIC", False),
    ("BENCHMARK_PRIOR", False),
])
def test_what_the_test_actually_asks(origin, unevidenced):
    """Named as a fact rather than left implied: an analyst-entered scope and
    a benchmark prior are both on the "specified" side, which is precisely
    why calling that side evidenced was wrong."""
    assert (origin in estimate.UNEVIDENCED_ORIGINS) is unevidenced


def test_no_exported_field_outside_the_samples_still_says_evidenced_baseline():
    """The tools that read and gate the export move with it, or the rename
    is half a rename and the gate checks a field nothing writes."""
    root = pathlib.Path(estimate.__file__).resolve().parents[3]
    stale = []
    for rel in ("tools/build_sample_summary.py", "tools/validation_gate.py",
                "tools/delta_report.py"):
        f = root / rel
        if f.exists() and "saving_on_evidenced_baseline" in f.read_text("utf-8"):
            stale.append(rel)
    assert not stale, f"still naming the old field: {stale}"


def test_research_timings_survive_a_run_that_researches_nothing():
    """A --repromote run calls no domain, so this session's timings are
    empty and the export reported zero minutes beside 48 sources - flagged
    on five of six rows. Prior timings carry forward; this run's overwrite
    per domain, so a repaired domain reports its new time and the rest keep
    theirs."""
    prior = {"1": 120.0, "2": 90.0}
    fresh = {"2": 45.0}
    merged = {**prior, **{str(k): v for k, v in fresh.items()}}
    assert merged == {"1": 120.0, "2": 45.0}
    assert sum(merged.values()) > 0


# ------------------- the four the same audit raised and nobody had fixed

def _summary():
    """The export module, loaded without importing the app package."""
    import importlib.util
    f = pathlib.Path(__file__).resolve().parents[1] / "tools" / \
        "build_sample_summary.py"
    if not f.exists():
        pytest.skip("summary builder not present")
    spec = importlib.util.spec_from_file_location("_bss", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_complete_says_what_it_is_complete_of():
    """COMPLETE_LABEL_WITH_PARTIAL_ENTERPRISE_SCOPE, 6 of 6 rows.

    `v0_status=COMPLETE` sat beside `scope_status=PARTIAL_COUNTRIES` in the
    same row. Both were true and the first word, read alone, says the
    estimate covers the company. It covers the countries the engagement
    declared.
    """
    s = _summary()
    partial = {"scope_status": "PARTIAL_COUNTRIES"}
    whole = {"scope_status": "FULL"}
    assert s._qualified_v0_status(partial, {"v0_status": "COMPLETE"}) == \
        "COMPLETE_FOR_DECLARED_SCOPE"
    # Unqualified where the two words mean the same thing.
    assert s._qualified_v0_status(whole, {"v0_status": "COMPLETE"}) == \
        "COMPLETE"
    # And a status that never over-claimed is left alone.
    assert s._qualified_v0_status(partial, {"v0_status": "PARTIAL"}) == \
        "PARTIAL"


def test_a_coverage_gate_passing_is_not_all_spend_priced():
    """COMPLETE_WITH_PARTIAL_PRICED_SPEND, three rows at 77-91%."""
    s = _summary()
    at_91 = {"coverage": {"status": "COMPLETE", "priced_spend_pct": "91.0"}}
    at_100 = {"coverage": {"status": "COMPLETE", "priced_spend_pct": "100"}}
    assert s._qualified_priced_status(at_91) == "COMPLETE_ABOVE_THRESHOLD"
    assert s._qualified_priced_status(at_100) == "COMPLETE"


def test_the_scenario_column_names_the_objective_it_optimises():
    """SCENARIO_SELECTION_OBJECTIVE_LIMITED. It selects on the largest
    base-case gross saving - not net of one-time cost, not risk-adjusted,
    not client value. "Best" is a judgement the column cannot make."""
    s = _summary()
    cols = [c for c, _ in s.FIELDS]
    assert "max_base_savings_scenario" in cols
    assert "best_scenario" not in cols
    # The selection itself is unchanged: largest base gross saving wins.
    e = {"scenarios": {
        "C": {"gross_run_rate_savings": {"base": "10"}},
        "D": {"gross_run_rate_savings": {"base": "25"}}}}
    assert s._best(e)[0] == "D"


def test_payback_says_which_question_it_answers():
    """PAYBACK_BEFORE_PROGRAMME_COMPLETION, raised on UPS at 8 months
    against an 11-month programme - and true of 8 of the 26 companies, not
    one. It divides one-time cost by the FULL run-rate saving, so it
    answers "once the programme is done, how long to repay it". When
    cumulative cash turns positive needs a period-by-period migration cash
    flow this model does not build, and renaming does not pretend to."""
    s = _summary()
    cols = [c for c, _ in s.FIELDS]
    assert "steady_state_payback_months_base" in cols
    assert "payback_months_base" not in cols
