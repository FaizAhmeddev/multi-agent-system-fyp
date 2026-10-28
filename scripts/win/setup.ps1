<#
  AgentsMind one-time setup on Windows (no Docker).
  Run from the repo root:   powershell -ExecutionPolicy Bypass -File scripts\win\setup.ps1
  - Creates .venv with Python 3.11 or 3.12
  - Installs pinned dependencies
  - Creates .env from .env.example with a random JWT_SECRET and a random first-admin password
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

function Write-Utf8NoBom([string]$Path, [string[]]$Lines) {
    $full = Join-Path (Get-Location) $Path
    [System.IO.File]::WriteAllLines($full, $Lines, (New-Object System.Text.UTF8Encoding($false)))
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

if (-not (Test-Path ".env")) {
    $secret = & $vpy -c "import secrets;print(secrets.token_urlsafe(48))"
    $adminPw = & $vpy -c "import secrets,string;a=string.ascii_letters+string.digits;print('-'.join(''.join(secrets.choice(a) for _ in range(5)) for _ in range(4)))"
    $lines = (Get-Content ".env.example") `
        -replace '^JWT_SECRET=$', "JWT_SECRET=$secret" `
        -replace '^AGENTSMIND_ADMIN_EMAIL=$', "AGENTSMIND_ADMIN_EMAIL=admin@example.com" `
        -replace '^AGENTSMIND_ADMIN_PASSWORD=$', "AGENTSMIND_ADMIN_PASSWORD=$adminPw"
    Write-Utf8NoBom ".env" $lines
    New-Item -ItemType Directory -Force -Path "data" | Out-Null
    Write-Utf8NoBom "data\first_admin.txt" @("admin@example.com`t$adminPw")
    Write-Host ""
    Write-Host "Created .env. First admin: admin@example.com  password: $adminPw"
    Write-Host "(also saved in data\first_admin.txt, which is gitignored)"
}

& $vpy -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }
Write-Host "Setup complete. Start the API with: scripts\win\run_backend.ps1"
