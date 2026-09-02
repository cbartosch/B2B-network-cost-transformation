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
    [ValidateSet('help', 'check', 'bundle-out', 'bundle-in', 'bootstrap-ca', 'test-all', 'tls-doctor', 'tls-doctor-in-container', 'up', 'down',
                 'reset', 'logs', 'test', 'seed', 'pins', 'attest', 'doctor',
                 'migrate', 'psql')]
    [string]$Target = 'help',

    # Second positional argument, used by bundle-in for the incoming file.
    [Parameter(Position = 1)]
    [string]$Path
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

function Assert-Service {
    <#
    Every target below `up` uses `docker compose exec`, which requires the
    container to already be running. Without this check the failure surfaced as
    `service "api" is not running` followed by a raw non-zero exit code, which
    names the symptom and not the fix. The Makefile has the same gap - `make
    test` does not depend on `up` either.
    #>
    param([string]$Service = 'api')
    $id = & docker compose ps -q $Service 2>$null
    if (-not $id) {
        throw "The '$Service' container is not running. Start the stack first:`n" +
              "    .\make.ps1 up`n" +
              "Then wait for it to become healthy (docker compose ps) and retry."
    }
    $state = & docker inspect -f '{{.State.Health.Status}}' $id 2>$null
    if ($state -and $state -ne 'healthy' -and $state -ne '<no value>') {
        Write-Host "Warning: '$Service' is running but reports health '$state'." `
                   -ForegroundColor Yellow
        Write-Host "         If this target fails, give it a moment and retry." `
                   -ForegroundColor Yellow
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
        Write-Host "  bootstrap-ca             acquire the corporate CA, then rebuild (managed laptops)"
        Write-Host "  bundle-out               package this repo (with history) to send for review"
        Write-Host "  bundle-in <path>         fetch a returned bundle and review before merging"
        Write-Host "  tls-doctor               diagnose TLS on a corporate net  (no Docker needed)"
        Write-Host "  up                       build and start the stack"
        Write-Host "  down                     stop the stack"
        Write-Host "  reset                    destroy data and rebuild"
        Write-Host "  logs                     follow api and ui logs"
        Write-Host "  test                     run the suite baked into the image"
        Write-Host "  test-all                 run it against the repo too (unskips build-config tests)"
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

    'bundle-out' {
        <#
        Package this repository for review elsewhere. Produces a bundle of the
        CURRENT branch plus main, so whoever receives it has the ancestry needed
        to build a real descendant commit rather than an orphan.

        A bundle carries history; a zip carries only a tree. With history, the
        change comes back as a commit whose parent is genuinely yours and
        fast-forwards. Without it, the receiver can only send a snapshot and you
        are left copying files over the top and hoping nothing silently
        disappears - which is exactly the failure mode this replaces.
        #>
        $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
        $out = if ($Path) { $Path } else { Join-Path $PSScriptRoot "wb-repo.bundle" }
        Invoke-Checked 'git' @('bundle', 'create', $out, '--all')
        & git bundle verify $out
        Write-Host ""
        Write-Host "Wrote $out" -ForegroundColor Green
        Write-Host "Current branch: $branch  ($((& git rev-parse --short HEAD).Trim()))"
        Write-Host ""
        Write-Host "A bundle is a normal file with normal contents. If this history" -ForegroundColor Yellow
        Write-Host "holds anything sensitive, it travels with it." -ForegroundColor Yellow
    }

    'bundle-in' {
        <#
        Fetch a returned bundle and fast-forward onto it.

        Fetched into a temporary ref rather than straight onto the checked-out
        branch: git refuses to overwrite the branch you are standing on, and
        that refusal is silent enough to look like nothing happened.
        #>
        if (-not $Path) {
            throw "Usage: .\make.ps1 bundle-in <path-to-bundle>"
        }
        if (-not (Test-Path $Path)) {
            throw "No such file: $Path`nCheck the name - browsers rename .bundle downloads."
        }
        & git bundle verify $Path
        if ($LASTEXITCODE -ne 0) {
            throw "That file is not a valid git bundle. If it was downloaded, it may " +
                  "be truncated - check the size and download it again."
        }
        $refs = & git bundle list-heads $Path
        Write-Host ""
        Write-Host "Refs in the bundle:" -ForegroundColor Cyan
        $refs | ForEach-Object { Write-Host "  $_" }

        <#
        Filtered to refs/heads, not "the first ref".

        A bundle carries remote-tracking refs too - this one holds
        refs/remotes/origin/HEAD alongside the branch - and taking the first
        line worked only because the branch happened to be listed first. If the
        ordering ever put a remote ref first, the strip below would not match
        it and git would be handed "refs/remotes/origin/HEAD:incoming-..." as a
        refspec, which fails in a way that reads like a corrupt bundle.
        #>
        $branches = $refs | Where-Object { $_ -match '\srefs/heads/' } |
                    ForEach-Object { $_ -replace '^\S+\s+refs/heads/', '' }
        $first = $branches | Select-Object -First 1
        if (-not $first) { throw "The bundle contains no branch refs." }
        if ($branches.Count -gt 1) {
            Write-Host ""
            Write-Host "More than one branch; taking '$first'." -ForegroundColor Yellow
        }

        Invoke-Checked 'git' @('fetch', $Path, "${first}:incoming-$first")
        Write-Host ""
        Write-Host "Fetched as 'incoming-$first'. Review, then fast-forward:" -ForegroundColor Green
        Write-Host ""
        Write-Host "  git log --oneline -3 incoming-$first" -ForegroundColor Cyan
        Write-Host "  git diff --stat HEAD incoming-$first" -ForegroundColor Cyan
        Write-Host "  git merge --ff-only incoming-$first" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "--ff-only is deliberate: if it refuses, the commit is not a clean"
        Write-Host "descendant of where you are, and that is worth knowing before merging."
    }

    'bootstrap-ca' {
        # One command for a managed laptop: acquire the inspection CA, confirm
        # it landed, and rebuild without cache. The COPY certs/ layer caches on
        # directory contents, so a plain rebuild after adding a certificate
        # reuses the pre-certificate layer and fails identically - which reads
        # as "the fix did not work" rather than "the cache was stale".
        $script = Join-Path $PSScriptRoot 'tools\export_corporate_ca.ps1'
        & powershell -ExecutionPolicy Bypass -File $script
        $found = Get-ChildItem (Join-Path $PSScriptRoot 'certs') -Filter *.crt -EA SilentlyContinue
        if (-not $found) {
            throw "No certificate was exported, so a rebuild would fail the same way. " +
                  "Run '.\make.ps1 tls-doctor' to see which step is failing."
        }
        Write-Host ""
        Write-Host "Trust anchors in certs\:" -ForegroundColor Green
        $found | ForEach-Object { Write-Host "  $($_.Name)" }
        Write-Host ""
        Assert-Docker
        Write-Host "Rebuilding without cache ..." -ForegroundColor Cyan
        Invoke-Checked 'docker' @('compose', 'build', '--no-cache')
        Write-Host ""
        Write-Host "Now run: .\make.ps1 up" -ForegroundColor Cyan
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
        Assert-Service
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
        Assert-Service
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

    'test-all' {
        <#
        The full suite, including the tests that read build-time artifacts.

        `test` runs against the copy baked into the image, which deliberately
        does not contain docker-compose.yml, the Dockerfiles, or analyst_ui/ -
        so 26 tests skip with "not present in this image". That is honest but
        it means the compose and interface controls never actually run.

        This mounts the repository at /src and points pytest there, so
        Path(__file__).parents[1] resolves to the real repository root and
        every file those tests look for exists. WORKDIR stays /app so
        `import app` still finds the installed package.

        Both are worth keeping: `test` proves the image is self-testing,
        `test-all` proves the build configuration is correct.
        #>
        Assert-Docker
        Assert-Service
        Invoke-Checked 'docker' @(
            'compose', 'run', '--rm', '--no-deps',
            '-v', "$($PSScriptRoot):/src",
            '-w', '/app',
            '-e', 'DATABASE_URL=sqlite://',
            '-e', 'WORKBENCH_ENVIRONMENT=TEST',
            'api', 'python', '-m', 'pytest', '/src/tests', '-v'
        )
    }

    'seed' {
        Assert-Docker
        Assert-Service
        Write-Host "This overwrites governed reference data, including analyst edits." -ForegroundColor Yellow
        $answer = Read-Host "Type 'seed' to continue"
        if ($answer -ne 'seed') { Write-Host "Cancelled."; break }
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-m', 'app.seed', '--force')
    }

    'pins' {
        Assert-Docker
        Assert-Service
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-c',
            "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/integrity/tls-pins')), indent=2))")
    }

    'attest' {
        Assert-Docker
        Assert-Service
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-c',
            "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/integrity/attestation')), indent=2))")
    }

    'doctor' {
        Assert-Docker
        Assert-Service
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-c',
            'from app import migrations; print(migrations.status())')
    }

    'migrate' {
        Assert-Docker
        Assert-Service
        Invoke-Checked 'docker' @('compose', 'exec', 'api', 'python', '-c',
            'from app import db, migrations; print(migrations.ensure(db.engine))')
    }

    'psql' {
        Assert-Docker
        & docker compose exec db psql -U workbench -d workbench
    }
}
