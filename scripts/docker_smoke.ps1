$ErrorActionPreference = "Stop"

function Wait-ForUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$Attempts = 60
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 | Out-Null
            Write-Host "$Name is ready: $Url"
            return
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    throw "$Name did not become ready: $Url"
}

$apiHealth = if ($env:API_HEALTH_URL) { $env:API_HEALTH_URL } else { "http://localhost:8000/health" }
$uiHealth = if ($env:UI_HEALTH_URL) { $env:UI_HEALTH_URL } else { "http://localhost:8501/_stcore/health" }

Wait-ForUrl -Name "API" -Url $apiHealth
Wait-ForUrl -Name "Streamlit" -Url $uiHealth
Invoke-RestMethod -Uri $apiHealth | ConvertTo-Json
docker compose ps
