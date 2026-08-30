"""Anthropic Messages API adapter. One code path, and it is an HTTPS call."""
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from . import _transport
from .base import ProviderCall, parse_http_date
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

    def complete(self, *, system: str, prompt: str, max_tokens: int = 1500,
                tools: list[dict] | None = None) -> ProviderCall:
        if not self.configured():
            raise errors.ProviderUnavailable("ANTHROPIC_API_KEY is not set")

        body = {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        if tools:
            # The hosted web_search tool runs server-side: Anthropic executes
            # the search and returns the result blocks in this same response,
            # no second round trip needed. That's what lets domain research
            # actually search rather than ask the model to recall training
            # data and self-report sources it cannot verify (see
            # domain/research.py's module docstring on this gap).
            body["tools"] = tools
        headers = {"x-api-key": self._api_key, "anthropic-version": API_VERSION,
                   "content-type": "application/json"}

        started = time.perf_counter()
        local_at = datetime.now(timezone.utc)
        try:
            with _transport.client(self._timeout) as c:
                resp = c.post(ENDPOINT, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise errors.ProviderUnavailable(f"anthropic transport error: {exc}") from exc
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
            # `content` carries the full block list - text, and when a tool
            # was used, server_tool_use / web_search_tool_result blocks too.
            # A caller that needs the actual search results (not just the
            # model's prose about them) reads this rather than `text`.
            raw={"usage": usage, "stop_reason": data.get("stop_reason"),
                "content": data.get("content", [])})
