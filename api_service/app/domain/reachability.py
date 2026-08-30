"""Live egress check (diagnostic; contributes nothing to an estimate).

Every other reachability signal in this system is indirect. /v1/health reports
whether an API *key is set*, pre-flight reports whether an adapter is
*configured*, and both say PASS on a container that cannot reach anything -
which is how a network fault reached the analyst as "no evidence found" and
"BUDGET_EXHAUSTED" rather than as a network fault. This answers the question
directly, and answers it with evidence rather than a status code.

**Why time-varying data.** An HTTP 200 proves a response arrived, not that it
came from the public internet: a proxy error page, a captive portal, or a
cached body all return 200. So each probe returns something that *changes* -
the current UTC time as an independent server reports it, and the current
weather at the subject entity's headquarters. A human reading the panel can
tell at a glance whether the answer is live: a temperature and a clock that
match reality cannot come from a stub, and a timestamp that is hours stale is
itself the finding. This is the same principle the LLM gateway already applies
to provider calls (spec 7.2C liveness proof), applied to plain egress.

**Which transport.** Deliberately outbound_client from llm/providers - the
same egress path, proxy and trust anchor that domain/research.py uses to
verify sources. Checking reachability over a *different* client than the one
that does the work would be a check that can pass while the work still fails,
which is what a bare httpx.get in research.py did before 4.38.0.

**Sources.** open-meteo.com: no API key, no account, no attribution
requirement, and documented as free for non-commercial use. Overridable by
environment, because a network that permits nothing but an internal mirror
should be able to point this somewhere it can actually reach rather than
report a permanent red light.

Nothing here has been exercised against the live services (no network egress in
the sandbox this was written in). The response shapes follow open-meteo's
documented contract; a field rename upstream would surface as a probe that
reports "reachable, unexpected shape", which is deliberately distinguished from
"unreachable" below.
"""
import os
from datetime import datetime, timezone

import httpx

from ..llm.providers import _transport

# Overridable so an air-gapped or mirror-only deployment can point at whatever
# it is permitted to reach, rather than showing a red light it cannot fix.
GEOCODE_URL = os.getenv(
    "REACHABILITY_GEOCODE_URL", "https://geocoding-api.open-meteo.com/v1/search")
WEATHER_URL = os.getenv(
    "REACHABILITY_WEATHER_URL", "https://api.open-meteo.com/v1/forecast")

TIMEOUT = float(os.getenv("REACHABILITY_TIMEOUT_SECONDS", "10"))

# ISO 3166-1 alpha-2 -> a place to ask about when that is all the case has.
# country_of_domicile is two letters; a weather probe needs a point. The
# capital is a defensible stand-in and is labelled as one in the output, so
# nobody mistakes it for the entity's actual registered address.
_CAPITALS = {
    "DE": "Berlin", "GB": "London", "US": "Washington", "FR": "Paris",
    "NL": "Amsterdam", "SG": "Singapore", "AE": "Abu Dhabi", "CH": "Bern",
    "IE": "Dublin", "ES": "Madrid", "IT": "Rome", "SE": "Stockholm",
    "PL": "Warsaw", "JP": "Tokyo", "CN": "Beijing", "IN": "New Delhi",
    "BR": "Brasilia", "CA": "Ottawa", "AU": "Canberra", "BE": "Brussels",
}


def _step(name: str, ok: bool, detail: str, **extra) -> dict:
    return {"step": name, "ok": ok, "detail": detail, **extra}


def _get(url: str, params: dict | None = None):
    """Returns (response, error). An error string means nothing arrived; a
    response means something did, whatever its status."""
    try:
        with _transport.outbound_client(TIMEOUT) as c:
            return c.get(url, params=params,
                         headers={"User-Agent": "network-workbench-reachability/1.0"}), None
    except httpx.HTTPError as exc:
        return None, _transport.transport_error("egress", exc)


def _clock_probe() -> dict:
    """Independent time, taken from an HTTP Date header.

    Not a time API: any server that answers gives an RFC 7231 Date, so this
    works against whatever host the deployment is allowed to reach, and the
    skew against our own clock is the part worth reading. A large skew is
    worth knowing on its own - the provider liveness check (7.2C) bounds skew
    too, so a container with a badly wrong clock fails LIVE runs for reasons
    that look nothing like a clock problem.
    """
    local_before = datetime.now(timezone.utc)
    resp, error = _get(GEOCODE_URL, {"name": "London", "count": 1})
    if resp is None:
        return _step("independent clock", False, error)

    from ..llm.providers.base import parse_http_date
    server_time = parse_http_date(resp.headers.get("date"))
    if server_time is None:
        return _step("independent clock", False,
                     "response carried no Date header to compare against")
    skew = abs((server_time - local_before).total_seconds())
    return _step(
        "independent clock", True,
        f"remote {server_time.isoformat()} vs local {local_before.isoformat()}",
        remote_time=server_time.isoformat(),
        local_time=local_before.isoformat(),
        skew_seconds=round(skew, 1),
        skew_note=("clocks agree" if skew < 120 else
                   f"local clock is {skew:.0f}s out - LIVE provider calls bound "
                   f"this skew and will fail while it stands"))


def _locate(place: str) -> tuple[dict | None, dict]:
    resp, error = _get(GEOCODE_URL, {"name": place, "count": 1, "language": "en"})
    if resp is None:
        return None, _step("locate headquarters", False, error)
    if resp.status_code != 200:
        return None, _step("locate headquarters", False,
                           f"geocoder returned HTTP {resp.status_code}")
    try:
        hit = (resp.json().get("results") or [None])[0]
    except ValueError:
        return None, _step("locate headquarters", False,
                           "geocoder response was not JSON - a proxy error page "
                           "or captive portal answers like this")
    if not hit:
        return None, _step("locate headquarters", False, f"no match for {place!r}")
    return hit, _step(
        "locate headquarters", True,
        f"{hit.get('name')}, {hit.get('country')} "
        f"({hit.get('latitude')}, {hit.get('longitude')})")


def _weather(hit: dict) -> dict:
    resp, error = _get(WEATHER_URL, {
        "latitude": hit["latitude"], "longitude": hit["longitude"],
        "current": "temperature_2m,wind_speed_10m", "timezone": "auto"})
    if resp is None:
        return _step("weather at headquarters", False, error)
    if resp.status_code != 200:
        return _step("weather at headquarters", False,
                     f"weather service returned HTTP {resp.status_code}")
    try:
        data = resp.json()
        current = data.get("current") or {}
    except ValueError:
        return _step("weather at headquarters", False,
                     "weather response was not JSON")
    if "temperature_2m" not in current:
        # Reached something, but not the service expected. Kept distinct from
        # unreachable: the remedy is a field rename here, not a network change.
        return _step("weather at headquarters", False,
                     "reachable, but the response did not carry the expected "
                     "fields - the upstream contract may have changed")
    return _step(
        "weather at headquarters", True,
        f"{current['temperature_2m']}{(data.get('current_units') or {}).get('temperature_2m', '')} "
        f"local time {current.get('time')} ({data.get('timezone')})",
        temperature=current.get("temperature_2m"),
        wind_speed=current.get("wind_speed_10m"),
        local_time=current.get("time"),
        timezone=data.get("timezone"))


def check(case_row=None, place: str | None = None) -> dict:
    """Run the probes. `place` overrides; otherwise the subject entity's
    country of domicile is used, and its capital stands in for a headquarters
    address this system does not hold."""
    steps = []
    resolved_from = "explicit"
    if not place and case_row is not None:
        code = (getattr(case_row, "country_of_domicile", None) or "").upper()
        place = _CAPITALS.get(code) or code or None
        resolved_from = (f"capital of {code} - a stand-in, not the entity's "
                         f"registered address" if code in _CAPITALS else
                         f"country of domicile {code!r}" if code else "unset")
    if not place:
        place = "London"
        resolved_from = "no domicile on the case; defaulted"

    steps.append(_clock_probe())
    hit, locate_step = _locate(place)
    steps.append(locate_step)
    if hit:
        steps.append(_weather(hit))

    ok = all(s["ok"] for s in steps)
    return {
        "reachable": ok,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "asked_about": place,
        "location_basis": resolved_from,
        "transport": {
            "egress_proxy": _transport.EGRESS_PROXY,
            "verification": _transport.tls_posture()["verification"],
            "note": "the same client domain/research.py uses to verify sources, "
                   "so a pass here means source verification can reach the "
                   "internet too",
        },
        "steps": steps,
        "how_to_read_this": (
            "The temperature and clock below change minute to minute. If they "
            "match reality the container is genuinely on the public internet; "
            "a proxy error page, captive portal or cached body cannot produce "
            "a correct current reading. A failure here explains a research run "
            "that finds nothing: sources cannot be fetched, so no domain can "
            "reach EVIDENCED_PUBLIC."),
    }
