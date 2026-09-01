"""Pinned HTTP transport, with TLS pin observation and enforcement.

httpx defaults to trust_env=True, so HTTP_PROXY, HTTPS_PROXY and SSL_CERT_FILE
from the ambient environment silently redirect calls. That is closed here.

The second audit found a deeper problem: the liveness proof and the transport
pin were not independent. The proof compares the provider's reported clock to
ours, but anyone controlling the endpoint returns `Date: <now>`, which is
trivially inside tolerance. The timestamp control therefore had no strength of
its own - it rested entirely on the transport being genuine, and an operator who
could install a CA in the container image defeated both at once.

TLS pinning supplies the missing independence. A pinned connection fails even
when the trust store has been subverted, because the peer's certificate has to
match a value fixed out of band. Three modes:

    OFF      pins neither recorded nor checked
    OBSERVE  pin recorded on every call, never enforced   (default)
    ENFORCE  a call whose pin is unknown or unmatched FAILS

OBSERVE is the default because a pin you have never seen cannot be configured:
run normally, read the observed values from `make pins`, put them in TLS_PINS,
then switch to ENFORCE. Recording the pin regardless means drift is visible even
when enforcement is off, and means each run carries the strength of the evidence
behind it rather than being presented as equally proven.

Two pins are computed per connection, and either matching is enough:

    sha256/BASE64        SHA-256 of the SubjectPublicKeyInfo (RFC 7469 form)
    cert-sha256/BASE64   SHA-256 of the whole leaf certificate

The first is what should be configured. An earlier revision recorded only the
second, which changes on *every* certificate renewal even when the provider
reuses the same key - so following the instruction to switch to ENFORCE bought a
quarterly outage. An SPKI pin survives renewal and only changes on a genuine key
rotation.

Pins are self-describing by prefix so the two can never be compared to each
other, and both are offered so an existing certificate pin keeps working while
an operator migrates.

Key rotation still moves an SPKI pin, so the connection also records the leaf
certificate's expiry. That turns the day enforcement would have broken into a
date reported in advance by `make pins` and /v1/health, which is the difference
between a scheduled task and an outage.
"""
import base64
import hashlib
import logging
import os
from datetime import datetime, timezone

import httpx

try:                                             # pragma: no cover - import guard
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    _CRYPTO = True
except ImportError:                              # pragma: no cover
    _CRYPTO = False

log = logging.getLogger("workbench.transport")

EGRESS_PROXY = os.getenv("LLM_EGRESS_PROXY") or None

# Explicit trust anchor. trust_env=False makes httpx ignore SSL_CERT_FILE and
# REQUESTS_CA_BUNDLE by design, because an ambient variable that silently
# changes who is trusted is the defect that made provider calls redirectable.
# A corporate anchor is therefore named here instead: a deployment input rather
# than whatever the shell happened to export, and recorded on every call.
CA_BUNDLE = os.getenv("LLM_CA_BUNDLE") or None

# Last resort for a network whose inspection cannot be trusted from the
# container at all. Off, loud when on, and never a silent default.
INSECURE_SKIP_VERIFY = (
    os.getenv("LLM_INSECURE_SKIP_TLS_VERIFY", "false").lower() == "true")

PIN_OFF, PIN_OBSERVE, PIN_ENFORCE = "OFF", "OBSERVE", "ENFORCE"
PIN_MODE = (os.getenv("TLS_PIN_MODE") or PIN_OBSERVE).upper()
PIN_EXPIRY_WARN_DAYS = int(os.getenv("TLS_PIN_EXPIRY_WARN_DAYS", "21"))

# Enforcing on certificate hashes alone is the pre-C3-03 behaviour: the pin
# changes on every renewal and, without cryptography, there is no expiry to warn
# on either. An operator who genuinely wants that must say so.
ALLOW_CERT_ONLY_ENFORCE = (
    os.getenv("TLS_PIN_ALLOW_CERT_ONLY", "false").lower() == "true")

# Enforcing without the ability to compute an SPKI pin is the configuration
# C3-03 exists to prevent. Set only if you have accepted the renewal exposure.
ALLOW_CERT_ONLY_PINNING = (
    os.getenv("TLS_ALLOW_CERT_ONLY_PINNING", "false").lower() == "true")

# Provenance strength recorded per call.
STRENGTH_ENFORCED = "PINNED_AND_ENFORCED"
STRENGTH_OBSERVED = "PINNED_OBSERVED"
STRENGTH_TRANSPORT_ONLY = "TRANSPORT_ONLY"


def _parse_pins(raw: str | None) -> dict:
    """TLS_PINS="api.anthropic.com:BASE64,api.openai.com:BASE64" - repeat a host
    to allow several pins, which is how a certificate rotation is survived."""
    pins: dict[str, set] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        host, pin = entry.split(":", 1)
        pins.setdefault(host.strip(), set()).add(pin.strip())
    return pins


TLS_PINS = _parse_pins(os.getenv("TLS_PINS"))


class PinMismatch(RuntimeError):
    """The peer certificate did not match any configured pin."""


class PinUnavailable(RuntimeError):
    """The peer certificate could not be read, so the pin cannot be checked."""


class PinConfigurationRefused(RuntimeError):
    """The pinning configuration would fail silently rather than protect."""


class PinningUnsupported(RuntimeError):
    """Enforcement is on but SPKI pins cannot be computed."""


def spki_supported() -> bool:
    return _CRYPTO


def assert_pinning_supported() -> None:
    """Refuse to start in the one combination that silently reverts C3-03.

    Without `cryptography` only certificate hashes can be computed, and a
    certificate hash changes on every renewal. So ENFORCE without it is either
    broken immediately - a configured `sha256/` pin can never match a
    `cert-sha256/` observation - or a scheduled outage on the provider's next
    renewal, with no expiry warning because the expiry cannot be read either.

    Both are worse than not starting, and a warning in a log nobody reads is
    what "silently" means. TLS_ALLOW_CERT_ONLY_PINNING is the deliberate
    override for someone who has accepted the exposure.
    """
    # FINDING (unresolved, needs an owner's decision): this same condition -
    # ENFORCE without cryptography - is refused in TWO places, with two
    # exception types and two different override names:
    #
    #   here            -> PinningUnsupported,      TLS_ALLOW_CERT_ONLY_PINNING
    #   assert_safe()   -> PinConfigurationRefused, TLS_PIN_ALLOW_CERT_ONLY
    #
    # Both fail closed, so there is no security hole. The trap is operational:
    # an operator who sets the override this message names is still refused by
    # the other check demanding a differently-named variable, with a message
    # that does not mention the one they just set. Pick one name and one
    # exception; this comment is here rather than a silent unification because
    # collapsing a security control on inference alone is not a safe edit.
    if PIN_MODE != PIN_ENFORCE or _CRYPTO or ALLOW_CERT_ONLY_PINNING:
        return
    raise PinningUnsupported(
        "TLS_PIN_MODE=ENFORCE but the cryptography package is unavailable, so "
        "only certificate hashes can be computed. A certificate pin changes on "
        "every renewal and its expiry cannot be read, so enforcement would fail "
        "either now or silently at the next rotation. Install cryptography, or "
        "set TLS_ALLOW_CERT_ONLY_PINNING=true to accept the renewal exposure "
        "deliberately.")


def verification():
    """What this transport verifies against, and why.

    Returns the value handed to httpx `verify=`. A path means a named bundle;
    True means the default; False means verification is off, which is only
    reachable by setting LLM_INSECURE_SKIP_TLS_VERIFY and is reported wherever
    transport state is reported.
    """
    if INSECURE_SKIP_VERIFY:
        return False
    if CA_BUNDLE and os.path.exists(CA_BUNDLE):
        return CA_BUNDLE
    return True


def client(timeout: float) -> httpx.Client:
    kwargs = {"timeout": timeout, "trust_env": False,
              "verify": verification(), "follow_redirects": False}
    if EGRESS_PROXY:
        kwargs["proxy"] = EGRESS_PROXY
    return httpx.Client(**kwargs)


def outbound_client(timeout: float) -> httpx.Client:
    """For fetching arbitrary third-party URLs - source verification in
    domain/research.py - not for provider calls.

    Same egress path and same trust anchor as a provider call, because a
    network that requires a proxy requires it for every host, and a proxy that
    re-signs provider traffic re-signs everything else too. Source
    verification previously used a bare `httpx.get`, so on a proxied network
    LLM_EGRESS_PROXY fixed the provider call and left every source fetch
    timing out - which then surfaced as an exhausted research budget rather
    than as the configuration gap it was.

    What this deliberately does NOT carry is the pin. TLS_PINS is a statement
    about specific provider hosts; it means nothing for a URL a model happened
    to cite, and applying it there would fail every fetch.

    follow_redirects is on, unlike the provider client: an article moving to a
    canonical URL is ordinary, and refusing to follow it would report a live
    source as unreachable.
    """
    kwargs = {"timeout": timeout, "trust_env": False,
              "verify": verification(), "follow_redirects": True}
    if EGRESS_PROXY:
        kwargs["proxy"] = EGRESS_PROXY
    return httpx.Client(**kwargs)


def spki_pin(der: bytes) -> str | None:
    """RFC 7469 form: SHA-256 of the SubjectPublicKeyInfo. Survives certificate
    renewal, because the key is unchanged. None when cryptography is absent."""
    if not _CRYPTO:
        return None
    try:
        cert = x509.load_der_x509_certificate(der)
        spki = cert.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo)
        return "sha256/" + base64.b64encode(hashlib.sha256(spki).digest()).decode()
    except Exception as exc:                                  # noqa: BLE001
        log.debug("SPKI pin unavailable: %s", exc)
        return None


def cert_pin(der: bytes) -> str:
    """SHA-256 of the whole leaf certificate. Changes on every renewal, so it is
    a fallback rather than the recommended form."""
    return "cert-sha256/" + base64.b64encode(hashlib.sha256(der).digest()).decode()


def cert_not_after(der: bytes) -> datetime | None:
    """Leaf expiry. The pin will change no later than this, so reporting it is
    what makes ENFORCE operable rather than a quarterly surprise."""
    if not _CRYPTO:
        return None
    try:
        cert = x509.load_der_x509_certificate(der)
        value = getattr(cert, "not_valid_after_utc", None)
        if value is None:                        # cryptography < 42
            value = cert.not_valid_after.replace(tzinfo=timezone.utc)
        return value
    except Exception as exc:                                  # noqa: BLE001
        log.debug("certificate expiry unavailable: %s", exc)
        return None


def peer_der(response) -> bytes | None:
    """The peer's DER certificate, read from the connection that carried this
    response.

    Read in band deliberately. A separate handshake to the same host would be
    simpler, but an interceptor could serve a genuine certificate on that probe
    and its own on the real request - so the pin has to come from the connection
    the answer actually arrived on.
    """
    try:
        stream = response.extensions.get("network_stream")
        if stream is None:
            return None
        ssl_object = stream.get_extra_info("ssl_object")
        if ssl_object is None:
            return None                      # plain HTTP, e.g. a local test server
        return ssl_object.getpeercert(binary_form=True) or None
    except Exception as exc:                                  # noqa: BLE001
        log.debug("peer certificate unavailable: %s", exc)
        return None


def peer_pins(response) -> tuple[list, str | None, datetime | None]:
    """Returns (all pins, preferred pin, certificate expiry).

    The preferred pin is the SPKI one where available, because that is the value
    an operator should configure.
    """
    der = peer_der(response)
    if der is None:
        return [], None, None
    pins, spki = [], spki_pin(der)
    if spki:
        pins.append(spki)
    pins.append(cert_pin(der))
    return pins, pins[0], cert_not_after(der)


def check_pin(host: str, pins) -> str:
    """Returns the provenance strength for this call, or raises under ENFORCE.

    `pins` is every pin computed for the connection. Any one matching is enough,
    so an operator migrating from certificate pins to SPKI pins is never locked
    out mid-change.
    """
    if isinstance(pins, str) or pins is None:    # tolerate a single value
        pins = [pins] if pins else []

    if PIN_MODE == PIN_OFF:
        return STRENGTH_TRANSPORT_ONLY

    if PIN_MODE == PIN_ENFORCE:
        expected = TLS_PINS.get(host)
        if not expected:
            raise PinMismatch(
                f"TLS_PIN_MODE=ENFORCE but no pin is configured for {host}. "
                f"Run in OBSERVE mode, take the value from `make pins`, and set "
                f"TLS_PINS before enforcing.")
        if not pins:
            # Cannot verify, so do not proceed. An unreadable certificate under
            # enforcement is exactly the shape an interception would take.
            raise PinUnavailable(
                f"peer certificate for {host} could not be read; refusing to "
                f"treat an unverifiable connection as pinned")
        if not set(pins) & expected:
            only_cert = all(p.startswith("cert-sha256/") for p in expected)
            wants_spki = any(p.startswith("sha256/") for p in expected)
            if wants_spki and not _CRYPTO:
                hint = ("  An SPKI pin is configured but cryptography is "
                        "unavailable, so only a certificate hash could be "
                        "computed and the two can never match. Install "
                        "cryptography.")
            elif only_cert:
                hint = ("  The configured pin is a certificate hash, which "
                        "changes on every renewal; a sha256/ SPKI pin would "
                        "have survived it.")
            else:
                hint = ""
            raise PinMismatch(
                f"peer certificate for {host} matches no configured pin. "
                f"Observed {pins}.{hint} Either the certificate rotated or the "
                f"trust store has been subverted - check the expiry reported by "
                f"`make pins` before assuming the latter.")
        return STRENGTH_ENFORCED

    # OBSERVE
    if not pins:
        return STRENGTH_TRANSPORT_ONLY
    expected = TLS_PINS.get(host)
    if expected and not set(pins) & expected:
        log.warning("TLS pin drift for %s: observed %s, configured %s",
                    host, pins, sorted(expected))
    return STRENGTH_OBSERVED


def expiry_warning(not_after, threshold_days: int = None) -> dict | None:
    """A pin changes when the certificate does, so the expiry is the deadline
    for updating TLS_PINS."""
    if not_after is None:
        return None
    days = (not_after - datetime.now(timezone.utc)).days
    limit = PIN_EXPIRY_WARN_DAYS if threshold_days is None else threshold_days
    return {"not_after": not_after.isoformat(), "days_remaining": days,
            "warn": days <= limit,
            "message": (f"pinned certificate expires in {days} day(s); update "
                        f"TLS_PINS before then or ENFORCE will start failing"
                        if days <= limit else None)}


def tls_posture() -> dict:
    """Where trust comes from, stated plainly.

    An operator on an inspected network needs to know whether verification is
    on, against what, and whether a pinned connection means what it appears to.
    """
    verify = verification()
    corporate = bool(CA_BUNDLE and os.path.exists(CA_BUNDLE))
    return {
        "verification": ("DISABLED" if verify is False
                         else f"named bundle: {CA_BUNDLE}" if corporate
                         else "default trust store"),
        "ca_bundle": CA_BUNDLE if corporate else None,
        "insecure_skip_verify": INSECURE_SKIP_VERIFY,
        "egress_proxy": EGRESS_PROXY,
        "pinning_caveat": (
            "Behind an inspecting proxy a pinned connection pins the inspector, "
            "not the provider. ENFORCE still detects the inspector's certificate "
            "changing; it cannot attest that the provider was reached."
            if (EGRESS_PROXY or corporate) else None),
    }


def startup_check() -> list:
    """Refuse a pinning configuration that would degrade silently.

    If `cryptography` is missing - a failed install, a stripped image - SPKI
    pinning is unavailable, so only certificate hashes can be computed. Under
    ENFORCE that is the pre-C3-03 behaviour: the pin breaks on the provider's
    next renewal, and with no certificate parsing there is no expiry to warn on,
    so the first sign is every call failing.

    A missing library must not quietly undo a fix. Returns warnings; raises when
    the combination is one that would fail closed on a date nobody was told
    about.
    """
    warnings = []
    if INSECURE_SKIP_VERIFY:
        warnings.append(
            "LLM_INSECURE_SKIP_TLS_VERIFY is set: certificate verification is "
            "OFF for every provider call. Any host on the path can read and "
            "alter them. Supply the corporate CA in certs/ instead.")
        if PIN_MODE == PIN_ENFORCE:
            raise PinConfigurationRefused(
                "TLS_PIN_MODE=ENFORCE with LLM_INSECURE_SKIP_TLS_VERIFY=true. "
                "Pinning an unverified connection is theatre: the pin would be "
                "whatever the peer offered. Choose one.")
    if CA_BUNDLE and not os.path.exists(CA_BUNDLE):
        warnings.append(
            f"LLM_CA_BUNDLE points at {CA_BUNDLE}, which does not exist. "
            f"Falling back to the default trust store, which will fail behind "
            f"an inspecting proxy.")
    # One description of degraded SPKI support, not two. spki_warning() already
    # carried it for the pins endpoint.
    degraded = spki_warning()
    if degraded:
        warnings.append(degraded["message"])
        if PIN_MODE == PIN_ENFORCE and not ALLOW_CERT_ONLY_ENFORCE:
            raise PinConfigurationRefused(
                "TLS_PIN_MODE=ENFORCE without cryptography. Only certificate "
                "hashes can be computed, so the pin will break on the provider's "
                "next renewal - and with no certificate parsing there is no "
                "expiry warning, so the first sign would be every LIVE call "
                "failing. Install cryptography, or set "
                "TLS_PIN_ALLOW_CERT_ONLY=true to accept that trade knowingly.")
    if PIN_MODE == PIN_ENFORCE and not TLS_PINS:
        raise PinConfigurationRefused(
            "TLS_PIN_MODE=ENFORCE with no pins configured in TLS_PINS. Every "
            "LIVE call would fail. Run in OBSERVE, take the values from "
            "`make pins`, then enforce.")
    cert_only = [h for h, pins in TLS_PINS.items()
                 if pins and all(p.startswith("cert-sha256/") for p in pins)]
    if cert_only and PIN_MODE == PIN_ENFORCE:
        warnings.append(
            f"pinned by certificate hash only: {', '.join(sorted(cert_only))}. "
            f"These break on the next renewal; prefer the sha256/ SPKI form.")
    return warnings


def safe_error(provider: str, status: int) -> str:
    """Provider error bodies can echo request content. The status is enough for
    the caller; the body is logged server-side only."""
    return f"{provider} returned HTTP {status}"


def transport_error(provider: str, exc: Exception) -> str:
    """An httpx transport failure, translated into what to do about it.

    The raw text is kept - an operator pasting it into a ticket needs it - but
    an unadorned `[SSL: UNEXPECTED_EOF_WHILE_READING]` in the interface reads
    as a certificate problem and sends people to certs/, which is the one
    remedy that cannot help: nothing rejected a certificate, the connection
    was cut. On a network where egress must traverse a proxy that is exactly
    what a direct call looks like, and provider calls go direct by default
    because trust_env=False makes them ignore the ambient HTTPS_PROXY the rest
    of the machine uses (see the module docstring for why that is deliberate).
    """
    detail = str(exc)
    hint = ""
    if "UNEXPECTED_EOF" in detail or "EOF occurred" in detail or "reset" in detail.lower():
        if EGRESS_PROXY:
            hint = (" The connection was cut rather than refused, and "
                   f"LLM_EGRESS_PROXY is set to {EGRESS_PROXY} - check that "
                   "value is reachable and permitted to reach this host. This "
                   "is not a certificate problem; adding a CA will not fix it.")
        else:
            hint = (" The connection was cut rather than refused, after "
                   "retrying. If other calls in the same run succeeded this is "
                   "a transient cut - most often an intermediary dropping a "
                   "long-lived request, which is what a searching call is - and "
                   "the remedy is to "
                   "re-run that domain, not to change the configuration. "
                   "If every call fails the same way, it is "
                   "configuration. This is not a "
                   "certificate problem - adding a CA to certs/ will not fix "
                   "it. If this network requires a proxy for outbound HTTPS, "
                   "set LLM_EGRESS_PROXY in .env: provider calls ignore the "
                   "ambient HTTPS_PROXY by design, so a direct call past a "
                   "mandatory proxy fails exactly like this. Run "
                   "`make tls-doctor` to confirm which it is.")
    elif "CERTIFICATE_VERIFY_FAILED" in detail:
        hint = (" The peer's certificate was rejected by this container's trust "
               "store, which is what an inspecting proxy looks like when its "
               "CA is missing. Put the CA in certs/ and rebuild; "
               "`make tls-doctor` names the issuer to look for.")
    return f"{provider} transport error: {detail}{hint}"


def spki_warning() -> dict | None:
    """Reported wherever pins are, so degraded support is visible rather than a
    boolean nobody reads."""
    if _CRYPTO:
        return None
    return {
        "spki_supported": False,
        "severity": "ERROR" if PIN_MODE == PIN_ENFORCE else "WARNING",
        "message": (
            "cryptography is unavailable, so only certificate hashes can be "
            "computed. Certificate pins break on every renewal and their expiry "
            "cannot be read, so no advance warning is possible. This is the "
            "behaviour C3-03 replaced."),
        "remedy": "install cryptography (it is in api_service/requirements.txt)",
    }


def pin_status() -> dict:
    configured = {h: sorted(p) for h, p in TLS_PINS.items()}
    cert_only = sorted(h for h, p in TLS_PINS.items()
                       if p and all(x.startswith("cert-sha256/") for x in p))
    try:
        warnings = startup_check()
        refused = None
    except PinConfigurationRefused as exc:
        warnings, refused = [], str(exc)
    return {"mode": PIN_MODE,
            "tls": tls_posture(),
            "spki_supported": _CRYPTO,
            "warnings": warnings,
            "refused": refused,
            "hosts_configured": sorted(TLS_PINS),
            "configured_pins": configured,
            "hosts_pinned_by_certificate_only": cert_only,
            "certificate_pin_caveat": (
                "these break on every certificate renewal; prefer a sha256/ SPKI pin"
                if cert_only else None),
            "expiry_warn_days": PIN_EXPIRY_WARN_DAYS,
            "spki_warning": spki_warning(),
            "allow_cert_only_pinning": ALLOW_CERT_ONLY_PINNING,
            "egress_proxy": EGRESS_PROXY}
