"""Whether the estimate actually refines, and whether that is visible.

The audit finding: the mechanism works and nothing showed it. Confidence
derives from priced coverage, the origin mix and domain completeness, all of
which respond to evidence - but every snapshot was an island with no link to
the one it improved on and no statement of what moved. A re-run after promoting
three sources produced a different number with no account of why, which is
indistinguishable from a number that changed for no reason.
"""
import pytest

from app.domain import refinement


def _snap(sid, created, *, score, band, coverage, origins, savings,
          method="BUILD_UP", calc="calc-1.0.0"):
    return {
        "estimate_snapshot_id": sid, "created_at": created,
        "version_label": "V0", "v0_status": "COMPLETE",
        "confidence": {"score": score, "band": band},
        "coverage": {"effective_coverage_pct": coverage},
        "current_tco": {"base": "1000000.00"},
        "scenarios": {"D": {"gross_run_rate_savings": {"base": savings}}},
        "asserted_share": "0.400", "simulated_share": "0.200",
        "pins": {"calculation_version": calc, "estimate_method": method,
                 "origin_breakdown": {k: {"share": v}
                                      for k, v in origins.items()}},
    }


def test_promoting_evidence_reads_as_a_refinement():
    """The case the whole workflow is for: a typed figure becomes public
    evidence, confidence rises, and the rise is attributed to the shift."""
    before = _snap("a", "2026-08-01T10:00:00", score="0.42", band="D",
                   coverage="0.550",
                   origins={"ANALYST_ENTERED_SCOPE": "0.80",
                            "EVIDENCED_PUBLIC": "0.20"},
                   savings="30000000.00")
    after = _snap("b", "2026-08-02T10:00:00", score="0.61", band="C",
                  coverage="0.800",
                  origins={"ANALYST_ENTERED_SCOPE": "0.30",
                           "EVIDENCED_PUBLIC": "0.70"},
                  savings="34000000.00")

    out = refinement.compare(before, after)
    assert out["is_refinement"] is True
    assert any(m["field"] == "confidence.score" for m in out["moved"])
    improving = [c for c in out["causes"] if c["improves"]]
    assert improving, "a rise in evidenced share must be named as the cause"
    assert "EVIDENCED_PUBLIC" in " ".join(c["statement"] for c in improving)
    assert "rose" in out["summary"]


def test_a_method_change_is_not_a_refinement():
    """BUILD_UP and ANCHOR answer different questions. Reading one as an
    improvement on the other would compare an enumerated estate with a share
    of a disclosed cost line."""
    before = _snap("a", "2026-08-01T10:00:00", score="0.42", band="D",
                   coverage="0.550", origins={"ANALYST_ENTERED_SCOPE": "1.0"},
                   savings="30000000.00", method="BUILD_UP")
    after = _snap("b", "2026-08-02T10:00:00", score="0.55", band="C",
                  coverage="0.550", origins={"PUBLIC_SPEND_ANCHOR": "1.0"},
                  savings="45000000.00", method="ANCHOR")

    out = refinement.compare(before, after)
    assert out["is_refinement"] is False
    assert any(c["kind"] == "method_change" for c in out["causes"])
    assert "different questions" in " ".join(
        c["statement"] for c in out["causes"])


def test_a_calculation_change_is_declared_not_attributed_to_evidence():
    """Part of the movement is the model. Saying so is the difference between
    a refinement narrative and a plausible one."""
    before = _snap("a", "2026-08-01T10:00:00", score="0.42", band="D",
                   coverage="0.550", origins={"EVIDENCED_PUBLIC": "0.5"},
                   savings="30000000.00", calc="calc-1.0.0")
    after = _snap("b", "2026-08-02T10:00:00", score="0.42", band="D",
                  coverage="0.550", origins={"EVIDENCED_PUBLIC": "0.5"},
                  savings="41000000.00", calc="calc-1.1.0")
    out = refinement.compare(before, after)
    assert any(c["kind"] == "calculation_change" for c in out["causes"])


def test_movement_with_no_observable_cause_is_reported_as_unexplained():
    """A narrative that always finds a cause is one nobody can check."""
    before = _snap("a", "2026-08-01T10:00:00", score="0.42", band="D",
                   coverage="0.550", origins={"EVIDENCED_PUBLIC": "0.5"},
                   savings="30000000.00")
    after = _snap("b", "2026-08-02T10:00:00", score="0.42", band="D",
                  coverage="0.550", origins={"EVIDENCED_PUBLIC": "0.5"},
                  savings="52000000.00")
    out = refinement.compare(before, after)
    assert out["unexplained"], "a figure moved with nothing behind it"
    assert out["is_refinement"] is False
    assert "not asserted here" in out["unexplained"][0]


def test_an_identical_re_run_reports_nothing_moved():
    same = dict(score="0.42", band="D", coverage="0.550",
                origins={"EVIDENCED_PUBLIC": "0.5"}, savings="30000000.00")
    out = refinement.compare(_snap("a", "2026-08-01T10:00:00", **same),
                             _snap("b", "2026-08-02T10:00:00", **same))
    assert out["moved"] == []
    assert "Nothing moved" in out["summary"]


def test_the_progression_orders_by_time_and_counts_refinements():
    a = _snap("a", "2026-08-01T10:00:00", score="0.40", band="D",
              coverage="0.500", origins={"ANALYST_ENTERED_SCOPE": "1.0"},
              savings="30000000.00")
    b = _snap("b", "2026-08-02T10:00:00", score="0.55", band="C",
              coverage="0.700", origins={"EVIDENCED_PUBLIC": "0.6",
                                         "ANALYST_ENTERED_SCOPE": "0.4"},
              savings="33000000.00")
    c = _snap("c", "2026-08-03T10:00:00", score="0.66", band="C",
              coverage="0.900", origins={"EVIDENCED_PUBLIC": "0.9",
                                         "ANALYST_ENTERED_SCOPE": "0.1"},
              savings="35000000.00")
    out = refinement.progression([c, a, b])
    assert [s["estimate_snapshot_id"] for s in out["snapshots"]] == ["a", "b", "c"]
    assert len(out["steps"]) == 2
    assert out["refinements"] == 2


def test_the_note_states_that_v1_is_not_implemented():
    """Every snapshot this build writes is labelled V0. A V1 estimate needs
    governed stage_ceiling_V1_* thresholds that nobody has approved, and
    policy.py holds no defaults by design - so claiming a V1 here would be the
    false-capability defect that module exists to prevent."""
    out = refinement.progression([])
    assert "labelled V0" in out["note"]
    assert "stage_ceiling_V1" in out["note"]


def test_a_single_snapshot_yields_no_steps():
    out = refinement.progression([
        _snap("a", "2026-08-01T10:00:00", score="0.4", band="D",
              coverage="0.5", origins={}, savings="1.00")])
    assert out["steps"] == [] and out["refinements"] == 0
