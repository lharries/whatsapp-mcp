<#
.SYNOPSIS
    Remove the WhatsAppBridge Scheduled Task created by install-bridge-task.ps1.
#>

$ErrorActionPreference = 'Stop'

$taskName = 'WhatsAppBridge'

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "No Scheduled Task named '$taskName' found." -ForegroundColor Cyan
    exit 0
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Removed Scheduled Task '$taskName'." -ForegroundColor Green
