@echo off
REM qr-bridge.bat
REM Runs the whatsapp-bridge in a VISIBLE console window so you can scan the login QR.
REM
REM Use this when WhatsApp has genuinely unlinked the session and you need to re-pair
REM the device. The watchdog launches this automatically when it detects that the
REM session needs re-linking, but you can also run it by hand.
REM
REM Once the QR shows, on your phone open:
REM   WhatsApp > Settings > Linked Devices > Link a device
REM and scan the code. After a successful link, close this window and let the hidden
REM launcher (start-whatsapp-hidden.vbs) take over again.
REM
REM Paths are resolved the same way as start-whatsapp-bridge.bat: via %WHATSAPP_MCP_DIR%
REM if set, otherwise derived from this script's own location (%~dp0). No user-specific
REM path is hard-coded.

chcp 65001 >nul
title WhatsApp QR - scan with your phone

setlocal enabledelayedexpansion

if defined WHATSAPP_MCP_DIR (
    set "MCP_DIR=%WHATSAPP_MCP_DIR%"
) else (
    set "SCRIPT_DIR=%~dp0"
    if "!SCRIPT_DIR:~-1!"=="\" set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"
    if exist "!SCRIPT_DIR!\whatsapp-bridge\whatsapp-bridge.exe" (
        set "MCP_DIR=!SCRIPT_DIR!"
    ) else (
        for %%I in ("!SCRIPT_DIR!\..") do set "MCP_DIR=%%~fI"
    )
)

set "BRIDGE_DIR=%MCP_DIR%\whatsapp-bridge"
set "BRIDGE_EXE=%BRIDGE_DIR%\whatsapp-bridge.exe"

if not exist "%BRIDGE_EXE%" (
    echo ERROR: bridge binary not found at "%BRIDGE_EXE%".
    echo Build the Go bridge first ^(see upstream lharries/whatsapp-mcp^), then retry.
    pause
    exit /b 1
)

cd /d "%BRIDGE_DIR%"
"%BRIDGE_EXE%"
