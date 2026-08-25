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

# Publicly-trusted roots. Exporting one of these is worse than useless: the
# base image already trusts it, so `update-ca-certificates` reports "2 added"
# and the build then fails verification anyway - which reads as "no CA
# supplied" when the truth is "the wrong CA supplied".
#
# This happened for real. The live-chain method below walks the chain of each
# host and exports the issuers it finds; on a host that is NOT being
# intercepted, that is simply the genuine public root. A run produced
# GlobalSign ECC Root CA R4 and Google Trust Services WE1, both public, and
# the build kept failing at the same line with a message pointing at the fix
# it had already appeared to apply.
#
# The rule is simple and worth stating: we want anchors the image does NOT
# already trust. A publicly-trusted root is by definition not one of them.
$publicRoots = 'GlobalSign|DigiCert|Google Trust|GTS |Let''s Encrypt|ISRG|' +
               'Baltimore|USERTrust|Sectigo|Comodo|Amazon|Microsoft |VeriSign|' +
               'Entrust|GoDaddy|Starfield|QuoVadis|Thawte|GeoTrust|RapidSSL|' +
               'AAA Certificate|Certum|Buypass|SwissSign|T-TeleSec|IdenTrust|' +
               'Actalis|SSL.com|Trustwave|Network Solutions'

function Test-PublicRoot {
    param([string]$Subject)
    if ($Subject -match $publicRoots) { return $true }
    return $false
}

$written = @{}
$skippedPublic = @()

# ---------------------------------------------------------------- method 1
# The Windows machine store. Tried FIRST because it needs no network at all:
# on a managed laptop the inspection CA is already installed there, which is
# exactly why the browser works. The live-chain method below needs a direct
# TCP connection to :443, and some managed networks require an explicit proxy
# or block raw sockets outright - in which case that method reports "every
# host was unreachable" and exports nothing, which is what happens in practice.
Write-Host "Scanning the Windows machine store for inspection CAs ..."
$patterns = 'Zscaler|Netskope|Palo Alto|Forcepoint|McAfee|Blue Coat|Symantec Web|' +
            'Cisco Umbrella|Fortinet|FortiGate|Sophos|Trend Micro|Menlo|iboss|' +
            'Proxy|Inspect|MITM|SSL Interc'
try {
    $storeHits = Get-ChildItem Cert:\LocalMachine\Root, Cert:\LocalMachine\CA `
                     -ErrorAction SilentlyContinue |
                 Where-Object { $_.Subject -match $patterns }
    foreach ($c in $storeHits) {
        if ($written.ContainsKey($c.Thumbprint)) { continue }
        $safe = ($c.Subject -replace '[^A-Za-z0-9]+','-').Trim('-')
        if ($safe.Length -gt 60) { $safe = $safe.Substring(0,60) }
        if (Test-PublicRoot $c.Subject) {
            $skippedPublic += $c.Subject
            continue
        }
        Export-Pem -Cert $c -Path (Join-Path $certsDir "$safe.crt")
        $written[$c.Thumbprint] = $c.Subject
        Write-Host "  found: $($c.Subject)" -ForegroundColor Green
    }
    if (-not $storeHits) {
        Write-Host "  no known inspection vendor matched by name." -ForegroundColor Yellow
        Write-Host "  That does not mean there is none - the name may be unfamiliar."
        Write-Host "  Method 2 below asks the network itself rather than guessing."
    }
} catch {
    Write-Host "  store scan failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

# ---------------------------------------------------------------- method 2
Write-Host ""
Write-Host "Asking each host what it actually presents ..."
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
if ($skippedPublic.Count -gt 0) {
    Write-Host ""
    Write-Host "Skipped $($skippedPublic.Count) publicly-trusted root(s) - the image" -ForegroundColor Yellow
    Write-Host "already trusts these, so exporting them would achieve nothing:" -ForegroundColor Yellow
    $skippedPublic | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" }
}

if ($written.Count -eq 0) {
    Write-Host "No certificates exported by either method." -ForegroundColor Red
    Write-Host ""
    Write-Host "Neither the machine store nor a live connection produced a CA. That"
    Write-Host "usually means one of:"
    Write-Host ""
    Write-Host "  * this network needs an explicit HTTP proxy, so raw :443 fails and"
    Write-Host "    the store holds a CA under a name none of the patterns match."
    Write-Host "    List candidates yourself and export by thumbprint:"
    Write-Host ""
    Write-Host "      Get-ChildItem Cert:\LocalMachine\Root |" -ForegroundColor Cyan
    Write-Host "        Sort-Object Subject | Select-Object Subject, Thumbprint" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  * egress is blocked entirely, in which case no certificate helps."
    Write-Host ""
    Write-Host "Run .\make.ps1 tls-doctor for a per-endpoint diagnosis." -ForegroundColor Cyan
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
