"""A saving is a percentage of a baseline, and the baseline has a coverage.

`coverage.assess` returns three statuses. REFUSED is never written. PARTIAL is
written and means one of four things, any of which is a material
qualification:

  * priced on 40-70% of its own scope
  * a product/bandwidth pair that cannot be sized at any approved rate
  * a country holding over 10% of the estate left uncovered
  * a cost layer in scope with nothing priced in it

And no consumer distinguished it from COMPLETE. The savings recommendation,
the V1 questionnaire, the calibration and the delta bridge all treated a
45%-covered estimate with an uncovered material country exactly as they
treated a clean one. The system says so on page 6 and did not carry it
forward.

Not a gate: PARTIAL is the ordinary state of an outside-in estimate and
refusing it downstream would block the normal case. What it needs is
propagation.
"""
from pathlib import Path

from app.domain import savings_bridge as bridge


SCENARIOS = {"A": {"levers": [{"lever_id": "LEV-REPRICE-001",
                               "family": "Same-service repricing",
                               "saving_base": "2000000"}],
                   "levers_not_applicable": []}}

PARTIAL = {
    "status": "PARTIAL",
    "effective_coverage_pct": "0.452",
    "material_country_breaches": ["GB"],
    "unpriced_layers": ["L1"],
    "unsizable_pairs": ["AE/DIA"],
    "unpriced_countries": ["AO"],
}


def test_the_bridge_carries_the_baselines_coverage():
    built = bridge.waterfall(SCENARIOS, current_total="20000000",
                             coverage=PARTIAL)
    assert built["coverage"]["status"] == "PARTIAL"
    assert built["coverage"]["effective_coverage_pct"] == "0.452"


def test_every_kind_of_qualification_is_named():
    """A status word alone does not tell a reader which of the four things
    went wrong, and they are not equivalent: an uncovered material country is
    a different problem from a thin layer."""
    built = bridge.waterfall(SCENARIOS, current_total="20000000",
                             coverage=PARTIAL)
    text = " ".join(built["coverage"]["qualifications"])
    assert "cannot be sized" in text
    assert "GB" in text
    assert "L1" in text
    assert "unpriced" in text


def test_it_says_what_the_qualification_means_for_the_saving():
    """The sentence a partner repeats. A percentage of a partial picture is
    not a percentage of the estate."""
    built = bridge.waterfall(SCENARIOS, current_total="20000000",
                             coverage=PARTIAL)
    meaning = built["coverage"]["what_it_means"]
    assert "share of a baseline priced on" in meaning
    assert "partial picture" in meaning


def test_a_complete_baseline_says_so_rather_than_staying_silent():
    """Silence reads as "fine" either way, so both cases are stated."""
    built = bridge.waterfall(
        SCENARIOS, current_total="20000000",
        coverage={"status": "COMPLETE", "effective_coverage_pct": "0.981"})
    assert "complete" in built["coverage"]["what_it_means"].lower()


def test_absent_coverage_is_none_and_not_a_reassuring_default():
    """A bridge that does not know its own coverage must not read as one
    priced on all of its scope."""
    built = bridge.waterfall(SCENARIOS, current_total="20000000")
    assert built["coverage"] is None


def test_every_call_site_passes_coverage():
    """Three sites: the two :run responses and the read path. A bridge that
    carries coverage in one of three places is one a reader cannot rely on."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    calls = api.count("savings_bridge.waterfall(")
    passing = api.count("coverage=cov") + api.count(
        'coverage=record.get("coverage")')
    assert passing >= calls, f"{calls} call sites, {passing} pass coverage"


def test_the_read_path_uses_the_snapshots_own_stored_coverage():
    """So a bridge read a week later carries the qualification the estimate
    was published with, not today's."""
    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert 'coverage=record.get("coverage")' in api


def test_the_savings_page_leads_with_the_qualification():
    """Before the steps, not after them. A reader who sees the number first
    has already formed a view."""
    root = Path(__file__).resolve().parents[1]
    page = next(root.glob(
        "analyst_ui/streamlit_app/pages/8_Savings*.py")).read_text()
    # The coverage block sits inside the `if _wf.get("steps")` branch and
    # before the steps table, which is what "leads with" means here.
    #
    # An earlier version compared `page.index()` of two strings with a 400
    # character fudge - a positional assertion with a magic number, which is
    # the habit this repository has broken five tests with today.
    assert "Baseline coverage" in page
    block = page[page.index('if _wf.get("steps"):'):]
    assert block.index("Baseline coverage") < block.index("st.dataframe"), (
        "the qualification must be rendered before the steps table - a "
        "reader who sees the number first has already formed a view")
