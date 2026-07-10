# install_operator_tasks.ps1 — Register Windows scheduled tasks
param([switch]$Uninstall, [switch]$RunAsSystem)

$ROOT = "F:\compound-interest-plan"
$OP = "$ROOT\ops\windows\compound_operator.ps1"
$HC = "$ROOT\ops\windows\compound_healthcheck.ps1"
$RUNAS = if ($RunAsSystem) { "SYSTEM" } else { [System.Security.Principal.WindowsIdentity]::GetCurrent().Name }

if ($Uninstall) {
    schtasks /delete /tn "CompoundInterestOperator" /f 2>$null
    schtasks /delete /tn "CompoundInterestHealthCheck" /f 2>$null
    Write-Output "Uninstalled."
    exit 0
}

# System startup operator
schtasks /create /tn "CompoundInterestOperator" /sc ONSTART /delay 0000:30 `
    /tr "Powershell -ExecutionPolicy Bypass -File `"$OP`"" /ru $RUNAS /f

# Health check every 15 minutes
schtasks /create /tn "CompoundInterestHealthCheck" /sc MINUTE /mo 15 `
    /tr "Powershell -ExecutionPolicy Bypass -File `"$HC`"" /ru $RUNAS /f

schtasks /query /tn CompoundInterestOperator
schtasks /query /tn CompoundInterestHealthCheck
Write-Output "Operator tasks installed as $RUNAS."
