@echo off
title WhatsApp Bridge
color 0A
echo.
echo  ================================================
echo   WhatsApp Bridge - Iniciando...
echo  ================================================
echo.

cd /d "C:\Users\eduar\whatsapp-mcp\whatsapp-bridge"
start "" "whatsapp-bridge.exe"

echo  Bridge iniciado! Esta janela pode ser fechada.
timeout /t 3 >nul
