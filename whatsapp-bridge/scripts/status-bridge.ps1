<#
.SYNOPSIS
    Report whether the background whatsapp-bridge.exe is running and tail its log.
#>

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$bridgeDir = Split-Path -Parent $scriptDir
$pidFile   = Join-Path $bridgeDir 'run\bridge.pid'
$outLog    = Join-Path $bridgeDir 'logs\bridge.out.log'
$errLog    = Join-Path $bridgeDir 'logs\bridge.err.log'

if (-not (Test-Path $pidFile)) {
    Write-Host 'State : stopped (no PID file)' -ForegroundColor Yellow
} else {
    $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $pidValue) {
        Write-Host 'State : stopped (empty PID file)' -ForegroundColor Yellow
    } else {
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if (-not $proc) {
            Write-Host "State : stopped (PID $pidValue not running; stale file)" -ForegroundColor Yellow
        } elseif ($proc.ProcessName -ne 'whatsapp-bridge') {
            Write-Host "State : unknown (PID $pidValue is '$($proc.ProcessName)')" -ForegroundColor Yellow
        } else {
            $uptime = (Get-Date) - $proc.StartTime
            Write-Host "State : running (PID $pidValue, uptime $([int]$uptime.TotalMinutes) min)" -ForegroundColor Green
        }
    }
}

if (Test-Path $outLog) {
    Write-Host ''
    Write-Host "--- last 20 lines of $outLog ---" -ForegroundColor Cyan
    Get-Content -Path $outLog -Tail 20
}

if (Test-Path $errLog) {
    $errInfo = Get-Item $errLog
    if ($errInfo.Length -gt 0) {
        Write-Host ''
        Write-Host "--- last 20 lines of $errLog ---" -ForegroundColor Cyan
        Get-Content -Path $errLog -Tail 20
    }
}
