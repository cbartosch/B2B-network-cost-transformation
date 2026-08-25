#!/usr/bin/env python3
"""Fail the build early, and say why.

Without this, a missing trust anchor surfaces as twelve seconds of pip retries
ending in `CERTIFICATE_VERIFY_FAILED`, which names a symptom rather than a
cause. This probes one host before pip runs and, if verification fails, states
the fix in the build output where the failure is.

Only distinguishes cases it can be sure about. A timeout is not a certificate
problem, so it says nothing and lets pip report it.
"""
import socket
import ssl
import sys

HOST = "pypi.org"

try:
    with socket.create_connection((HOST, 443), timeout=15) as raw:
        with ssl.create_default_context().wrap_socket(raw, server_hostname=HOST):
            pass
except ssl.SSLCertVerificationError:
    sys.exit(
        "\n"
        "  TLS verification failed against pypi.org.\n"
        "\n"
        "  This network re-signs HTTPS with a CA the image does not trust -\n"
        "  standard on a managed laptop. Your host trusts it, which is why the\n"
        "  browser works and this does not.\n"
        "\n"
        "  Export the CA your network actually presents and rebuild:\n"
        "\n"
        "      powershell -ExecutionPolicy Bypass -File tools\\export_corporate_ca.ps1\n"
        "      docker compose build --no-cache\n"
        "\n"
        "  See certs/README.md for the manual route and why the certificate is\n"
        "  a build input rather than something read from the environment.\n")
except Exception:
    # Blocked, offline, or proxied. Not a certificate fault; let pip say so.
    pass
