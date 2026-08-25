# Corporate TLS trust anchors

Put your organisation's root CA certificates here, as `.crt` files in PEM
format. Anything in this directory is installed into both images at build time
and becomes the trust anchor for `pip` during the build and for provider calls
at runtime.

    certs/
      corporate-root.crt
      corporate-issuing.crt      # if the chain has an intermediate

**Why this is needed.** An inspecting proxy — Zscaler, Netskope, Palo Alto and
similar — terminates TLS and re-signs it with a certificate the container has
never seen. Verification then fails, correctly, and everything that talks HTTPS
stops: `pip install` during the build, and every provider call afterwards.

**Why the certificates are not simply trusted from the environment.** The
transport sets `trust_env=False`, so `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE`
are deliberately ignored — an ambient variable that silently changes who is
trusted is the defect that made provider calls redirectable in the first place.
Supplying the anchor here makes it a build input: visible, versioned with the
deployment, and recorded on every call rather than picked up from whatever
happened to be set.

## Getting the certificate

**Run this.** It connects to the hosts the build needs, asks Windows to build
the chain it would use, and writes every issuer to this directory. No guessing
at vendor names — whatever is actually inspecting your connection ends up in the
file.

```powershell
powershell -ExecutionPolicy Bypass -File tools\export_corporate_ca.ps1
docker compose build --no-cache
docker compose up -d
```

### Manual alternatives

If the script cannot run, **Windows**, where the CA is already in the machine
store:

```powershell
Get-ChildItem Cert:\LocalMachine\Root |
  Where-Object { $_.Subject -match "Zscaler|Netskope|YourCompany" } |
  ForEach-Object {
    $b = [Convert]::ToBase64String($_.RawData, 'InsertLineBreaks')
    "-----BEGIN CERTIFICATE-----`n$b`n-----END CERTIFICATE-----" |
      Out-File -Encoding ascii "certs\$($_.Thumbprint).crt"
  }
```

Or export via `certmgr.msc` → Trusted Root Certification Authorities → the
inspection CA → All Tasks → Export → **Base-64 encoded X.509 (.CER)** → rename
to `.crt`.

**From the connection itself**, which shows you exactly what is being presented:

```powershell
openssl s_client -showcerts -connect api.anthropic.com:443 </dev/null
```

The last certificate in the chain is the root you need.

## Verifying

    make tls-doctor

Reports whether a corporate anchor is installed, what each endpoint presents,
and which specific step is failing. Run it before reading error messages.

## What this does not do

It does not make TLS pinning meaningful under interception. A pinned connection
through an inspecting proxy pins **the inspector**, not the provider — the
proxy is a legitimate man in the middle by policy. `TLS_PIN_MODE=ENFORCE` on an
inspected network is still useful, because it detects the inspector's
certificate changing, but it cannot attest that you reached Anthropic or OpenAI.
Say so rather than reporting a pinned connection as end-to-end.

Files here are gitignored. Do not commit them.
