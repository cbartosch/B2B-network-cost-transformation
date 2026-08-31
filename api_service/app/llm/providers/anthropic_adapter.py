"""Anthropic Messages API adapter. One code path, and it is an HTTPS call."""
import logging
import time
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from . import _transport
from .base import ProviderCall, parse_http_date, strictify
from .. import errors

log = logging.getLogger("workbench.provider.anthropic")

ENDPOINT = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
# Derived, not repeated: an endpoint change must move the pin host with it.
HOST = urlparse(ENDPOINT).hostname


class AnthropicAdapter:
    name = "anthropic"
    reconciliation_tier = "A"          # per-model usage via the Admin usage API

    def __init__(self, api_key: str, model: str, timeout: float = 60.0):
        self._api_key = api_key
        self.model = model
        self._timeout = timeout

    def configured(self) -> bool:
        return bool(self._api_key)


    def parse(self, *, system: str, prompt: str, schema: dict,
              schema_name: str, max_tokens: int = 4000,
              tools: list[dict] | None = None) -> ProviderCall:
        """Structured output through a tool whose input_schema is the shape.

        Without other tools the emit tool is pinned, so the model cannot
        answer in prose: the response carries a tool_use block whose `input`
        is the object.

        **With a search tool it must not be pinned.** Pinning a specific tool
        forces the model to call that tool immediately, which means it can
        never search first - so every search-using service answered from
        memory and the search-attempted gate rejected all three attempts.
        The first version of this method pinned unconditionally and claimed in
        this docstring that "search runs first"; it does not, and the claim
        was wrong rather than merely optimistic.

        With search present the choice is `any`: the model must end on a tool
        call, but may search before it. That is weaker than pinning - it can
        take more than one turn's worth of reasoning to get there - and it is
        the compromise a single-call design forces. The CR's discovery and
        extraction split exists precisely because a searching turn and a
        schema-enforced extracting turn should not be the same call. Until
        that lands, a reply with no emit block is a rejection the retry loop
        handles rather than something to salvage.
        """
        if not self.configured():
            raise errors.ProviderUnavailable("ANTHROPIC_API_KEY is not set")

        emit = {"name": schema_name,
                "description": "Return the result in this exact shape.",
                "input_schema": strictify(schema)}
        choice = ({"type": "any"} if tools
                  else {"type": "tool", "name": schema_name})
        body = {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": prompt}],
                "tools": list(tools or []) + [emit],
                "tool_choice": choice}
        call = self._request(body)

        parsed = None
        for block in (call.raw.get("content") or []):
            if isinstance(block, dict) and block.get("type") == "tool_use" \
                    and block.get("name") == schema_name:
                parsed = block.get("input")
        if parsed is None:
            # The provider answered without using the pinned tool. That is a
            # conformance failure, not something to recover from by reading
            # the prose: a plausible prose answer is exactly what the schema
            # channel exists to stop being accepted.
            raise errors.StructuredOutputInvalid(
                f"anthropic did not emit the {schema_name!r} tool"
                + (" - with a search tool present the emit tool cannot be "
                   "pinned, so the model may stop after searching; this is a "
                   "rejection to retry, not a reply to salvage"
                   if tools else "; the reply cannot be treated as "
                                 "schema-conformant"))
        return replace(call, parsed=parsed)

    def complete(self, *, system: str, prompt: str, max_tokens: int = 1500,
                tools: list[dict] | None = None) -> ProviderCall:
        if not self.configured():
            raise errors.ProviderUnavailable("ANTHROPIC_API_KEY is not set")
        body = {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        if tools:
            # The hosted web_search tool runs server-side: Anthropic executes
            # the search and returns the result blocks in this same response.
            body["tools"] = tools
        return self._request(body)

    def _request(self, body: dict) -> ProviderCall:
        """The shared transport path for complete() and parse().

        Factored out when parse() arrived: two copies of the liveness proof,
        the pin check and the Date-header requirement would have been two
        places for the structured path to quietly diverge from the audited
        one, and the structured path is the one that will carry the evidence.
        """
        headers = {"x-api-key": self._api_key, "anthropic-version": API_VERSION,
                   "content-type": "application/json"}

        started = time.perf_counter()
        local_at = datetime.now(timezone.utc)
        try:
            with _transport.client(self._timeout) as c:
                resp = c.post(ENDPOINT, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise errors.ProviderUnavailable(
                _transport.transport_error("anthropic", exc)) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        # Pin read from the connection this response arrived on. Under ENFORCE
        # a mismatched or unreadable certificate raises before the body is used.
        pins, pin, not_after = _transport.peer_pins(resp)
        strength = _transport.check_pin(HOST, pins)

        if resp.status_code != 200:
            log.warning("anthropic %s: %s", resp.status_code, resp.text[:500])
            raise errors.ProviderUnavailable(
                _transport.safe_error("anthropic", resp.status_code))

        data = resp.json()
        provider_at = parse_http_date(resp.headers.get("date"))
        if provider_at is None:
            raise errors.LivenessProofFailed(
                "anthropic response carried no Date header; provider-issued "
                "timestamp is required for a LIVE run")

        text = "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")
        usage = data.get("usage") or {}
        return ProviderCall(
            provider=self.name, model=data.get("model", self.model), text=text,
            provider_response_id=data.get("id", ""),
            provider_request_id=resp.headers.get("request-id"),
            provider_request_at=provider_at,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            local_request_at=local_at, latency_ms=latency_ms,
            http_status=resp.status_code, egress_proxy=_transport.EGRESS_PROXY,
            tls_pin=pin, provenance_strength=strength, tls_cert_not_after=not_after,
            raw={"usage": usage, "stop_reason": data.get("stop_reason"),
                "content": data.get("content", [])})
