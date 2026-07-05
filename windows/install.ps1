<#
.SYNOPSIS
    Installs the Windows companion for lharries/whatsapp-mcp: hidden autostart of the
    Go bridge plus a recover-first watchdog scheduled task.

.DESCRIPTION
    This is an UNOFFICIAL Windows companion. It does not replace the upstream server
    or bridge; it only makes the already-built Go bridge run reliably on Windows:
      * hidden (no console window) as a normal user process,
      * with an auto-restart loop,
      * with a watchdog that silently recovers simple crashes and only surfaces a
        visible QR window when the WhatsApp session is genuinely unlinked.

    It creates exactly two things:
      1. A per-user autostart entry that runs start-whatsapp-hidden.vbs at logon.
         By default this is an "at logon" Scheduled Task (robust; survives reboots
         and does not depend on the Startup folder). Pass -UseStartupShortcut to use
         a Startup-folder .lnk instead.
      2. A Scheduled Task "WhatsApp Bridge Watchdog" that runs the watchdog every
         ~10 minutes while you are logged on.

    Everything is per-user and interactive-session scoped ON PURPOSE: the bridge only
    opens its :8080 REST port as a user process, never as a LocalSystem service.

.PARAMETER WhatsAppMcpDir
    The folder that contains the built bridge (whatsapp-bridge\whatsapp-bridge.exe)
    and this toolkit's "scripts" folder. Required. Example:
      -WhatsAppMcpDir "$env:USERPROFILE\whatsapp-mcp"

.PARAMETER WatchdogIntervalMinutes
    How often the watchdog runs. Default 10.

.PARAMETER UseStartupShortcut
    Use a Startup-folder shortcut for autostart instead of an at-logon scheduled task.

.PARAMETER Uninstall
    Remove everything this script creates (both scheduled tasks and/or the Startup
    shortcut). WhatsAppMcpDir is still required so the correct tasks are matched.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -WhatsAppMcpDir "$env:USERPROFILE\whatsapp-mcp"

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -WhatsAppMcpDir "$env:USERPROFILE\whatsapp-mcp" -Uninstall

.NOTES
    Run in a NORMAL (non-elevated) PowerShell as the user who will run WhatsApp.
    Do NOT run this elevated or as a service account: the tasks must run in your
    interactive user session for :8080 to come up.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WhatsAppMcpDir,

    [int]$WatchdogIntervalMinutes = 10,

    [switch]$UseStartupShortcut,

    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

# Task names are stable identifiers so uninstall can find them.
$AutostartTaskName = 'WhatsApp Bridge Autostart'
$WatchdogTaskName  = 'WhatsApp Bridge Watchdog'

# --- Resolve and validate paths ----------------------------------------------------
$WhatsAppMcpDir = (Resolve-Path -LiteralPath $WhatsAppMcpDir -ErrorAction Stop).Path

# The helper scripts live in a "windows" subfolder in the upstream repo layout, or a
# "scripts" subfolder in the standalone toolkit. Detect whichever exists.
$scriptsDir = $null
foreach ($candidate in @('windows', 'scripts')) {
    $probe = Join-Path $WhatsAppMcpDir $candidate
    if (Test-Path (Join-Path $probe 'start-whatsapp-hidden.vbs')) { $scriptsDir = $probe; break }
}
if (-not $scriptsDir) {
    # Fall back to a flat layout: scripts sit directly in the install dir.
    $scriptsDir = $WhatsAppMcpDir
}

$hiddenVbs      = Join-Path $scriptsDir 'start-whatsapp-hidden.vbs'
$watchdogPs1    = Join-Path $scriptsDir 'whatsapp-bridge-watchdog.ps1'
$bridgeExe      = Join-Path $WhatsAppMcpDir 'whatsapp-bridge\whatsapp-bridge.exe'

$startupDir      = [Environment]::GetFolderPath('Startup')
$startupShortcut = Join-Path $startupDir 'WhatsApp Bridge.lnk'

function Assert-File($path, $hint) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Not found: $path`n$hint"
    }
}

function Remove-Autostart {
    # Remove both possible autostart mechanisms so uninstall is thorough.
    if (Get-ScheduledTask -TaskName $AutostartTaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $AutostartTaskName -Confirm:$false
        Write-Host "Removed scheduled task: $AutostartTaskName"
    }
    if (Test-Path -LiteralPath $startupShortcut) {
        Remove-Item -LiteralPath $startupShortcut -Force
        Write-Host "Removed Startup shortcut: $startupShortcut"
    }
}

function Remove-Watchdog {
    if (Get-ScheduledTask -TaskName $WatchdogTaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $WatchdogTaskName -Confirm:$false
        Write-Host "Removed scheduled task: $WatchdogTaskName"
    }
}

# --- Uninstall path ----------------------------------------------------------------
if ($Uninstall) {
    Remove-Autostart
    Remove-Watchdog
    Write-Host ""
    Write-Host "Uninstall complete. The bridge itself and its data (store\, *.db) were left untouched."
    Write-Host "If the hidden bridge is still running, log off/on or reboot to clear it, or stop"
    Write-Host "the whatsapp-bridge process manually."
    return
}

# --- Install path ------------------------------------------------------------------
Assert-File $hiddenVbs   "Expected the toolkit 'scripts' folder inside -WhatsAppMcpDir."
Assert-File $watchdogPs1 "Expected the toolkit 'scripts' folder inside -WhatsAppMcpDir."
Assert-File $bridgeExe   "Build the upstream Go bridge first (lharries/whatsapp-mcp) so whatsapp-bridge.exe exists."

Write-Host "Install dir : $WhatsAppMcpDir"
Write-Host "Autostart   : $(if ($UseStartupShortcut) { 'Startup-folder shortcut' } else { 'At-logon scheduled task' })"
Write-Host "Watchdog    : every $WatchdogIntervalMinutes min while logged on"
Write-Host ""

# Set a persistent user environment variable so every script agrees on the location,
# regardless of how it is launched. This is the single source of truth for the path.
[Environment]::SetEnvironmentVariable('WHATSAPP_MCP_DIR', $WhatsAppMcpDir, 'User')
Write-Host "Set user environment variable WHATSAPP_MCP_DIR=$WhatsAppMcpDir"

# --- 1. Autostart ------------------------------------------------------------------
# Clear any prior autostart so re-running install is idempotent.
Remove-Autostart

if ($UseStartupShortcut) {
    # Startup-folder shortcut that runs the hidden VBS. Simple, but only fires when
    # Explorer processes the Startup folder.
    $wsh = New-Object -ComObject WScript.Shell
    $lnk = $wsh.CreateShortcut($startupShortcut)
    $lnk.TargetPath       = 'wscript.exe'
    $lnk.Arguments        = "`"$hiddenVbs`""
    $lnk.WorkingDirectory = $WhatsAppMcpDir
    $lnk.Description       = 'Start WhatsApp bridge hidden (unofficial Windows companion)'
    $lnk.Save()
    Write-Host "Created Startup shortcut: $startupShortcut"
} else {
    # At-logon scheduled task. More robust than the Startup folder: explicit trigger,
    # runs in the interactive session, survives Startup-folder quirks.
    $action  = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$hiddenVbs`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    # Run only when the user is logged on (interactive), never elevated.
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $AutostartTaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Start WhatsApp bridge hidden at logon (unofficial Windows companion)' | Out-Null
    Write-Host "Registered scheduled task: $AutostartTaskName (at logon)"
}

# --- 2. Watchdog scheduled task ----------------------------------------------------
Remove-Watchdog

# Run the watchdog with a hidden PowerShell window. -WindowStyle Hidden still flashes
# very briefly on some systems; if you want zero flash, wrap it with a no-window
# launcher of your choice. Correctness does not depend on it.
$psArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogPs1`""
$wdAction  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $psArgs

# Repeat every N minutes, indefinitely, starting a minute from now.
$wdTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $WatchdogIntervalMinutes)
$wdPrincipal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$wdSettings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $WatchdogTaskName -Action $wdAction -Trigger $wdTrigger -Principal $wdPrincipal -Settings $wdSettings -Description 'Recover-first watchdog for the WhatsApp bridge (unofficial Windows companion)' | Out-Null
Write-Host "Registered scheduled task: $WatchdogTaskName (every $WatchdogIntervalMinutes min)"

Write-Host ""
Write-Host "Done. What was created:"
Write-Host "  * User env var WHATSAPP_MCP_DIR -> $WhatsAppMcpDir"
if ($UseStartupShortcut) {
    Write-Host "  * Startup shortcut            -> $startupShortcut"
} else {
    Write-Host "  * Scheduled task              -> '$AutostartTaskName' (at logon)"
}
Write-Host "  * Scheduled task              -> '$WatchdogTaskName' (every $WatchdogIntervalMinutes min)"
Write-Host ""
Write-Host "To start now without logging off, run:"
Write-Host "  wscript `"$hiddenVbs`""
Write-Host ""
Write-Host "To undo everything:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\install.ps1 -WhatsAppMcpDir `"$WhatsAppMcpDir`" -Uninstall"
