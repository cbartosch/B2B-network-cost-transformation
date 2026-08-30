#!/usr/bin/env python3
"""TLS diagnosis for a corporate network.

An SSL failure inside a container produces a stack trace that names a library,
not the problem. On an inspected network the problem is almost always one of
three things, and they need different fixes:

    1. no corporate CA in the image      -> put the .crt in certs/, rebuild
    2. an egress proxy is required       -> set LLM_EGRESS_PROXY
    3. the endpoint is blocked outright  -> nothing here can fix that

This reports which. Standard library only, so it runs during a build failure as
well as after one: `make tls-doctor`, or `python tools/tls_doctor.py`.
"""
import os
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse

ENDPOINTS = [
    ("PyPI (needed to build)", "https://pypi.org"),
    ("PyPI files", "https://files.pythonhosted.org"),
    ("Anthropic", "https://api.anthropic.com"),
    ("OpenAI", "https://api.openai.com"),
]

SYSTEM_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
CORPORATE_DIR = "/usr/local/share/ca-certificates/corporate"


def _line(label, value):
    print(f"  {label:<34} {value}")


def _resolves(host: str):
    """DNS only. Separates 'the name does not resolve' from 'it resolves and
    the connection is refused or dropped' - different faults, different teams."""
    try:
        return True, socket.gethostbyname(host), None
    except OSError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


def _via_proxy(proxy_url: str, host: str, port: int = 443, timeout: int = 8):
    """HTTP CONNECT through a proxy. Answers the question the direct probes
    cannot: is this host reachable *when the proxy is used properly*? A
    network where egress is mandatory-proxied fails every direct probe below
    while working perfectly through here, and the two results together are
    what distinguish 'blocked' from 'you have not told the app about the
    proxy'."""
    parsed = urlparse(proxy_url if "://" in proxy_url else f"http://{proxy_url}")
    if not parsed.hostname:
        return False, f"could not parse proxy URL {proxy_url!r}"
    try:
        with socket.create_connection(
                (parsed.hostname, parsed.port or 8080), timeout=timeout) as raw:
            raw.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\n"
                        f"Host: {host}:{port}\r\n\r\n".encode())
            reply = raw.recv(256).decode("latin-1", "replace").split("\r\n")[0]
        return ("200" in reply), reply.strip() or "empty reply"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _issuer(host: str, port: int = 443, cafile: str | None = None):
    """Return (ok, issuer_common_name, error). The issuer is the tell: a
    corporate name there means the connection is being inspected."""
    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=8) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert() or {}
                issuer = dict(x[0] for x in cert.get("issuer", ())).get(
                    "commonName", "unknown")
                return True, issuer, None
    except ssl.SSLCertVerificationError as exc:
        return False, None, f"certificate not trusted: {exc.verify_message or exc}"
    except (socket.timeout, TimeoutError):
        return False, None, "timed out - blocked, or a proxy is required"
    except ssl.SSLError as exc:
        # An EOF mid-handshake is not a trust problem: nothing was rejected,
        # the connection was cut. On an inspected network that is what a
        # policy block looks like when the proxy resets rather than refusing,
        # and it is also what a *mandatory* proxy looks like when the client
        # tries to connect directly past it - which the provider transport
        # does by default, since trust_env=False makes it ignore the ambient
        # HTTPS_PROXY the rest of the machine uses. Classified separately
        # because the remedy is different from either of the two above.
        detail = str(exc)
        if "UNEXPECTED_EOF" in detail or "EOF occurred" in detail:
            return False, None, f"connection cut during handshake: {detail}"
        return False, None, f"SSL error: {detail}"
    except ConnectionResetError as exc:
        return False, None, f"connection reset: {exc}"
    except OSError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


def main() -> int:
    print("TLS diagnosis\n")

    print("Trust anchors")
    corporate = sorted(Path(CORPORATE_DIR).glob("*.crt")) if Path(CORPORATE_DIR).exists() else []
    _line("corporate CAs supplied", f"{len(corporate)}" if corporate else "none")
    for c in corporate:
        _line("", c.name)
    _line("system bundle", SYSTEM_BUNDLE if Path(SYSTEM_BUNDLE).exists() else "MISSING")
    _line("LLM_CA_BUNDLE", os.getenv("LLM_CA_BUNDLE") or "unset")
    _line("LLM_EGRESS_PROXY", os.getenv("LLM_EGRESS_PROXY") or "unset")
    _line("verification disabled",
          "YES - every call is readable in transit"
          if os.getenv("LLM_INSECURE_SKIP_TLS_VERIFY", "").lower() == "true" else "no")

    ambient = {k: v for k, v in os.environ.items()
               if k.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "SSL_CERT_FILE",
                                "REQUESTS_CA_BUNDLE", "NO_PROXY")}
    if ambient:
        print("\nAmbient variables (deliberately ignored by the provider transport)")
        for k, v in sorted(ambient.items()):
            _line(k, v)
        print("  These are honoured by pip and by this script, and not by provider")
        print("  calls - see certs/README.md for why.")

    bundle = os.getenv("LLM_CA_BUNDLE") if Path(
        os.getenv("LLM_CA_BUNDLE") or "/nonexistent").exists() else None

    print("\nEndpoints")
    inspected = False
    failures = []
    dns_failures = []
    for label, url in ENDPOINTS:
        host = urlparse(url).hostname
        resolved, addr, dns_error = _resolves(host)
        if not resolved:
            _line(label, f"FAIL DNS: {dns_error}")
            dns_failures.append((label, dns_error))
            failures.append((label, f"dns: {dns_error}"))
            continue
        ok, issuer, error = _issuer(host, cafile=bundle)
        if ok:
            _line(label, f"OK   issuer: {issuer}")
            if issuer and not any(
                    t in issuer.lower() for t in ("amazon", "digicert", "let's encrypt",
                                                  "globalsign", "sectigo", "google",
                                                  "baltimore", "isrg")):
                inspected = True
        else:
            _line(label, f"FAIL {error}   (dns ok: {addr})")
            failures.append((label, error))

    # A direct probe cannot distinguish "blocked" from "proxy is mandatory and
    # was not used". If a proxy is named anywhere, try it - a host that fails
    # above and succeeds here is a configuration gap, not a policy block.
    proxy = (os.getenv("LLM_EGRESS_PROXY") or os.getenv("HTTPS_PROXY")
             or os.getenv("https_proxy") or "")
    proxy_results = []
    if proxy and failures:
        print(f"\nThrough the proxy ({proxy})")
        for label, url in ENDPOINTS:
            host = urlparse(url).hostname
            ok, detail = _via_proxy(proxy, host)
            _line(label, f"{'OK  ' if ok else 'FAIL'} {detail}")
            proxy_results.append((label, ok))
    elif failures and not proxy:
        print("\nThrough the proxy")
        _line("no proxy configured",
              "LLM_EGRESS_PROXY and HTTPS_PROXY are both unset")

    print("\nDiagnosis")
    if inspected:
        print("  The certificate issuer is not a public CA, so TLS is being")
        print("  inspected. That is expected on a corporate network and is not a")
        print("  fault - it only means the anchor must be supplied deliberately.")
    if not failures:
        print("  Every endpoint verified. No TLS problem to fix.")
        if inspected and not corporate:
            print("  Note: verification succeeded against the host's own trust store.")
            print("  Inside the image it will not, unless certs/ holds the CA.")
        return 0

    untrusted = [f for f in failures if "not trusted" in (f[1] or "")]
    blocked = [f for f in failures if "timed out" in (f[1] or "")]
    cut = [f for f in failures
           if "connection cut" in (f[1] or "") or "connection reset" in (f[1] or "")]
    if dns_failures:
        print("  DNS did not resolve. Nothing was blocked or rejected - the name")
        print("  could not be looked up at all, which is a container networking")
        print("  fault rather than a TLS or policy one. On Docker Desktop check")
        print("  that the VM has the corporate DNS servers, and restart Docker.")
    if any(ok for _, ok in proxy_results):
        print("  Reachable THROUGH THE PROXY but not directly. This is a")
        print("  configuration gap, not a policy block: egress on this network is")
        print("  mandatory-proxied, and provider calls deliberately ignore the")
        print("  ambient HTTPS_PROXY. Name it explicitly in .env and rebuild:")
        print(f"      LLM_EGRESS_PROXY={proxy}")
        print("      docker compose up --build -d")
        return 1
    if proxy_results and not any(ok for _, ok in proxy_results):
        print("  Unreachable directly AND through the configured proxy. Either the")
        print("  proxy address is wrong, or policy blocks these hosts. Confirm the")
        print("  proxy with your network team before assuming the latter.")
    if untrusted:
        print("  Certificates are not trusted. The inspecting proxy's CA is missing")
        print("  from this trust store. Export it, put the .crt in certs/, rebuild:")
        print("      make check && docker compose build --no-cache")
    if cut:
        print("  The connection was cut during the TLS handshake. Nothing rejected a")
        print("  certificate, so this is NOT a missing-CA problem and adding a CA to")
        print("  certs/ will not fix it. Two things look like this:")
        print()
        print("    1. Egress must traverse a proxy, and the call went direct.")
        print("       Provider calls set trust_env=False, so the ambient HTTPS_PROXY")
        print("       the rest of the machine uses is deliberately ignored. Name it:")
        print("           LLM_EGRESS_PROXY=http://proxy.host:port   in .env")
        print("       Take the value from your shell:  echo $HTTPS_PROXY")
        print()
        print("    2. Policy blocks the host outright and the proxy resets rather")
        print("       than refusing. Confirm with your network team; if Anthropic")
        print("       is blocked, LIVE runs fail closed and the deterministic half")
        print("       of Stage 0 still works.")
    if blocked:
        print("  Connections timed out. Either the endpoint is blocked by policy,")
        print("  or an egress proxy is mandatory. If a proxy is required:")
        print("      LLM_EGRESS_PROXY=http://proxy.host:port  in .env")
        print("  If Anthropic and OpenAI are blocked but PyPI is not, the bundle")
        print("  still builds and runs - LIVE agent runs fail closed, and every")
        print("  deterministic part of Stage 0 works without a provider.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
