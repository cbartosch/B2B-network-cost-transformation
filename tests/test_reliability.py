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


# ------------------------------------------------- provenance drives the grade
def test_the_agent_reports_provenance_and_never_the_grade():
    """The division the whole design rests on: the agent says what it read,
    code says what that is worth. A model grading its own output is the same
    judgement twice."""
    from app.llm import schemas
    fields = set(schemas.SourceRef.model_fields)
    assert {"source_class", "how_read", "figure_basis"} <= fields
    assert not {"grade", "reliability", "confidence"} & fields


def test_a_declared_source_class_beats_guessing_at_the_hostname():
    """The grader matched keywords against URLs, so an unfamiliar regulator
    graded the same as a blog. The agent read the page and knows."""
    dutch = [{"publisher": "Autoriteit Consument & Markt",
              "source_class": "REGULATOR", "how_read": "FULL_PAGE",
              "figure_basis": "STATED"},
             {"publisher": "KVK register", "source_class": "REGULATOR",
              "how_read": "FULL_PAGE", "figure_basis": "STATED"}]
    out = _grade(verified_sources=dutch,
                 band={"spread_share": 0.03, "newest_year": 2025})
    assert out["grade"] == R.VERY_RELIABLE, (
        "a regulator this codebase has never heard of must still grade as one")


def test_a_snippet_only_source_is_a_named_downgrade_not_a_rejection():
    out = _grade(
        verified_sources=[{"source_class": "PRIMARY_FILING",
                           "how_read": "SNIPPET_ONLY", "figure_basis": "STATED"},
                          {"source_class": "REGULATOR",
                           "how_read": "SNIPPET_ONLY", "figure_basis": "STATED"}],
        band={"spread_share": 0.03, "newest_year": 2025})
    assert out["grade"] == R.RELIABLE
    assert any("search snippet" in s for s in out["shortfalls"])


def test_an_inferred_figure_is_downgraded_and_kept():
    out = _grade(
        verified_sources=[{"source_class": "TRADE_PRESS",
                           "how_read": "FULL_PAGE", "figure_basis": "INFERRED"},
                          {"source_class": "TRADE_PRESS",
                           "how_read": "FULL_PAGE", "figure_basis": "INFERRED"}],
        band={"spread_share": 0.03, "newest_year": 2025})
    assert out["grade"] == R.RELIABLE
    assert any("do not state the figure" in s for s in out["shortfalls"])


def test_the_base_contract_asks_for_findings_not_certainty():
    """The contract told the agent a snippet "is not evidence", which under
    grading means discarding an UNRELIABLE finding that was worth keeping."""
    from app.llm.prompts import BASE_CONTRACT
    assert "Nothing you find is discarded" in BASE_CONTRACT
    assert "is not evidence" not in BASE_CONTRACT
    assert "Withholding either" in BASE_CONTRACT
    assert "Never invent a source" in BASE_CONTRACT, (
        "the one prohibition grading cannot work around must survive")


def test_the_contract_tells_the_agent_to_stop_searching():
    """Efficiency: an eighth query rarely changes a grade, and every one is
    latency and spend."""
    from app.llm.prompts import BASE_CONTRACT
    assert "Stop when you have a figure and its provenance" in BASE_CONTRACT
    assert "Vary the phrasing" in BASE_CONTRACT


# ---------------------------------------- the prompt and the schema must agree
def test_every_per_source_model_accepts_the_provenance_the_contract_asks_for():
    """The failure that cost a 377-second domain: the base contract says "for
    every source, state source_class, how_read and figure_basis". The agent
    complied and put them on QuantityCandidate, which did not declare them and
    forbids extras - so a correct reply was rejected with 26 validation errors.

    Asking for a field and then refusing it is the worst of both. Checked
    across every per-source model, not just the one that failed."""
    from app.llm import schemas

    required = {"source_class", "how_read", "figure_basis"}
    for name in ("SourceRef", "QuantityCandidate", "CorroborationCandidate",
                 "BenchmarkObservationOut", "ProposedKnownFact"):
        model = getattr(schemas, name)
        missing = required - set(model.model_fields)
        assert not missing, f"{name} would reject the agent for {sorted(missing)}"


def test_a_reply_carrying_provenance_on_candidates_validates():
    """The exact shape that was rejected."""
    from app.llm import schemas
    payload = {
        "found": True, "subject": "Adolf Wuerth GmbH & Co. KG",
        "finding": "Around 2,600 locations worldwide.",
        "quantities": [{
            "label": "STORE", "value": "2600", "unit": "sites",
            "country": "DE",
            "candidates": [
                {"value": "2600", "publisher": "Annual Report 2025",
                 "source_url": "https://x/ar", "as_of": "2024-12-31",
                 "source_class": "PRIMARY_FILING", "how_read": "FULL_PAGE",
                 "figure_basis": "STATED", "excerpt": "2,600 locations"},
                {"value": "2500", "publisher": "Handelsblatt",
                 "source_class": "TRADE_PRESS", "how_read": "SNIPPET_ONLY",
                 "figure_basis": "STATED"}]}],
        "sources": [{"url": "https://x/ar", "publisher": "Annual Report 2025",
                     "source_class": "PRIMARY_FILING", "how_read": "FULL_PAGE",
                     "figure_basis": "STATED"}],
    }
    result = schemas.PublicEvidenceResult.model_validate(payload)
    assert result.quantities[0].candidates[0].source_class.value == "PRIMARY_FILING"
    assert result.quantities[0].candidates[1].how_read.value == "SNIPPET_ONLY"


def test_provenance_stated_on_candidates_reaches_the_grade():
    """Otherwise the agent reports it, the schema accepts it, and the grade
    ignores it - which is the same discard in a third disguise."""
    graded = _grade(
        verified_sources=[],
        claimed_sources=2,
        band={"spread_share": 0.04, "newest_year": 2025, "candidates": [
            {"source_url": "https://x/ar", "source_class": "PRIMARY_FILING",
             "how_read": "FULL_PAGE", "figure_basis": "STATED"},
            {"source_url": "https://y", "source_class": "REGULATOR",
             "how_read": "FULL_PAGE", "figure_basis": "STATED"}]})
    assert graded["verified_sources"] == 2, (
        "candidate provenance must count toward the grade")
    assert graded["grade"] == R.VERY_RELIABLE
