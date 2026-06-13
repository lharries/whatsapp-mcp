@echo off
setlocal enabledelayedexpansion
title Setup - Agente WhatsApp Cismetro
color 0B
echo.
echo  ============================================================
echo   SETUP — Agente WhatsApp Cismetro
echo   Instala dependencias e configura o ambiente
echo  ============================================================
echo.

set SCRIPT_DIR=%~dp0

REM ── 1. Verifica Go ────────────────────────────────────────────────────────────
echo  [1/5] Verificando Go...
where go >nul 2>&1
if errorlevel 1 (
    echo  [!] Go nao encontrado.
    echo  Baixe e instale Go em: https://go.dev/dl/
    echo  Apos instalar, feche e reabra este script.
    pause & exit /b 1
)
for /f "tokens=3" %%V in ('go version') do echo  [OK] Go %%V encontrado.

REM ── 2. Compila whatsapp-bridge ────────────────────────────────────────────────
echo.
echo  [2/5] Compilando whatsapp-bridge.exe...
cd /d "%SCRIPT_DIR%whatsapp-bridge"

if exist whatsapp-bridge.exe (
    echo  [OK] Binario ja existe. Recompilando para garantir versao atual...
)

set CGO_ENABLED=1
go build -o whatsapp-bridge.exe . 2>&1
if errorlevel 1 (
    echo.
    echo  [ERRO] Falha na compilacao.
    echo  Dica: No Windows, CGO requer MinGW. Instale via:
    echo    https://github.com/brechtsanders/winlibs_mingw/releases
    echo    ou: winget install --id GnuWin32.Make
    echo  Depois adicione C:\mingw64\bin ao PATH do sistema.
    pause & exit /b 1
)
echo  [OK] whatsapp-bridge.exe compilado com sucesso.
cd /d "%SCRIPT_DIR%"

REM ── 3. Detecta / instala Python ───────────────────────────────────────────────
echo.
echo  [3/5] Verificando Python...

set PYTHON=
for %%P in (
    "%SCRIPT_DIR%venv\Scripts\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "%USERPROFILE%\AppData\Local\anaconda3\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\anaconda3\python.exe"
) do (
    if exist %%P if "!PYTHON!"=="" set PYTHON=%%P
)

if "%PYTHON%"=="" (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%P in ('where python') do if "!PYTHON!"=="" set PYTHON=%%P
    )
)

if "%PYTHON%"=="" (
    echo  [!] Python nao encontrado.
    echo  Opcao A - Instale Python: https://python.org/downloads
    echo  Opcao B - Instale Anaconda: https://anaconda.com/download
    echo  Apos instalar, reabra este script.
    pause & exit /b 1
)
echo  [OK] Python encontrado: %PYTHON%

REM ── 4. Instala dependencias Python ───────────────────────────────────────────
echo.
echo  [4/5] Instalando pacotes Python...
%PYTHON% -m pip install --upgrade pip -q
%PYTHON% -m pip install openpyxl python-docx anthropic requests -q

if errorlevel 1 (
    echo  [ERRO] Falha ao instalar pacotes. Verifique sua conexao com a internet.
    pause & exit /b 1
)
echo  [OK] Pacotes instalados: openpyxl, python-docx, anthropic, requests

REM ── 5. Cria atalhos na area de trabalho ──────────────────────────────────────
echo.
echo  [5/5] Criando atalhos na area de trabalho...

set DESKTOP=%USERPROFILE%\Desktop
if not exist "%DESKTOP%" set DESKTOP=%USERPROFILE%\OneDrive\Desktop

REM Atalho: Iniciar Bridge
%PYTHON% -c "
import os, sys
try:
    import winshell
    from win32com.client import Dispatch
except:
    sys.exit(0)
desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
if not os.path.exists(desktop):
    desktop = os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop')
shell = Dispatch('WScript.Shell')
for name, target in [
    ('Iniciar WhatsApp Bridge', r'%SCRIPT_DIR%Iniciar WhatsApp Bridge.bat'),
    ('Relatorio Cismetro',      r'%SCRIPT_DIR%Gerar Relatorio Cismetro.bat'),
]:
    lnk = shell.CreateShortCut(os.path.join(desktop, name + '.lnk'))
    lnk.Targetpath = target
    lnk.WorkingDirectory = r'%SCRIPT_DIR%'
    lnk.save()
print('Atalhos criados.')
" 2>nul

REM Metodo alternativo via PowerShell se Python nao tiver winshell
powershell -NoProfile -Command "
$WshShell = New-Object -ComObject WScript.Shell
$desktop = [System.Environment]::GetFolderPath('Desktop')
if (-not (Test-Path $desktop)) { $desktop = Join-Path $env:USERPROFILE 'OneDrive\Desktop' }

$lnk1 = $WshShell.CreateShortcut(\"$desktop\Iniciar WhatsApp Bridge.lnk\")
$lnk1.TargetPath = '%SCRIPT_DIR%Iniciar WhatsApp Bridge.bat'
$lnk1.WorkingDirectory = '%SCRIPT_DIR%'
$lnk1.Save()

$lnk2 = $WshShell.CreateShortcut(\"$desktop\Relatorio Cismetro.lnk\")
$lnk2.TargetPath = '%SCRIPT_DIR%Gerar Relatorio Cismetro.bat'
$lnk2.WorkingDirectory = '%SCRIPT_DIR%'
$lnk2.Save()
Write-Host '[OK] Atalhos criados na area de trabalho.'
" 2>nul

echo.
echo  ============================================================
echo   SETUP CONCLUIDO!
echo  ============================================================
echo.
echo  PROXIMO PASSO — Autenticar WhatsApp:
echo  ----------------------------------------
echo  1. Clique duplo em "Iniciar WhatsApp Bridge" na area de trabalho
echo  2. Uma janela abrira com um QR Code
echo  3. No seu celular: WhatsApp ^> Dispositivos conectados ^> Conectar dispositivo
echo  4. Escaneie o QR Code
echo  5. Aguarde "Client is ready!" aparecer na janela
echo.
echo  Depois disso:
echo  - Clique em "Relatorio Cismetro" para gerar os relatorios
echo  - Na primeira vez, informe sua API Key Anthropic e token GitHub
echo.
echo  Repositorio: https://github.com/conejoOCN/whatsapp-mcp
echo  ============================================================
echo.
pause
