"""Asking an estimate how it was reached, and what would improve it.

An analyst asking "why is this number what it is" and "what should I go and
find" deserves an answer, and an LLM is the right way to turn a structured
answer into prose. It is the wrong way to work out the answer: a model asked
what is missing will produce a plausible list, and a plausible list of gaps is
worse than none because it sends people to look for the wrong things.

So the figures come from the snapshot, the gaps are computed from the
estimate's own state, and the model explains what it is given. The gate below
is the control that makes that safe.
"""
import re
import types

import pytest


class _Rejection:
    CLAIMED_FINDING_WITHOUT_SOURCE = "CLAIMED_FINDING_WITHOUT_SOURCE"
    OPTION_NOT_SUPPLIED = "OPTION_NOT_SUPPLIED"


PACKET = {
    "figures": {"current_annual_cost": "117150000.00",
                "headline_savings_base": "34000000.00",
                "confidence_score": "0.51", "confidence_band": "C",
                "priced_circuits": 337, "total_circuits": 337},
    "gaps": [{"gap": "STAGE_CEILING"}, {"gap": "ASSUMED_TOPOLOGY"}],
}


def _answer(text, gaps=(), unanswerable=False):
    return types.SimpleNamespace(answer=text, gaps_referenced=list(gaps),
                                 unanswerable=unanswerable)


def _gate():
    from app.llm import quality
    return quality.estimate_answer


# ------------------------------------------------------------- the control
def test_a_figure_the_packet_does_not_contain_is_refused():
    """The control the whole feature rests on. A model discussing numbers will
    produce numbers, and one it worked out is indistinguishable in prose from
    one the estimate produced - so it is refused rather than shown with a
    caveat."""
    verdict = _gate()(
        _answer("Current annual cost is 117150000.00 and the five-year NPV is "
                "142800000.00."), {"packet": PACKET})
    assert not verdict.accepted
    assert "not in the packet" in verdict.detail[0]


def test_a_figure_quoted_from_the_packet_is_accepted():
    assert _gate()(
        _answer("Current annual cost is 117150000.00, saving 34000000.00."),
        {"packet": PACKET}).accepted


def test_a_figure_written_readably_is_accepted():
    """The packet holds "34000000.00" and a readable answer says "EUR 34
    million". A gate that rejects a correct answer for writing a number well is
    a gate that gets turned off."""
    assert _gate()(
        _answer("The baseline is EUR 117.15 million and the base case saves "
                "EUR 34 million."), {"packet": PACKET}).accepted


def test_an_invented_gap_is_refused():
    """A plausible gap sends someone to look for the wrong thing, which is
    worse than not answering."""
    verdict = _gate()(_answer("Confidence is 0.51.",
                              gaps=("MISSING_CONTRACT_DATA",)),
                      {"packet": PACKET})
    assert not verdict.accepted
    assert "not in the computed gap list" in verdict.detail[0]


def test_a_real_gap_is_accepted():
    assert _gate()(
        _answer("Confidence is 0.51, capped by the V0 stage ceiling.",
                gaps=("STAGE_CEILING",)), {"packet": PACKET}).accepted


def test_declining_to_answer_is_always_accepted():
    """"The estimate does not record that" is the correct answer to a good many
    reasonable questions, and a model with no way to say it will guess."""
    assert _gate()(_answer("", unanswerable=True), {"packet": PACKET}).accepted


# --------------------------------------------------------- computed gaps
def test_the_gap_list_is_computed_not_described():
    """Every entry has to say what closes it and what that would change, or it
    is an observation rather than a next step."""
    from app.domain import explain

    snapshot = types.SimpleNamespace(
        estimate_snapshot_id="s1", version_label="V0", v0_status="COMPLETE",
        current_tco={"base": "117150000.00"},
        scenarios={"D": {"gross_run_rate_savings": {
            "low": "1", "base": "34000000.00", "high": "3"}}},
        confidence={"score": "0.51", "band": "C",
                    "ceilings_applied": ["stage_ceiling_V0_realization=0.35"]},
        coverage={"effective_coverage_pct": "0.55", "unpriced_pairs": [1, 2]},
        asserted_share="0.400", simulated_share="0.200", levers=[],
        pins={"estimate_method": "BUILD_UP",
              "topology_basis": {"assumed_fields": ["BRANCH.users_base"]}})

    class _Session:
        def execute(self, _q):
            return types.SimpleNamespace(all=lambda: [])

    gaps = explain.gaps(_Session(), case_id="c", snapshot=snapshot)
    assert gaps, "an estimate with a ceiling and unpriced scope has gaps"
    for gap in gaps:
        for field in ("gap", "detail", "closes_with", "would_change", "caps",
                      "priority"):
            assert gap.get(field), f"{gap.get('gap')} has no {field}"


def test_gaps_are_ordered_by_what_they_cap():
    """A confidence ceiling no other work can lift outranks a missing price in
    one country: the second is arithmetic, the first limits the estimate."""
    from app.domain import explain

    snapshot = types.SimpleNamespace(
        estimate_snapshot_id="s1", version_label="V0", v0_status="COMPLETE",
        current_tco={}, scenarios={}, confidence={
            "ceilings_applied": ["stage_ceiling_V0_realization=0.35"]},
        coverage={"unpriced_pairs": [1]}, asserted_share="0",
        simulated_share="0", levers=[], pins={})

    class _Session:
        def execute(self, _q):
            return types.SimpleNamespace(all=lambda: [])

    gaps = explain.gaps(_Session(), case_id="c", snapshot=snapshot)
    assert gaps[0]["gap"] == "STAGE_CEILING"
    assert [g["priority"] for g in gaps] == sorted(g["priority"] for g in gaps)


def test_the_explainer_has_no_search_tool():
    """It answers from the estimate. A search tool would let it answer from the
    internet and present that as what the estimate says."""
    from app.llm import prompts
    definition = prompts.get("estimate.explain.answer")
    assert definition.tool_policy_version.startswith("none")


def test_the_answer_schema_carries_no_computed_figure():
    """No field for a number the model worked out - the only numbers in an
    answer are the ones it quotes from the packet."""
    from app.llm import schemas
    fields = set(schemas.EstimateAnswer.model_fields)
    assert not {"savings", "confidence", "total", "value", "npv"} & fields
    assert "unanswerable" in fields
