@echo off
REM start-whatsapp-bridge.bat
REM Auto-restart loop for the whatsapp-bridge (the Go binary from lharries/whatsapp-mcp).
REM
REM Why the UTF-8 console (chcp 65001): the bridge draws the login QR code to its
REM   console when WhatsApp needs to be re-linked. Forcing the console to UTF-8 keeps
REM   the QR block characters legible in bridge.log, so a captured QR is still scannable.
REM Why the loop: the bridge is a long-running process; if it crashes we restart it
REM   after a short delay instead of leaving WhatsApp offline until someone notices.
REM
REM Paths: this script does NOT hard-code any user-specific path. It resolves the
REM   install directory in this order:
REM     1. %WHATSAPP_MCP_DIR% if set (exported by start-whatsapp-hidden.vbs or install.ps1)
REM     2. otherwise, derived from this script's own location (%~dp0):
REM          - if this .bat sits in a "scripts" subfolder, the install dir is its parent
REM          - if it sits directly in the install dir, that folder is used
REM   The bridge binary is expected at <install dir>\whatsapp-bridge\whatsapp-bridge.exe
REM   and bridge.log is written to <install dir>\bridge.log.

chcp 65001 >nul

setlocal enabledelayedexpansion

REM --- Resolve the install directory (WHATSAPP_MCP_DIR) ---
if defined WHATSAPP_MCP_DIR (
    set "MCP_DIR=%WHATSAPP_MCP_DIR%"
) else (
    set "SCRIPT_DIR=%~dp0"
    REM Strip trailing backslash for clean comparisons.
    if "!SCRIPT_DIR:~-1!"=="\" set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"
    if exist "!SCRIPT_DIR!\whatsapp-bridge\whatsapp-bridge.exe" (
        REM Flat layout: scripts live directly in the install dir.
        set "MCP_DIR=!SCRIPT_DIR!"
    ) else (
        REM Normal layout: scripts live in <install dir>\scripts\, so go up one level.
        for %%I in ("!SCRIPT_DIR!\..") do set "MCP_DIR=%%~fI"
    )
)

set "BRIDGE_DIR=%MCP_DIR%\whatsapp-bridge"
set "BRIDGE_EXE=%BRIDGE_DIR%\whatsapp-bridge.exe"
set "LOG=%MCP_DIR%\bridge.log"

if not exist "%BRIDGE_EXE%" (
    echo [%date% %time%] ERROR: bridge binary not found at "%BRIDGE_EXE%" >> "%LOG%"
    echo Build the Go bridge first ^(see upstream lharries/whatsapp-mcp^), then retry. >> "%LOG%"
    exit /b 1
)

:loop
cd /d "%BRIDGE_DIR%"
"%BRIDGE_EXE%" >> "%LOG%" 2>&1
echo [%date% %time%] whatsapp-bridge exited, restarting in 10s >> "%LOG%"
timeout /t 10 /nobreak >nul
goto loop
