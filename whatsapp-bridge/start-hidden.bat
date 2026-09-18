@echo off
cd /d "E:\Whatsapp MCP\whatsapp-bridge"
echo. >> bridge.log
echo ===== Inicio %date% %time% ===== >> bridge.log
"E:\Whatsapp MCP\whatsapp-bridge\whatsapp-bridge.exe" >> bridge.log 2>&1
