"""Asking questions about a published estimate, without letting it invent one.

Two rules make this safe. The gaps are computed, not asked for - "what is
missing" has a deterministic answer, and asking a model to work it out would
invite a plausible list competing with the measured one. And every figure in
the answer must already be in the packet, because the model is explaining a
calculation rather than performing one, and an explanation of a cost model is
exactly where an invented figure would be believed.
"""
import pytest

from app.domain import estimate_qa

PACKET = {
    "current_tco": {"base": "2855220.00"},
    "scenarios": {"D": {"gross_run_rate_savings": {"base": "45150000.00"}}},
    "coverage": {"effective_coverage_pct": "0.550",
                 "unpriced_countries": ["FR", "NL"]},
    "confidence": {"score": "0.51", "band": "C"},
}


# ------------------------------------------------------ no invented figures
@pytest.mark.parametrize("answer,clean", [
    ("The modelled cost is 2,855,220 and scenario D saves 45,150,000.", True),
    ("About 2.9 million, saving around 45 million.", True),
    ("Coverage is 0.550.", True),
    ("17 domains carry a disposition.", True),
    ("Confidence is capped by a ceiling, not by coverage.", True),
    ("The addressable pool implies 12,480,000.", False),
    ("Coverage of 0.550 leaves 0.782 unpriced.", False),
    ("Roughly 3.4 million of current spend.", False),
])
def test_a_figure_the_estimate_does_not_contain_is_caught(answer, clean):
    """The strongest control available here. A rounded restatement is
    explaining - refusing "about 2.9 million" of 2,855,220 would refuse an
    answer for the reasonable act of rounding - and a number nobody computed is
    an invention however plausible."""
    unsupported = estimate_qa.unsupported_figures(answer, PACKET)
    assert (unsupported == []) is clean, unsupported


def test_rounding_is_recognised_in_both_directions():
    """2,855,220 at two significant digits is 2.9, not 2.8. Truncating alone
    read a correct rounding as invented."""
    for text in ("2.9 million", "2.86 million", "2.8 million", "2,855,220"):
        assert estimate_qa.unsupported_figures(text, PACKET) == [], text


# ------------------------------------------------------- the gaps are computed
def _gaps(**over):
    snapshot = {"coverage": {"unpriced_countries": ["FR", "NL"]},
                "confidence": {"ceilings_applied": ["stage_ceiling_V0=0.35"]}}
    snapshot.update(over.pop("snapshot", {}))
    return estimate_qa.gaps(snapshot=snapshot,
                            dispositions=over.get("dispositions", []),
                            topology_basis=over.get("topology_basis"),
                            known_facts=over.get("known_facts"))


def test_an_unpriced_country_is_a_gap_with_a_next_step():
    """"Coverage is 55%" is a measurement; "research domain 19 for FR and NL"
    is something an analyst can do."""
    gap = next(g for g in _gaps() if g["gap"] == "unpriced countries")
    assert "FR" in gap["detail"] and "NL" in gap["detail"]
    assert "domain 19" in gap["closes_it"]
    assert gap["costs"]


def test_unknown_domains_are_grouped_by_reason_with_the_right_remedy():
    """The remedy differs entirely: an out-of-perimeter domain needs an alias,
    a partial finding needs a re-run, and nothing public needs the register."""
    dispositions = [
        {"domain_no": 7, "domain_name": "Architecture",
         "disposition": "DECLARED_UNKNOWN", "reason": "OUT_OF_PERIMETER"},
        {"domain_no": 9, "domain_name": "Public cost",
         "disposition": "DECLARED_UNKNOWN",
         "reason": "PARTIAL_EVIDENCE_BELOW_THRESHOLD"},
    ]
    found = {g["gap"]: g for g in _gaps(dispositions=dispositions)}
    perimeter = found["domains declared unknown (OUT_OF_PERIMETER)"]
    partial = found[
        "domains declared unknown (PARTIAL_EVIDENCE_BELOW_THRESHOLD)"]
    assert "alias" in perimeter["closes_it"]
    assert "re-run" in partial["closes_it"]


def test_an_assumed_topology_field_is_a_gap_that_costs_nothing_measurable():
    """Honest about what it is: a simulated topology is a sizing instrument
    either way (0.3B), so overstating this as a coverage loss would be wrong."""
    gap = next(g for g in _gaps(
        topology_basis={"assumed_fields": ["BRANCH.backup_product"]})
        if g["gap"] == "topology still assumed")
    assert "nothing measurable" in gap["costs"]
    assert "0.3B" in gap["costs"]


def test_an_uncorroborated_fact_names_the_ceiling_it_triggers():
    gap = next(g for g in _gaps(
        known_facts=[{"corroboration_state": "UNCORROBORATED"}])
        if g["gap"] == "uncorroborated assertions")
    assert "0.6A" in gap["costs"]
    assert "corroborate" in gap["closes_it"]


def test_a_clean_estimate_reports_no_gaps():
    assert estimate_qa.gaps(
        snapshot={"coverage": {}, "confidence": {}}, dispositions=[]) == []


# --------------------------------------------------------------- the packet
def test_the_packet_carries_the_mechanism_not_just_the_answer():
    """A question about why confidence sits where it does is answerable only
    from the ceilings, the origin mix and the coverage basis."""
    pack = estimate_qa.packet(
        case={"subject_entity_legal_name": "Adolf Wuerth GmbH & Co. KG"},
        snapshot={"coverage": {"coverage_basis": "MIN_OF_VALUE_AND_CIRCUIT"},
                  "confidence": {"ceilings_applied": ["x"]},
                  "pins": {"estimate_method": "BUILD_UP",
                           "origin_breakdown": {"EVIDENCED_PUBLIC": {"share": "0.6"}}}},
        dispositions=[], known_facts=[])
    for key in ("coverage", "confidence", "origin_breakdown", "method",
                "gaps", "dispositions"):
        assert key in pack, key


def test_the_gate_refuses_an_invented_figure():
    from app.llm import quality, schemas
    invented = schemas.EstimateAnswer.model_validate(
        {"answer": "The addressable pool is 12,480,000."})
    verdict = quality.evaluate("estimate.explain", invented, {"packet": PACKET})
    assert not verdict.accepted
    assert quality.Rejection.FIGURE_NOT_IN_PACKET in verdict.reasons

    quoted = schemas.EstimateAnswer.model_validate(
        {"answer": "The modelled cost is 2,855,220."})
    assert quality.evaluate("estimate.explain", quoted,
                            {"packet": PACKET}).accepted


def test_saying_the_packet_cannot_answer_it_is_accepted():
    """Naming what would have to be recorded is a useful answer; inferring it
    is not."""
    from app.llm import quality, schemas
    abstained = schemas.EstimateAnswer.model_validate(
        {"answer": "", "cannot_answer_from_packet":
         "the estimate records no per-vendor split, so the question needs "
         "domain 8 researched and promoted first"})
    assert quality.evaluate("estimate.explain", abstained,
                            {"packet": PACKET}).accepted


def test_a_reference_to_a_gap_that_was_not_supplied_is_refused():
    from app.llm import quality, schemas
    answer = schemas.EstimateAnswer.model_validate(
        {"answer": "Coverage is the binding constraint.",
         "gaps_referenced": [0, 7]})
    verdict = quality.evaluate("estimate.explain", answer,
                              {"packet": {**PACKET, "gaps": [{"gap": "one"}]}})
    assert not verdict.accepted


def test_the_answer_schema_cannot_carry_a_recommendation():
    """This explains what was computed. LLM-07 recommends, and a service that
    quietly did both would put an unapproved recommendation in an explanation."""
    from app.llm import schemas
    fields = set(schemas.EstimateAnswer.model_fields)
    assert not {"scenario_code", "percentile", "recommendation",
                "savings"} & fields
