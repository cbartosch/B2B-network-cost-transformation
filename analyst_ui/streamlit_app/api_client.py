"""HTTP-only client.

Spec 2.1: Streamlit holds no database, model or Internet credentials and never
imports a provider SDK. Every action is a typed FastAPI call.

The shared secret is the one cross-service contract in the bundle. An earlier
build enforced it on the API and sent no headers at all from here, so setting
API_TOKEN broke the entire interface with 401s - the only authentication control
could not be switched on. The header name is now defined once, in contract/auth.py,
and copied into both images, so there is nothing left to drift. `probe_auth()`
still checks at runtime, because a *token* mismatch is a separate failure that a
shared constant cannot prevent.
"""
import os

import httpx

from contract.auth import AUTH_HEADER

BASE = os.getenv("API_BASE_URL", "http://api:8000")
API_TOKEN = os.getenv("API_TOKEN", "")
# 120s was the original value and it was too short for this system's own
# workload: a single LIVE agent call now carries a hosted web search plus
# source fetches, and entity resolution, fact corroboration, the questionnaire
# prefill and the savings advisor all go through this synchronous path. The
# failure mode was indistinguishable from an outage - "API unreachable: timed
# out" - while the request was in fact still running and would have succeeded.
#
# Configurable rather than hardcoded so a slow or heavily-proxied network can
# raise it further without a rebuild of the interface's source.
TIMEOUT = float(os.getenv("UI_API_TIMEOUT_SECONDS", "360"))


def auth_configured() -> bool:
    return bool(API_TOKEN)


def auth_headers() -> dict:
    """Sent on every request. Empty when no token is configured, so the
    unauthenticated default path is unchanged."""
    return {AUTH_HEADER: API_TOKEN} if API_TOKEN else {}


def _req(method: str, path: str, **kw):
    headers = {**auth_headers(), **kw.pop("headers", {})}
    # Per-call override. Most routes answer in well under TIMEOUT; a single
    # domain of research is a LIVE provider call plus up to a dozen source
    # fetches and legitimately runs longer. Raising the global default instead
    # would mean a genuinely wedged request hangs the interface for minutes.
    timeout = kw.pop("timeout", TIMEOUT)
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.request(method, f"{BASE}{path}", headers=headers, **kw)
    except httpx.HTTPError as e:
        return {"_error": f"API unreachable: {e}"}
    if r.status_code == 401:
        return {"_error": (
            "401 from the API. The API has API_TOKEN set; this interface "
            + ("is sending a token that does not match."
               if API_TOKEN else "has no API_TOKEN configured.")
            + " Set the same value for both services in .env and restart."),
            "_status": 401}
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:                        # noqa: BLE001
            detail = r.text
        return {"_error": detail, "_status": r.status_code}
    return r.json()


def probe_auth(health: dict) -> str | None:
    """Returns a human-readable problem, or None if the two sides agree.

    /v1/health is deliberately unauthenticated, so it succeeds even when every
    other route would 401. Without this check the operator sees a green home
    page and failures everywhere else.
    """
    if health.get("auth_required") and not auth_configured():
        return ("The API requires a token but this interface has none. "
                "Set API_TOKEN to the same value for both services in .env.")
    if auth_configured() and not health.get("auth_required"):
        return ("This interface is sending a token but the API is not enforcing "
                "one. Harmless, but the two are out of step.")
    expected = health.get("auth_header")
    if expected and expected != AUTH_HEADER:
        return (f"Header mismatch: the API expects {expected!r}, this client "
                f"sends {AUTH_HEADER!r}.")
    if auth_configured():
        # One authenticated call against a protected route. Health alone proves
        # nothing, because health is exempt.
        probe = get("/v1/agents")
        if isinstance(probe, dict) and probe.get("_status") == 401:
            return "Token rejected by the API. The two values do not match."
    return None


# Cheap reads. The long default exists for LIVE agent calls; applying it to a
# page's routine reads means an unhealthy API hangs the interface for minutes
# per call instead of saying so. Page 5 renders five reads, so at the long
# timeout an API that is down looks like a page that is stuck.
FAST_TIMEOUT = float(os.getenv("UI_API_FAST_TIMEOUT_SECONDS", "20"))


def get(path, timeout=None, **params):
    return _req("GET", path, params=params or None,
                timeout=timeout if timeout is not None else FAST_TIMEOUT)


def post(path, payload=None, timeout=None):
    kw = {"json": payload or {}}
    if timeout is not None:
        kw["timeout"] = timeout
    return _req("POST", path, **kw)


def delete(path, **params):
    return _req("DELETE", path, params=params or None)


def put(path, payload=None):
    return _req("PUT", path, json=payload or [])


# --------------------------------------------------------------- flash messages
def flash(message: str, key: str = "_flash") -> None:
    """Record a confirmation that must survive an st.rerun().

    st.success() immediately followed by st.rerun() shows nothing: the message
    is written and the script restarts before the browser renders it. Every
    place that confirmed an action and then reran was therefore silent, and a
    successful registration looked exactly like a form that had cleared itself
    for no reason.
    """
    import streamlit as st
    st.session_state[key] = message


def show_flash(key: str = "_flash") -> None:
    """Render and clear a pending confirmation. Call once, near the top."""
    import streamlit as st
    message = st.session_state.pop(key, None)
    if message:
        st.success(message)
