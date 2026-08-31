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
