@echo off
SET PATH=C:\msys64\ucrt64\bin;C:\Program Files\Go\bin;%PATH%
SET CGO_ENABLED=1
SET CC=C:\msys64\ucrt64\bin\gcc.exe
cd /d C:\Users\TAB\whatsapp-mcp\whatsapp-bridge
echo Iniciando WhatsApp Bridge...
echo Escanea el codigo QR con WhatsApp en tu telefono.
whatsapp-bridge.exe
pause
