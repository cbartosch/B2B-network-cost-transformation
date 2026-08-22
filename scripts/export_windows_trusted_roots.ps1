[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\certs")
)

$ErrorActionPreference = "Stop"
$destinationPath = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null

$stores = @(
    "Cert:\CurrentUser\Root",
    "Cert:\CurrentUser\CA",
    "Cert:\LocalMachine\Root",
    "Cert:\LocalMachine\CA"
)

$certificates = foreach ($store in $stores) {
    if (Test-Path $store) {
        Get-ChildItem $store -ErrorAction SilentlyContinue
    }
}

$uniqueCertificates = $certificates |
    Where-Object { $_.HasPrivateKey -eq $false } |
    Sort-Object Thumbprint -Unique

$count = 0
foreach ($certificate in $uniqueCertificates) {
    $der = $certificate.Export(
        [System.Security.Cryptography.X509Certificates.X509ContentType]::Cert
    )
    $base64 = [System.Convert]::ToBase64String(
        $der,
        [System.Base64FormattingOptions]::InsertLineBreaks
    )
    $pem = "-----BEGIN CERTIFICATE-----`r`n$base64`r`n-----END CERTIFICATE-----`r`n"
    $path = Join-Path $destinationPath ("{0}.crt" -f $certificate.Thumbprint)
    [System.IO.File]::WriteAllText($path, $pem, [System.Text.Encoding]::ASCII)
    $count++
}

Write-Host "Exported $count trusted root/intermediate certificates to $destinationPath"
Write-Host "These files contain public certificates only, not private keys."
Write-Host "They are ignored by Git but included in the local Docker build context."
