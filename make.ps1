<#
.SYNOPSIS
    PowerShell equivalent of the Makefile, for Windows 11 where `make` is not present.

.DESCRIPTION
    Same targets, same semantics. Run from the repository root:

        .\make.ps1 check
        .\make.ps1 up
        .\make.ps1 test

    If PowerShell refuses to run this file ("running scripts is disabled on this
    system"), either unblock it once:

        Unblock-File .\make.ps1

    or run it without changing your machine's policy:

        powershell -ExecutionPolicy Bypass -File .\make.ps1 test

.NOTES
    A note on Git Bash: `docker compose exec -e DATABASE_URL=sqlite:// ...` is safe
    in PowerShell, but MSYS/Git Bash rewrites arguments that look like paths, and
    turns `sqlite://` into something like `sqlite:/C:/Program Files/Git/`. That
    silently rebinds the test suite. Use PowerShell, or prefix the command with
    MSYS_NO_PATHCONV=1 if you must use Git Bash.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'check', 'tls-doctor', 'tls-doctor-in-container', 'up', 'down',
                 'reset', 'logs', 'test', 'seed', 'pins', 'attest', 'doctor',
                 'migrate', 'psql')]
    [string]$Target = 'help'
)

$ErrorActionPreference = 'Stop'

function Get-Python {
    foreach ($candidate in @('python', 'python3', 'py')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { return $candidate }
    }
    throw "No Python interpreter found on PATH. Install Python 3, or run the target that uses Docker instead."
}

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Exe $($Arguments -join ' ') exited with code $LASTEXITCODE"
    }
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "docker was not found on PATH. Start Docker Desktop, or open a new terminal after installing it."
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is installed but not responding. Is Docker Desktop running?"
    }
}

switch ($Target) {

    'help' {
        Write-Host ""
        Write-Host "Targets (mirror of the Makefile):" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  check                    validate build configuration     (no Docker needed)"
        Write-Host "  tls-doctor               diagnose TLS on a corporate net  (no Docker needed)"
        Write-Host "  up                       build and start the stack"
        Write-Host "  down                     stop the stack"
        Write-Host "  reset                    destroy data and rebuild"
        Write-Host "  logs                     follow api and ui logs"
        Write-Host "  test                     run the full suite in the api container"
        Write-Host "  seed                     reload reference data (DESTRUCTIVE)"
        Write-Host "  doctor                   report schema version and drift"
        Write-Host "  migrate                  apply pending schema migrations"
        Write-Host "  pins                     show observed TLS pins"
        Write-Host "  attest                   provenance summary"
        Write-Host "  psql                     open a database shell"
        Write-Host "  tls-doctor-in-container  TLS check from inside the api container"
        Write-Host ""
        Write-Host "Example:  .\make.ps1 test" -ForegroundColor DarkGray
        Write-Host ""
    }

    'check' {
        # No Docker required. This is the one worth running first.
        Invoke-Checked (Get-Python) @('tests/check_build_config.py')
    }

    'tls-doctor' {
        Invoke-Checked (Get-Python) @('tools/tls_doctor.py')
    }

    'tls-doctor-in-container' {
        Assert-Docker
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', 'tools/tls_doctor.py')
    }

    'up' {
        # `up` depends on `check` in the Makefile; same ordering here.
        Invoke-Checked (Get-Python) @('tests/check_build_config.py')
        Assert-Docker
        Invoke-Checked 'docker' @('compose', 'up', '--build', '-d')
        Write-Host "UI  -> http://localhost:8501" -ForegroundColor Green
        Write-Host "API -> http://localhost:8000/docs" -ForegroundColor Green
    }

    'down' {
        Assert-Docker
        Invoke-Checked 'docker' @('compose', 'down')
    }

    'reset' {
        Assert-Docker
        Invoke-Checked 'docker' @('compose', 'down', '-v')
        Invoke-Checked 'docker' @('compose', 'up', '--build', '-d')
    }

    'logs' {
        Assert-Docker
        & docker compose logs -f api ui
    }

    'test' {
        Assert-Docker
        # DATABASE_URL is passed explicitly so the suite can never bind to
        # Postgres, independently of anything conftest.py does. Same reasoning
        # as the Makefile: three independent layers, and this is one of them.
        Invoke-Checked 'docker' @(
            'compose', 'exec',
            '-e', 'DATABASE_URL=sqlite://',
            '-e', 'WORKBENCH_ENVIRONMENT=TEST',
            'api', 'python', '-m', 'pytest', '/app/tests', '-v'
        )
    }

    'seed' {
        Assert-Docker
        Write-Host "This overwrites governed reference data, including analyst edits." -ForegroundColor Yellow
        $answer = Read-Host "Type 'seed' to continue"
        if ($answer -ne 'seed') { Write-Host "Cancelled."; break }
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-m', 'app.seed', '--force')
    }

    'pins' {
        Assert-Docker
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-c',
            "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/integrity/tls-pins')), indent=2))")
    }

    'attest' {
        Assert-Docker
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-c',
            "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/integrity/attestation')), indent=2))")
    }

    'doctor' {
        Assert-Docker
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-c',
            'from app import migrations; print(migrations.status())')
    }

    'migrate' {
        Assert-Docker
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-c',
            'from app import db, migrations; print(migrations.ensure(db.engine))')
    }

    'psql' {
        Assert-Docker
        & docker compose exec db psql -U workbench -d workbench
    }
}
