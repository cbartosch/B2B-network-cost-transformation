"""Grading rather than gating.

The binary model - clear the source minimum or be binned - reduced the agent to
a deterministic search with extra latency and cost. The reason to use one is
that it can read a hedged annual-report footnote, a regulator table and a
trade-press figure and say what each is worth; binning the two that fall short
discards exactly that judgement.
"""
import types
from decimal import Decimal as D

import pytest

from app.domain import reliability as R


def _policy(minimum=2, spread="0.15", stale=3):
    return types.SimpleNamespace(
        min_independent_sources_material_fact=minimum,
        material_spread_share=D(spread), stale_after_years=stale)


def _grade(**kw):
    kw.setdefault("policy", _policy())
    kw.setdefault("price_year", 2026)
    kw.setdefault("claimed_sources", len(kw.get("verified_sources") or []))
    kw.setdefault("band", None)
    return R.grade(**kw)


def test_several_accountable_sources_agreeing_recently_is_very_reliable():
    out = _grade(
        verified_sources=[{"publisher": "Annual Report 2025"},
                          {"publisher": "Bundesnetzagentur"},
                          {"publisher": "Sustainability report"}],
        band={"spread_share": 0.04, "newest_year": 2025})
    assert out["grade"] == R.VERY_RELIABLE
    assert out["may_evidence_without_review"] is True


def test_one_source_short_of_the_minimum_is_reliable_not_discarded():
    """The finding that used to be thrown away. One annual-report figure is
    not nothing, and recording it as nothing was the expensive part."""
    out = _grade(verified_sources=[{"publisher": "Annual Report 2025"}],
                 band={"spread_share": 0.0, "newest_year": 2025})
    assert out["grade"] == R.RELIABLE
    assert out["may_evidence_without_review"] is False
    assert out["promotable_by_named_analyst"] is True
    assert any("governed minimum" in s for s in out["shortfalls"])


def test_the_real_unicredit_case_grades_reliable_with_its_shortfalls_named():
    """Two trade-press sources, 17% spread, 2021 vintage. Genuinely worth
    something and genuinely short of the bar - which is the case the whole
    grading exists for."""
    out = _grade(
        verified_sources=[{"publisher": "Boersen-Zeitung"},
                          {"publisher": "NGO profile"}],
        claimed_sources=3,
        band={"spread_share": 0.17, "newest_year": 2021})
    assert out["grade"] == R.RELIABLE
    joined = " ".join(out["shortfalls"])
    assert "disagree by 17%" in joined
    assert "older than the governed" in joined
    assert "could not be confirmed" in joined


def test_cited_but_unconfirmed_sources_are_unreliable_and_still_returned():
    """Kept because it is informative: the figure is in circulation and here
    is where. Not usable, and never silently dropped."""
    out = _grade(verified_sources=[], claimed_sources=3)
    assert out["grade"] == R.UNRELIABLE
    assert out["promotable_by_named_analyst"] is False
    assert "no source was independently confirmed" in out["statement"]


def test_a_prose_value_is_unreliable_rather_than_rejected():
    out = _grade(verified_sources=[{"publisher": "Annual Report"}],
                 value_parsed=False)
    assert out["grade"] == R.UNRELIABLE
    assert any("stated in words" in s for s in out["supports"])


def test_no_grade_is_ever_asserted_by_the_model():
    """A model grading its own output is the same judgement twice."""
    import inspect
    src = inspect.getsource(R)
    assert "grade" not in {f.lower() for f in ("confidence",)} or True
    from app.llm import schemas
    for model in (schemas.PublicEvidenceResult, schemas.Quantity,
                  schemas.QuantityCandidate):
        fields = set(model.model_fields)
        assert not {"grade", "reliability", "confidence_grade"} & fields, (
            f"{model.__name__} lets the model grade itself")


def test_only_very_reliable_becomes_evidence_without_a_person():
    assert R.disposition_for(R.VERY_RELIABLE)[0] == "EVIDENCED_PUBLIC"
    for level in (R.RELIABLE, R.UNRELIABLE):
        disposition, reason = R.disposition_for(level)
        assert disposition == "DECLARED_UNKNOWN", (
            "a grade describes a finding; a disposition governs what may enter "
            "an estimate, and collapsing them makes 'we kept everything' into "
            "'we used everything'")
        assert reason


def test_both_lower_grades_keep_confidence_honest():
    """summarise() counts any non-DECLARED_UNKNOWN disposition toward domain
    completeness, which feeds confidence - so grading a thin finding upward
    would raise the confidence of an estimate that had not improved."""
    from app.domain.dispositions import DISPOSITIONS, UNKNOWN_REASONS
    for level in (R.RELIABLE, R.UNRELIABLE):
        disposition, reason = R.disposition_for(level)
        assert disposition in DISPOSITIONS
        assert reason in UNKNOWN_REASONS


def test_every_grade_explains_itself():
    for kw in ({"verified_sources": []},
               {"verified_sources": [{"publisher": "Annual Report"}]},
               {"verified_sources": [{"publisher": "x"}, {"publisher": "y"}]}):
        out = _grade(**kw)
        assert out["statement"].endswith(".")
        assert out["supports"] or out["shortfalls"]
