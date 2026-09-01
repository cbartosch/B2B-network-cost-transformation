"""Shared LLM gateway - where the anti-fake controls are enforced.

Properties this module guarantees:

  1. Environment is server-resolved. A caller cannot assert it.
  2. A mode without a registered executor is rejected *before* an agent_run row
     exists, so no orphan run can accumulate. MOCK in PRODUCTION is additionally
     rejected with a durable rejection record (7.2C).
  3. A LIVE call goes to a real provider over a pinned transport. If no provider
     is configured, or the provider errors, the run FAILS. No code path here
     returns model-shaped text that a provider did not produce.
  4. The liveness proof is built from provider-issued evidence: a body response
     identifier, a transport request identifier, a timestamp the provider
     reported, and token counts it billed. The provider timestamp is compared
     against our own clock and the *skew* is bounded.

     That check is deliberately not described as independent proof. An
     interceptor returns `Date: <now>` and passes it, so on its own it
     establishes consistency, not liveness. Independence comes from the TLS pin
     in providers/_transport.py, which survives a subverted trust store. Each
     run records which controls were actually in force, so a call made over an
     unpinned connection is not presented as equally proven.
  5. Response-id uniqueness is a database constraint.
  6. No automatic mode downgrade, and no mode change after creation.
  7. Idempotency keys are enforced: a repeat submission returns the original run
     rather than creating a duplicate and duplicate provider spend.
"""
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from pydantic import ValidationError

from .. import config, db
from . import errors, prompts, quality, registry
from .providers import _transport
from .providers.anthropic_adapter import AnthropicAdapter
from .providers.openai_adapter import OpenAIAdapter

log = logging.getLogger("workbench.gateway")

# Maximum tolerated difference between the provider's reported time and ours.
MAX_CLOCK_SKEW = timedelta(seconds=config.MAX_CLOCK_SKEW_SECONDS)


def _adapters():
    a, o = config.PROVIDERS["anthropic"], config.PROVIDERS["openai"]
    return {"anthropic": AnthropicAdapter(a["api_key"], a["model"]),
            "openai": OpenAIAdapter(o["api_key"], o["model"])}


def available_providers() -> dict:
    return {n: ad.configured() for n, ad in _adapters().items()}


def provider_tiers() -> dict:
    return {n: ad.reconciliation_tier for n, ad in _adapters().items()}


def transport_status() -> dict:
    return _transport.pin_status()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assert_mode_permitted(agent_id: str, mode: str) -> None:
    if mode not in registry.DECLARED_MODES:
        raise errors.ModeNotPermitted(f"unknown execution mode {mode!r}")
    agent = registry.AGENTS.get(agent_id)
    if agent is None:
        raise errors.ModeNotPermitted(f"unregistered agent {agent_id!r}")
    if mode not in agent["permitted_execution_modes"]:
        raise errors.ModeNotPermitted(
            f"{agent_id} does not permit {mode}; permitted: "
            f"{agent['permitted_execution_modes']}")
    if mode not in registry.IMPLEMENTED_MODES:
        raise errors.ModeNotPermitted(
            f"{mode} has no registered executor in this build; "
            f"implemented modes: {registry.IMPLEMENTED_MODES}")
    if mode == "DETERMINISTIC_ONLY" and not agent["deterministic_fallback_endpoint"]:
        raise errors.ModeNotPermitted(
            f"{agent_id} has no registered deterministic_fallback_endpoint")


def create_agent_run(session, *, agent_id: str, mode: str, case_id: str | None,
                     idempotency_key: str | None = None) -> str:
    env = config.environment()                      # server-side, never from caller

    # MOCK in production is refused with a durable record, even though this build
    # has no MOCK executor at all - the record is the spec 7.2C control and must
    # exist independently of whether the mode happens to be implemented.
    if mode == "MOCK" and env == "PRODUCTION":
        session.execute(insert(db.rejected_run).values(
            id=str(uuid.uuid4()), agent_id=agent_id, execution_mode=mode,
            environment=env,
            reason="MOCK rejected at run creation in PRODUCTION (spec 7.2C)"))
        session.commit()
        raise errors.ModeNotPermitted(
            "MOCK execution is not permitted in a PRODUCTION environment")

    # Rejected before any row is written, so an unimplemented mode cannot leave
    # an orphan behind.
    _assert_mode_permitted(agent_id, mode)

    if idempotency_key:
        existing = session.execute(
            select(db.agent_run.c.agent_run_id)
            .where(db.agent_run.c.idempotency_key == idempotency_key)).first()
        if existing:
            return existing.agent_run_id

    run_id = str(uuid.uuid4())
    try:
        session.execute(insert(db.agent_run).values(
            agent_run_id=run_id, case_id=case_id, agent_id=agent_id,
            graph_version=registry.AGENTS[agent_id]["graph_version"],
            execution_mode=mode, environment=env, status="QUEUED",
            idempotency_key=idempotency_key,
            started_at=datetime.now(timezone.utc)))
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.execute(
            select(db.agent_run.c.agent_run_id)
            .where(db.agent_run.c.idempotency_key == idempotency_key)).first()
        if existing:
            return existing.agent_run_id
        raise
    return run_id


def verify_liveness(call, local_start: datetime, local_end: datetime) -> None:
    """Every element below is issued by the provider. None of it is written by
    this process, which is what distinguishes this from the earlier tautological
    check against our own clock."""
    if not call.provider_response_id:
        raise errors.LivenessProofFailed("provider returned no response identifier")
    if call.input_tokens <= 0 or call.output_tokens <= 0:
        raise errors.LivenessProofFailed(
            f"provider reported zero token usage "
            f"(in={call.input_tokens}, out={call.output_tokens})")
    if call.provider_request_at is None:
        raise errors.LivenessProofFailed("provider reported no request timestamp")
    if config.REQUIRE_PROVIDER_REQUEST_ID and not call.provider_request_id:
        raise errors.LivenessProofFailed(
            "REQUIRE_PROVIDER_REQUEST_ID is set and the response carried no "
            "provider request identifier, so this call could not be confirmed "
            "with the provider afterwards")

    # Compare the provider's clock to ours. A forged response must now also
    # forge a plausible provider clock, and cannot simply echo local time.
    skew = abs(call.provider_request_at - call.local_request_at)
    if skew > MAX_CLOCK_SKEW:
        raise errors.LivenessProofFailed(
            f"provider timestamp differs from local time by {skew.total_seconds():.0f}s, "
            f"beyond the {MAX_CLOCK_SKEW.total_seconds():.0f}s bound")
    if not (local_start - MAX_CLOCK_SKEW <= call.provider_request_at
            <= local_end + MAX_CLOCK_SKEW):
        raise errors.LivenessProofFailed(
            "provider timestamp falls outside the run window")


def execute(session, *, agent_run_id: str, provider: str, system: str,
            prompt: str, max_tokens: int = 1500,
            tools: list[dict] | None = None,
            definition=None, schema_name: str | None = None,
            supplied_source_ids: list | None = None) -> dict:
    row = session.execute(
        select(db.agent_run).where(db.agent_run.c.agent_run_id == agent_run_id)).one()
    if row.execution_mode != "LIVE":
        raise errors.ModeNotPermitted(
            f"gateway.execute handles LIVE only; run is {row.execution_mode}")
    if row.status not in ("QUEUED", "RUNNING"):
        raise errors.ModeNotPermitted(
            f"run is {row.status}; a completed run cannot be re-executed")

    adapter = _adapters().get(provider)
    if adapter is None or not adapter.configured():
        _fail(session, agent_run_id, f"provider {provider!r} is not configured")
        raise errors.ProviderUnavailable(
            f"provider {provider!r} is not configured; LIVE run fails closed")

    local_start = datetime.now(timezone.utc)
    try:
        if definition is not None and schema_name:
            # Schema-enforced channel. The adapter must return an object
            # conforming to the registered model or raise; there is no prose
            # fallback, because accepting a plausible prose answer is the
            # failure this path replaces.
            call = adapter.parse(system=system, prompt=prompt,
                                 schema=definition.output_model.model_json_schema(),
                                 schema_name=schema_name, max_tokens=max_tokens,
                                 tools=tools)
        else:
            call = adapter.complete(system=system, prompt=prompt,
                                    max_tokens=max_tokens, tools=tools)
    except (_transport.PinMismatch, _transport.PinUnavailable) as exc:
        # A pin failure is a provenance failure, not a transport hiccup: the
        # answer may be genuine, but nothing here can show that it is.
        _fail(session, agent_run_id, f"TLS pin check failed: {exc}")
        raise errors.LivenessProofFailed(str(exc)) from exc
    except (errors.ProviderUnavailable, errors.LivenessProofFailed) as exc:
        _fail(session, agent_run_id, str(exc))
        raise
    local_end = datetime.now(timezone.utc)

    try:
        verify_liveness(call, local_start, local_end)
    except errors.LivenessProofFailed as exc:
        _fail(session, agent_run_id, f"liveness proof failed: {exc}")
        raise

    try:
        llm_run_id = str(uuid.uuid4())
        session.execute(insert(db.llm_run).values(
            llm_run_id=llm_run_id, agent_run_id=agent_run_id,
            provider=call.provider, model=call.model,
            request_hash=_sha(system + prompt), response_hash=_sha(call.text),
            provider_response_id=call.provider_response_id,
            provider_request_id=call.provider_request_id,
            provider_request_at=call.provider_request_at,
            local_request_at=call.local_request_at,
            clock_skew_seconds=call.clock_skew_seconds,
            egress_proxy=call.egress_proxy, http_status=call.http_status,
            tls_pin=call.tls_pin, provenance_strength=call.provenance_strength,
            tls_cert_not_after=call.tls_cert_not_after,
            externally_verifiable=bool(call.provider_request_id),
            input_tokens=call.input_tokens, output_tokens=call.output_tokens,
            latency_ms=call.latency_ms, policy_version="policy-1.0.0",
            # Registered-call identity. Null for a call made outside the
            # registry, which is the truth about it rather than a gap.
            prompt_id=getattr(definition, "prompt_id", None),
            prompt_version=getattr(definition, "prompt_version", None),
            prompt_hash=getattr(definition, "prompt_hash", None),
            output_schema_version=getattr(definition, "output_schema_version", None),
            tool_policy_version=getattr(definition, "tool_policy_version", None),
            parsed_output=call.parsed,
            supplied_source_ids=list(supplied_source_ids or []) or None))
        session.commit()
    except IntegrityError:
        session.rollback()
        _fail(session, agent_run_id,
              "a provider identifier on this call is already recorded against "
              "another run - a stored response was presented as a fresh LIVE call")
        raise errors.LivenessProofFailed(
            "duplicate provider_response_id or provider_request_id")

    return {"text": call.text, "provider": call.provider, "model": call.model,
            "parsed": call.parsed, "llm_run_id": llm_run_id,
            # Returned so the quality gate can write its verdict onto the
            # exact call it judged. Without it _record_quality silently did
            # nothing and every verdict was lost.
            "llm_run_id": llm_run_id,
            # The block list a caller needs to find real tool-result content
            # (e.g. web_search_tool_result) rather than the model's prose
            # about it. Empty when no tools were requested or the provider
            # doesn't surface one (raw.get is defensive against either).
            "content_blocks": call.raw.get("content", []),
            # "max_tokens" here means the provider cut the reply off. A caller
            # parsing structured output needs to tell that apart from a model
            # that answered badly: the remedy is a bigger budget, not a better
            # prompt, and "not valid JSON" points at the wrong one.
            "stop_reason": call.raw.get("stop_reason"),
            "provider_response_id": call.provider_response_id,
            "provider_request_id": call.provider_request_id,
            "externally_verifiable": bool(call.provider_request_id),
            "provider_request_at": call.provider_request_at.isoformat(),
            "clock_skew_seconds": round(call.clock_skew_seconds, 3),
            "egress_proxy": call.egress_proxy,
            "tls_pin": call.tls_pin,
            "tls_cert_expiry": _transport.expiry_warning(call.tls_cert_not_after),
            "provenance_strength": call.provenance_strength,
            "input_tokens": call.input_tokens, "output_tokens": call.output_tokens,
            "latency_ms": call.latency_ms}


# A cut or timed-out connection may succeed on the next attempt. A refusal, an
# auth failure or an unsupported request will not, and retrying it wastes the
# operator's time while hiding the real cause.
_TRANSIENT = ("UNEXPECTED_EOF", "EOF occurred", "reset by peer", "timed out",
              "timeout", "Connection aborted", "Server disconnected",
              "Temporary failure", "502", "503", "504", "529")


def _is_transient(exc: Exception) -> bool:
    text = str(exc)
    if any(bad in text for bad in ("API_KEY", "authentication", "401", "403")):
        return False
    return any(hint.lower() in text.lower() for hint in _TRANSIENT)


def structured_call(session, *, agent_run_id: str, prompt_id: str,
                    prompt: str, provider: str = "anthropic",
                    max_tokens: int = 4000, tools: list[dict] | None = None,
                    prompt_version: str | None = None,
                    supplied_source_ids: list | None = None,
                    gate_context: dict | None = None,
                    max_attempts: int = 3,
                    max_transport_retries: int = 2,
                    transport_backoff_seconds: int = 5):
    """The single entry point for a registered LLM service.

    Resolves the prompt from the registry, calls the provider through its
    schema-enforced channel, validates the reply against the registered output
    model, puts it through the registered quality gate, and records which
    prompt, schema and tool policy produced it - and whether it was accepted.

    Returns (typed_result, provenance).

    Schema validity says the reply has the right shape; it says nothing about
    whether the reply is usable. A result with found=true, no sources and no
    quantities validates perfectly and is worth nothing, so llm/quality.py
    judges every reply and each attempt's verdict is written to its own
    audit.llm_run row - a rejection is a measurable event, not an exception
    that disappears into a stack trace.

    A rejected attempt is retried with the guidance for its reason, up to a
    governed limit - but only when the reason is one a further attempt could
    fix. quality.TERMINAL marks the ones that cannot: a reply about the wrong
    company will still be about the wrong company next time, and retrying it
    spends money to arrive at the same place.

    Exhausting the attempts fails closed. No partial accept and no best-of: a
    reply that never passed the gate is not evidence of anything.
    """
    definition = prompts.get(prompt_id, prompt_version)
    # The most complete reply seen, kept so a rejection can hand it back.
    best_payload, best_result = None, None

    # A declared tool policy that the call site does not honour makes the
    # registry a description of intentions rather than a contract. Entity
    # resolution declared web_search and passed no tool, so it was recall-only
    # while advertising search - and a recalled answer is indistinguishable
    # from a searched one at the point it is read.
    if definition.tool_policy_version.startswith("web_search") and not tools:
        raise errors.ProviderUnavailable(
            f"{definition.prompt_id} declares tool policy "
            f"{definition.tool_policy_version} but was called without a search "
            f"tool. Answering from memory here would be a recall-only result "
            f"presented as a searched one; the call fails closed instead.")

    ctx = dict(gate_context or {})
    attempts, last = [], None
    body = prompt

    for attempt in range(1, max(1, max_attempts) + 1):
        # A cut connection is not a poor answer, and it escaped this loop
        # entirely: ProviderUnavailable propagated on the first failure, so a
        # firewall dropping one long-lived request out of seventeen cost that
        # domain its research after twenty seconds of work.
        #
        # Retried on its own budget, with a pause, and never at the expense of
        # the attempts reserved for judging what the model said. An auth
        # failure or a refused request is not retried: those do not improve by
        # asking again, and hiding them behind a retry is worse than failing.
        call = None
        for transport_try in range(max(1, max_transport_retries + 1)):
            try:
                call = execute(session, agent_run_id=agent_run_id,
                               provider=provider,
                               system=definition.system_template, prompt=body,
                               max_tokens=max_tokens, tools=tools,
                               definition=definition,
                               schema_name=definition.output_model.__name__,
                               supplied_source_ids=supplied_source_ids)
                break
            except errors.ProviderUnavailable as exc:
                if not _is_transient(exc) or transport_try >= max_transport_retries:
                    raise
                wait = transport_backoff_seconds * (transport_try + 1)
                log.warning("%s: connection cut (%s), retrying in %ds "
                            "[%d/%d]", definition.prompt_id, exc, wait,
                            transport_try + 1, max_transport_retries)
                time.sleep(wait)
        run_id = call.get("llm_run_id")
        ctx["stop_reason"] = call.get("stop_reason")
        ctx["content_blocks"] = call.get("content_blocks")

        payload = call.get("parsed")
        result = None
        if payload is None:
            verdict = quality.Verdict(
                False, [quality.Rejection.EMPTY_RESULT_WITHOUT_ABSTENTION],
                ["the provider returned no structured payload"])
        else:
            try:
                result = definition.output_model.model_validate(payload)
                verdict = quality.evaluate(definition.prompt_id, result, ctx)
            except ValidationError as exc:
                verdict = quality.Verdict(
                    False, [quality.Rejection.SCHEMA_INVALID],
                    [f"failed the registered schema "
                     f"{definition.output_schema_version}: {str(exc)[:300]}"])

        # A reply that validated against the schema is worth keeping even when
        # a gate refused it: schema-valid means readable, and the gates judge
        # sufficiency rather than legibility.
        if result is not None:
            best_payload, best_result = payload, result

        _record_verdict(session, run_id, verdict, attempt)
        attempts.append({"attempt": attempt, **verdict.as_dict()})
        last = verdict

        if verdict.accepted:
            return result, {
                "prompt_id": definition.prompt_id,
                "prompt_version": definition.prompt_version,
                "prompt_hash": definition.prompt_hash,
                "output_schema_version": definition.output_schema_version,
                "tool_policy_version": definition.tool_policy_version,
                "provider": call["provider"], "model": call["model"],
                "provider_response_id": call.get("provider_response_id"),
                "provider_request_id": call.get("provider_request_id"),
                "stop_reason": call.get("stop_reason"),
                # Cost and latency belong in provenance, not only in the audit
                # row. Callers displayed them from the old execute() return and
                # broke when structured_call replaced it - and a caller that
                # can see what a run cost is a caller who notices a retry loop
                # spending three times over.
                "input_tokens": call.get("input_tokens"),
                "output_tokens": call.get("output_tokens"),
                "latency_ms": call.get("latency_ms"),
                "content_blocks": call.get("content_blocks"),
                "attempts": attempts,
            }

        if not verdict.retryable:
            break

        # The guidance names the defect; the sentence after it repeats that
        # abstaining is allowed. Without that, "you cited no source" is
        # pressure to produce one, and inventing it is the cheapest way to
        # comply - a gate that raises the fabrication rate to raise its own
        # pass rate has made the system worse.
        body = (prompt + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED\n"
                + verdict.guidance()
                + " Do not invent anything to satisfy this: if the evidence is "
                  "genuinely not there, returning nothing with an abstention "
                  "reason is correct and will be accepted.")
        log.info("%s attempt %d rejected: %s", definition.prompt_id, attempt,
                 [r.value for r in verdict.reasons])

    reasons = [r.value for r in (last.reasons if last else [])]
    # The exception carries the best reply the run produced, so a caller can
    # keep what was found at a lower disposition rather than throwing it away.
    #
    # This mattered more than the rejection itself. A reply that cited two
    # sources when three were required, or one quantity that parsed and one
    # that did not, was discarded whole - so a domain that had genuinely found
    # something was recorded as having found nothing, and the provider call was
    # paid for and binned. Rejecting a reply as *sufficient* is not the same as
    # judging it *worthless*, and only the caller knows which it needs.
    error = errors.StructuredOutputInvalid(
        f"{definition.prompt_id} rejected after {len(attempts)} attempt(s)"
        + ("" if (last and last.retryable) else " (terminal, not retried)")
        + f": {reasons} {'; '.join(last.detail) if last else ''}")
    error.rejected_payload = best_payload
    error.rejected_result = best_result
    error.reasons = reasons
    error.attempts = attempts
    raise error


def _record_verdict(session, llm_run_id, verdict, attempt: int) -> None:
    """The verdict belongs on the row for the call it judged.

    reviewer_outcome arrived with the WP1 audit columns and was written by
    nothing, so an accepted call and a rejected one were indistinguishable
    afterwards. Best effort: failing to record a verdict must not fail a call
    that otherwise succeeded, but it is logged rather than swallowed.
    """
    if not llm_run_id:
        return
    outcome = ("ACCEPTED" if verdict.accepted else
               "REJECTED:" + ",".join(r.value for r in verdict.reasons))
    try:
        session.execute(update(db.llm_run)
                        .where(db.llm_run.c.llm_run_id == llm_run_id)
                        .values(reviewer_outcome=f"{outcome}@{attempt}"[:32]))
        session.commit()
    except Exception:                                     # noqa: BLE001
        session.rollback()
        log.warning("could not record gate verdict on llm_run %s", llm_run_id)


def execute_deterministic(session, *, agent_run_id: str, fn) -> dict:
    """Runs a registered deterministic_fallback_endpoint (Tranche 2: LLM-06,
    LLM-07). No provider call and no liveness proof to check - the guarantee
    here is different from execute()'s: the run's mode was DETERMINISTIC_ONLY
    from creation, never a downgrade from a failed LIVE attempt. That is
    enforced upstream (create_agent_run -> _assert_mode_permitted only
    permits a mode explicitly requested at creation, and mode cannot change
    after), not re-checked here - this function only refuses to run a mode
    other than the one already committed to the row.

    fn is the caller's already-resolved deterministic function - a plain
    Python callable, not something this module looks up. registry.py's
    deterministic_fallback_endpoint is documentary; the real dispatch is an
    ordinary import in the domain module that owns the logic.
    """
    row = session.execute(
        select(db.agent_run).where(db.agent_run.c.agent_run_id == agent_run_id)).one()
    if row.execution_mode != "DETERMINISTIC_ONLY":
        raise errors.ModeNotPermitted(
            f"gateway.execute_deterministic handles DETERMINISTIC_ONLY only; "
            f"run is {row.execution_mode}")
    if row.status not in ("QUEUED", "RUNNING"):
        raise errors.ModeNotPermitted(
            f"run is {row.status}; a completed run cannot be re-executed")
    try:
        return fn()
    except Exception as exc:                         # noqa: BLE001
        _fail(session, agent_run_id, f"deterministic executor raised: {exc}")
        raise


def _fail(session, agent_run_id: str, message: str) -> None:
    session.rollback()
    session.execute(update(db.agent_run)
                    .where(db.agent_run.c.agent_run_id == agent_run_id)
                    .values(status="FAILED", error=message[:2000],
                            ended_at=datetime.now(timezone.utc)))
    session.commit()


def fail(session, agent_run_id: str, message: str) -> None:
    """Public wrapper around _fail(), for a caller whose own post-execute
    validation rejects an otherwise-successful call.

    Found while building Tranche 2: execute()'s LIVE call can succeed fully -
    valid provider response, liveness verified, llm_run recorded - and the
    *caller* (research.py, savings_advisory.py) still rejects the content
    because it names an unknown domain, scenario or shape. That rejection
    happens outside execute(), so execute()'s own failure handling never
    runs, and nothing else was marking the row FAILED - it sat in QUEUED
    forever. The same class of defect test_unimplemented_mode_creates_no_
    orphan_run exists to catch, reached by a different path. research.py's
    shape-violation branch had exactly this gap before this fix; it's
    corrected there too, not just here.
    """
    _fail(session, agent_run_id, message)


def succeed(session, agent_run_id: str, result: dict) -> None:
    row = session.execute(
        select(db.agent_run).where(db.agent_run.c.agent_run_id == agent_run_id)).one()
    if row.execution_mode == "LIVE":
        proof = session.execute(
            select(db.llm_run.c.llm_run_id)
            .where(db.llm_run.c.agent_run_id == agent_run_id)).first()
        if proof is None:
            _fail(session, agent_run_id,
                  "LIVE run cannot succeed without a persisted provider record")
            raise errors.LivenessProofFailed(
                "no provider record for LIVE run; refusing SUCCEEDED")
    session.execute(update(db.agent_run)
                    .where(db.agent_run.c.agent_run_id == agent_run_id)
                    .values(status="SUCCEEDED", result=result,
                            # True exactly for DETERMINISTIC_ONLY. MOCK and
                            # REPLAY represent an LLM's own output (canned or
                            # historical) and are not this claim, even though
                            # neither has an executor in this build.
                            produced_without_llm=(row.execution_mode == "DETERMINISTIC_ONLY"),
                            ended_at=datetime.now(timezone.utc)))
    session.commit()


def fence(label: str, value) -> str:
    """Spec 7.3 untrusted-content fencing. Caller-supplied values go inside a
    delimited data block and delimiters are stripped from the value, so content
    cannot escape into the instruction position."""
    text = str(value if value is not None else "")
    for token in ("</untrusted", "<untrusted", "```"):
        text = text.replace(token, "")
    return f"<untrusted name=\"{label}\">\n{text}\n</untrusted>"


def parse_json_strict(text: str) -> dict | list:
    """Unsupported fields are null, not invented. A reply that is not valid JSON
    is an abstention, never a salvage-by-regex."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError as exc:
        raise errors.StructuredOutputInvalid(
            f"model output was not valid JSON: {exc}") from exc
