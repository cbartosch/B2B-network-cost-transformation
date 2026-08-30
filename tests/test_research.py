"""Tests for domain research (Tranche 1: LLM-01/LLM-08 wiring into the
24-domain disposition contract).

Mocking is at the provider-adapter boundary (a fake object returning a real
ProviderCall), not at gateway.execute itself. That distinction matters:
gateway.execute's own behaviour - liveness verification, the llm_run insert,
idempotency - has a real effect this module depends on (succeed() refuses to
mark a LIVE run SUCCEEDED without a persisted llm_run proof). Replacing
gateway.execute wholesale with a bare stub, as an earlier draft of this file
did, skips that side effect and makes succeed() raise LivenessProofFailed on
every call that reaches it - a bug in the test, not in research.py, caught by
tracing the call chain rather than by running it (SQLAlchemy is not
installed in the environment this was written in). _fetch_source_fragment is
mocked directly, since it makes a real outbound HTTP call this suite has no
business making.

Like the rest of this suite, none of this has been executed against a real
interpreter. It is written and traced by hand, not proven; `make test` is the
first real signal.
"""
import itertools
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, select

from app import db
from app.domain import dispositions, research
from app.domain.policy import ResearchPolicy
from app.llm.providers.base import ProviderCall


def _seeded(set_name):
    """Same principle as test_integrity.py: read the policy that actually
    ships, so a seed change that breaks this is caught here."""
    from app.seed import THRESHOLDS
    return {k: v for sn, k, v in THRESHOLDS if sn == set_name}


POLICY = ResearchPolicy.from_rows(_seeded("research_budget_profile"))

# A tighter policy for the budget-exhaustion test, so it does not depend on
# how many LLM-01 domains happen to exist today.
TIGHT_POLICY = ResearchPolicy(
    set_name="test-tight", max_queries_per_domain=2, max_captures_per_domain=4,
    max_captures_per_run=3, min_independent_sources_material_fact=2,
    research_wall_clock_budget_minutes=5, max_web_searches_per_domain=3,
    max_seconds_per_domain=240)

_response_ids = (f"msg_test_{i}" for i in itertools.count())


def _case(session, *, confirmed=True, legal_name="Acme Global Logistics") -> str:
    case_id = str(uuid.uuid4())
    values = {"case_id": case_id, "created_by": "test",
              "subject_entity_legal_name": legal_name,
              "in_scope_countries": ["GB"]}
    if confirmed:
        values["resolved_entity_id"] = str(uuid.uuid4())
        values["entity_confirmed_by"] = "Jane Okafor"
    session.execute(insert(db.case).values(**values))
    session.commit()
    return case_id


def _found_text(n_sources=2, subject="Acme Global Logistics"):
    return json.dumps({
        "found": True, "subject": subject, "finding": "a finding",
        "sources": [{"url": f"https://example.com/{i}", "publisher": "p",
                     "as_of": "2026"} for i in range(n_sources)],
        "confidence_note": "n/a"})


def _not_found_text():
    return json.dumps({"found": False, "subject": "", "finding": "",
                       "sources": [], "confidence_note": "n/a"})


def _verified_fetch(url, timeout=10.0):
    return {"url": url, "status_code": 200, "fragment": "a real page fragment"}


class _FakeAdapter:
    """Stands in for AnthropicAdapter/OpenAIAdapter. gateway.execute()'s own
    logic runs for real against whatever this returns; only the network call
    is replaced.

    `raw["content"]` carries synthetic web_search_tool_result blocks echoing
    whichever URLs the text_fn's JSON claims, so research.py's
    "was this URL actually returned by a search?" filter sees a consistent
    response by default. A test that wants to exercise the model naming a
    source no search returned passes observed_urls explicitly.
    """

    def __init__(self, text_fn, configured=True, observed_urls=None):
        self._text_fn = text_fn
        self._configured = configured
        self._observed_urls = observed_urls
        self.name = "anthropic"
        self.reconciliation_tier = "A"
        self.last_tools = None

    def configured(self) -> bool:
        return self._configured

    def complete(self, *, system, prompt, max_tokens=1500, tools=None) -> ProviderCall:
        now = datetime.now(timezone.utc)
        self.last_tools = tools
        text = self._text_fn(system=system, prompt=prompt, max_tokens=max_tokens)
        if self._observed_urls is None:
            # Default: the search "returned" exactly what the response claims,
            # so the filter is satisfied and tests exercise the path after it.
            urls = []
            try:
                urls = [s["url"] for s in (json.loads(text).get("sources") or [])
                       if isinstance(s, dict) and s.get("url")]
            except (ValueError, AttributeError):
                pass
        else:
            urls = list(self._observed_urls)
        content = [{"type": "web_search_tool_result",
                    "content": [{"url": u, "title": "t"} for u in urls]}]
        return ProviderCall(
            provider="anthropic", model="fake-model", text=text,
            provider_response_id=next(_response_ids),
            provider_request_id=str(uuid.uuid4()),
            provider_request_at=now, input_tokens=50, output_tokens=50,
            local_request_at=now, latency_ms=10, http_status=200,
            egress_proxy=None, raw={"content": content})


def _wire_fake_provider(monkeypatch, text_fn=None, *, configured=True,
                        observed_urls=None):
    """Patches gateway._adapters(), which gateway.execute() calls internally,
    rather than gateway.execute itself - see the module docstring."""
    text_fn = text_fn or (lambda **kw: _found_text())
    fake = _FakeAdapter(text_fn, configured=configured, observed_urls=observed_urls)
    monkeypatch.setattr(research.gateway, "_adapters",
                        lambda: {"anthropic": fake, "openai": fake})
    return fake


# --------------------------------------------------------------- preconditions

def test_refuses_to_run_before_the_entity_is_confirmed(session):
    case_id = _case(session, confirmed=False)
    with pytest.raises(PermissionError, match="resolved and confirmed"):
        research.run_domain_research(session, case_id=case_id, research_policy=POLICY)


def test_raises_lookup_error_for_an_unknown_case(session):
    with pytest.raises(LookupError):
        research.run_domain_research(session, case_id="no-such-case",
                                     research_policy=POLICY)


def test_raises_value_error_for_an_agent_this_module_does_not_run(session):
    case_id = _case(session)
    with pytest.raises(ValueError, match="LLM-09"):
        research.run_domain_research(session, case_id=case_id, agent_ids=["LLM-09"],
                                     research_policy=POLICY)


# --------------------------------------------------------------- the map itself

def test_domain_agent_map_covers_all_24_domains_exactly_once():
    real = {no for no, _ in dispositions.DOMAINS}
    assert set(research.DOMAIN_AGENT_MAP) == real


def test_domain_agent_map_only_names_registered_agents():
    from app.llm import registry
    named = {a for a in research.DOMAIN_AGENT_MAP.values() if a is not None}
    assert named <= set(registry.AGENTS)
    assert named == {"LLM-01", "LLM-08"}


# --------------------------------------------------------------- success path

def test_a_verified_finding_is_written_as_evidenced_public(session, monkeypatch):
    case_id = _case(session)
    _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    result = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY)

    llm01_domains = {no for no, a in research.DOMAIN_AGENT_MAP.items() if a == "LLM-01"}
    assert result["domains_attempted"] == len(llm01_domains)
    assert result["failed"] == 0
    assert result["resolved"] == len(llm01_domains)

    rows = session.execute(select(db.domain_disposition)
                           .where(db.domain_disposition.c.case_id == case_id)).all()
    by_domain = {r.domain_no: r for r in rows}
    assert set(by_domain) == llm01_domains
    for r in by_domain.values():
        assert r.disposition == "EVIDENCED_PUBLIC"
        assert r.reason is None
        assert r.agent_run_id is not None
        assert r.evidence and len(r.evidence["sources"]) >= \
            POLICY.min_independent_sources_material_fact


def test_a_negative_finding_is_declared_unknown_no_public_evidence(session, monkeypatch):
    case_id = _case(session)
    _wire_fake_provider(monkeypatch, lambda **kw: _not_found_text())

    research.run_domain_research(session, case_id=case_id, agent_ids=["LLM-08"],
                                 research_policy=POLICY)

    rows = session.execute(select(db.domain_disposition)
                           .where(db.domain_disposition.c.case_id == case_id)).all()
    assert rows and all(r.disposition == "DECLARED_UNKNOWN" for r in rows)
    assert all(r.reason == "NO_PUBLIC_EVIDENCE" for r in rows)


def test_an_out_of_perimeter_subject_is_declared_unknown_out_of_perimeter(
        session, monkeypatch):
    case_id = _case(session, legal_name="Acme Global Logistics")
    _wire_fake_provider(
        monkeypatch, lambda **kw: _found_text(subject="A Totally Unrelated Company"))

    research.run_domain_research(session, case_id=case_id, agent_ids=["LLM-01"],
                                 research_policy=POLICY)

    rows = session.execute(select(db.domain_disposition)
                           .where(db.domain_disposition.c.case_id == case_id)).all()
    assert rows and all(r.reason == "OUT_OF_PERIMETER" for r in rows)


# --------------------------------------------------------------- failure handling

def test_a_provider_failure_writes_no_disposition_at_all(session, monkeypatch):
    case_id = _case(session)
    _wire_fake_provider(monkeypatch, configured=False)   # gateway.execute fails closed

    result = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY)

    assert result["failed"] == len(
        [1 for no, a in research.DOMAIN_AGENT_MAP.items() if a == "LLM-01"])
    rows = session.execute(select(db.domain_disposition)
                           .where(db.domain_disposition.c.case_id == case_id)).all()
    assert rows == [], (
        "a technical failure must not produce a disposition row - "
        "validate() should still report these domains as missing")


def test_malformed_model_output_writes_no_disposition(session, monkeypatch):
    case_id = _case(session)
    _wire_fake_provider(monkeypatch, lambda **kw: json.dumps({"unexpected": "shape"}))

    result = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-08"], research_policy=POLICY)

    assert result["failed"] > 0
    rows = session.execute(select(db.domain_disposition)
                           .where(db.domain_disposition.c.case_id == case_id)).all()
    assert rows == []

    # Found while building Tranche 2, fixed retroactively here: a rejected
    # shape must terminate the underlying agent_run as FAILED, not leave it
    # QUEUED forever - execute()'s own failure handling only covers what
    # execute() itself detects, not a caller's post-hoc shape check.
    from app import db as db_module
    runs = session.execute(select(db_module.agent_run)
                           .where(db_module.agent_run.c.case_id == case_id)).all()
    assert runs and all(r.status == "FAILED" for r in runs), (
        "every agent_run this research call created must reach a terminal "
        "state, not sit in QUEUED")


# --------------------------------------------------------------- budget and composition

def test_the_run_wide_capture_cap_is_enforced_across_domains(session, monkeypatch):
    case_id = _case(session)
    _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    result = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=TIGHT_POLICY)

    assert result["captures_used_this_run"] <= TIGHT_POLICY.max_captures_per_run
    reasons = {r["domain_no"]: r["reason"] for r in result["results"]}
    assert "BUDGET_EXHAUSTED" in reasons.values(), (
        "with max_captures_per_run=3 and 2 sources fetched per resolved "
        "domain, not every LLM-01 domain can be reached")


def test_research_does_not_overwrite_an_existing_disposition_by_default(
        session, monkeypatch):
    case_id = _case(session)
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
        domain_no=1, domain_name="Company and industry profile",
        disposition="ANALYST_ASSERTED_PRIOR", reason=None))
    session.commit()

    _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    result = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY)

    assert result["domains_skipped_already_disposed"] == 1
    row = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id,
        db.domain_disposition.c.domain_no == 1)).one()
    assert row.disposition == "ANALYST_ASSERTED_PRIOR", (
        "a pre-existing disposition must survive a research run unless "
        "overwrite=True was passed explicitly")


def test_overwrite_true_replaces_an_existing_disposition(session, monkeypatch):
    case_id = _case(session)
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
        domain_no=1, domain_name="Company and industry profile",
        disposition="ANALYST_ASSERTED_PRIOR", reason=None))
    session.commit()

    _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    research.run_domain_research(session, case_id=case_id, agent_ids=["LLM-01"],
                                 research_policy=POLICY, overwrite=True)

    row = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id,
        db.domain_disposition.c.domain_no == 1)).one()
    assert row.disposition == "EVIDENCED_PUBLIC"


def test_a_research_run_never_touches_domains_outside_its_map(session, monkeypatch):
    """Domains 3, 4, 5, 11, 17, 23, 24 are None in DOMAIN_AGENT_MAP - benchmark
    or simulation territory. A research run for LLM-01/LLM-08 must leave them
    alone even when nothing has disposed them yet."""
    case_id = _case(session)
    _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    research.run_domain_research(session, case_id=case_id, research_policy=POLICY)

    out_of_scope = {no for no, a in research.DOMAIN_AGENT_MAP.items() if a is None}
    rows = session.execute(select(db.domain_disposition.c.domain_no)
                           .where(db.domain_disposition.c.case_id == case_id)).all()
    touched = {r.domain_no for r in rows}
    assert touched.isdisjoint(out_of_scope)


# --------------------------------------------------------------- client-data protection

def test_research_never_discards_client_confirmed_data_even_with_overwrite(
        session, monkeypatch):
    """Found in audit. overwrite=True cleared the whole skip set, so a re-run
    of public research silently replaced a CLIENT_CONFIRMED disposition -
    destroying the client's answer, the named person who recorded it, and the
    attribution in the evidence column. The mirror of the rule mapping already
    enforced in the other direction."""
    case_id = _case(session)
    session.execute(insert(db.domain_disposition).values(
        id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
        domain_no=2, domain_name="Location footprint",
        disposition="CLIENT_CONFIRMED", reason=None,
        evidence={"client_answer": "122 sites", "answered_by": "Client Contact"}))
    session.commit()

    _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    result = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY,
        overwrite=True)

    assert 2 in result["domains_protected_client_confirmed"]
    row = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id,
        db.domain_disposition.c.domain_no == 2)).one()
    assert row.disposition == "CLIENT_CONFIRMED"
    assert row.evidence["answered_by"] == "Client Contact", (
        "the client's attribution must survive a research re-run")


# --------------------------------------------------------------- real search
# The module previously had no browsing capability at all: "found: true" was a
# claim recalled from training, and the URLs beside it were recalled too. These
# cover the two halves of closing that - the search actually being requested,
# and a source the search never returned being refused.

def test_the_anthropic_path_requests_a_real_web_search(session, monkeypatch):
    """Without tools on the request the model answers from recall, which is
    the gap this module's docstring spent three paragraphs apologising for."""
    case_id = _case(session)
    fake = _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    research.run_domain_research(session, case_id=case_id, agent_ids=["LLM-01"],
                                 provider="anthropic", research_policy=POLICY)

    assert fake.last_tools, "no tool was sent; the model would answer from recall"
    assert fake.last_tools[0]["name"] == "web_search"
    assert fake.last_tools[0]["max_uses"] == POLICY.max_web_searches_per_domain, (
        "the search cap must come from the governed budget, not a constant")


def test_a_source_the_search_never_returned_is_not_evidence(session, monkeypatch):
    """The failure mode real search introduces: the tool runs, and the model
    still cites a plausible URL from memory beside the results. An unobserved
    URL must not reach _verify_sources - otherwise a live-looking run
    launders a recalled citation into EVIDENCED_PUBLIC."""
    case_id = _case(session)
    # The response claims two sources; the search returned neither.
    _wire_fake_provider(monkeypatch, observed_urls=[])
    # Fetch would succeed for anything, so only the observed-URL filter can
    # be what stops these.
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    research.run_domain_research(session, case_id=case_id, agent_ids=["LLM-01"],
                                 provider="anthropic", research_policy=POLICY)

    rows = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id)).all()
    assert rows, "domains should still be dispositioned"
    assert not any(r.disposition == "EVIDENCED_PUBLIC" for r in rows), (
        "a URL the search never returned was accepted as public evidence")


def test_a_short_brand_name_is_not_treated_as_out_of_perimeter(session):
    """The DHL case. A >3-char token floor dropped the one word every public
    source uses - "DHL" - so "DHL Group" shared nothing with "DHL
    International GmbH" and real findings were quarantined as wrong-entity,
    surfacing to the analyst as "no evidence found"."""
    class _Row:
        subject_entity_legal_name = "DHL International GmbH"

    for subject in ("DHL Group", "Deutsche Post DHL Group", "DHL Logistics Group"):
        assert not research._looks_out_of_perimeter(subject, _Row()), subject
    # Still catches a genuinely different company.
    assert research._looks_out_of_perimeter("FedEx Corporation", _Row())


def test_unreachable_sources_are_an_egress_failure_not_budget_exhaustion(
        session, monkeypatch):
    """Found in the field. A container with no egress fetched nothing, so every
    claimed source failed, captures drained, the domain retried until its
    per-domain cap was gone, and the result was written up as
    DECLARED_UNKNOWN / BUDGET_EXHAUSTED - "we searched hard and found nothing".
    The run budget then drained the same way and later domains were marked
    exhausted without being attempted at all.

    A request that never completed says nothing about the source. The module
    contract is that an operational failure gets no disposition; this is the
    same rule one layer down."""
    case_id = _case(session)
    _wire_fake_provider(monkeypatch)

    def _unreachable(url, timeout=10.0):
        raise research.SourceUnreachable("ConnectError: [Errno -3] Temporary failure")

    monkeypatch.setattr(research, "_fetch_source_fragment", _unreachable)

    result = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY)

    rows = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id)).all()
    assert not any(r.reason == "BUDGET_EXHAUSTED" for r in rows), (
        "an egress failure was reported as an exhausted search budget")
    assert not rows, (
        "no disposition should be written for a domain that was never actually "
        "researched")
    assert any("egress failure" in (d.get("failure_detail") or "")
               for d in result["results"]), result["results"]


def test_a_404_still_counts_for_nothing_without_being_called_an_outage(
        session, monkeypatch):
    """The other half: a source that resolves and 404s IS evidence about that
    source, and must keep behaving as it did - no evidence, budget spent,
    eventually NO_PUBLIC_EVIDENCE. Only a request that never completed is an
    operational failure."""
    case_id = _case(session)
    _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment",
                        lambda url, timeout=10.0: None)

    research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY)

    rows = session.execute(select(db.domain_disposition).where(
        db.domain_disposition.c.case_id == case_id)).all()
    assert rows, "a genuinely fruitless search must still be dispositioned"
    assert all(r.disposition == "DECLARED_UNKNOWN" for r in rows)


def test_domain_nos_narrows_the_run_to_one_domain(session, monkeypatch):
    """The interface walks the 17 domains one request at a time: a single
    synchronous request for all of them ran for minutes and tripped the client
    timeout, reporting "API unreachable" with no sight of what had already
    succeeded. Narrowing has to actually narrow, or the walk is 17 full runs."""
    case_id = _case(session)
    _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    result = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY,
        domain_nos=[2])

    assert result["domains_attempted"] == 1
    rows = session.execute(select(db.domain_disposition.c.domain_no).where(
        db.domain_disposition.c.case_id == case_id)).all()
    assert {r.domain_no for r in rows} == {2}


def test_walking_domain_by_domain_resumes_rather_than_restarts(session, monkeypatch):
    """Each step is skipped on the next pass because it already carries a
    disposition - which is what makes an interrupted walk safe to re-run."""
    case_id = _case(session)
    _wire_fake_provider(monkeypatch)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    first = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY,
        domain_nos=[2])
    assert first["domains_attempted"] == 1

    again = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY,
        domain_nos=[2])
    assert again["domains_attempted"] == 0, (
        "a domain already disposed must not be researched a second time")


def test_a_single_domain_is_bounded_by_wall_clock(session, monkeypatch):
    """Regression from 4.40.0. research_wall_clock_budget_minutes is checked
    between domains in run_domain_research; once the interface began walking
    domains one request at a time, every request started a fresh run clock and
    that check stopped binding anything. A domain could then retry until its
    query and capture caps ran out - minutes of provider calls - and the
    interface reported the request as an outage.

    Effort caps bound effort. This bounds duration."""
    import app.domain.policy as policy_module

    case_id = _case(session)
    # Never verifies, so the loop always wants another attempt.
    _wire_fake_provider(monkeypatch, observed_urls=[])
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)

    slow = policy_module.ResearchPolicy(
        set_name="test-slow", max_queries_per_domain=50,
        max_captures_per_domain=500, max_captures_per_run=500,
        min_independent_sources_material_fact=2,
        research_wall_clock_budget_minutes=45,
        max_web_searches_per_domain=3,
        max_seconds_per_domain=0)          # every attempt after the first is late

    result = research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=slow,
        domain_nos=[2])

    entry = result["results"][0]
    assert entry["reason"] == "BUDGET_EXHAUSTED"
    assert entry["queries_used"] == 1, (
        "the clock must stop the loop long before the 50-query cap")
    assert "max_seconds_per_domain" in (entry["budget_note"] or ""), (
        "which budget ran out has to be recorded - time and captures have "
        "different remedies")


def test_the_prompt_carries_the_domain_brief_and_the_case_scope(session, monkeypatch):
    """The prompt used to carry the domain *name* and nothing else. A label is
    not a question: for an entity with abundant public disclosure the agent
    guessed at scope, returned group-level prose and cited a homepage, which
    reached the analyst as "no evidence found"."""
    case_id = _case(session)
    seen = {}

    def _capture(**kw):
        seen.update(kw)
        return _found_text()

    _wire_fake_provider(monkeypatch, text_fn=_capture)
    monkeypatch.setattr(research, "_fetch_source_fragment", _verified_fetch)
    research.run_domain_research(
        session, case_id=case_id, agent_ids=["LLM-01"], research_policy=POLICY,
        domain_nos=[2])

    prompt = seen.get("prompt", "")
    assert "WAREHOUSE" in prompt and "LARGE_OFFICE" in prompt, (
        "domain 2 must ask for counts in the archetype vocabulary the "
        "simulation actually uses")
    assert "in-scope countries" in prompt, (
        "without scope the agent answers at group level for a global entity")
    assert "quantities" in prompt, "the estimate consumes numbers, not prose"


def test_every_agent_routed_domain_has_a_brief():
    """A domain routed to an agent with no brief falls back to its bare name -
    the exact condition that produced empty findings."""
    missing = sorted(no for no, agent in research.DOMAIN_AGENT_MAP.items()
                     if agent and no not in research.DOMAIN_BRIEFS)
    assert not missing, f"domains routed to an agent with no research brief: {missing}"


def test_the_displayed_prompt_is_hashed_the_way_the_gateway_hashes_it():
    """The prompt viewer claims 'this is what was sent'. That claim rests on
    the hash being computed identically to gateway.execute's request_hash - if
    the two ever diverge the panel would report a mismatch on every domain and
    be quietly ignored."""
    import hashlib
    from app.llm import gateway

    system, prompt = "sys", "usr"
    assert gateway._sha(system + prompt) == hashlib.sha256(
        (system + prompt).encode("utf-8")).hexdigest()
