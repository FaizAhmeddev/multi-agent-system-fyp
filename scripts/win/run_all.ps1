<#
  Start the whole AgentsMind system on this computer, each part in its own window:
    Finance Portal  http://127.0.0.1:8201      IT Helpdesk  http://127.0.0.1:8202
    finance-mcp     http://127.0.0.1:8101/mcp  it-mcp       http://127.0.0.1:8102/mcp
    calendar-mcp    http://127.0.0.1:8103/mcp  workspace-mcp http://127.0.0.1:8104/mcp
    Core API        http://127.0.0.1:8000      Queue worker
  Run:  powershell -ExecutionPolicy Bypass -File scripts\win\run_all.ps1
  Stop: close the windows, or run scripts\win\stop_all.ps1
#>
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root
$vpy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { throw "Run scripts\win\setup.ps1 -Dev first." }
& $vpy -m alembic upgrade head

$es = Join-Path $root "external_systems"
$parts = @(
  @{ Name = "Finance Portal"; Args = "-m uvicorn finance_portal.app:create_app --factory --app-dir `"$es`" --host 127.0.0.1 --port 8201" },
  @{ Name = "IT Helpdesk";    Args = "-m uvicorn it_portal.app:create_app --factory --app-dir `"$es`" --host 127.0.0.1 --port 8202" },
  @{ Name = "finance-mcp";    Args = "-m mcp_servers.finance_mcp.server" },
  @{ Name = "it-mcp";         Args = "-m mcp_servers.it_mcp.server" },
  @{ Name = "calendar-mcp";   Args = "-m mcp_servers.calendar_mcp.server" },
  @{ Name = "workspace-mcp";  Args = "-m mcp_servers.workspace_mcp.server" },
  @{ Name = "Core API";       Args = "-m uvicorn agentsmind.main:app --app-dir backend --host 127.0.0.1 --port 8000" },
  @{ Name = "Queue worker";   Args = "-m agentsmind.queue.worker"; Env = "backend" }
)
$pids = @()
foreach ($p in $parts) {
  $cmd = "`$host.UI.RawUI.WindowTitle = 'AgentsMind - $($p.Name)'; Set-Location '$root'; "
  if ($p.Env) { $cmd += "`$env:PYTHONPATH = '$($p.Env)'; " }
  $cmd += "& '$vpy' $($p.Args)"
  $proc = Start-Process powershell -ArgumentList @("-NoExit", "-NoProfile", "-Command", $cmd) -PassThru
  $pids += $proc.Id
  Write-Host ("started {0,-15} (window pid {1})" -f $p.Name, $proc.Id)
  Start-Sleep -Milliseconds 700
}
New-Item -ItemType Directory -Force -Path "data" | Out-Null
$pids -join "`n" | Set-Content "data\run_all.pids" -Encoding ascii
Write-Host ""
if (Test-Path "frontend\dist\index.html") { Write-Host "AgentsMind    http://127.0.0.1:8000   (web app)" }
else { Write-Host "Web app not built yet: cd frontend; npm install; npm run build   (needs Node.js 22)" }
Write-Host "Core API      http://127.0.0.1:8000/api/docs"
Write-Host "Finance Portal http://127.0.0.1:8201   IT Helpdesk http://127.0.0.1:8202"
Write-Host "Sign-in details: data\local_credentials.txt"
