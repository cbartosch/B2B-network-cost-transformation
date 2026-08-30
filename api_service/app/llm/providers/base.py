"""Provider-neutral adapter protocol.

The liveness proof (spec 7.2C) rests on evidence the *provider* issued, not on
values this process generated. An earlier revision recorded a locally generated
timestamp and then checked it against a window derived from the same clock,
which was tautological. Every timestamp and identifier below is now read out of
the provider's response.

An adapter that cannot supply a provider-issued timestamp and identifier cannot
be used for LIVE work.

A later audit found that the timestamp alone proves little: an interceptor
returns `Date: <now>` and passes. The clock check and the transport pin were not
independent controls but one control with two names. Each call therefore also
carries the TLS pin of the connection it arrived on, and the provenance strength
that pin earned, so a run made over an unpinned connection is not presented as
equally proven.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol


def parse_http_date(value: str | None) -> datetime | None:
    """RFC 7231 Date header -> aware datetime, or None."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class ProviderCall:
    provider: str
    model: str
    text: str

    # --- provider-issued evidence -------------------------------------
    provider_response_id: str          # body identifier
    provider_request_id: str | None    # transport identifier, independently issued
    provider_request_at: datetime      # from the provider, never from our clock
    input_tokens: int
    output_tokens: int

    # --- locally observed, for skew comparison only --------------------
    local_request_at: datetime
    latency_ms: int
    http_status: int
    egress_proxy: str | None
    raw: dict

    # --- transport provenance ------------------------------------------
    # The clock comparison is only as strong as the connection it arrived on,
    # so the strength of that connection is recorded rather than assumed.
    tls_pin: str | None = None
    provenance_strength: str = "TRANSPORT_ONLY"
    # A pin changes when the certificate does, so the expiry is the deadline for
    # updating TLS_PINS. Recorded so the change is scheduled, not discovered.
    tls_cert_not_after: "datetime | None" = None

    @property
    def clock_skew_seconds(self) -> float:
        return abs((self.provider_request_at - self.local_request_at).total_seconds())


class ProviderAdapter(Protocol):
    name: str
    reconciliation_tier: str          # A | B | C  (spec 7.2E)

    def configured(self) -> bool: ...
    def complete(self, *, system: str, prompt: str, max_tokens: int,
                tools: list[dict] | None = None) -> ProviderCall: ...
