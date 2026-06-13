@echo off
title Copiar Sessao WhatsApp para VPS
color 1F
echo.
echo  ============================================================
echo   COPIAR SESSAO WHATSAPP PARA VPS
echo  ============================================================
echo.
echo  Este script copia a pasta /store (sessao autenticada)
echo  do seu PC para a VPS, dispensando novo QR Code.
echo.

REM ---- CONFIGURE AQUI ----
set VPS_USER=seu_usuario
set VPS_IP=00.00.00.00
set VPS_PATH=/opt/cismetro/store
REM -------------------------

set LOCAL_STORE=%USERPROFILE%\store

if not exist "%LOCAL_STORE%" (
    echo  [ERRO] Pasta de sessao nao encontrada: %LOCAL_STORE%
    echo  Certifique-se de que o bridge foi executado ao menos uma vez.
    pause
    exit /b 1
)

echo  Origem:  %LOCAL_STORE%
echo  Destino: %VPS_USER%@%VPS_IP%:%VPS_PATH%
echo.
echo  Iniciando copia via SCP...
echo.

scp -r "%LOCAL_STORE%\*" %VPS_USER%@%VPS_IP%:%VPS_PATH%/

if errorlevel 1 (
    echo.
    echo  [ERRO] Falha na copia. Verifique:
    echo    - IP da VPS esta correto
    echo    - SSH esta habilitado na VPS
    echo    - Usuario tem permissao em %VPS_PATH%
) else (
    echo.
    echo  [OK] Sessao copiada com sucesso!
    echo.
    echo  Na VPS, execute:
    echo    systemctl start whatsapp-bridge
    echo    systemctl status whatsapp-bridge
)

echo.
pause
