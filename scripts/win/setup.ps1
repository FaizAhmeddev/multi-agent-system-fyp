<#
  AgentsMind one-time setup on Windows (no Docker).
  Run from the repo root:   powershell -ExecutionPolicy Bypass -File scripts\win\setup.ps1
  - Creates .venv with Python 3.11 or 3.12
  - Installs pinned dependencies
  - Creates or completes .env from .env.example with random secrets (scripts\env_setup.py)
  - Applies database migrations
#>
param([switch]$Dev)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")

function Find-Python {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.11") },
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "python"; Args = @() },
        @{ Exe = "python3"; Args = @() }
    )
    foreach ($c in $candidates) {
        try {
            $a = $c.Args
            $v = & $c.Exe @a -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
            if ($v -in @("3.11", "3.12")) { return $c }
        } catch { }
    }
    throw "Python 3.11 or 3.12 not found. Install it from python.org and re-run."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $py = Find-Python
    $pa = $py.Args
    Write-Host "Creating .venv with $($py.Exe) $($pa -join ' ')"
    & $py.Exe @pa -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
$vpy = ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
$req = if ($Dev) { "requirements\dev.txt" } else { "requirements\backend.txt" }
& $vpy -m pip install -r $req
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# Create .env, or fill in any settings added by a newer version (existing values are kept).
& $vpy scripts\env_setup.py
if ($LASTEXITCODE -ne 0) { throw "env setup failed" }

& $vpy -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }
Write-Host "Setup complete. Start the API with: scripts\win\run_backend.ps1"
