"""Turning a completed engagement into a validation case.

The harness could compare an estimate against an outturn since 4.160 and the
corpus stayed empty, because nothing produced a case. A folder somebody has to
remember to fill is not a workflow.
"""
import types

import pytest

from app.domain import validation, validation_capture


def _snapshot(**over):
    fields = dict(
        estimate_snapshot_id="snap-1", case_id="case-1",
        current_tco={"low": "3800000", "base": "4600000", "high": "5400000"},
        target_tco={"base": "3900000"},
        gross_run_rate_savings={"base": "700000"},
        scenarios={"B": {"transition": {"one_time_cost": {"base": "1650000"}}}},
        pins={})
    fields.update(over)
    return types.SimpleNamespace(**fields)


def test_the_estimated_half_is_read_from_the_snapshot_never_typed():
    """The integrity property. A case opened after the outturn is known would
    let someone adjust what the model said to match what happened, and a corpus
    that can be fitted measures nothing."""
    out = validation_capture.open_case(
        _snapshot(), simulation_output={"sites": 2290},
        opened_by="CB")
    assert out["estimated"]["current_annual_cost"] == "4600000"
    assert out["estimated"]["site_count"] == "2290"
    assert out["actual"] is None


def test_a_measure_the_snapshot_does_not_carry_is_omitted_not_guessed():
    """A fabricated measure would improve the error statistics without
    improving the model."""
    out = validation_capture.open_case(_snapshot(), opened_by="CB")
    assert "site_count" not in out["estimated"]
    assert "of 7 measure(s)" in out["note"]


def test_the_one_time_cost_comes_from_the_scenario_not_the_header():
    """It belongs to a plan rather than to a baseline."""
    out = validation_capture.open_case(_snapshot(), opened_by="CB")
    assert out["estimated"]["one_time_cost"] == "1650000"


def test_an_unknown_evidence_tier_is_refused():
    """A mislabelled synthetic case is the one thing that makes the whole
    corpus untrustworthy: the statistics exclude synthetic cases by name, so
    one labelled HISTORICAL_ACTUAL is counted as evidence."""
    case = validation_capture.open_case(_snapshot(), opened_by="CB")
    with pytest.raises(validation_capture.CaseIncomplete, match="evidence tier"):
        validation_capture.record_actuals(
            case, actual={"current_annual_cost": "3812151"},
            evidence_tier="PROBABLY_RIGHT", recorded_by="CB")


def test_actuals_with_no_comparable_measure_are_refused():
    """A case with none is a record that an engagement finished rather than
    evidence about the model."""
    case = validation_capture.open_case(_snapshot(), opened_by="CB")
    with pytest.raises(validation_capture.CaseIncomplete, match="comparable"):
        validation_capture.record_actuals(
            case, actual={"client_mood": "positive"},
            evidence_tier=validation.TIER_ACTUAL, recorded_by="CB")


def test_a_field_that_is_not_a_measure_is_reported_not_silently_dropped():
    case = validation_capture.open_case(
        _snapshot(), simulation_output={"sites": 2290}, opened_by="CB")
    out = validation_capture.record_actuals(
        case, actual={"site_count": "2290", "client_mood": "positive"},
        evidence_tier=validation.TIER_ACTUAL, recorded_by="CB")
    assert out["ignored_fields"] == ["client_mood"]
    assert "kept out rather than silently dropped" in out["note"]


def test_a_case_awaiting_its_outturn_is_not_comparable():
    """Held, and counting toward nothing."""
    case = validation_capture.open_case(
        _snapshot(), simulation_output={"sites": 2290}, opened_by="CB")
    assert validation_capture.comparable(case) is False


def test_a_completed_case_compares_and_is_scored():
    case = validation_capture.open_case(
        _snapshot(), simulation_output={"sites": 2290}, opened_by="CB")
    done = validation_capture.record_actuals(
        case, actual={"current_annual_cost": "3812151", "site_count": "2290"},
        evidence_tier=validation.TIER_ACTUAL, recorded_by="CB")
    assert validation_capture.comparable(done)

    stats = validation.statistics([validation.compare(done)])
    assert stats["cases_included"] == 1
    cost = stats["per_measure"]["current_annual_cost"]
    assert cost["n"] == 1
    # 4,600,000 against 3,812,151: the model was high.
    assert cost["overestimated"] == 1


def test_a_synthetic_case_is_captured_and_excluded_from_the_statistics():
    """Useful for exercising the harness, and not evidence."""
    case = validation_capture.open_case(_snapshot(), opened_by="CB")
    done = validation_capture.record_actuals(
        case, actual={"current_annual_cost": "4600000"},
        evidence_tier=validation.TIER_SYNTHETIC, recorded_by="CB")
    stats = validation.statistics([validation.compare(done)])
    assert stats["cases_included"] == 0
    assert stats["cases_excluded_as_synthetic"] == 1


def test_one_estimate_is_one_case():
    """Opening a second would let the more flattering one be kept."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "routers").exists())
    api = (app / "routers" / "api.py").read_text()
    assert "a case is already open on this estimate" in api
