<#
  AgentsMind: final step before publishing. Run in PowerShell next to agentsmind.bundle:

      powershell -ExecutionPolicy Bypass -File .\finish-agentsmind.ps1

  What it does (nothing here pushes to GitHub):
    1. Installs git-filter-repo 2.47.0 into the gate's .venv (run agentsmind-gate.ps1 first).
    2. Makes a mirror backup of the GitHub repository (agentsmind-backup-<date>.git).
    3. Makes a fresh clone (agentsmind-publish) and adds every phase branch from agentsmind.bundle.
    4. Removes FYP_FINAL/database/fyp_data.db and FYP_FINAL/logs/orchestrator.log from ALL history
       (main and every phase branch) with git filter-repo.
    5. Verifies the purge and runs the secrets scan on the rewritten history.
    6. Prints the exact push commands. You run them yourself, only when you decide to publish.
#>
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here
$Url = "https://github.com/FaizAhmeddev/multi-agent-system-fyp.git"
$Bundle = Join-Path $Here "agentsmind.bundle"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Backup = Join-Path $Here "agentsmind-backup-$Stamp.git"
$Work = Join-Path $Here "agentsmind-publish"
$Paths = @("FYP_FINAL/database/fyp_data.db", "FYP_FINAL/logs/orchestrator.log")
$Branches = @("phase/0-audit", "phase/1a-foundation", "phase/1b-queue-rbac-agents", "phase/2-portals-mcp",
              "phase/3-agents-calendar", "phase/4-ui", "phase/5-quality")

function Say([string]$m) { Write-Host ""; Write-Host ">>> $m" -ForegroundColor Cyan }
# Named G, not Git: PowerShell names are case-insensitive, so a function called Git would call itself.
function G { & git.exe @args; if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') failed (exit $LASTEXITCODE)" } }

if (-not (Test-Path $Bundle)) { throw "agentsmind.bundle not found next to this script." }

Say "1. git-filter-repo (installed into the gate's .venv)"
$Venv = Join-Path $Here "agentsmind\.venv\Scripts"
if (-not (Test-Path (Join-Path $Venv "python.exe"))) { throw "Run agentsmind-gate.ps1 once first; it creates agentsmind\.venv." }
& (Join-Path $Venv "python.exe") -m pip install --disable-pip-version-check -q git-filter-repo==2.47.0
if ($LASTEXITCODE -ne 0) { throw "pip install git-filter-repo failed" }
$env:PATH = "$Venv;$env:PATH"      # git finds git-filter-repo.exe on PATH
G filter-repo --version

Say "2. Mirror backup of GitHub -> $Backup"
G clone --mirror $Url $Backup
Copy-Item $Bundle (Join-Path $Here "agentsmind-backup-$Stamp.bundle")
Write-Host "Backup done. Keep this folder and the .bundle copy until the project is finished."

Say "3. Fresh clone with all phase branches -> $Work"
if (Test-Path $Work) { throw "$Work already exists. Rename or delete it, then run again." }
G clone $Url $Work
Set-Location $Work
G bundle verify $Bundle
foreach ($b in $Branches) { G fetch $Bundle "${b}:${b}" }
$before = @{}
foreach ($b in @("main") + $Branches) { $before[$b] = (& git rev-list --count $b) }

Say "4. Purge both files from every branch"
$fr = @("filter-repo", "--force", "--invert-paths")
foreach ($p in $Paths) { $fr += @("--path", $p) }
G @fr
# filter-repo removes 'origin' on purpose, so a mistaken push cannot happen until you add it back.

Say "5. Verify"
$bad = 0
$left = & git log --all --oneline -- $Paths[0] $Paths[1]
if ($left) { Write-Host "STILL IN HISTORY:"; $left; $bad++ } else { Write-Host "history: no commit touches either file" }
foreach ($b in @("main") + $Branches) {
    $files = & git ls-tree -r $b --name-only | Where-Object { $Paths -contains $_ }
    $n = (& git rev-list --count $b)
    $state = "clean"
    if ($files) { $state = "FILE STILL PRESENT"; $bad++ }
    Write-Host ("{0,-28} commits {1} (was {2})  {3}" -f $b, $n, $before[$b], $state)
}
G checkout -q phase/5-quality
& (Join-Path $Venv "python.exe") scripts\secrets_scan.py
if ($LASTEXITCODE -ne 0) { $bad++ }

Say "Result"
if ($bad -gt 0) {
    Write-Host "PURGE CHECK: FAILED. Do not push. Send me the output above." -ForegroundColor Red
    exit 1
}
Write-Host "PURGE CHECK: PASS. Nothing has been pushed." -ForegroundColor Green
Write-Host @"

When you decide to publish, run these yourself (every commit hash changes, so main needs --force):

    cd "$Work"
    git remote add origin $Url
    git push --force origin main
    git push origin $($Branches -join ' ')

Afterwards, delete or re-clone every other copy of the repository (including .\agentsmind used by the
gate) so the old history is never pushed back.
"@
