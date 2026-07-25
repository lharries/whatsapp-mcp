# Starts the WhatsApp bridge. Keep this window open — the MCP server needs it
# running to sync messages (and, if enabled, to send them).
# First run prints a QR code: scan it in WhatsApp > Linked devices.

# --- Send capability -------------------------------------------------------
# "0" = read-only: the bridge refuses /api/send with 403 and cannot send at all.
# "1" = sending allowed.
# NOTE: this only controls the bridge. Claude also needs the matching flag in
# claude_desktop_config.json ("whatsapp" > env > WHATSAPP_MCP_ALLOW_SEND).
# Both must be "1" before a message can leave this machine.
$env:WHATSAPP_MCP_ALLOW_SEND = '0'
# ---------------------------------------------------------------------------

$env:Path = 'C:\Program Files\Go\bin;C:\msys64\ucrt64\bin;' + $env:Path
$env:CGO_ENABLED = '1'

Set-Location $PSScriptRoot\whatsapp-bridge

if (-not (Test-Path .\whatsapp-bridge.exe)) {
    Write-Host "Building bridge..." -ForegroundColor Cyan
    go build -o whatsapp-bridge.exe .
}

if ($env:WHATSAPP_MCP_ALLOW_SEND -eq '0') {
    Write-Host "Read-only mode: sending is disabled." -ForegroundColor Green
} else {
    Write-Host "WARNING: sending is ENABLED." -ForegroundColor Yellow
}

.\whatsapp-bridge.exe
