# Optional corporate root CA certificates

If the Docker image build fails with `CERTIFICATE_VERIFY_FAILED`, the Linux
container does not trust the CA used by the corporate proxy or security gateway.
The bundle supports safe CA injection without disabling TLS verification.

## Fastest Windows option

From PowerShell in the bundle directory:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\export_windows_trusted_roots.ps1

docker compose down
docker compose build --no-cache api ui
docker compose up -d
.\scripts\docker_smoke.ps1
```

The helper exports the public trusted-root certificates from the Windows Current
User and Local Machine stores into this directory. It does **not** export private
keys. Generated `.crt` files are ignored by Git.

## Preferred minimal option

Export only the organization's TLS-inspection root CA as **Base-64 encoded X.509
/ PEM** and save it here, for example:

```text
certs/corporate-root-ca.crt
```

The first line must be:

```text
-----BEGIN CERTIFICATE-----
```

Then rebuild without cache:

```powershell
docker compose down
docker compose build --no-cache api ui
docker compose up -d
.\scripts\docker_smoke.ps1
```

If the certificate was exported as binary DER `.cer`, convert it first:

```powershell
certutil -encode .\corporate-root-ca.cer .\certs\corporate-root-ca.crt
```

Do not use `--trusted-host`, `PIP_NO_VERIFY_CERTS`, or disabled TLS verification as
a permanent workaround.
