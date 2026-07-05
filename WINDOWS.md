# Running whatsapp-mcp on Windows

This page covers running the Go `whatsapp-bridge` reliably on Windows: hidden (no console window), as a normal user process, with auto-restart and a QR-recovery watchdog. The helper scripts live in the [`windows/`](./windows) folder.

The Python MCP server and the Go bridge themselves are unchanged. This is purely the Windows process-management layer around them.

## Why Windows needs special handling

- **The bridge must run as a user process, not a Windows service.** whatsmeow links WhatsApp Web's multi-device session in the interactive user context. Run the bridge as a LocalSystem service and it starts, but its `:8080` REST port never opens, so the MCP server has nothing to connect to. Running it as the logged-in user is the only configuration that reliably brings `:8080` up.
- **A permanent visible console is undesirable.** Running it as a user process normally leaves a terminal window open forever. The scripts here run it hidden.
- **The QR is only needed occasionally.** WhatsApp sometimes unlinks a device and the bridge then waits for a fresh QR scan. Showing a window on every restart is noise. The watchdog discriminates: it silently recovers ordinary crashes and only surfaces a visible QR window when the bridge log actually indicates the session is unlinked.

## Files

| File | Purpose |
| --- | --- |
| `windows/start-whatsapp-hidden.vbs` | Launches the bridge hidden (no window), fire-and-forget. |
| `windows/start-whatsapp-bridge.bat` | Auto-restart loop; UTF-8 console so a logged QR stays legible; writes `bridge.log`. |
| `windows/qr-bridge.bat` | Runs the bridge in a visible window so the QR is scannable. |
| `windows/whatsapp-bridge-watchdog.ps1` | Recover-first watchdog; QR window + notification only when truly unlinked. |
| `windows/install.ps1` | Registers hidden autostart + the watchdog scheduled task. Parameterized. |

No script hard-codes a user-specific path. They resolve the install directory from the `WHATSAPP_MCP_DIR` environment variable, or fall back to their own location.

## Prerequisites

- Windows 10 or 11.
- The Go bridge already built, so `whatsapp-bridge/whatsapp-bridge.exe` exists (follow the main README's bridge build steps).
- PowerShell 5.1+ (ships with Windows).

## Setup

1. Build the bridge as usual, and do a first manual link (scan the QR once) so you know it works.

2. From the repo root, smoke-test in a visible window to confirm `:8080` comes up:

   ```powershell
   $env:WHATSAPP_MCP_DIR = (Get-Location).Path
   .\windows\qr-bridge.bat
   ```

   In another terminal, `Get-NetTCPConnection -LocalPort 8080 -State Listen` should show it listening. Close the window when satisfied.

3. Install hidden autostart + the watchdog (run as your normal, non-elevated user):

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\windows\install.ps1 -WhatsAppMcpDir (Get-Location).Path
   ```

4. Start it now without logging off:

   ```powershell
   wscript "$(Get-Location)\windows\start-whatsapp-hidden.vbs"
   ```

From then on the bridge starts hidden at logon, restarts itself on crash, and only surfaces a QR window when WhatsApp genuinely unlinks the device.

### What `install.ps1` creates

- A user environment variable `WHATSAPP_MCP_DIR` (the single source of truth for paths).
- An at-logon Scheduled Task `WhatsApp Bridge Autostart` (or a Startup-folder shortcut with `-UseStartupShortcut`).
- A Scheduled Task `WhatsApp Bridge Watchdog` running every ~10 minutes (`-WatchdogIntervalMinutes` to change).

### Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install.ps1 -WhatsAppMcpDir (Get-Location).Path -Uninstall
```

Removes the scheduled tasks and/or Startup shortcut. Does not touch the bridge binary, `store/`, or the message database.

## How the watchdog decides (recover-first)

1. `:8080` listening -> healthy. Closes any leftover QR window, clears the alert flag.
2. `:8080` down -> re-check after a few seconds (a normal restart must not trigger anything).
3. Still down -> relaunch the hidden bridge and wait ~15s. If `:8080` returns, it was a simple crash: recovered silently.
4. Still not connecting -> read the tail of `bridge.log`:
   - Log shows the session is unlinked (waiting for a QR) -> open `qr-bridge.bat` in a visible window and notify.
   - Otherwise -> notify "bridge down, not reconnecting".

A flag file provides a cooldown so the alert is not repeated until `:8080` is healthy again.

## Notes and limitations

- Everything runs in the interactive user session by design; there is no headless/service mode, because `:8080` only opens as a user process.
- The QR-detection strings the watchdog matches in `bridge.log` are `Timeout waiting for QR` and `Scan this QR code`. If the bridge's log wording changes, update the match in `whatsapp-bridge-watchdog.ps1`.
- `-WindowStyle Hidden` on the watchdog task may flash briefly on some systems; it does not affect correctness.
