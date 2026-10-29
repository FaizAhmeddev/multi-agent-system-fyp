<#
  AgentsMind phase-gate runner (Windows PowerShell 5.1+).

  Put this file and agentsmind.bundle in the same folder, then run:
      powershell -ExecutionPolicy Bypass -File .\agentsmind-gate.ps1
  Optional:
      -Branch phase/1a-foundation   branch to test (default: newest phase branch in the bundle)
      -Push                         after a green run, push that branch to GitHub (never main)

  What it does, all inside .\agentsmind (a separate clone; nothing else is touched):
    1. clone GitHub repo if missing, import commits from agentsmind.bundle, check out the branch
    2. scripts\win\setup.ps1 -Dev   (venv, pinned pip install, .env with random secrets, migrations)
    3. ruff, pytest (backend, portals, MCP servers, assistant, characterization), migrations, seeds
    4. frontend: npm ci, tsc, vite build, WCAG contrast check (needs Node.js 22)
    5. live system (portals, 4 MCP servers in sandbox mode, core API serving the web app, worker):
       MCP smoke, API checks, assistant prompts, then Playwright end-to-end tests
    6. writes everything to .\gate-logs\gate-<time>.log  (no secrets are written to the log)
#>
param(
    [string]$Branch = "",
    [switch]$Push
)
$ErrorActionPreference = "Continue"
# No web call may hang the gate.
$PSDefaultParameterValues["Invoke-RestMethod:TimeoutSec"] = 180
$PSDefaultParameterValues["Invoke-WebRequest:TimeoutSec"] = 60
$Here = $PSScriptRoot
$Repo = Join-Path $Here "agentsmind"
$Bundle = Join-Path $Here "agentsmind.bundle"
$LogDir = Join-Path $Here "gate-logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("gate-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
$script:Failures = @()

function Say([string]$m) { $m | Tee-Object -FilePath $Log -Append }
function Step([string]$name) { Say ""; Say ("=" * 70); Say ">>> $name"; Say ("=" * 70) }
function Run([string]$label, [string]$exe, [string[]]$argv) {
    Say "`$ $exe $($argv -join ' ')"
    & $exe @argv 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $Log -Append | Out-Host
    $code = $LASTEXITCODE
    Say "[exit $code] $label"
    if ($code -ne 0) { $script:Failures += $label }
    return $code
}

Step "Environment"
Say ("Date: " + (Get-Date -Format o))
Say ("PowerShell: " + $PSVersionTable.PSVersion)
Say ("OS: " + [System.Environment]::OSVersion.VersionString)
Run "git version" "git" @("--version") | Out-Null

Step "Repository"
if (-not (Test-Path (Join-Path $Repo ".git"))) {
    Run "git clone" "git" @("clone", "https://github.com/FaizAhmeddev/multi-agent-system-fyp.git", $Repo) | Out-Null
}
Set-Location $Repo
if (-not (Test-Path $Bundle)) { Say "ERROR: $Bundle not found."; exit 1 }
Run "bundle verify" "git" @("bundle", "verify", $Bundle) | Out-Null
Run "fetch origin" "git" @("fetch", "origin") | Out-Null
Run "fetch bundle" "git" @("fetch", "--force", $Bundle, "+refs/heads/*:refs/remotes/bundle/*") | Out-Null
if (-not $Branch) {
    $Branch = (git for-each-ref --sort=-committerdate --format="%(refname:strip=3)" refs/remotes/bundle/phase/ | Select-Object -First 1)
    $Branch = "phase/" + ($Branch -replace '^phase/', '')
}
Say "Branch: $Branch"
# .\agentsmind is the gate's own test copy: local edits to tracked files there are discarded.
Run "checkout" "git" @("checkout", "-f", "-B", $Branch, "bundle/$Branch") | Out-Null
$head = (git rev-parse HEAD).Trim(); $want = (git rev-parse "bundle/$Branch").Trim()
if ($head -ne $want) { Say "ERROR: checkout of $Branch failed (HEAD is $head). Stopping so the wrong code is not tested."; exit 1 }
Run "log" "git" @("log", "--oneline", "-8") | Out-Null
Run "status" "git" @("status", "--short") | Out-Null

Step "Setup (venv, pip install, .env, migrations)"
Run "setup.ps1" "powershell" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\win\setup.ps1", "-Dev") | Out-Null
$vpy = Join-Path $Repo ".venv\Scripts\python.exe"
Run "python version" $vpy @("--version") | Out-Null
Run "pip freeze" $vpy @("-m", "pip", "freeze") | Out-Null

Step "Lint"
Run "ruff" $vpy @("-m", "ruff", "check", "backend", "db", "scripts", "mcp_servers", "external_systems", "tests/backend", "tests/portals", "tests/mcp_servers_tests", "tests/assistant") | Out-Null

Step "Tests"
Remove-Item -ErrorAction SilentlyContinue (Join-Path $Repo ".coverage")
$cov = @("--cov", "--cov-append", "--cov-report=")
Run "pytest backend" $vpy (@("-m", "pytest", "tests/backend", "-v", "-rfE") + $cov) | Out-Null
Run "pytest portals" $vpy (@("-m", "pytest", "tests/portals", "-v", "-rfE") + $cov) | Out-Null
Run "pytest MCP servers" $vpy (@("-m", "pytest", "tests/mcp_servers_tests", "-v", "-rfE") + $cov) | Out-Null
Run "pytest assistant (real langgraph)" $vpy (@("-m", "pytest", "tests/assistant", "-v", "-rfE") + $cov) | Out-Null
Run "langgraph and openai installed" $vpy @("-c", "import importlib.metadata as m; print('langgraph', m.version('langgraph'), 'openai', m.version('openai'), 'google-api-python-client', m.version('google-api-python-client'))") | Out-Null
Run "pytest characterization" $vpy @("-m", "pytest", "tests/characterization", "-v", "-rfE") | Out-Null

Step "Quality: coverage, bandit, secrets scan, pip-audit"
Run "quality" $vpy @("scripts\quality.py") | Out-Null

Step "Migrations from a clean database"
$env:DATABASE_URL = "sqlite:///" + ((Join-Path $Repo "data\gate-clean.db") -replace '\\', '/')
Remove-Item -ErrorAction SilentlyContinue (Join-Path $Repo "data\gate-clean.db")
Run "alembic upgrade (clean)" $vpy @("-m", "alembic", "upgrade", "head") | Out-Null
Run "alembic current" $vpy @("-m", "alembic", "current") | Out-Null
$env:AGENTSMIND_SEED_CREDENTIALS = Join-Path $Repo "data\gate-clean-credentials.txt"
Run "seed (clean db)" $vpy @("scripts\seed.py") | Out-Null
Run "seed again (idempotent)" $vpy @("scripts\seed.py") | Out-Null
# The live checks and Playwright use their own fresh database and demo users, so leftovers from
# earlier runs (or from your own use of data\agentsmind.db) can never mismatch the passwords.
$env:DATABASE_URL = "sqlite:///" + ((Join-Path $Repo "data\gate-live.db") -replace '\\', '/')
$env:AGENTSMIND_SEED_CREDENTIALS = Join-Path $Repo "data\gate-live-credentials.txt"
Remove-Item -ErrorAction SilentlyContinue (Join-Path $Repo "data\gate-live.db"), $env:AGENTSMIND_SEED_CREDENTIALS
Run "alembic upgrade (live db)" $vpy @("-m", "alembic", "upgrade", "head") | Out-Null
Run "seed core (live db)" $vpy @("scripts\seed.py") | Out-Null
Run "seed Finance Portal" $vpy @("external_systems\finance_portal\seed.py") | Out-Null
Run "seed IT Helpdesk" $vpy @("external_systems\it_portal\seed.py") | Out-Null
# The gate always uses the sandbox calendar and mailbox, even if Google is set up, so it never touches real data.
$env:CALENDAR_MODE = "sandbox"; $env:WORKSPACE_MODE = "sandbox"; $env:CORE_API_URL = "http://127.0.0.1:18000"
Remove-Item -ErrorAction SilentlyContinue (Join-Path $Repo "data\calendar_sandbox.db")
Run "seed sandbox calendar" $vpy @("-m", "mcp_servers.calendar_mcp.seed") | Out-Null

Step "Frontend (React + TypeScript + Vite)"
$fe = Join-Path $Repo "frontend"
$node = Get-Command node -ErrorAction SilentlyContinue
$FrontendBuilt = $false
if (-not $node) {
    Say "Node.js not found: install Node.js 22 LTS (https://nodejs.org) to build the UI and run Playwright."
    $script:Failures += "node missing"
} else {
    Run "node version" "node" @("--version") | Out-Null
    Push-Location $fe
    Run "npm ci (exact versions from package-lock.json)" "npm.cmd" @("ci", "--no-audit", "--no-fund") | Out-Null
    Run "typecheck (tsc)" "npm.cmd" @("run", "typecheck") | Out-Null
    $before = $script:Failures.Count
    Run "vite build" "npm.cmd" @("run", "build") | Out-Null
    $buildOk = ($script:Failures.Count -eq $before)
    Run "WCAG contrast (both themes)" "node" @("scripts/contrast.mjs") | Out-Null
    Pop-Location
    $FrontendBuilt = $buildOk -and (Test-Path (Join-Path $fe "dist\index.html"))
}

Step "Live system: portals, MCP servers, core API, worker"
$es = Join-Path $Repo "external_systems"
$parts = [ordered]@{
    "finance-portal" = @("-m", "uvicorn", "finance_portal.app:create_app", "--factory", "--app-dir", $es, "--host", "127.0.0.1", "--port", "8201")
    "it-portal"      = @("-m", "uvicorn", "it_portal.app:create_app", "--factory", "--app-dir", $es, "--host", "127.0.0.1", "--port", "8202")
    "finance-mcp"    = @("-m", "mcp_servers.finance_mcp.server")
    "it-mcp"         = @("-m", "mcp_servers.it_mcp.server")
    "calendar-mcp"   = @("-m", "mcp_servers.calendar_mcp.server")
    "workspace-mcp"  = @("-m", "mcp_servers.workspace_mcp.server")
    "core-api"       = @("-m", "uvicorn", "agentsmind.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "18000")
    "worker"         = @("-m", "agentsmind.queue.worker")
}
$Ports = @(8201, 8202, 8101, 8102, 8103, 8104, 18000)
function Free-Ports {
    foreach ($p in $Ports) {
        $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        foreach ($x in $c) {
            if ($x.OwningProcess -gt 0) {
                Say ("port $p was still in use by process " + $x.OwningProcess + " (left over from an earlier run): stopping it")
                Stop-Process -Id $x.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Start-Sleep -Milliseconds 500
}
function Quote-Args([string[]]$a) { ($a | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join " " }
Free-Ports
$procs = @{}
try {
$env:PYTHONPATH = "backend"
foreach ($k in $parts.Keys) {
    $procs[$k] = Start-Process -FilePath $vpy -ArgumentList (Quote-Args $parts[$k]) -PassThru -WindowStyle Hidden -WorkingDirectory $Repo `
        -RedirectStandardOutput (Join-Path $LogDir "$k.out.log") -RedirectStandardError (Join-Path $LogDir "$k.err.log")
    Start-Sleep -Milliseconds 800
}
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
function WaitUrl([string]$u) { for ($i = 0; $i -lt 40; $i++) { try { Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 2 | Out-Null; return $true } catch { if ($_.Exception.Response) { return $true } }; Start-Sleep -Milliseconds 500 }; return $false }
$up = @{ "finance-portal" = WaitUrl "http://127.0.0.1:8201/api/v1/health"; "it-portal" = WaitUrl "http://127.0.0.1:8202/api/v1/health";
         "finance-mcp" = WaitUrl "http://127.0.0.1:8101/mcp"; "it-mcp" = WaitUrl "http://127.0.0.1:8102/mcp";
         "calendar-mcp" = WaitUrl "http://127.0.0.1:8103/mcp"; "workspace-mcp" = WaitUrl "http://127.0.0.1:8104/mcp"; "core-api" = WaitUrl "http://127.0.0.1:18000/health" }
foreach ($k in $up.Keys) { Say ("{0,-15} {1}" -f $k, $(if ($up[$k]) { "up" } else { "NOT UP" })); if (-not $up[$k]) { $script:Failures += "$k start" } }

Run "MCP smoke" $vpy @("scripts\smoke\mcp_smoke.py") | Out-Null

$cred = @{}
Get-Content (Join-Path $Repo "data\local_credentials.txt") -ErrorAction SilentlyContinue | ForEach-Object { $c = $_ -split "`t"; if ($c.Count -ge 3) { $cred[$c[0]] = $c } }
$base = "http://127.0.0.1:18000"
try {
    $adm = $cred["AgentsMind"]
    $t = Invoke-RestMethod -Method Post -Uri "$base/api/auth/login" -ContentType "application/json" -Body (@{ email = $adm[1]; password = $adm[2] } | ConvertTo-Json)
    $auth = @{ Authorization = "Bearer " + $t.access_token }
    Say ("POST /api/auth/login -> roles=" + ($t.user.roles -join ","))
    $deps = Invoke-RestMethod -Uri "$base/api/departments" -Headers $auth
    Say ("GET /api/departments -> " + (($deps.items | ForEach-Object { $_.slug + "=" + $_.accessible }) -join ", "))
    $mcp = Invoke-RestMethod -Uri "$base/api/admin/mcp" -Headers $auth
    foreach ($srv in $mcp.servers) { Say ("MCP {0,-14} configured={1} reachable={2} tools={3}" -f $srv.server, $srv.configured, $srv.reachable, (@($srv.tools) -join ",")) }
    $sum = Invoke-RestMethod -Uri "$base/api/finance/summary" -Headers $auth
    Say ("GET /api/finance/summary -> active=" + $sum.result.people_active + " payroll=" + (($sum.result.payroll_by_currency | ForEach-Object { $_.currency + " " + $_.total_monthly_payroll }) -join "; ") + " source=" + $sum.source)
    $tk = Invoke-RestMethod -Method Post -Uri "$base/api/it/tickets" -Headers ($auth + @{ "Idempotency-Key" = "gate-" + (Get-Date -Format "yyyyMMddHHmmss") }) -ContentType "application/json" `
        -Body (@{ department = "Operations"; category = "network"; priority = "medium"; summary = "Laptop cannot join office Wi-Fi"; description = "My laptop cannot connect to office wifi (gate check)." } | ConvertTo-Json)
    Say ("POST /api/it/tickets -> " + $tk.result.ticket.number + " via " + $tk.result.ticket.source)
    $conf = Invoke-WebRequest -UseBasicParsing -Uri $tk.result.confirmation_url
    Say ("confirmation page -> HTTP " + $conf.StatusCode + ", contains 'Complaint submitted': " + ($conf.Content -match "Complaint submitted"))
    if (-not ($conf.Content -match "Complaint submitted")) { $script:Failures += "confirmation page" }
    $runBody = @{ action = "troubleshoot"; inputs = @{ problem = "My laptop cannot connect to office wifi" } } | ConvertTo-Json -Depth 4
    $run = Invoke-RestMethod -Method Post -Uri "$base/api/agents/it/runs" -Headers $auth -Body $runBody -ContentType "application/json"
    $final = $null
    for ($j = 0; $j -lt 40; $j++) { Start-Sleep -Milliseconds 500; $final = Invoke-RestMethod -Uri ("$base/api/agents/runs/" + $run.id) -Headers $auth; if ($final.status -in @("done", "failed")) { break } }
    Say ("agent run via queue worker -> status=" + $final.status + " simulated=" + $final.simulated)
    if ($final.status -ne "done") { $script:Failures += "worker end-to-end" }

    # Assistant: prompt -> plan -> agent -> MCP -> approval card -> approve -> read back
    function Ask([string]$text) {
        return Invoke-RestMethod -Method Post -Uri "$base/api/assistant/messages" -Headers $auth -ContentType "application/json" `
            -Body (@{ text = $text } | ConvertTo-Json)
    }
    $a = Ask "Schedule a design review tomorrow at 3 pm for 45 minutes with a Google Meet link"
    $c = $a.cards[0]
    Say ("assistant calendar -> card=" + $c.kind + " simulated=" + $c.simulated + " warnings=" + (@($c.warnings) -join " | "))
    foreach ($d in $c.approval.details) { Say ("    " + $d.label + ": " + $d.value) }
    if ($c.kind -ne "approval") { $script:Failures += "assistant calendar card" }
    else {
        $ap = Invoke-RestMethod -Method Post -Uri ("$base/api/approvals/" + $c.approval.id + "/approve") -Headers $auth -ContentType "application/json" -Body "{}"
        Say ("approve -> " + $ap.outcome.status + ": " + $ap.outcome.result.body)
        if ($ap.outcome.status -ne "ok") { $script:Failures += "calendar approve" }
    }
    $m = Ask "Show my unread emails"
    Say ("assistant inbox -> " + $m.cards[0].kind + " rows=" + @($m.cards[0].data.rows).Count + " suspicious=" + @($m.cards[0].data.rows | Where-Object { $_.suspicious }).Count)
    $p = Ask "What is the total monthly payroll?"
    Say ("assistant payroll -> " + $p.cards[0].kind + ": " + $p.cards[0].body)
    $h = Ask "Draft replies to my unread emails"
    Say ("assistant hostile-email check -> tools=" + ((@($h.cards | Where-Object { $_.kind -eq "approval" }) | ForEach-Object { $_.approval.tool } | Sort-Object -Unique) -join ","))
    if (@($h.cards | Where-Object { $_.kind -eq "approval" -and $_.approval.tool -ne "gmail_send_email" }).Count -gt 0) { $script:Failures += "hostile email" }
    $cv = Ask "Screen the CVs for the Python Developer role"
    foreach ($row in $cv.cards[0].data.rows) { Say ("    CV {0,-14} rubric={1} keyword={2} {3} review={4}" -f $row.candidate, $row.rubric_score, $row.keyword_score, $row.recommendation, $row.needs_human_review) }
    $st = Invoke-RestMethod -Uri "$base/api/admin/queue" -Headers $auth
    Say ("queue -> " + ($st.queues | ConvertTo-Json -Compress))
    $webapp = Invoke-WebRequest -UseBasicParsing -Uri "$base/"
    Say ("GET / (web app) -> HTTP " + $webapp.StatusCode + ", serves React app: " + ($webapp.Content -match 'id="root"'))
} catch {
    Say ("live check FAILED: " + $_.Exception.Message); $script:Failures += "live checks"
}
if ($FrontendBuilt) {
    Step "Playwright end-to-end (Chromium, against the live system)"
    Push-Location $fe
    Run "playwright install chromium" "npx.cmd" @("playwright", "install", "chromium") | Out-Null
    $env:AGENTSMIND_URL = $base
    Run "playwright e2e" "npx.cmd" @("playwright", "test", "--reporter=list") | Out-Null
    Remove-Item Env:\AGENTSMIND_URL -ErrorAction SilentlyContinue
    Pop-Location
    Say "Playwright HTML report: frontend\playwright-report\index.html"
}
} finally {
    # Runs on success, on error and on Ctrl+C, so no server is left holding a port.
    foreach ($k in $procs.Keys) { if ($procs[$k] -and -not $procs[$k].HasExited) { Stop-Process -Id $procs[$k].Id -Force -ErrorAction SilentlyContinue } }
    Remove-Item Env:\AGENTSMIND_URL -ErrorAction SilentlyContinue
    Remove-Item Env:\DATABASE_URL, Env:\AGENTSMIND_SEED_CREDENTIALS -ErrorAction SilentlyContinue
}
foreach ($k in $parts.Keys) {
    $errf = Join-Path $LogDir "$k.err.log"
    $lines = Get-Content $errf -ErrorAction SilentlyContinue | Select-String -Pattern "Error|Traceback|refus" | Select-Object -First 6
    foreach ($l in $lines) { Say "$k| $l" }
}

Step "Summary"
if ($script:Failures.Count -eq 0) { Say "GATE RESULT: GREEN" } else { Say ("GATE RESULT: RED -> " + ($script:Failures -join "; ")) }

if ($Push) {
    Step "Push"
    if ($script:Failures.Count -ne 0) { Say "Not pushing: gate is red." }
    elseif ($Branch -notmatch '^phase/') { Say "Not pushing: only phase/* branches are allowed." }
    else {
        $leak = git rev-list $Branch -- FYP_FINAL/database/fyp_data.db FYP_FINAL/logs/orchestrator.log
        if ($leak) { Say "Not pushing: branch history still contains fyp_data.db / orchestrator.log. Run the history purge first." }
        else { Run "git push" "git" @("push", "-u", "origin", "${Branch}:${Branch}") | Out-Null }
    }
}
Say ""
Say "Log written to: $Log"
