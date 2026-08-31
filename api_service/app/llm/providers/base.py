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
    # The provider-parsed object when parse() was used. Distinct from `text`:
    # this came out of a schema-enforced channel, so a caller reading it is
    # not parsing prose and cannot be handed a plausible string where a
    # number was required.
    parsed: dict | None = None

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

    # Structured output. The provider is handed a JSON schema and must return
    # an object conforming to it, using whatever native mechanism it has -
    # a forced tool, a response format, a grammar. An adapter that cannot
    # enforce the schema is non-conformant for that service and says so by
    # raising; it must not fall back to asking for JSON in prose, because a
    # plausible prose answer is the failure this replaces.
    def parse(self, *, system: str, prompt: str, schema: dict,
              schema_name: str, max_tokens: int,
              tools: list[dict] | None = None) -> ProviderCall: ...


def strictify(schema: dict) -> dict:
    """Make a Pydantic JSON schema acceptable to a provider's strict mode.

    Both approved providers require every property to be listed in `required`
    and `additionalProperties` to be false at each object level. Pydantic
    marks a field with a default as optional, which is correct for Python and
    rejected by strict mode - so optional fields become required-but-nullable
    rather than being dropped, which keeps abstention expressible.
    """
    def walk(node):
        if not isinstance(node, dict):
            return node
        node = {k: walk(v) if isinstance(v, (dict, list)) else v
                for k, v in node.items()}
        for key in ("properties", "$defs", "definitions"):
            if isinstance(node.get(key), dict):
                node[key] = {k: walk(v) for k, v in node[key].items()}
        if isinstance(node.get("items"), dict):
            node["items"] = walk(node["items"])
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
            if isinstance(node.get("properties"), dict):
                node["required"] = sorted(node["properties"])
        return node

    def walk_list(node):
        return [walk(x) for x in node] if isinstance(node, list) else node

    out = walk(schema)
    for key in ("anyOf", "oneOf", "allOf"):
        if key in out:
            out[key] = walk_list(out[key])
    return out
