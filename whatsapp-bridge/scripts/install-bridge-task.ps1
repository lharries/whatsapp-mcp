<#
.SYNOPSIS
    Register a per-user Scheduled Task that runs start-bridge.ps1 at every logon.

.DESCRIPTION
    No admin required. Task name: WhatsAppBridge. Re-running this script
    replaces any existing task with the same name.
#>

$ErrorActionPreference = 'Stop'

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $scriptDir 'start-bridge.ps1'

if (-not (Test-Path $startScript)) {
    Write-Host "start-bridge.ps1 not found next to this script." -ForegroundColor Red
    exit 1
}

$taskName = 'WhatsAppBridge'

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Remove any existing task with the same name so this script is re-runnable.
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $taskName `
    -Description 'Launch whatsapp-bridge.exe at logon (per-user, hidden).' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal | Out-Null

Write-Host "Registered Scheduled Task '$taskName' for user $env:USERNAME." -ForegroundColor Green
Write-Host 'It will run start-bridge.ps1 every time you log on.'
Write-Host 'To test now, log off and back on, or run:'
Write-Host "    Start-ScheduledTask -TaskName $taskName"
