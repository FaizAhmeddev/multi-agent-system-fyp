<#
  Start the AgentsMind queue worker (processes agent runs and other background tasks).
  Run in a second window next to run_backend.ps1:
      powershell -ExecutionPolicy Bypass -File scripts\win\run_worker.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
$vpy = ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { throw "Run scripts\win\setup.ps1 first." }
$env:PYTHONPATH = "backend"
& $vpy -m agentsmind.queue.worker
