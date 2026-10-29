# Stop everything started by run_all.ps1 (each window and the process running inside it).
Set-Location (Resolve-Path "$PSScriptRoot\..\..")
if (Test-Path "data\run_all.pids") {
  Get-Content "data\run_all.pids" | ForEach-Object { & taskkill /T /F /PID ([int]$_) 2>$null | Out-Null; Write-Host "stopped window $_" }
  Remove-Item "data\run_all.pids"
} else { Write-Host "Nothing to stop (data\run_all.pids not found)." }

# Also stop anything still listening on AgentsMind ports (for example after a closed window or Ctrl+C).
foreach ($p in @(8000, 8101, 8102, 8103, 8104, 8201, 8202, 18000)) {
  Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.OwningProcess -gt 0) { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host "freed port $p" }
  }
}

# The queue worker listens on no port, so also stop any AgentsMind Python process still running
# (for example one left behind by an interrupted run). It would otherwise keep data\agentsmind.db locked.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'agentsmind|mcp_servers|external_systems' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "stopped process $($_.ProcessId)" }
