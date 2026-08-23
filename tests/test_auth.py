"""Shared-secret enforcement.

C2-04: the API enforced `X-API-Token` and the Streamlit client sent no headers
at all, so setting API_TOKEN broke the whole interface with 401s. The only
authentication control in the bundle could not be switched on, and nothing
tested it because each half was plausible in isolation.

The header name now has a single definition in contract/auth.py, copied into
both images, so the mismatch class is gone rather than merely tested for. What
remains testable is enforcement, which these exercise through a real request
stack rather than by reading source.
"""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

TOKEN = "s3cret-token-value"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --- default: unauthenticated, unchanged ------------------------------------
def test_open_by_default(client, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "")
    assert client.get("/v1/agents").status_code == 200


# --- enforcement ------------------------------------------------------------
def test_missing_token_is_rejected(client, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", TOKEN)
    r = client.get("/v1/agents")
    assert r.status_code == 401
    assert config.AUTH_HEADER in r.json()["detail"]


def test_wrong_token_is_rejected(client, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", TOKEN)
    r = client.get("/v1/agents", headers={config.AUTH_HEADER: "wrong"})
    assert r.status_code == 401


def test_correct_token_is_accepted(client, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", TOKEN)
    assert client.get("/v1/agents",
                      headers={config.AUTH_HEADER: TOKEN}).status_code == 200


def test_write_routes_are_protected_too(client, monkeypatch):
    """Enforcement must not be limited to the routes that happen to be read-only."""
    monkeypatch.setattr(config, "API_TOKEN", TOKEN)
    r = client.post("/v1/outside-in/cases", json={"created_by": "attacker"})
    assert r.status_code == 401


def test_health_stays_open_so_misconfiguration_is_diagnosable(client, monkeypatch):
    """The container healthcheck polls it, and the UI reads auth_required from it
    to tell the operator the two sides disagree."""
    monkeypatch.setattr(config, "API_TOKEN", TOKEN)
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["auth_required"] is True


def test_exempt_set_is_minimal(monkeypatch):
    """Only the two probes. An earlier version also exempted /docs and
    /openapi.json, publishing the API surface while a token was configured."""
    assert config.AUTH_EXEMPT_PATHS == frozenset({"/v1/health", "/v1/ready"})


def test_readiness_stays_open_so_the_healthcheck_can_reach_it(client, monkeypatch):
    """The container probe cannot send a header. Requiring one would mark the
    container unhealthy forever the moment a token was configured - and
    `depends_on: service_healthy` would never let the UI start."""
    monkeypatch.setattr(config, "API_TOKEN", TOKEN)
    assert client.get("/v1/ready").status_code == 200


# --- the cross-service contract ---------------------------------------------
def test_health_advertises_the_header_the_middleware_checks(client):
    """The client learns the expected header name here and compares it to what
    it sends, so a rename on one side is caught at runtime rather than by 401s
    with no explanation."""
    assert client.get("/v1/health").json()["auth_header"] == config.AUTH_HEADER


def test_both_sides_resolve_to_one_definition():
    """The defect was two halves that never met. There is now one definition,
    copied into both images, so there is nothing left to mismatch."""
    from contract.auth import AUTH_EXEMPT_PATHS, AUTH_HEADER
    assert config.AUTH_HEADER is AUTH_HEADER
    assert config.AUTH_EXEMPT_PATHS is AUTH_EXEMPT_PATHS


def test_contract_module_carries_no_secret():
    """It is copied into both images and into source control, so it must hold
    only the shape of the agreement, never the token."""
    import contract.auth as c
    public = {k: v for k, v in vars(c).items() if not k.startswith("_")}
    assert set(public) == {"AUTH_HEADER", "AUTH_EXEMPT_PATHS"}


# --- timing -----------------------------------------------------------------
def test_secret_comparison_goes_through_compare_digest(client, monkeypatch):
    """`!=` on a secret leaks its length and prefix through response timing.

    A statistical timing test would be flaky and slow, and reading the source
    would be the grep theatre this suite has twice had to remove. Instrumenting
    the primitive is neither: if the comparison is changed to `!=`, the spy
    never fires and this fails.
    """
    import secrets as _secrets

    calls = []
    real = _secrets.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(config, "API_TOKEN", TOKEN)
    monkeypatch.setattr(_secrets, "compare_digest", spy)

    assert client.get("/v1/agents",
                      headers={config.AUTH_HEADER: TOKEN}).status_code == 200
    assert calls, "the token was compared without secrets.compare_digest"
    assert calls[0] == (TOKEN, TOKEN)


def test_a_rejected_token_also_goes_through_compare_digest(client, monkeypatch):
    """The failure path is the one an attacker times."""
    import secrets as _secrets

    calls = []
    real = _secrets.compare_digest
    monkeypatch.setattr(config, "API_TOKEN", TOKEN)
    monkeypatch.setattr(_secrets, "compare_digest",
                        lambda a, b: (calls.append((a, b)), real(a, b))[1])

    assert client.get("/v1/agents",
                      headers={config.AUTH_HEADER: "x"}).status_code == 401
    assert calls == [("x", TOKEN)]
