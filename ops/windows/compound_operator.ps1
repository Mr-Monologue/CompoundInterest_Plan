# compound_operator.ps1 — Autonomous Operator: start the Hermes runtime
# Called by: Windows Task Scheduler at system startup
# Purpose: ensure backend + scheduler are running
# Does NOT auto git pull — updates require separate command

$ErrorActionPreference = "Stop"
$ROOT = "F:\compound-interest-plan"
$PYTHON = "$ROOT\.venv\Scripts\python.exe"
$CTL = "$ROOT\compoundctl.py"
$EVIDENCE = "$ROOT\reports\handoff\operator_health.json"

Set-Location $ROOT

# Checkout release branch
git checkout release 2>&1 | Out-Null

# Check for dirty workspace
$dirty = git status --porcelain 2>&1
if ($dirty) {
    $ts = Get-Date -Format "o"
    @{timestamp=$ts;status="BLOCKED";reason="workspace_dirty";dirty=$dirty} | ConvertTo-Json | Out-File $EVIDENCE -Encoding utf8
    Write-Output "$ts BLOCKED: workspace dirty"
    exit 1
}

& $PYTHON $CTL start --mode hermes-only
& $PYTHON $CTL status

Write-Output "$(Get-Date -Format 'o') Operator started"
