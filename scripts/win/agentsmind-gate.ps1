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
    3. ruff, pytest (backend + characterization), seed, live /health and login smoke test
    4. writes everything to .\gate-logs\gate-<time>.log  (no secrets are written to the log)
#>
param(
    [string]$Branch = "",
    [switch]$Push
)
$ErrorActionPreference = "Continue"
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
Run "checkout" "git" @("checkout", "-B", $Branch, "bundle/$Branch") | Out-Null
Run "log" "git" @("log", "--oneline", "-8") | Out-Null
Run "status" "git" @("status", "--short") | Out-Null

Step "Setup (venv, pip install, .env, migrations)"
Run "setup.ps1" "powershell" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\win\setup.ps1", "-Dev") | Out-Null
$vpy = Join-Path $Repo ".venv\Scripts\python.exe"
Run "python version" $vpy @("--version") | Out-Null
Run "pip freeze" $vpy @("-m", "pip", "freeze") | Out-Null

Step "Lint"
Run "ruff" $vpy @("-m", "ruff", "check", "backend", "db", "scripts", "tests/backend") | Out-Null

Step "Tests"
Run "pytest backend" $vpy @("-m", "pytest", "tests/backend", "-q", "-rA") | Out-Null
Run "pytest characterization" $vpy @("-m", "pytest", "tests/characterization", "-q") | Out-Null

Step "Migrations from a clean database"
$env:DATABASE_URL = "sqlite:///" + ((Join-Path $Repo "data\gate-clean.db") -replace '\\', '/')
Remove-Item -ErrorAction SilentlyContinue (Join-Path $Repo "data\gate-clean.db")
Run "alembic upgrade (clean)" $vpy @("-m", "alembic", "upgrade", "head") | Out-Null
Run "alembic current" $vpy @("-m", "alembic", "current") | Out-Null
Run "seed (clean db)" $vpy @("scripts\seed.py") | Out-Null
Run "seed again (idempotent)" $vpy @("scripts\seed.py") | Out-Null
Remove-Item Env:\DATABASE_URL

Step "Live smoke test (uvicorn on 127.0.0.1:18765)"
$port = 18765
$proc = Start-Process -FilePath $vpy -ArgumentList @("-m", "uvicorn", "agentsmind.main:app", "--app-dir", "backend",
    "--host", "127.0.0.1", "--port", "$port") -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "uvicorn.out.log") -RedirectStandardError (Join-Path $LogDir "uvicorn.err.log")
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2; $ok = $true; break } catch { }
}
if ($ok) {
    Say ("GET /health -> " + ($h | ConvertTo-Json -Compress))
    $adm = (Get-Content (Join-Path $Repo "data\first_admin.txt") -ErrorAction SilentlyContinue) -split "`t"
    if ($adm.Count -ge 2) {
        try {
            $body = @{ email = $adm[0]; password = $adm[1] } | ConvertTo-Json
            $t = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$port/api/auth/login" -Body $body -ContentType "application/json"
            Say ("POST /api/auth/login -> 200, roles=" + ($t.user.roles -join ","))
            $auth = @{ Authorization = "Bearer " + $t.access_token }
            $me = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/auth/me" -Headers $auth
            Say ("GET /api/auth/me -> " + $me.email)
            $deps = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/departments" -Headers $auth
            Say ("GET /api/departments -> " + (($deps.items | ForEach-Object { $_.slug + "=" + $_.accessible }) -join ", "))
            # End to end through the persistent queue: API enqueues, a separate worker process runs it.
            $env:PYTHONPATH = "backend"
            $wproc = Start-Process -FilePath $vpy -ArgumentList @("-m", "agentsmind.queue.worker") -PassThru -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $LogDir "worker.out.log") -RedirectStandardError (Join-Path $LogDir "worker.err.log")
            $runBody = @{ action = "troubleshoot"; inputs = @{ problem = "My laptop cannot connect to office wifi" } } | ConvertTo-Json -Depth 4
            $run = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$port/api/agents/it/runs" -Headers $auth -Body $runBody -ContentType "application/json"
            Say ("POST /api/agents/it/runs -> run " + $run.id + " status=" + $run.status)
            $final = $null
            for ($j = 0; $j -lt 40; $j++) {
                Start-Sleep -Milliseconds 500
                $final = Invoke-RestMethod -Uri ("http://127.0.0.1:$port/api/agents/runs/" + $run.id) -Headers $auth
                if ($final.status -in @("done", "failed")) { break }
            }
            Say ("GET /api/agents/runs/" + $run.id + " -> status=" + $final.status + " simulated=" + $final.simulated)
            Say ("   output: " + ($final.output.Substring(0, [Math]::Min(160, $final.output.Length))))
            if ($final.status -ne "done") { $script:Failures += "worker end-to-end" }
            if ($wproc -and -not $wproc.HasExited) { Stop-Process -Id $wproc.Id -Force }
            Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
        } catch { Say ("login smoke FAILED: " + $_.Exception.Message); $script:Failures += "login smoke" }
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/admin/users" | Out-Null
            Say "GET /api/admin/users without token -> UNEXPECTED SUCCESS"; $script:Failures += "unauth check"
        } catch { Say ("GET /api/admin/users without token -> " + [int]$_.Exception.Response.StatusCode + " (expected 401)") }
    } else { Say "data\first_admin.txt missing (an existing .env was reused); login smoke skipped" }
} else {
    Say "API did not start. uvicorn stderr:"; Get-Content (Join-Path $LogDir "uvicorn.err.log") | Tee-Object -FilePath $Log -Append
    $script:Failures += "api start"
}
if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
Get-Content (Join-Path $LogDir "uvicorn.out.log"), (Join-Path $LogDir "uvicorn.err.log") -ErrorAction SilentlyContinue |
    Select-Object -Last 15 | ForEach-Object { Say "uvicorn| $_" }

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
