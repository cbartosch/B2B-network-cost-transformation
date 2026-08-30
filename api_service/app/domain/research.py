"""Domain research (spec 0.2, 0.3A). Wires LLM-01 (public evidence, footprint
and current-state proposals) and LLM-08 (source-backed market-data gathering)
into the 24-domain disposition contract, which previously had no research path
at all - every domain was disposed by hand via PUT .../domain-dispositions.

Read this before trusting what this module produces:

**Anthropic calls now actually search**, via the hosted web_search tool
(gateway.execute(tools=...), see anthropic_adapter.py). That tool runs
server-side and returns real search-result blocks in the same response - no
second round trip - so "found: true" can now be backed by a search that
actually happened, not just a claim recalled from training. A model can still
misdescribe or over-interpret what a search turned up, so this is not treated
as sufficient on its own: _extract_observed_urls reads the real
web_search_tool_result blocks from the response, and only a claimed source
whose URL was actually among those results survives - the filter in
_research_one_domain is a hard drop, not a hint. A URL the model names but
the tool never returned never reaches _verify_sources.

Spec 0.3A ties EVIDENCED_PUBLIC to "a stored source fragment", so a real
search result still isn't taken as sufficient by itself: every URL that
survives the above is independently fetched again with plain httpx
(_fetch_source_fragment), separately from the pinned LLM-provider transport,
which exists for provider APIs and has no reason to extend to arbitrary
third-party URLs. Only a source that both (a) came from a real search-tool
result and (b) actually resolves on refetch counts toward
min_independent_sources_material_fact.

**OpenAI calls do not search.** Chat Completions has no equivalent hosted,
server-executed search tool this codebase can wire up in one request/response
(openai_adapter.py raises rather than silently completing without one if
research.py ever passes it tools). Selecting "openai" as the research
provider means recall-only, with the same evidentiary weakness described
above for the pre-search build - only the anthropic path currently searches.

None of the search-tool wiring in this module has been exercised against a
real API response (no network egress in the sandbox this was built in); the
request/response shape follows Anthropic's documented web_search tool
contract as of this codebase's training data, but block-type names, field
names inside a web_search_tool_result, or the tool's exact name string could
have moved on. Expect to find and fix something on first real run, the same
posture the rest of this bundle takes about anything untested.

**This module never writes DERIVED_PUBLIC.** Recognising that a value was
combined from other approved public facts, and recording the derivation method
correctly, needs a dependency graph over prior EVIDENCED_PUBLIC facts that
does not exist yet. Attempting it here would be a second, weaker guess bolted
onto the first. Out of scope for this tranche; every resolved domain below is
EVIDENCED_PUBLIC or nothing.

**Three distinct reasons a domain ends a run without EVIDENCED_PUBLIC, and
they are not interchangeable:**

  - genuinely searched, found nothing attributable -> DECLARED_UNKNOWN /
    NO_PUBLIC_EVIDENCE
  - a budget cap (per-domain or per-run, query or capture, or wall clock) was
    hit first -> DECLARED_UNKNOWN / BUDGET_EXHAUSTED
  - the agent call itself failed - no provider configured, liveness proof
    failed, or the model's output was not valid structured JSON -> **no
    disposition is written at all.** A technical failure is not evidence of
    anything, and writing DECLARED_UNKNOWN for it would misrepresent an
    operational failure as a completed, if fruitless, search. validate() will
    correctly report the domain as missing rather than accept a disposition
    nothing actually earned; the domain is left for a retry or manual entry.

**DOMAIN_AGENT_MAP is a first pass**, inferred from the domain catalogue in
dispositions.DOMAINS and the two agents' one-line registry descriptions - not
sourced from a spec table, because none assigning research domains to agents
turned up in what this was built against. It is declared as data, in one
place, specifically so it is easy to correct if a real one exists or is
written later. Ten domains route to LLM-01, seven to LLM-08; the remaining
seven (archetype, bandwidth, remote-user population, operating-model cost,
resilience, Northstar scenarios, and the evidence/confidence metadata domain
itself) are benchmark-prior or simulation territory by design and were never
in scope for these two agents - closing this gap does not mean all 24 domains
stop being manual, only that the ones these agents can genuinely address do.

**Research never runs before the entity is confirmed** (0.1A: resolve the
entity before researching it) and never overwrites a domain that already
carries any disposition, from any source, unless overwrite=True is passed
explicitly - composing with manual entry, not replacing it, is the point.

**CLIENT_CONFIRMED domains are protected even from overwrite=True.** First-party
client data, recorded by a named person, is not something a re-run of public
research may discard as a side effect. See _client_confirmed_domain_nos.
"""
import logging
import re
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import insert, select, update

from .. import db
from ..llm import errors, gateway, registry
from ..llm.providers import _transport
from . import dispositions
from .policy import ResearchPolicy

log = logging.getLogger("workbench.research")

# domain_no -> agent_id, or None. None means out of scope for this tranche:
# benchmark-prior or simulation territory (0.3B), not a public-research
# target. See the module docstring - this mapping needs confirming.
DOMAIN_AGENT_MAP: dict[int, str | None] = {
    1: "LLM-01", 2: "LLM-01", 3: None, 4: None, 5: None, 6: "LLM-01",
    7: "LLM-01", 8: "LLM-01", 9: "LLM-08", 10: "LLM-08", 11: None,
    12: "LLM-01", 13: "LLM-01", 14: "LLM-01", 15: "LLM-01", 16: "LLM-01",
    17: None, 18: "LLM-08", 19: "LLM-08", 20: "LLM-08", 21: "LLM-08",
    22: "LLM-08", 23: None, 24: None,
}

_RESPONSE_SHAPE = (
    '{"found": bool, "subject": str, "finding": str, '
    '"sources": [{"url": str, "publisher": str, "as_of": str}], '
    '"confidence_note": str}')

_SEARCH_INSTRUCTION = (
    "You have a web_search tool. Use it before answering - actually search "
    "for current public information about the named entity for this domain; "
    "do not answer from what you already recall without searching. Every URL "
    "in \"sources\" must be a URL your search actually returned, not one you "
    "are recalling or reconstructing from memory - a source that did not come "
    "back from a search this turn will be discarded regardless of how "
    "confident you are that it exists.")

AGENT_SYSTEM_PROMPTS = {
    "LLM-01": (
        "You are a research agent proposing public evidence for one input "
        "domain of an outside-in network cost estimate (footprint, "
        "architecture, vendor signals, transformation announcements, "
        "regulatory posture). You may only assert what a named public source "
        f"states. {_SEARCH_INSTRUCTION} Respond with a single JSON object and "
        f"nothing else, matching this shape exactly: {_RESPONSE_SHAPE}. If "
        'your search finds nothing you can attribute to a named public '
        'source, set "found": false and leave "sources" empty - never '
        "invent a source to satisfy the shape."),
    "LLM-08": (
        "You are a research agent proposing source-backed market data for "
        "one input domain of an outside-in network cost estimate (public "
        "cost evidence, market pricing, serviceability, currency and tax). "
        f"{_SEARCH_INSTRUCTION} Respond with a single JSON object and "
        f"nothing else, matching this shape exactly: {_RESPONSE_SHAPE}. If "
        'your search finds nothing you can attribute to a named public '
        'source, set "found": false and leave "sources" empty - never '
        "invent a source to satisfy the shape."),
}


def _web_search_tool(max_uses: int) -> list[dict]:
    """Anthropic's hosted search tool config. Only meaningful for the
    anthropic adapter - see the module docstring on the openai path."""
    return [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}]


def _extract_observed_urls(content_blocks: list) -> set[str]:
    """Real URLs a web_search_tool_result block actually returned this turn -
    as opposed to a URL the model's own JSON merely claims. Tolerant of the
    exact block/field shape being wrong: an unrecognised or malformed block
    contributes nothing rather than raising, since a parsing miss here should
    fail toward "found no verified sources", not toward a crash that drops
    an otherwise-successful research call.
    """
    urls = set()
    for block in content_blocks or []:
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        content = block.get("content")
        items = content if isinstance(content, list) else [content]
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                urls.add(item["url"])
    return urls

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class DomainResult:
    """One domain's outcome for one research call to run_domain_research.
    disposition is None exactly when failed is True - a failure means no row
    was written, not that a row was written with a placeholder disposition."""

    __slots__ = ("domain_no", "domain_name", "agent_id", "disposition",
                 "reason", "agent_run_id", "queries_used", "captures_used",
                 "verified_sources", "failed", "failure_detail", "budget_note")

    def __init__(self, domain_no: int, domain_name: str, agent_id: str | None):
        self.domain_no = domain_no
        self.domain_name = domain_name
        self.agent_id = agent_id
        self.disposition: str | None = None
        self.reason: str | None = None
        self.agent_run_id: str | None = None
        self.queries_used = 0
        self.captures_used = 0
        self.verified_sources: list[dict] = []
        self.failed = False
        self.failure_detail: str | None = None
        # Which budget ran out, when one did. "BUDGET_EXHAUSTED" alone does not
        # say whether the limit was time, captures for this domain, or captures
        # for the run - three different remedies.
        self.budget_note: str | None = None

    def as_dict(self) -> dict:
        return {"domain_no": self.domain_no, "domain_name": self.domain_name,
                "agent_id": self.agent_id, "disposition": self.disposition,
                "reason": self.reason, "agent_run_id": self.agent_run_id,
                "queries_used": self.queries_used,
                "captures_used": self.captures_used,
                "verified_source_count": len(self.verified_sources),
                "failed": self.failed, "failure_detail": self.failure_detail,
                "budget_note": self.budget_note}


class SourceUnreachable(RuntimeError):
    """The fetch failed at the transport layer, so nothing was learned about
    the source itself.

    Distinct from "fetched and it was a 404". A 404 is evidence: that URL does
    not resolve, and a source that does not resolve counts for nothing. A
    connection that never completed is not evidence of anything - it says the
    container could not reach the internet, which is a statement about this
    deployment and not about the claim being researched.
    """


def _fetch_source_fragment(url: str, timeout: float = 10.0) -> dict | None:
    """Independently resolves a source the model named.

    Returns None when the source resolved but did not stand up - a non-200, an
    empty body, a URL that is not http(s). Raises SourceUnreachable when the
    request never completed, because those two must not be conflated: see the
    class docstring, and _research_one_domain for what the difference changes.

    Deliberately not the *pinned* transport in llm/providers/_transport.py:
    that pin is scoped to specific LLM provider hosts and has no reason to
    extend to arbitrary third-party URLs a model happens to cite. It does use
    that module's outbound_client, so the egress proxy and trust anchor a
    deployment configures apply here too - a bare httpx.get meant that on a
    proxied network LLM_EGRESS_PROXY fixed provider calls and left every
    source fetch timing out.

    The fragment is a naive tag-strip, not real content extraction - no HTML
    parser is a dependency here. Good enough to show a human what was found;
    not a substitute for reading the page.
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    try:
        with _transport.outbound_client(timeout) as c:
            resp = c.get(url, headers={"User-Agent": "network-workbench-research/1.0"})
    except httpx.HTTPError as exc:
        log.info("source fetch could not complete for %s: %s", url, exc)
        raise SourceUnreachable(f"{type(exc).__name__}: {exc}") from exc
    if resp.status_code != 200:
        return None
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", resp.text[:20_000])).strip()
    if not text:
        return None
    return {"url": url, "status_code": resp.status_code, "fragment": text[:600]}


def _verify_sources(claimed: list[dict],
                    captures_remaining: int) -> tuple[list[dict], int, int, str | None]:
    """Fetches up to captures_remaining of the model's claimed sources.

    Returns (verified, captures_used, unreachable, first_unreachable_detail).
    captures_used counts fetch *attempts*, successful or not, since a failed
    fetch still spends gateway effort. `unreachable` counts only the attempts
    that never completed a request - the caller needs that separately, because
    a domain where nothing was reachable has not been researched at all.
    """
    verified, used, unreachable, detail = [], 0, 0, None
    for source in claimed:
        if used >= captures_remaining:
            break
        used += 1
        try:
            fetched = _fetch_source_fragment(source.get("url", ""))
        except SourceUnreachable as exc:
            unreachable += 1
            detail = detail or str(exc)
            continue
        if fetched is not None:
            verified.append({**source, **fetched})
    return verified, used, unreachable, detail


# Legal-form suffixes and generic scope words: dropped because they carry no
# brand identity, not because of their length. Anything else survives the
# filter regardless of how short it is, so "DHL" or "3M" is not discarded the
# way a length-only floor discarded it.
_NOISE_TOKENS = {
    "gmbh", "inc", "incorporated", "corp", "corporation", "ltd", "limited",
    "llc", "llp", "plc", "co", "company", "group", "holding", "holdings",
    "international", "global", "worldwide", "the", "and", "of",
}


def _content_tokens(text: str) -> set:
    return {t for t in re.split(r"\W+", text) if t and t not in _NOISE_TOKENS}


def _looks_out_of_perimeter(subject: str, case_row) -> bool:
    """A heuristic, not a match. Flags a finding whose stated subject shares no
    recognisable token with the confirmed entity's name, so an obviously
    wrong-entity result does not get filed as evidence for this case. It will
    both under- and over-flag on legal-name variants, trading names and
    subsidiaries - a real perimeter check belongs with entity_resolution.py's
    candidate data, not a string comparison, and this is a placeholder for
    that, not a replacement.

    A short brand name is the single most likely word to appear in *every*
    public reference to a company - "DHL", "IBM", "3M" - and a >3-char length
    floor threw exactly those out: a legal name like "DHL International GmbH"
    kept only "international"/"gmbh", while a public source calling it "DHL
    Group" or "Deutsche Post DHL Group" kept "group"/"deutsche"/"post" - two
    token sets sharing nothing despite both plainly describing the same
    company. Genuinely uninformative words (legal-form suffixes and scope
    words that attach to almost any entity) are now dropped by name instead
    of by length, so a real brand token survives the filter on both sides
    regardless of how short it is.
    """
    name = (case_row.subject_entity_legal_name or "").lower()
    if not name or not subject:
        return False
    name_tokens = _content_tokens(name)
    subject_tokens = _content_tokens(subject.lower())
    if not name_tokens:
        return False
    if not name_tokens.isdisjoint(subject_tokens):
        return False
    # A brand abbreviation sometimes shows up fused with another word rather
    # than as its own token - "DPDHL" for "Deutsche Post DHL" - so a name
    # token appearing as a substring of a subject token (or vice versa) also
    # counts as a match, provided it is not so short a fragment that almost
    # anything would contain it.
    for nt in name_tokens:
        if len(nt) < 3:
            continue
        for st in subject_tokens:
            if len(st) < 3:
                continue
            if nt in st or st in nt:
                return False
    return True


def _build_prompt(domain_name: str, case_row) -> str:
    """Returns the user-turn prompt; system comes from AGENT_SYSTEM_PROMPTS,
    provider is chosen by the caller. Case-derived values are fenced (spec
    7.3) - an entity name is ultimately caller-supplied at intake, and
    treating it as untrusted content here is the conservative default."""
    entity = gateway.fence("subject_entity_legal_name",
                           case_row.subject_entity_legal_name or "")
    country = gateway.fence("country_of_domicile", case_row.country_of_domicile or "")
    domain = gateway.fence("input_domain", domain_name)
    return (f"Research this input domain for the named entity.\n{entity}\n{country}\n"
            f"{domain}\nRespond with the JSON object only.")


def _existing_domain_nos(session, case_id: str) -> set[int]:
    rows = session.execute(
        select(db.domain_disposition.c.domain_no)
        .where(db.domain_disposition.c.case_id == case_id)).all()
    return {r.domain_no for r in rows}


def _client_confirmed_domain_nos(session, case_id: str) -> set[int]:
    """Domains holding first-party client data.

    Protected from overwrite even when overwrite=True, and the symmetry is the
    argument: questionnaire.map_answers refuses to let a client answer silently
    replace public evidence, because two independent sources disagreeing is
    information. The reverse is the same situation. A research run finding a
    public source that contradicts what the client said about their own estate
    is a finding to adjudicate, not a reason to discard the client's answer and
    the named person who recorded it.

    Re-dispositioning one of these is still possible - manually via
    PUT .../domain-dispositions, which reports the provenance it drops - but it
    cannot happen as a side effect of re-running research.
    """
    rows = session.execute(
        select(db.domain_disposition.c.domain_no).where(
            db.domain_disposition.c.case_id == case_id,
            db.domain_disposition.c.disposition == "CLIENT_CONFIRMED")).all()
    return {r.domain_no for r in rows}


def _upsert_disposition(session, *, case_id: str, domain_no: int, domain_name: str,
                        disposition: str, reason: str | None,
                        agent_run_id: str | None, evidence: dict | None) -> None:
    """Writes exactly one domain's row without touching the other 23.

    domain_disposition carries no unique constraint on (case_id, domain_no) -
    it was designed for PUT .../domain-dispositions, which deletes and
    re-inserts the whole case at once. Upsert is therefore done at the
    application level: look up the row, update it if present, insert if not.
    Two concurrent research runs for the same case and domain could still
    race here; this tranche does not add locking for that, since the existing
    manual endpoint has the same property and nothing in this build serialises
    writes to this table.
    """
    existing = session.execute(
        select(db.domain_disposition.c.id)
        .where(db.domain_disposition.c.case_id == case_id,
               db.domain_disposition.c.domain_no == domain_no)).first()
    values = {"disposition": disposition, "reason": reason,
              "agent_run_id": agent_run_id, "evidence": evidence}
    if existing:
        session.execute(update(db.domain_disposition)
                        .where(db.domain_disposition.c.id == existing.id)
                        .values(**values))
    else:
        session.execute(insert(db.domain_disposition).values(
            id=str(uuid.uuid4()), case_id=case_id, estimate_snapshot_id=None,
            domain_no=domain_no, domain_name=domain_name, **values))
    session.commit()


def _research_one_domain(session, *, case_row, domain_no: int, domain_name: str,
                         agent_id: str, provider: str,
                         research_policy: ResearchPolicy,
                         captures_remaining_in_run: int,
                         request_scope: str) -> DomainResult:
    result = DomainResult(domain_no, domain_name, agent_id)
    captures_left_for_domain = research_policy.max_captures_per_domain
    domain_start = datetime.now(timezone.utc)

    for attempt in range(1, research_policy.max_queries_per_domain + 1):
        # Time first. The query and capture caps bound *effort*, not duration,
        # and with a provider call now carrying a hosted web search a domain
        # could sit inside its caps for many minutes - long enough for the
        # interface to give up on the request and report an outage on a run
        # that was working. The run-level clock in run_domain_research cannot
        # help: it is checked between domains, and a domain researched alone
        # never reaches that check.
        elapsed = (datetime.now(timezone.utc) - domain_start).total_seconds()
        if attempt > 1 and elapsed >= research_policy.max_seconds_per_domain:
            result.disposition, result.reason = "DECLARED_UNKNOWN", "BUDGET_EXHAUSTED"
            result.budget_note = (
                f"stopped after {elapsed:.0f}s ({attempt - 1} attempt(s)) - "
                f"max_seconds_per_domain is "
                f"{research_policy.max_seconds_per_domain}s")
            return result
        if captures_remaining_in_run - result.captures_used <= 0:
            result.disposition, result.reason = "DECLARED_UNKNOWN", "BUDGET_EXHAUSTED"
            result.budget_note = "run-level capture budget exhausted"
            return result
        if captures_left_for_domain <= 0:
            result.disposition, result.reason = "DECLARED_UNKNOWN", "BUDGET_EXHAUSTED"
            result.budget_note = (
                f"per-domain capture budget exhausted "
                f"({research_policy.max_captures_per_domain} captures)")
            return result

        result.queries_used = attempt
        # Scoped to this invocation, not to the case. A key stable across
        # separate calls means create_agent_run returns the *previous*
        # (SUCCEEDED or FAILED) run and execute() then refuses it as
        # "a completed run cannot be re-executed" - so overwrite=True could
        # never actually re-research anything. Found in Tranche 3; the same
        # defect existed here and in savings_advisory.py.
        idem_key = f"research:{request_scope}:{domain_no}:{attempt}"
        run_id = None
        try:
            run_id = gateway.create_agent_run(
                session, agent_id=agent_id, mode="LIVE", case_id=case_row.case_id,
                idempotency_key=idem_key)
            prompt = _build_prompt(domain_name, case_row)
            # Only the anthropic adapter has a hosted search tool to hand it
            # (see module docstring); passing tools to openai raises rather
            # than silently completing without one.
            tools = (_web_search_tool(research_policy.max_web_searches_per_domain)
                    if provider == "anthropic" else None)
            call = gateway.execute(
                session, agent_run_id=run_id, provider=provider,
                system=AGENT_SYSTEM_PROMPTS[agent_id], prompt=prompt, tools=tools)
            parsed = gateway.parse_json_strict(call["text"])
            observed_urls = _extract_observed_urls(call.get("content_blocks"))
        except (errors.ProviderUnavailable, errors.LivenessProofFailed,
                errors.StructuredOutputInvalid, errors.ModeNotPermitted) as exc:
            # execute() already calls _fail() internally for ProviderUnavailable/
            # LivenessProofFailed before re-raising. StructuredOutputInvalid from
            # parse_json_strict() below it does not - that call is pure and has
            # no session to fail anything with. Calling gateway.fail() here
            # unconditionally is safe either way: re-marking an already-FAILED
            # row FAILED is a no-op, not a second error.
            if run_id is not None:
                gateway.fail(session, run_id, f"{type(exc).__name__}: {exc}")
            result.failed = True
            result.failure_detail = f"{type(exc).__name__}: {exc}"
            result.agent_run_id = run_id
            return result

        if not isinstance(parsed, dict) or "found" not in parsed:
            # A shape violation ends this call rather than retrying within it -
            # treated the same as StructuredOutputInvalid above, not silently
            # retried, so `failed` never lingers on a result that later
            # succeeds (disposition is None exactly when failed is True).
            # gateway.fail() terminates the row as FAILED - found after
            # Tranche 1 shipped: without it, an otherwise-successful LIVE call
            # whose content this branch rejects left agent_run sitting in
            # QUEUED forever, since execute()'s own failure handling only
            # covers failures execute() itself detects, not a caller's
            # post-hoc shape check.
            gateway.fail(session, run_id,
                        "model output was valid JSON but not the agreed shape")
            result.failed = True
            result.failure_detail = "model output was valid JSON but not the agreed shape"
            result.agent_run_id = run_id
            return result

        if not parsed.get("found"):
            gateway.succeed(session, run_id, {"found": False})
            result.agent_run_id = run_id
            continue        # genuinely searched this attempt, found nothing - keep trying

        subject = str(parsed.get("subject", ""))
        if _looks_out_of_perimeter(subject, case_row):
            gateway.succeed(session, run_id,
                            {"found": True, "quarantined": "OUT_OF_PERIMETER"})
            result.agent_run_id = run_id
            result.disposition, result.reason = "DECLARED_UNKNOWN", "OUT_OF_PERIMETER"
            return result

        claimed_sources = [s for s in (parsed.get("sources") or [])
                           if isinstance(s, dict) and s.get("url")]
        claimed_count = len(claimed_sources)
        dropped_unobserved = 0
        if tools:
            # A real search happened this turn (anthropic path only - see
            # module docstring). A URL the model names that the search tool
            # never actually returned is dropped here, before it ever reaches
            # the independent httpx refetch below - "found: true" with search
            # available is not licence to recall a source from memory.
            kept = [s for s in claimed_sources if s["url"] in observed_urls]
            dropped_unobserved = len(claimed_sources) - len(kept)
            claimed_sources = kept
        budget_left = min(captures_left_for_domain,
                          captures_remaining_in_run - result.captures_used)
        verified, used, unreachable, unreachable_detail = _verify_sources(
            claimed_sources, budget_left)
        result.captures_used += used
        captures_left_for_domain -= used

        if used and unreachable == used:
            # Every fetch attempted this turn failed to complete a request.
            # That is not a statement about the sources - it is a statement
            # about this container's egress, and the module contract is that
            # an operational failure gets no disposition rather than being
            # written up as a completed search. Without this the domain
            # burned its capture budget on unreachable URLs, retried until
            # exhausted, and reported BUDGET_EXHAUSTED - which reads as "we
            # searched hard and ran out of budget" when nothing was ever
            # reached. The run-level budget then drained the same way and
            # later domains were marked BUDGET_EXHAUSTED without being
            # attempted at all, so one network fault presented as an
            # exhaustive-but-fruitless search across the whole contract.
            gateway.succeed(session, run_id, {
                "found": True, "subject": subject,
                "sources_unreachable": unreachable,
                "note": "no claimed source could be fetched from this container"})
            result.agent_run_id = run_id
            result.failed = True
            result.failure_detail = (
                f"none of the {unreachable} claimed source(s) could be fetched: "
                f"{unreachable_detail}. This is an egress failure, not a research "
                f"outcome - the domain is left undisposed for a retry. Check that "
                f"the container can reach the public internet (see "
                f"`docker compose exec api python tools/tls_doctor.py`).")
            return result

        gateway.succeed(session, run_id, {
            "found": True, "subject": subject, "finding": parsed.get("finding"),
            # The count the model actually claimed, before the observed-URL
            # filter - reporting the post-filter count here would make a run
            # that cited two unobserved sources look like it cited none.
            "claimed_sources": claimed_count,
            "verified_sources": len(verified),
            "sources_unreachable": unreachable,
            "dropped_unobserved_sources": dropped_unobserved})
        result.agent_run_id = run_id

        if len(verified) >= research_policy.min_independent_sources_material_fact:
            result.disposition = "EVIDENCED_PUBLIC"
            result.reason = None
            result.verified_sources = verified
            return result
        # Found a claim but could not independently verify enough of it -
        # try again if budget allows; a claim without enough verification is
        # not written as evidence of anything.

    result.disposition, result.reason = "DECLARED_UNKNOWN", "NO_PUBLIC_EVIDENCE"
    return result


def run_domain_research(session, *, case_id: str, agent_ids: list[str] | None = None,
                        provider: str = "anthropic",
                        research_policy: ResearchPolicy,
                        overwrite: bool = False,
                        domain_nos: list[int] | None = None,
                        idempotency_key: str | None = None) -> dict:
    """Runs the research phase for whichever DOMAIN_AGENT_MAP domains are
    assigned to agent_ids (default: LLM-01 and LLM-08 both) and either have no
    existing disposition or overwrite=True was passed. Never raises for an
    individual domain's outcome - those are reported per-domain in the
    return value, so one bad call does not take the others down with it.

    Raises LookupError if the case does not exist, PermissionError if the
    entity has not been resolved and confirmed (0.1A), and ValueError for an
    agent_id this module does not know how to run.
    """
    agent_ids = agent_ids or ["LLM-01", "LLM-08"]
    for a in agent_ids:
        if a not in registry.AGENTS:
            raise ValueError(f"{a!r} is not a registered agent")
        if a not in AGENT_SYSTEM_PROMPTS:
            raise ValueError(
                f"{a!r} is registered but this module has no prompt for it "
                f"(only LLM-01 and LLM-08 are wired)")

    case_row = session.execute(
        select(db.case).where(db.case.c.case_id == case_id)).one_or_none()
    if case_row is None:
        raise LookupError(f"no such case: {case_id}")
    if not case_row.resolved_entity_id or not case_row.entity_confirmed_by:
        raise PermissionError(
            "the subject entity must be resolved and confirmed before "
            "research runs (0.1A: resolve the entity before researching it)")

    already = set() if overwrite else _existing_domain_nos(session, case_id)
    # Protected regardless of overwrite - see _client_confirmed_domain_nos.
    protected = _client_confirmed_domain_nos(session, case_id)
    skipped = already | protected
    # domain_nos narrows the run to a subset. Researching 17 domains in one
    # request takes minutes - each domain is a LIVE provider call plus source
    # fetches - which exceeds any sane HTTP timeout, so the interface walks the
    # list a domain at a time and shows progress. Nothing about the semantics
    # changes: a domain already carrying a disposition is still skipped, so a
    # walk that stops halfway resumes rather than restarts.
    wanted = set(domain_nos) if domain_nos else None
    targets = [(no, name) for no, name in dispositions.DOMAINS
              if DOMAIN_AGENT_MAP.get(no) in agent_ids and no not in skipped
              and (wanted is None or no in wanted)]

    # One idempotency scope per invocation unless the caller supplies one -
    # the same pattern EstimateIn already uses. A caller who wants
    # double-submit protection passes a key; a caller deliberately re-running
    # gets fresh runs rather than a refusal.
    request_scope = idempotency_key or str(uuid.uuid4())

    results: list[DomainResult] = []
    captures_this_run = 0
    run_start = datetime.now(timezone.utc)

    for domain_no, domain_name in targets:
        agent_id = DOMAIN_AGENT_MAP[domain_no]
        elapsed_minutes = (datetime.now(timezone.utc) - run_start).total_seconds() / 60
        remaining_captures = research_policy.max_captures_per_run - captures_this_run

        if elapsed_minutes >= research_policy.research_wall_clock_budget_minutes \
                or remaining_captures <= 0:
            result = DomainResult(domain_no, domain_name, agent_id)
            result.disposition, result.reason = "DECLARED_UNKNOWN", "BUDGET_EXHAUSTED"
            _upsert_disposition(session, case_id=case_id, domain_no=domain_no,
                               domain_name=domain_name, disposition=result.disposition,
                               reason=result.reason, agent_run_id=None, evidence=None)
            results.append(result)
            continue

        result = _research_one_domain(
            session, case_row=case_row, domain_no=domain_no, domain_name=domain_name,
            agent_id=agent_id, provider=provider, research_policy=research_policy,
            captures_remaining_in_run=remaining_captures,
            request_scope=request_scope)
        captures_this_run += result.captures_used
        results.append(result)

        if not result.failed:
            evidence = None
            if result.verified_sources:
                evidence = {"sources": result.verified_sources,
                           "queries_used": result.queries_used,
                           "captures_used": result.captures_used}
            elif result.budget_note:
                # Which limit stopped this, stored beside the disposition.
                # BUDGET_EXHAUSTED on its own sent an analyst looking for a
                # bigger budget when the real answer was often a slow network.
                evidence = {"budget_note": result.budget_note,
                           "queries_used": result.queries_used,
                           "captures_used": result.captures_used}
            _upsert_disposition(session, case_id=case_id, domain_no=domain_no,
                               domain_name=domain_name, disposition=result.disposition,
                               reason=result.reason, agent_run_id=result.agent_run_id,
                               evidence=evidence)

    current = [dict(r._mapping) for r in session.execute(
        select(db.domain_disposition).where(
            db.domain_disposition.c.case_id == case_id)).all()]

    return {
        "case_id": case_id,
        "agent_ids": agent_ids,
        "domains_in_scope_for_these_agents": len(
            [1 for no, _ in dispositions.DOMAINS if DOMAIN_AGENT_MAP.get(no) in agent_ids]),
        "domains_attempted": len(targets),
        "domains_skipped_already_disposed": len(
            [1 for no, _ in dispositions.DOMAINS
             if DOMAIN_AGENT_MAP.get(no) in agent_ids and no in already]),
        # Reported, never silent: a caller who passed overwrite=True and got
        # fewer domains than expected needs to see why.
        "domains_protected_client_confirmed": sorted(
            no for no, _ in dispositions.DOMAINS
            if DOMAIN_AGENT_MAP.get(no) in agent_ids and no in protected),
        "results": [r.as_dict() for r in results],
        "resolved": sum(1 for r in results if r.disposition == "EVIDENCED_PUBLIC"),
        "declared_unknown": sum(1 for r in results if r.disposition == "DECLARED_UNKNOWN"),
        "failed": sum(1 for r in results if r.failed),
        "captures_used_this_run": captures_this_run,
        "publication_blockers": dispositions.validate(current),
        "summary": dispositions.summarise(current),
    }
