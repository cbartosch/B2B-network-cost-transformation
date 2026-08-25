<#
.SYNOPSIS
  Export the CA chain your network actually presents, into certs/.

.DESCRIPTION
  The build failed with CERTIFICATE_VERIFY_FAILED because an inspecting proxy
  re-signs HTTPS and the container does not trust the re-signing CA. Your
  laptop does trust it - that is why the browser works and the container does
  not.

  Rather than guessing which root that is by vendor name, this connects to the
  hosts the build needs, asks Windows to build the certificate chain it would
  use, and writes every issuer in that chain to certs/ as PEM. Whatever is
  actually inspecting the connection ends up in the file.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\export_corporate_ca.ps1
#>

$ErrorActionPreference = "Stop"
$certsDir = Join-Path $PSScriptRoot "..\certs"
$hosts = @("pypi.org", "files.pythonhosted.org", "api.anthropic.com", "api.openai.com")

function Export-Pem {
    param($Cert, $Path)
    $b64 = [Convert]::ToBase64String($Cert.RawData, 'InsertLineBreaks')
    "-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----" |
        Out-File -Encoding ascii -FilePath $Path
}

$written = @{}
foreach ($h in $hosts) {
    Write-Host "Inspecting $h ..." -NoNewline
    try {
        $tcp = [Net.Sockets.TcpClient]::new($h, 443)
        # Accept whatever is presented: the point is to see it, not trust it.
        $ssl = [Net.Security.SslStream]::new($tcp.GetStream(), $false,
                   { param($s,$c,$ch,$e) $true })
        $ssl.AuthenticateAsClient($h)
        $leaf = [Security.Cryptography.X509Certificates.X509Certificate2]::new($ssl.RemoteCertificate)
        $ssl.Dispose(); $tcp.Close()

        $chain = [Security.Cryptography.X509Certificates.X509Chain]::new()
        $chain.ChainPolicy.RevocationMode = 'NoCheck'
        [void]$chain.Build($leaf)

        # Skip the leaf; everything above it is an issuer worth trusting.
        $issuers = $chain.ChainElements | Select-Object -Skip 1
        if (-not $issuers) {
            Write-Host " no issuers returned (unusual)" -ForegroundColor Yellow
            continue
        }
        foreach ($el in $issuers) {
            $c = $el.Certificate
            if ($written.ContainsKey($c.Thumbprint)) { continue }
            $safe = ($c.Subject -replace '[^A-Za-z0-9]+','-').Trim('-')
            if ($safe.Length -gt 60) { $safe = $safe.Substring(0,60) }
            Export-Pem -Cert $c -Path (Join-Path $certsDir "$safe.crt")
            $written[$c.Thumbprint] = $c.Subject
        }
        Write-Host " ok"
    } catch {
        Write-Host " unreachable: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host ""
if ($written.Count -eq 0) {
    Write-Host "No certificates exported. Every host was unreachable - that is a" -ForegroundColor Red
    Write-Host "connectivity problem, not a certificate one. Run: make tls-doctor" -ForegroundColor Red
    exit 1
}
Write-Host "Exported $($written.Count) certificate(s) to certs\:" -ForegroundColor Green
$written.Values | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "These are trust anchors, not secrets, but they are specific to your"
Write-Host "network and are gitignored. Now rebuild:"
Write-Host ""
Write-Host "  docker compose build --no-cache" -ForegroundColor Cyan
Write-Host "  docker compose up -d"
