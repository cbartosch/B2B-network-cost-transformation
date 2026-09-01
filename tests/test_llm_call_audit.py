"""Deep audit: does every LLM call keep what it was given?

The theme, found three times in one session: a reply that contained real
information was discarded because it was insufficient. Rejecting a reply as
*sufficient* is not the same as judging it *worthless*, and the provider call,
the search and the source fetches were all paid for before the judgement.

The rule these encode: a schema-valid reply is never thrown away. It may fail
to be evidence - and must, where it does - but it is recorded, visible, and
distinguishable from having found nothing.
"""
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = next(c for c in (ROOT / "api_service" / "app", ROOT / "app")
           if (c / "routers" / "api.py").exists())


def test_a_gate_rejection_carries_the_best_reply():
    """structured_call retried three times and raised with only a message, so
    a reply that cited two sources when three were required was discarded
    whole - including the two sources and the numbers they supported."""
    from app.llm import gateway
    src = inspect.getsource(gateway.structured_call)
    assert "best_payload" in src and "rejected_payload" in src
    assert "rejected_result" in src, (
        "the typed object is more use to a caller than the raw dict")


def test_a_schema_valid_reply_is_kept_even_when_a_gate_refuses_it():
    """Schema-valid means legible; the gates judge sufficiency. Those are
    different questions and only the caller knows which one it needs."""
    from app.llm import gateway
    src = inspect.getsource(gateway.structured_call)
    assert "if result is not None:" in src, (
        "the best attempt has to be captured before the verdict is applied")


def test_partial_verification_is_recorded_not_overwritten():
    """The most expensive discard in the codebase: a verified source and a
    parsed quantity in hand, and the domain wrote DECLARED_UNKNOWN /
    NO_PUBLIC_EVIDENCE over them - so "there is nothing public" and "there is
    something, one source short of the bar" were indistinguishable."""
    research = (APP / "domain" / "research.py").read_text()
    assert "PARTIAL_EVIDENCE_BELOW_THRESHOLD" in research
    assert "if len(verified) > len(result.verified_sources or []):" in research, (
        "the best partial result must survive the retry loop")


def test_the_partial_reason_is_in_the_governed_vocabulary():
    from app.domain.dispositions import UNKNOWN_REASONS
    assert "PARTIAL_EVIDENCE_BELOW_THRESHOLD" in UNKNOWN_REASONS


def test_partial_evidence_does_not_become_a_disposition():
    """The tempting move and the wrong one. summarise() counts any
    non-DECLARED_UNKNOWN disposition toward domain completeness, which feeds
    confidence - so a PARTIAL_PUBLIC_EVIDENCE disposition would have *raised*
    confidence for a domain that found too little evidence to use."""
    from app.domain.dispositions import DISPOSITIONS
    assert not any("PARTIAL" in d for d in DISPOSITIONS)


def test_a_rejected_research_reply_keeps_its_findings():
    research = (APP / "domain" / "research.py").read_text()
    assert 'getattr(exc, "rejected_payload", None)' in research
    assert "the rejected reply is kept" in research
    assert "result.failed = True" in research, (
        "kept findings must not become a disposition - failed stays true")


def test_a_rejected_benchmark_extraction_returns_its_observations():
    """The source was converted, uploaded and paid for. Nothing is stored, so
    no control is skipped - the operator simply does not pay twice to see what
    the reply said."""
    ingest = (APP / "domain" / "benchmark_ingest.py").read_text()
    assert "exc.salvaged" in ingest
    assert "None is stored" in ingest
    api = (APP / "routers" / "api.py").read_text()
    assert 'getattr(exc, "salvaged", None)' in api


def test_nothing_salvaged_can_reach_an_estimate():
    """The whole safety argument. Salvage is a record of work, never evidence:
    no disposition, no storage, no gate satisfied."""
    research = (APP / "domain" / "research.py").read_text()
    salvage = research[research.index('_rejected = getattr(exc, "rejected_payload"'):]
    salvage = salvage[:salvage.index("return result")]
    for forbidden in ("result.disposition", "result.verified_sources ="):
        assert forbidden not in salvage, (
            f"salvaged content must not set {forbidden}")


@pytest.mark.parametrize("module", [
    "research", "benchmark_ingest", "entity_resolution", "known_facts",
    "questionnaire", "savings_advisory",
])
def test_every_llm_module_fails_closed_on_a_provider_error(module):
    """Distinct from the discard question: a provider that is unreachable must
    not produce a result at all. Salvage applies to a reply that arrived and
    was judged insufficient, never to one that never arrived."""
    src = (APP / "domain" / f"{module}.py").read_text()
    assert "ProviderUnavailable" in src, (
        f"{module} does not distinguish an unreachable provider from a poor "
        f"answer")


def test_every_agent_routed_domain_survives_the_pipeline():
    """The end-to-end check that can run without a network.

    A realistic reply for each of the 17 agent-routed domains is validated
    against the real schemas, triangulated, graded, given a disposition and
    JSON-serialised as the evidence blob it would be stored as. Three separate
    releases died at three different points on this path - the result-object
    rebinding, a Decimal in a JSON column, and a schema forbidding a field the
    prompt asked for - and each was only visible once the one before it was
    cleared.
    """
    import subprocess
    import sys
    from pathlib import Path

    tool = Path(__file__).resolve().parents[1] / "tools" / "verify_domains.py"
    result = subprocess.run([sys.executable, str(tool)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All 17 agent-routed domains" in result.stdout


# ------------------------------------------------------- efficiency and yield
def test_a_domain_inherits_what_earlier_domains_found():
    """The largest waste in the build. Every domain call started from nothing
    and searched the same company again: 17 domains at up to 8 searches each,
    plus four intake calls, is several hundred searches of one entity for one
    case - most of it rediscovering the same annual report.

    Handing a domain its predecessors' findings is cheaper and better: it can
    cite a source already verified, and can disagree with a sibling explicitly
    rather than in ignorance of it."""
    research = (APP / "domain" / "research.py").read_text()
    assert "def _prior_findings" in research
    assert 'ctx["prior_findings"]' in research
    assert '{prior_block}' in research, (
        "the block is built and read but must also be rendered into the prompt")
    block = research[research.index("def _prior_findings"):
                     research.index("def _build_context")]
    assert "not evidence for yours unless the same source says so" in block, (
        "inherited findings must not become citable evidence by proximity")


def test_a_terminal_rejection_does_not_burn_its_remaining_attempts():
    """Retrying a rejection that cannot be satisfied is pure spend."""
    from app.llm import gateway
    import inspect
    src = inspect.getsource(gateway.structured_call)
    assert "if not verdict.retryable:" in src and "break" in src


def test_the_quantity_schema_carries_what_the_briefs_ask_for():
    """The briefs asked for vendor, currency, contract term and technology and
    no field carried them, so the agent either dropped them or forced them into
    `label` where nothing downstream could read them. A price without its
    currency and term is not comparable with another price."""
    from app.llm import schemas
    fields = set(schemas.Quantity.model_fields)
    for needed in ("currency", "vendor", "term_months", "technology",
                   "bandwidth_mbps", "country", "as_of"):
        assert needed in fields, f"Quantity cannot carry {needed}"


def test_no_brief_asks_for_something_the_schema_cannot_hold():
    """Checked across every brief rather than the ones that happened to fail."""
    import ast
    from app.domain.research_briefs import RESEARCH_BRIEFS
    from app.llm import schemas

    carriable = (set(schemas.Quantity.model_fields)
                 | set(schemas.PublicEvidenceResult.model_fields))
    wanted = {"vendor": "vendor", "carrier": "vendor", "currency": "currency",
              "technology": "technology", "bandwidth": "bandwidth_mbps"}
    gaps = []
    for no, brief in RESEARCH_BRIEFS.items():
        text = (brief.get("wants") or "").lower()
        for term, field in wanted.items():
            if term in text and field not in carriable:
                gaps.append(f"domain {no} wants {term}")
    assert not gaps, gaps


def test_every_stage_boundary_agrees_on_what_crosses_it():
    """Every functional defect in this build has been the same shape: one stage
    wrote something and the next read something slightly different. A parameter
    renamed and not updated at the call site, a dict key that moved, a
    classifier gaining a target the bucket dict never got, a Decimal in a JSON
    column, a field the prompt asked for that the schema forbade.

    None of those are visible by reading one file, and none survive a check
    that names the producer and the consumer and compares them."""
    import subprocess
    import sys
    from pathlib import Path

    tool = Path(__file__).resolve().parents[1] / "tools" / "validate_flow.py"
    result = subprocess.run([sys.executable, str(tool)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_out_of_perimeter_finding_is_retained_not_discarded():
    """The integrity endpoint promised "Nothing was deleted" while
    audit.quarantined_row had never been written to: research detected a finding
    about the wrong subject, logged "quarantined: OUT_OF_PERIMETER", and threw
    it away.

    Such a finding is informative twice over - the perimeter may be wrong, or
    an alias may be missing, which is exactly how HypoVereinsbank was lost -
    and neither is diagnosable from a disposition that says only
    DECLARED_UNKNOWN."""
    research = (APP / "domain" / "research.py").read_text()
    assert "insert(db.quarantined_row)" in research
    block = research[research.index("if _looks_out_of_perimeter"):]
    block = block[:block.index("return result")]
    assert "add it" in block and "alias" in block, (
        "the remedy has to be named where the finding is lost")
    assert 'reason="OUT_OF_PERIMETER"' in block
