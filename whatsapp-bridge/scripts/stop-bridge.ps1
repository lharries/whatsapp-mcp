<#
.SYNOPSIS
    Stop the background whatsapp-bridge.exe process.

.DESCRIPTION
    Reads run\bridge.pid, verifies the process name, stops it, and removes the
    PID file. Exits 0 even if the bridge is already stopped (idempotent).
#>

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$bridgeDir = Split-Path -Parent $scriptDir
$pidFile   = Join-Path $bridgeDir 'run\bridge.pid'

if (-not (Test-Path $pidFile)) {
    Write-Host 'No PID file; bridge is not running.' -ForegroundColor Cyan
    exit 0
}

$pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pidValue) {
    Write-Host 'PID file empty; cleaning up.' -ForegroundColor Cyan
    Remove-Item $pidFile -Force
    exit 0
}

$proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Host "Stale PID $pidValue (process not running); cleaning up." -ForegroundColor Cyan
    Remove-Item $pidFile -Force
    exit 0
}

if ($proc.ProcessName -ne 'whatsapp-bridge') {
    Write-Host "PID $pidValue is '$($proc.ProcessName)', not whatsapp-bridge. Refusing to kill." -ForegroundColor Yellow
    Write-Host 'Delete run\bridge.pid manually after verifying.' -ForegroundColor Yellow
    exit 1
}

Stop-Process -Id $pidValue -Force
Remove-Item $pidFile -Force
Write-Host "Stopped whatsapp-bridge.exe (PID $pidValue)." -ForegroundColor Green
