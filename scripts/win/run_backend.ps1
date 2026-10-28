<#
  Start the AgentsMind core API on http://127.0.0.1:8000
  Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\win\run_backend.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
$vpy = ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { throw "Run scripts\win\setup.ps1 first." }
& $vpy -m alembic upgrade head
& $vpy -m uvicorn agentsmind.main:app --app-dir backend --host 127.0.0.1 --port 8000
