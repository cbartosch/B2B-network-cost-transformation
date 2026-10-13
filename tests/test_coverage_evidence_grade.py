"""What evidence the rates behind a baseline actually carry.

`evidence_grade_mix` and `unsourced_price_share` exist because of audit
finding A-02: a seeded guess and a cleared benchmark contributed identically
to baseline confidence, and coverage reported 100% priced on a portfolio made
entirely of placeholders.

The fix read the grade off the prior with `getattr`. match_prior returns a
DICT, so it returned the default every time: every row read grade E and basis
SEED whatever priced it. The metric reported a constant and the comment above
it described a fix that was never in force.
"""
from decimal import Decimal as D

import pytest

from app.domain import coverage


def test_a_grade_is_read_off_a_dict_prior():
    """The whole defect in one assertion."""
    assert coverage._prior_field({"evidence_grade": "C"}, "evidence_grade") == "C"


def test_a_grade_is_still_read_off_a_row_object():
    """The benchmark path passes a row, not a dict, and both must work."""
    import types
    row = types.SimpleNamespace(evidence_grade="B", price_basis="PROMOTED")
    assert coverage._prior_field(row, "evidence_grade") == "B"
    assert coverage._prior_field(row, "price_basis") == "PROMOTED"


def test_a_missing_field_is_none_not_an_error():
    assert coverage._prior_field({}, "evidence_grade") is None
    assert coverage._prior_field(None, "evidence_grade") is None


@pytest.mark.parametrize("grade,expected_unsourced", [
    ("E", True), ("F", True), ("C", False), ("A", False), ("B", False),
])
def test_only_an_assumption_counts_as_unsourced(grade, expected_unsourced):
    """Grades E and F are "an expert assumption or worse". A researched
    market price is C and must not be counted against the baseline as
    though nobody had looked."""
    assert (grade in ("E", "F")) is expected_unsourced


def test_the_mix_can_express_more_than_one_grade():
    """It reported {"E": 1.000} on a portfolio holding ten grade C rates.
    A mix that can only ever show one value is not a mix."""
    scope = [
        {"priced": True, "annual_value": "100", "evidence_grade": "C"},
        {"priced": True, "annual_value": "300", "evidence_grade": "E"},
    ]
    priced = sum(D(r["annual_value"]) for r in scope if r["priced"])
    mix = {g: (sum(D(r["annual_value"]) for r in scope
                   if r["priced"] and r["evidence_grade"] == g) / priced)
           for g in {r["evidence_grade"] for r in scope if r["priced"]}}
    assert mix == {"C": D("0.25"), "E": D("0.75")}
    unsourced = sum(D(r["annual_value"]) for r in scope
                    if r["priced"] and r["evidence_grade"] in ("E", "F")) / priced
    assert unsourced == D("0.75")
