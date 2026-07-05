<#
    whatsapp-bridge-watchdog.ps1

    Watches the whatsapp-bridge (which runs HIDDEN, exposing a REST server on :8080).
    Intended to be fired by a scheduled task every ~10 minutes, with no visible window.

    RECOVER-FIRST logic (robust, avoids false QR alarms):
      1. :8080 is listening  -> healthy. If a leftover qr-bridge window is still open
         from an already-resolved episode, close it and return to hidden mode. Clear
         the alert flag.
      2. :8080 is NOT listening -> re-confirm after a few seconds (a normal restart
         must not trigger anything).
      3. Still down -> ATTEMPT RECOVERY: relaunch the hidden bridge and wait ~15s.
           - If :8080 comes back, it was a simple crash: recovered silently, no
             notification.
      4. If it still will not connect -> now discriminate using the bridge log:
           - The log asks for a QR (session genuinely unlinked) -> launch qr-bridge.bat
             (a VISIBLE window with the QR) and notify. This is the only case that
             needs a human action (scanning the code).
           - Otherwise -> notify "down, not reconnecting".
    Cooldown via a flag file: the alert is not repeated until :8080 is healthy again.

    INSTALL LOCATION:
      Set $WhatsAppMcpDir below to the folder that contains the "whatsapp-bridge"
      directory and the scripts. By default it reads the WHATSAPP_MCP_DIR environment
      variable, and if that is not set, falls back to the parent of this script's
      folder (the normal "scripts\" layout). Edit the default if your layout differs.
#>

$ErrorActionPreference = 'SilentlyContinue'

# --- Resolve the install directory -------------------------------------------------
# Priority: WHATSAPP_MCP_DIR env var -> parent of this script's folder -> script folder.
$WhatsAppMcpDir = $env:WHATSAPP_MCP_DIR
if ([string]::IsNullOrWhiteSpace($WhatsAppMcpDir) -or -not (Test-Path $WhatsAppMcpDir)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path (Join-Path $scriptDir 'whatsapp-bridge')) {
        # Flat layout: this script sits directly in the install dir.
        $WhatsAppMcpDir = $scriptDir
    } else {
        # Normal layout: this script sits in <install dir>\scripts\.
        $WhatsAppMcpDir = Split-Path -Parent $scriptDir
    }
}

$wa     = $WhatsAppMcpDir
$log    = Join-Path $wa 'bridge.log'
$vbs    = Join-Path $wa 'scripts\start-whatsapp-hidden.vbs'
$qrbat  = Join-Path $wa 'scripts\qr-bridge.bat'
$bdir   = Join-Path $wa 'whatsapp-bridge'
$flag   = Join-Path $wa '.watchdog-alert.flag'
$slashC = [char]47 + 'c'   # "/c" without embedding a literal slash the parser might mangle

# Fallback for a flat layout where scripts sit next to the bridge, not under scripts\.
if (-not (Test-Path $vbs))   { $vbs   = Join-Path $wa 'start-whatsapp-hidden.vbs' }
if (-not (Test-Path $qrbat)) { $qrbat = Join-Path $wa 'qr-bridge.bat' }

function Test-Up {
    [bool](Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue)
}

function Notify([string]$title, [string]$body) {
    # Balloon notification (NotifyIcon): reliable on Windows 11 Home, non-modal,
    # works from an interactive session.
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
        Add-Type -AssemblyName System.Drawing -ErrorAction SilentlyContinue
        $ni = New-Object System.Windows.Forms.NotifyIcon
        $ni.Icon = [System.Drawing.SystemIcons]::Warning
        $ni.Visible = $true
        $ni.ShowBalloonTip(20000, $title, $body, [System.Windows.Forms.ToolTipIcon]::Warning)
        Start-Sleep -Seconds 8
        $ni.Dispose()
    } catch {}
}

function Stop-AllBridge {
    # Kill the restart-loop .bat (hidden or QR) and the bridge binary itself, so a
    # clean relaunch does not race an old instance for :8080.
    Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'start-whatsapp-bridge|qr-bridge' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-Process whatsapp-bridge -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

function Start-Hidden {
    # Relaunch the hidden loop via wscript, propagating the resolved install dir so
    # the child scripts agree on paths.
    ([wmiclass]'Win32_Process').Create("wscript.exe `"$vbs`"") | Out-Null
}

# --- 1. Healthy state --------------------------------------------------------------
if (Test-Up) {
    $qr = Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
          Where-Object { $_.CommandLine -match 'qr-bridge' }
    if ($qr) { Stop-AllBridge; Start-Hidden }   # QR episode already resolved -> back to hidden
    Remove-Item $flag -Force -ErrorAction SilentlyContinue
    return
}

# --- 2. Re-confirm (do not act during a momentary restart) -------------------------
Start-Sleep -Seconds 6
if (Test-Up) { return }

# --- 3. Attempt recovery (simple crash): relaunch the hidden loop ------------------
Stop-AllBridge
Start-Hidden
Start-Sleep -Seconds 15
if (Test-Up) {
    Remove-Item $flag -Force -ErrorAction SilentlyContinue
    return
}

# --- 4. Not reconnecting: discriminate via the log and notify (once per episode) ---
if (-not (Test-Path $flag)) {
    $needsQR = $false
    if (Test-Path $log) {
        # These strings are what the upstream bridge prints when the session is
        # unlinked and it is waiting for a fresh QR scan.
        $tail = Get-Content $log -Tail 40 -ErrorAction SilentlyContinue
        if ($tail -match 'Timeout waiting for QR|Scan this QR code') { $needsQR = $true }
    }
    if ($needsQR) {
        Stop-AllBridge
        # Launch the VISIBLE QR window in the bridge directory so the code renders.
        ([wmiclass]'Win32_Process').Create("cmd.exe $slashC `"$qrbat`"", $bdir) | Out-Null
        Notify 'WhatsApp bridge unlinked' 'A window with a QR code has appeared. Scan it from your phone: WhatsApp > Linked Devices > Link a device.'
    } else {
        Notify 'WhatsApp bridge down' 'The bridge is not reconnecting on its own. Check it when you can (run qr-bridge.bat, or inspect bridge.log).'
    }
    # Set the cooldown flag so we do not renotify until :8080 is healthy again.
    Set-Content -Path $flag -Value ((Get-Date).ToString('s')) -ErrorAction SilentlyContinue
}
return
