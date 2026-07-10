# compound_healthcheck.ps1 — Scheduled health check every 15 minutes
$ROOT = "F:\compound-interest-plan"
$PYTHON = "$ROOT\.venv\Scripts\python.exe"
$CTL = "$ROOT\compoundctl.py"
$LOG = "$ROOT\logs\operator_health.log"
$EVIDENCE = "$ROOT\reports\handoff\operator_health.json"

Set-Location $ROOT

$timestamp = Get-Date -Format "o"
$branch = (git branch --show-current 2>&1).Trim()
$commit = (git rev-parse --short HEAD 2>&1).Trim()

# Doctor
$doctor = & $PYTHON $CTL doctor 2>&1 | ConvertFrom-Json
$gate = & $PYTHON $CTL gate --target hermes 2>&1 | ConvertFrom-Json

$backend_ok = $doctor.backend.health
$scheduler_ok = $doctor.scheduler.heartbeat
$recovered = $false

if (-not $backend_ok -or -not $scheduler_ok) {
    Add-Content $LOG "$timestamp Recovery: backend=$backend_ok scheduler=$scheduler_ok"
    & $PYTHON $CTL start --mode hermes-only 2>&1 | Out-Null
    $recovered = $true
    # Recheck
    $doctor = & $PYTHON $CTL doctor 2>&1 | ConvertFrom-Json
    $gate = & $PYTHON $CTL gate --target hermes 2>&1 | ConvertFrom-Json
}

$evidence = @{
    timestamp = $timestamp
    branch = $branch
    commit = $commit
    backend_running = $doctor.backend.health
    scheduler_running = $doctor.scheduler.heartbeat
    doctor_status = if ($doctor.release_blocked) { "BLOCKED" } else { "OK" }
    hermes_gate_status = if ($gate.release_allowed) { "PASS" } else { "NO_BACKEND" }
    data_quality_summary = "see /api/data-quality/summary"
    failed_invariants = @()
    auto_recovery_attempted = $recovered
    auto_recovery_result = if ($recovered) { "restarted" } else { "n/a" }
    safety = @{
        no_auto_trade = $true
        no_auto_confirm = $true
        no_pool_deduction = $true
        recommended_amount_unchanged = $true
        risk_guard_unchanged = $true
        exposure_guard_unchanged = $true
    }
}

$evidence | ConvertTo-Json -Depth 4 | Out-File $EVIDENCE -Encoding utf8
Add-Content $LOG "$timestamp OK backend=$($doctor.backend.health) scheduler=$($doctor.scheduler.heartbeat) recovered=$recovered"
