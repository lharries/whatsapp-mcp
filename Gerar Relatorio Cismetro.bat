@echo off
title Agente Cismetro - Relatorios Automaticos
color 1F
echo.
echo  ================================================
echo   AGENTE CISMETRO - Relatorios Automaticos
echo  ================================================
echo.

set SCRIPT_DIR=%~dp0
set DIAS=7
if not "%~1"=="" set DIAS=%~1

echo  Periodo: ultimos %DIAS% dias
echo.

REM ── Detecta Python automaticamente ───────────────────────────────────────────
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
    "C:\Python310\python.exe"
    "C:\anaconda3\python.exe"
) do (
    if exist %%P (
        if "!PYTHON!"=="" set PYTHON=%%P
    )
)

REM Tenta pelo PATH
if "%PYTHON%"=="" (
    where python >nul 2>&1
    if not errorlevel 1 set PYTHON=python
)

if "%PYTHON%"=="" (
    echo  [ERRO] Python nao encontrado.
    echo  Instale em https://python.org ou rode setup_windows.bat
    pause & exit /b 1
)
echo  [OK] Python: %PYTHON%
echo.

REM ── Verifica / pede API Key Anthropic ────────────────────────────────────────
set KEY_FILE=%SCRIPT_DIR%.anthropic_key

if not exist "%KEY_FILE%" goto PEDIR_KEY
set /p ANTHROPIC_API_KEY=<"%KEY_FILE%"
if "%ANTHROPIC_API_KEY%"=="" goto PEDIR_KEY
goto TEM_ANTHROPIC_KEY

:PEDIR_KEY
echo  Para o relatorio executivo com IA e necessaria a API Key da Anthropic.
echo  Acesse: https://console.anthropic.com ^> API Keys ^> Create Key
echo.
set /p ANTHROPIC_API_KEY="  Cole sua API Key Anthropic (sk-ant-...): "
if "%ANTHROPIC_API_KEY%"=="" (
    echo  [ERRO] Nenhuma key informada.
    pause & exit /b 1
)
echo %ANTHROPIC_API_KEY%> "%KEY_FILE%"
echo  [OK] Key Anthropic salva para proximas execucoes.
echo.

:TEM_ANTHROPIC_KEY

REM ── Verifica / pede Token GitHub ──────────────────────────────────────────────
set GH_TOKEN_FILE=%SCRIPT_DIR%.github_token
set GH_CONFIG_FILE=%SCRIPT_DIR%.github_config

set GITHUB_OWNER=
set GITHUB_REPO=
if exist "%GH_CONFIG_FILE%" (
    for /f "tokens=1,2 delims==" %%A in (%GH_CONFIG_FILE%) do (
        if "%%A"=="OWNER" set GITHUB_OWNER=%%B
        if "%%A"=="REPO"  set GITHUB_REPO=%%B
    )
)

if "%GITHUB_OWNER%"=="" goto CONFIG_GITHUB
if "%GITHUB_REPO%"==""  goto CONFIG_GITHUB
goto TEM_GH_CONFIG

:CONFIG_GITHUB
echo  ------------------------------------------------
echo  CONFIGURACAO GITHUB (primeira vez)
echo  ------------------------------------------------
echo  Repositorio onde os bugs serao registrados como Issues.
echo  Crie um repositorio em: https://github.com/new
echo.
set /p GITHUB_OWNER="  Seu usuario GitHub (ex: seunome): "
set /p GITHUB_REPO="  Nome do repositorio (ex: cismetro-bugs): "
if "%GITHUB_OWNER%"=="" (
    echo  [AVISO] GitHub desativado nesta execucao.
    set GITHUB_OWNER=SKIP
    goto TEM_GH_TOKEN
)
echo OWNER=%GITHUB_OWNER%> "%GH_CONFIG_FILE%"
echo REPO=%GITHUB_REPO%>> "%GH_CONFIG_FILE%"
echo  [OK] Configuracao GitHub salva.
echo.

:TEM_GH_CONFIG
if "%GITHUB_OWNER%"=="SKIP" goto TEM_GH_TOKEN

if not exist "%GH_TOKEN_FILE%" goto PEDIR_GH_TOKEN
set /p GITHUB_TOKEN=<"%GH_TOKEN_FILE%"
if "%GITHUB_TOKEN%"=="" goto PEDIR_GH_TOKEN
goto TEM_GH_TOKEN

:PEDIR_GH_TOKEN
echo  ------------------------------------------------
echo  Token GitHub: https://github.com/settings/tokens/new
echo    - Permissoes: repo (ou public_repo)
echo  ------------------------------------------------
set /p GITHUB_TOKEN="  Cole seu GitHub Token (ghp_...): "
if "%GITHUB_TOKEN%"=="" (
    echo  [AVISO] Token nao informado. GitHub ignorado.
    set GITHUB_TOKEN=SKIP
    goto TEM_GH_TOKEN
)
echo %GITHUB_TOKEN%> "%GH_TOKEN_FILE%"
echo  [OK] Token GitHub salvo.
echo.

:TEM_GH_TOKEN

REM ── Passo 1: Relatorio de Mensagens (Excel) ───────────────────────────────────
echo  [1/3] Gerando relatorio de mensagens (Excel)...
echo  ------------------------------------------------
%PYTHON% "%SCRIPT_DIR%relatorio_agente.py" %DIAS%

if errorlevel 1 (
    echo  [ERRO] Falha no relatorio Excel.
    pause & exit /b 1
)

echo.
echo  ------------------------------------------------
echo  [2/3] Gerando relatorio executivo (Word + IA)...
echo  ------------------------------------------------
%PYTHON% "%SCRIPT_DIR%gerar_relatorio_executivo.py" %DIAS%

if errorlevel 1 (
    echo  [ERRO] Falha no relatorio executivo.
    echo  Se a API Key for invalida, delete: %KEY_FILE%
    pause & exit /b 1
)

echo.
echo  ------------------------------------------------
echo  [3/3] Sincronizando bugs com GitHub Issues...
echo  ------------------------------------------------

if "%GITHUB_TOKEN%"=="SKIP" (
    echo  [--] GitHub ignorado (token nao configurado).
    goto FIM
)
if "%GITHUB_OWNER%"=="SKIP" (
    echo  [--] GitHub ignorado (repositorio nao configurado).
    goto FIM
)

%PYTHON% "%SCRIPT_DIR%github_bugs_sync.py" %DIAS%

if errorlevel 1 (
    echo  [AVISO] Falha no GitHub. Relatorios gerados normalmente.
)

:FIM
echo.
echo  ================================================
echo   Concluido!
echo   Pasta: %USERPROFILE%\Relatorios_Cismetro\
if not "%GITHUB_OWNER%"=="SKIP" (
    echo   GitHub: https://github.com/%GITHUB_OWNER%/%GITHUB_REPO%/issues
)
echo  ================================================
echo.
pause
