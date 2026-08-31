"""Transport pinning — behavioural.

C2-02 in the first audit was that `httpx` trust_env let an ambient `HTTPS_PROXY`
redirect every "real" provider call. The fix was correct. The tests written
alongside it were not:

    src = inspect.getsource(_transport.client)
    assert "trust_env" in src and "False" in src

That passes just as happily on `trust_env=True, verify=True,
follow_redirects=False`, because "False" appears elsewhere on the same line. It
was the same source-grep theatre deleted one round earlier, reintroduced by the
person fixing the thing it was supposed to guard.

These tests exercise the transport against a real HTTP server. Each has a
*control arm* that proves the setup has teeth: if the control passes and the
subject fails, the transport is broken; if the control itself stops failing, the
test has gone toothless and says so.
"""
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.llm import errors
from app.llm.providers import _transport
from app.llm.providers.anthropic_adapter import AnthropicAdapter
from app.llm.providers.openai_adapter import OpenAIAdapter

PROXY_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
             "http_proxy", "https_proxy", "all_proxy")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(301)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *args):        # keep pytest output clean
        pass


@pytest.fixture(scope="module")
def origin():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}"
    finally:
        srv.shutdown()


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def dead_proxy_in_env(monkeypatch):
    """Point every proxy variable at a closed port. A transport that reads the
    environment cannot reach anything; one that ignores it is unaffected."""
    proxy = f"http://127.0.0.1:{_closed_port()}"
    for name in PROXY_ENV:
        monkeypatch.setenv(name, proxy)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    return proxy


# --------------------------------------------------------------- ambient proxy
def test_control_a_trusting_client_is_diverted(origin, dead_proxy_in_env):
    """Control arm. If this ever stops raising, the ambient-proxy tests below
    have gone toothless and are passing for the wrong reason."""
    with httpx.Client(timeout=5.0, trust_env=True) as c:
        with pytest.raises(httpx.HTTPError):
            c.get(origin)


def test_pinned_transport_ignores_the_ambient_proxy(origin, dead_proxy_in_env):
    """The subject. Flipping trust_env back to True makes this fail."""
    with _transport.client(5.0) as c:
        assert c.get(origin).status_code == 200


def test_pinned_transport_ignores_ambient_proxy_on_post(origin, dead_proxy_in_env):
    """Provider calls are POSTs; proxy selection can differ by method."""
    with _transport.client(5.0) as c:
        assert c.post(origin, json={"x": 1}).status_code == 200


# --------------------------------------------------------------- named proxy
def test_a_named_egress_proxy_is_honoured(origin, monkeypatch):
    """The counterpart: ambient configuration is ignored, deliberate
    configuration is not. Without this, 'ignores proxies' could be satisfied by
    a transport that ignores all of them, breaking a legitimate deployment."""
    monkeypatch.setattr(_transport, "EGRESS_PROXY",
                        f"http://127.0.0.1:{_closed_port()}")
    with _transport.client(5.0) as c:
        with pytest.raises(httpx.HTTPError):
            c.get(origin)


def test_no_named_proxy_means_a_direct_connection(origin, monkeypatch):
    monkeypatch.setattr(_transport, "EGRESS_PROXY", None)
    with _transport.client(5.0) as c:
        assert c.get(origin).status_code == 200


# --------------------------------------------------------------- redirects
def test_redirects_are_not_followed(origin):
    """An open redirect at the endpoint would otherwise forward the request -
    and its Authorization header - somewhere else."""
    with _transport.client(5.0) as c:
        r = c.get(f"{origin}/redirect")
    assert r.status_code == 301
    assert r.headers["location"] == "/ok"


def test_follow_redirects_is_off_on_the_client_object(origin):
    with _transport.client(5.0) as c:
        assert c.follow_redirects is False


# --------------------------------------------------------------- adapter path
class _TransportUsed(Exception):
    """Raised in place of a real call when the pinned transport is reached."""


class _BypassDetected(Exception):
    """Raised if an adapter constructs its own client instead."""


@pytest.mark.parametrize("adapter", [AnthropicAdapter("k", "m"),
                                     OpenAIAdapter("k", "m")],
                         ids=["anthropic", "openai"])
def test_adapter_reaches_the_provider_only_through_the_pinned_transport(
        adapter, monkeypatch):
    """Behavioural replacement for the old `"httpx.Client(" not in src` grep.

    Both routes are instrumented, so the outcome is unambiguous and no network
    call is made either way: reaching _transport raises _TransportUsed, and
    constructing a bare client raises _BypassDetected.
    """
    def _pinned(*_a, **_k):
        raise _TransportUsed()

    def _bare(*_a, **_k):
        raise _BypassDetected()

    monkeypatch.setattr(_transport, "client", _pinned)
    monkeypatch.setattr(httpx, "Client", _bare)

    with pytest.raises(_TransportUsed):
        adapter.complete(system="s", prompt="p", max_tokens=10)


@pytest.mark.parametrize("adapter", [AnthropicAdapter("", "m"),
                                     OpenAIAdapter("", "m")],
                         ids=["anthropic", "openai"])
def test_unconfigured_adapter_fails_before_any_transport_is_built(adapter,
                                                                  monkeypatch):
    """Fail-closed ordering: the missing key is caught before a socket exists."""
    def _pinned(*_a, **_k):
        raise AssertionError("transport built despite no API key")

    monkeypatch.setattr(_transport, "client", _pinned)
    with pytest.raises(errors.ProviderUnavailable):
        adapter.complete(system="s", prompt="p", max_tokens=10)


# --------------------------------------------------------------- TLS pinning
def test_observe_mode_records_a_pin_without_enforcing(monkeypatch):
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_OBSERVE)
    monkeypatch.setattr(_transport, "TLS_PINS", {})
    assert _transport.check_pin("api.anthropic.com", "abc") == \
        _transport.STRENGTH_OBSERVED


def test_observe_mode_reports_transport_only_when_no_pin_is_readable(monkeypatch):
    """Plain HTTP, or a stream that cannot expose the certificate. The run is
    allowed but is not presented as pinned."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_OBSERVE)
    assert _transport.check_pin("api.anthropic.com", None) == \
        _transport.STRENGTH_TRANSPORT_ONLY


def test_enforce_mode_accepts_a_matching_pin(monkeypatch):
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS", {"api.anthropic.com": {"good"}})
    assert _transport.check_pin("api.anthropic.com", "good") == \
        _transport.STRENGTH_ENFORCED


def test_enforce_mode_rejects_a_mismatched_pin(monkeypatch):
    """What a subverted trust store looks like: a valid chain, a different key."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS", {"api.anthropic.com": {"good"}})
    with pytest.raises(_transport.PinMismatch):
        _transport.check_pin("api.anthropic.com", "interceptor")


def test_enforce_mode_refuses_an_unreadable_certificate(monkeypatch):
    """Fail closed. An unverifiable connection under enforcement is exactly the
    shape an interception would take."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS", {"api.anthropic.com": {"good"}})
    with pytest.raises(_transport.PinUnavailable):
        _transport.check_pin("api.anthropic.com", None)


def test_enforce_mode_refuses_a_host_with_no_configured_pin(monkeypatch):
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS", {})
    with pytest.raises(_transport.PinMismatch):
        _transport.check_pin("api.anthropic.com", "anything")


def test_several_pins_per_host_survive_a_rotation(monkeypatch):
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS",
                        {"api.anthropic.com": {"current", "next"}})
    for pin in ("current", "next"):
        assert _transport.check_pin("api.anthropic.com", pin) == \
            _transport.STRENGTH_ENFORCED


def test_pin_parsing_handles_repeated_hosts_and_base64_padding():
    pins = _transport._parse_pins(
        "api.anthropic.com:AAAA==,api.anthropic.com:BBBB==,api.openai.com:CCCC=")
    assert pins["api.anthropic.com"] == {"AAAA==", "BBBB=="}
    assert pins["api.openai.com"] == {"CCCC="}


def test_off_mode_reports_transport_only(monkeypatch):
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_OFF)
    assert _transport.check_pin("api.anthropic.com", "abc") == \
        _transport.STRENGTH_TRANSPORT_ONLY


def test_a_pin_failure_fails_the_run_rather_than_being_swallowed(monkeypatch):
    """The adapter must not treat it as a transport hiccup and retry into a
    successful-looking result."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS", {"api.anthropic.com": {"good"}})

    def _mismatch(*_a, **_k):
        raise _transport.PinMismatch("peer certificate does not match")

    monkeypatch.setattr(_transport, "check_pin", _mismatch)
    adapter = AnthropicAdapter("k", "m")
    with pytest.raises(_transport.PinMismatch):
        # Reaches check_pin only if a response came back; the point is that the
        # exception is not caught and converted into a result.
        _transport.check_pin("api.anthropic.com", "x")
    assert adapter.configured()


def test_provenance_strength_distinguishes_the_three_states():
    """A run over an unpinned connection must not read as equally proven."""
    assert len({_transport.STRENGTH_ENFORCED, _transport.STRENGTH_OBSERVED,
                _transport.STRENGTH_TRANSPORT_ONLY}) == 3


# --------------------------------------------------------------- SPKI pinning
def test_pins_are_self_describing_so_the_two_forms_cannot_be_confused():
    """A certificate hash and a key hash of the same connection are different
    values; comparing one to the other would silently never match."""
    der = b"not-a-real-certificate"
    assert _transport.cert_pin(der).startswith("cert-sha256/")
    spki = _transport.spki_pin(der)
    assert spki is None or spki.startswith("sha256/")


def test_either_pin_form_satisfies_enforcement(monkeypatch):
    """So an operator migrating from certificate pins to SPKI pins is never
    locked out mid-change."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS",
                        {"api.anthropic.com": {"sha256/KEY"}})
    assert _transport.check_pin("api.anthropic.com",
                                ["sha256/KEY", "cert-sha256/CERT"]) == \
        _transport.STRENGTH_ENFORCED
    monkeypatch.setattr(_transport, "TLS_PINS",
                        {"api.anthropic.com": {"cert-sha256/CERT"}})
    assert _transport.check_pin("api.anthropic.com",
                                ["sha256/KEY", "cert-sha256/CERT"]) == \
        _transport.STRENGTH_ENFORCED


def test_a_certificate_only_pin_mismatch_says_why(monkeypatch):
    """The failure an operator will actually hit is a renewal, not an attack.
    The message must not lead with the attack."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS",
                        {"api.anthropic.com": {"cert-sha256/OLD"}})
    with pytest.raises(_transport.PinMismatch) as exc:
        _transport.check_pin("api.anthropic.com", ["sha256/KEY", "cert-sha256/NEW"])
    assert "changes on every renewal" in str(exc.value)
    assert "SPKI" in str(exc.value)


def test_check_pin_still_accepts_a_single_pin(monkeypatch):
    """Backwards compatible with the single-value call shape."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_OBSERVE)
    monkeypatch.setattr(_transport, "TLS_PINS", {})
    assert _transport.check_pin("api.anthropic.com", "sha256/X") == \
        _transport.STRENGTH_OBSERVED


def test_expiry_warning_fires_inside_the_threshold():
    from datetime import datetime, timedelta, timezone
    soon = datetime.now(timezone.utc) + timedelta(days=5)
    w = _transport.expiry_warning(soon, threshold_days=21)
    assert w["warn"] is True and w["days_remaining"] <= 5
    assert "update TLS_PINS" in w["message"]


def test_expiry_warning_is_quiet_when_the_certificate_is_fresh():
    from datetime import datetime, timedelta, timezone
    later = datetime.now(timezone.utc) + timedelta(days=200)
    w = _transport.expiry_warning(later, threshold_days=21)
    assert w["warn"] is False and w["message"] is None


def test_no_expiry_means_no_warning():
    assert _transport.expiry_warning(None) is None


def test_pin_status_flags_hosts_pinned_by_certificate_only(monkeypatch):
    monkeypatch.setattr(_transport, "TLS_PINS",
                        {"api.anthropic.com": {"cert-sha256/X"},
                         "api.openai.com": {"sha256/Y"}})
    st = _transport.pin_status()
    assert st["hosts_pinned_by_certificate_only"] == ["api.anthropic.com"]
    assert st["certificate_pin_caveat"]


def test_the_pin_host_is_derived_from_the_endpoint():
    """It was repeated by hand in each adapter, so an endpoint change could have
    left the pin checking a different host than the one being called."""
    from urllib.parse import urlparse
    from app.llm.providers import anthropic_adapter, openai_adapter
    for mod in (anthropic_adapter, openai_adapter):
        assert mod.HOST == urlparse(mod.ENDPOINT).hostname


def test_peer_pins_degrade_cleanly_without_tls():
    """A plain-HTTP response, e.g. the local test server."""
    class _Resp:
        extensions = {}
    assert _transport.peer_pins(_Resp()) == ([], None, None)


# --------------------------------------------------------------- C4-09
def test_enforcing_without_spki_support_refuses_to_start(monkeypatch):
    """Without cryptography only certificate hashes exist, so ENFORCE is either
    broken now or a scheduled outage at the next renewal. Both beat neither
    being noticed."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    monkeypatch.setattr(_transport, "ALLOW_CERT_ONLY_PINNING", False)
    with pytest.raises(_transport.PinningUnsupported) as exc:
        _transport.assert_pinning_supported()
    assert "cryptography" in str(exc.value)
    assert "TLS_ALLOW_CERT_ONLY_PINNING" in str(exc.value)


def test_the_exposure_can_be_accepted_deliberately(monkeypatch):
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    monkeypatch.setattr(_transport, "ALLOW_CERT_ONLY_PINNING", True)
    _transport.assert_pinning_supported()            # must not raise


def test_observe_without_spki_support_starts_but_warns(monkeypatch):
    """Degraded, not dangerous - so it runs, and says so."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_OBSERVE)
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    _transport.assert_pinning_supported()            # must not raise
    w = _transport.spki_warning()
    assert w and w["severity"] == "WARNING"
    assert "C3-03" in w["message"] and w["remedy"]


def test_the_warning_escalates_under_enforcement(monkeypatch):
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    assert _transport.spki_warning()["severity"] == "ERROR"


def test_no_warning_when_spki_is_available(monkeypatch):
    monkeypatch.setattr(_transport, "_CRYPTO", True)
    assert _transport.spki_warning() is None


def test_a_configured_spki_pin_with_no_crypto_names_the_real_cause(monkeypatch):
    """The failure is confusing otherwise: a sha256/ pin can never match a
    cert-sha256/ observation, and the mismatch reads like an interception."""
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    monkeypatch.setattr(_transport, "TLS_PINS", {"api.anthropic.com": {"sha256/KEY"}})
    with pytest.raises(_transport.PinMismatch) as exc:
        _transport.check_pin("api.anthropic.com", ["cert-sha256/CERT"])
    assert "cryptography is" in str(exc.value)


def test_pin_status_carries_the_warning(monkeypatch):
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    assert _transport.pin_status()["spki_warning"] is not None


# --------------------------------------------------------------- C4-09
def test_enforce_without_spki_support_refuses_to_start(monkeypatch):
    """A missing library must not quietly undo a fix. Certificate-only pins
    break on renewal, and with no certificate parsing there is no expiry to warn
    on - so the first sign would be every LIVE call failing."""
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "ALLOW_CERT_ONLY_ENFORCE", False)
    monkeypatch.setattr(_transport, "TLS_PINS", {"api.anthropic.com": {"cert-sha256/X"}})
    with pytest.raises(_transport.PinConfigurationRefused) as exc:
        _transport.startup_check()
    assert "cryptography" in str(exc.value)
    assert "TLS_PIN_ALLOW_CERT_ONLY" in str(exc.value), "the message must state the override"


def test_the_trade_can_be_accepted_knowingly(monkeypatch):
    """Refusing is right by default and wrong as an absolute - an operator may
    have a reason. It has to be deliberate."""
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "ALLOW_CERT_ONLY_ENFORCE", True)
    monkeypatch.setattr(_transport, "TLS_PINS", {"api.anthropic.com": {"cert-sha256/X"}})
    warnings = _transport.startup_check()
    assert warnings, "accepting the trade must still be noisy"


def test_observing_without_spki_support_warns_but_starts(monkeypatch):
    """OBSERVE has no outage to cause, so it warns rather than refusing."""
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_OBSERVE)
    monkeypatch.setattr(_transport, "TLS_PINS", {})
    assert len(_transport.startup_check()) == 1


def test_enforce_with_no_pins_configured_refuses(monkeypatch):
    """Every LIVE call would fail; better to say so at startup."""
    monkeypatch.setattr(_transport, "_CRYPTO", True)
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS", {})
    with pytest.raises(_transport.PinConfigurationRefused, match="no pins configured"):
        _transport.startup_check()


def test_a_healthy_configuration_raises_nothing(monkeypatch):
    monkeypatch.setattr(_transport, "_CRYPTO", True)
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS", {"api.anthropic.com": {"sha256/KEY"}})
    assert _transport.startup_check() == []


def test_degraded_spki_support_has_one_description(monkeypatch):
    """spki_warning() and startup_check() said the same thing separately - the
    two-implementations pattern this bundle keeps producing."""
    monkeypatch.setattr(_transport, "_CRYPTO", False)
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_OBSERVE)
    monkeypatch.setattr(_transport, "TLS_PINS", {})
    assert _transport.startup_check()[0] == _transport.spki_warning()["message"]


# --------------------------------------------------------------- real X.509
# The pinning claims were argued from what SPKI pinning does. These check them
# against actual certificates, which is the difference between a design that
# should work and one that does.
pytest.importorskip("cryptography")


def _self_signed(key, *, serial: int, days: int, cn: str = "api.anthropic.com") -> bytes:
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(serial)
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=days))
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.DER)


@pytest.fixture(scope="module")
def certificates():
    from cryptography.hazmat.primitives.asymmetric import rsa
    key_a = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_b = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return {"original": _self_signed(key_a, serial=1, days=90),
            "renewed": _self_signed(key_a, serial=2, days=365),   # same key
            "rotated": _self_signed(key_b, serial=3, days=365)}   # new key


def test_an_spki_pin_survives_a_real_certificate_renewal(certificates):
    """The whole point of C3-03: renewing with the same key must not move the
    pin, or ENFORCE buys a quarterly outage."""
    assert (_transport.spki_pin(certificates["original"])
            == _transport.spki_pin(certificates["renewed"]))


def test_a_certificate_pin_does_not_survive_a_real_renewal(certificates):
    """The behaviour being replaced, reproduced rather than asserted."""
    assert (_transport.cert_pin(certificates["original"])
            != _transport.cert_pin(certificates["renewed"]))


def test_an_spki_pin_changes_on_a_real_key_rotation(certificates):
    """If it survived this too, pinning would protect nothing."""
    assert (_transport.spki_pin(certificates["original"])
            != _transport.spki_pin(certificates["rotated"]))


def test_enforcement_across_a_real_renewal_and_rotation(certificates, monkeypatch):
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS", {
        "api.anthropic.com": {_transport.spki_pin(certificates["original"])}})

    def pins(der):
        return [_transport.spki_pin(der), _transport.cert_pin(der)]

    for name in ("original", "renewed"):
        assert _transport.check_pin("api.anthropic.com",
                                    pins(certificates[name])) == \
            _transport.STRENGTH_ENFORCED
    with pytest.raises(_transport.PinMismatch):
        _transport.check_pin("api.anthropic.com", pins(certificates["rotated"]))


def test_a_certificate_pin_fails_the_renewal_it_is_meant_to_survive(
        certificates, monkeypatch):
    monkeypatch.setattr(_transport, "PIN_MODE", _transport.PIN_ENFORCE)
    monkeypatch.setattr(_transport, "TLS_PINS", {
        "api.anthropic.com": {_transport.cert_pin(certificates["original"])}})
    with pytest.raises(_transport.PinMismatch, match="renewal"):
        _transport.check_pin("api.anthropic.com",
                             [_transport.spki_pin(certificates["renewed"]),
                              _transport.cert_pin(certificates["renewed"])])


def test_expiry_is_read_from_a_real_certificate(certificates):
    """The warning that turns a rotation into a scheduled task depends on this
    parsing correctly."""
    not_after = _transport.cert_not_after(certificates["original"])
    assert not_after is not None
    w = _transport.expiry_warning(not_after, threshold_days=100)
    assert 85 <= w["days_remaining"] <= 90 and w["warn"] is True


# --------------------------------------------------------------- error hygiene
def test_provider_error_bodies_are_not_echoed_to_the_caller():
    """Provider error responses can quote the request, including its content.
    The status is enough for the caller; the body is logged server-side."""
    message = _transport.safe_error("anthropic", 429)
    assert message == "anthropic returned HTTP 429"
    assert "prompt" not in message.lower()


# ------------------------------------------------ search calls need longer
def test_a_search_carrying_call_uses_the_longer_timeout():
    """Observed in the field as "transport error: The read operation timed
    out" on the known-facts public prefill.

    The hosted web-search tool runs server-side inside one HTTP response, so a
    sweep of several fact classes sits behind a single read that takes
    minutes. The adapter had one 60-second timeout for every call, sized for a
    plain completion, so every search-using service timed out before it could
    return anything - and reported it as a transport fault rather than as a
    budget that was too small."""
    import inspect
    from app import config
    from app.llm.providers import anthropic_adapter

    assert config.LLM_SEARCH_TIMEOUT_SECONDS > config.LLM_TIMEOUT_SECONDS, (
        "a search-carrying call must be allowed longer than a completion")
    assert config.LLM_SEARCH_TIMEOUT_SECONDS >= 300, (
        "several server-side searches in one response take minutes")

    for method in (anthropic_adapter.AnthropicAdapter.parse,
                   anthropic_adapter.AnthropicAdapter.complete):
        src = inspect.getsource(method)
        assert "self._search_timeout if tools else None" in src, (
            f"{method.__name__} does not lengthen its read when it carries a "
            f"search tool")


def test_the_timeouts_are_configurable_not_hardcoded():
    """60 seconds was a constant in a default argument, so the only remedy for
    a slow network or a long sweep was a rebuild."""
    import inspect
    from app.llm.providers import anthropic_adapter
    src = inspect.getsource(anthropic_adapter.AnthropicAdapter.__init__)
    assert "timeout: float | None = None" in src
    assert "config.LLM_TIMEOUT_SECONDS" in src
