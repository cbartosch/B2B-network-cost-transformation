"""Does the bottom-up estimate agree with what the company disclosed?

Specification 0.4: "Calibrate bottom-up current TCO against disclosed or proxy
spend", control "Show direct, derived and residual components separately."

The system had both halves and never put them together. ANCHOR apportions a
disclosed figure into layers; BUILD_UP constructs a total from sites, circuits
and rates. Nothing ran both on one case and asked whether they agreed - and
that comparison is the only self-check the estimate has.
"""
from decimal import Decimal as D

import pytest

from app.domain import calibration

LAYERS = {"L0": D("5100000"), "L2": D("400000"), "L4": D("300000"),
          "OPS": D("1200000")}


def _cal(disclosed, direct=("L0",)):
    return calibration.calibrate(
        bottom_up=sum(LAYERS.values()), disclosed=disclosed,
        direct_layers=list(direct), layer_totals=LAYERS)


def test_the_three_parts_are_reported_separately():
    """Collapsing them into one variance number is how a calibration becomes a
    reassurance. Direct is what the disclosure covers, derived is what the
    model built beyond it, residual is what neither explains - and the residual
    is the number worth arguing about."""
    out = _cal("8400000")
    assert out["direct"] == "5100000"
    assert out["derived"] == "1900000"     # L2 + L4 + OPS
    assert out["residual"] == "3300000"


def test_naming_a_different_covered_layer_changes_the_answer():
    """A disclosure saying "network costs" might mean circuits only or circuits
    plus the team that runs them, and the difference is the whole answer. Which
    is why it is an analyst's reading rather than something arithmetic
    decides."""
    circuits_only = _cal("6500000", direct=("L0",))
    with_ops = _cal("6500000", direct=("L0", "OPS"))
    assert circuits_only["verdict"] == calibration.MODEL_LOW
    assert with_ops["verdict"] == calibration.AGREES


def test_the_three_verdicts_are_distinguished():
    """A model short of a disclosure and a model over it need different
    investigations, and a single variance number would flatten them."""
    assert _cal("8400000")["verdict"] == calibration.MODEL_LOW
    assert _cal("5400000")["verdict"] == calibration.AGREES
    assert _cal("3800000")["verdict"] == calibration.MODEL_HIGH


def test_variance_is_measured_against_the_figure_with_a_source():
    """Dividing by the model's own output would measure the model against
    itself."""
    out = _cal("8400000")
    assert D(out["variance_pct"]) == (D("3300000") / D("8400000") * 100).quantize(D("0.1"))


def test_a_disagreement_names_what_to_rule_out_first():
    """Before concluding the estimate is short, rule out what the disclosure
    may include that the model does not."""
    out = _cal("8400000")
    assert out["check_first"]
    assert any("voice" in x for x in out["check_first"])
    # and an agreement offers none, because there is nothing to rule out
    assert _cal("5400000")["check_first"] == []


def test_guessing_the_covered_layers_is_refused():
    """Arithmetic cannot decide it and guessing would invent the result."""
    with pytest.raises(calibration.CalibrationInvalid, match="whole answer"):
        calibration.calibrate(bottom_up="1", disclosed="1", direct_layers=[],
                              layer_totals=LAYERS)


def test_a_zero_disclosure_is_refused():
    """Zero is not a disclosure, it is the absence of one."""
    with pytest.raises(calibration.CalibrationInvalid, match="absence"):
        _cal("0")


def test_one_side_alone_is_not_a_calibration():
    with pytest.raises(calibration.CalibrationInvalid, match="check on one"):
        calibration.calibrate(bottom_up="100", disclosed=None,
                              direct_layers=["L0"], layer_totals=LAYERS)


def test_a_failing_calibration_becomes_a_registrable_gap():
    """It costs the credibility of the whole baseline - two independent
    constructions of the same number disagree."""
    gap = calibration.as_assumption(_cal("8400000"))
    assert gap["gap"].startswith("bottom-up estimate does not match")
    assert "credibility" in gap["costs"]


def test_a_passing_calibration_is_not_a_question_to_ask_the_client():
    """Registering it would fill the data request with items the client cannot
    act on."""
    assert calibration.as_assumption(_cal("5400000")) is None


def test_agreement_does_not_claim_correctness():
    """Two independent constructions agreeing is worth more than either alone,
    and is not proof that both are right in the same way."""
    assert "not proof that both are right" in _cal("5400000")["note"]


def test_a_calibration_never_feeds_the_estimate():
    """An estimate tuned until it matches a disclosure has been fitted to one
    number and stopped being a measurement - the same reason the validation
    corpus refuses to feed the model."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = next(c for c in (root / "api_service" / "app", root / "app")
               if (c / "db.py").exists())
    readers = []
    for path in (app / "domain").glob("*.py"):
        if path.stem == "calibration":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Attribute)
                    and node.attr == "outside_in_tco_calibration"):
                readers.append(path.name)
    assert not readers, f"{readers} read the calibration back into the model"
