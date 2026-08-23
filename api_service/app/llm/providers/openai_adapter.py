"""OpenAI Chat Completions adapter. One code path, and it is an HTTPS call."""
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from . import _transport
from .base import ProviderCall, parse_http_date
from .. import errors

log = logging.getLogger("workbench.provider.openai")

ENDPOINT = "https://api.openai.com/v1/chat/completions"
# Derived, not repeated: an endpoint change must move the pin host with it.
HOST = urlparse(ENDPOINT).hostname


class OpenAIAdapter:
    name = "openai"
    reconciliation_tier = "A"

    def __init__(self, api_key: str, model: str, timeout: float = 60.0):
        self._api_key = api_key
        self.model = model
        self._timeout = timeout

    def configured(self) -> bool:
        return bool(self._api_key)

    def complete(self, *, system: str, prompt: str, max_tokens: int = 1500) -> ProviderCall:
        if not self.configured():
            raise errors.ProviderUnavailable("OPENAI_API_KEY is not set")

        body = {"model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}]}
        headers = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}

        started = time.perf_counter()
        local_at = datetime.now(timezone.utc)
        try:
            with _transport.client(self._timeout) as c:
                resp = c.post(ENDPOINT, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise errors.ProviderUnavailable(f"openai transport error: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        # Pin read from the connection this response arrived on. Under ENFORCE
        # a mismatched or unreadable certificate raises before the body is used.
        pins, pin, not_after = _transport.peer_pins(resp)
        strength = _transport.check_pin(HOST, pins)

        if resp.status_code != 200:
            log.warning("openai %s: %s", resp.status_code, resp.text[:500])
            raise errors.ProviderUnavailable(
                _transport.safe_error("openai", resp.status_code))

        data = resp.json()
        # Two independent provider-issued timestamps: body `created` and the
        # transport Date header. Prefer the body; fall back to the header.
        provider_at = None
        if isinstance(data.get("created"), int):
            provider_at = datetime.fromtimestamp(data["created"], tz=timezone.utc)
        if provider_at is None:
            provider_at = parse_http_date(resp.headers.get("date"))
        if provider_at is None:
            raise errors.LivenessProofFailed(
                "openai response carried neither `created` nor a Date header; "
                "provider-issued timestamp is required for a LIVE run")

        choices = data.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return ProviderCall(
            provider=self.name, model=data.get("model", self.model), text=text,
            provider_response_id=data.get("id", ""),
            provider_request_id=resp.headers.get("x-request-id"),
            provider_request_at=provider_at,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            local_request_at=local_at, latency_ms=latency_ms,
            http_status=resp.status_code, egress_proxy=_transport.EGRESS_PROXY,
            tls_pin=pin, provenance_strength=strength, tls_cert_not_after=not_after,
            raw={"usage": usage, "finish_reason": choices[0].get("finish_reason")})
