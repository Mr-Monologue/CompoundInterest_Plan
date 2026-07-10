# compound_operator.ps1 — Autonomous Operator: start the Hermes runtime
# Called by: Windows Task Scheduler at system startup
# Purpose: ensure backend + scheduler are running

$ErrorActionPreference = "Stop"
$ROOT = "F:\compound-interest-plan"
$PYTHON = "$ROOT\.venv\Scripts\python.exe"
$CTL = "$ROOT\compoundctl.py"

Set-Location $ROOT
git checkout release 2>&1 | Out-Null
git pull github release 2>&1 | Out-Null

& $PYTHON $CTL start --mode hermes-only
& $PYTHON $CTL status

Write-Output "$(Get-Date -Format 'o') Operator started"
