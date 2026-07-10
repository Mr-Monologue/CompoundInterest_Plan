# install_operator_tasks.ps1 — Register Windows scheduled tasks
param([switch]$Uninstall)

$ROOT = "F:\compound-interest-plan"
$PYTHON = "$ROOT\.venv\Scripts\python.exe"
$OP = "$ROOT\ops\windows\compound_operator.ps1"
$HC = "$ROOT\ops\windows\compound_healthcheck.ps1"

if ($Uninstall) {
    schtasks /delete /tn "CompoundInterestOperator" /f 2>$null
    schtasks /delete /tn "CompoundInterestHealthCheck" /f 2>$null
    Write-Output "Uninstalled."
    exit 0
}

# System startup operator
schtasks /create /tn "CompoundInterestOperator" /sc ONSTART /delay 0000:30 `
    /tr "Powershell -ExecutionPolicy Bypass -File `"$OP`"" /ru SYSTEM /f

# Health check every 15 minutes
schtasks /create /tn "CompoundInterestHealthCheck" /sc MINUTE /mo 15 `
    /tr "Powershell -ExecutionPolicy Bypass -File `"$HC`"" /ru SYSTEM /f

schtasks /query /tn CompoundInterestOperator
schtasks /query /tn CompoundInterestHealthCheck
Write-Output "Operator tasks installed."
