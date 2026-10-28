# Stop everything started by run_all.ps1 (each window and the process running inside it).
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
if (Test-Path "data\run_all.pids") {
  Get-Content "data\run_all.pids" | ForEach-Object { & taskkill /T /F /PID ([int]$_) 2>$null | Out-Null; Write-Host "stopped window $_" }
  Remove-Item "data\run_all.pids"
} else { Write-Host "Nothing to stop (data\run_all.pids not found)." }
