# WhatsApp MCP — setup multi-cuenta (SerItaliano)

Fork de [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) adaptado para
varios números y para exportar el historial completo.

## Cambios sobre el repo original
- `whatsapp-bridge/`: whatsmeow actualizado (la versión original era rechazada por WhatsApp);
  puerto por `WHATSAPP_PORT`; QR guardado en `store/qr.png`; pairing por código con
  `WHATSAPP_PAIR_PHONE`; `WHATSAPP_LOGOUT=1` desvincula y sale; al vincular pide historial
  completo (`WHATSAPP_FULL_SYNC_DAYS`, default 3650 — sin esto el teléfono manda solo 1 año).
- `whatsapp-bridge/backfill.go`: history sync bajo demanda por chat (`POST /api/backfill`,
  `/api/backfill/status`, `/api/backfill/stop`). Guarda también mensajes sin texto
  (llamadas, stickers, ubicaciones) como `<tipo>`.
- `whatsapp-mcp-server/`: `WHATSAPP_MESSAGES_DB`, `WHATSAPP_API_BASE_URL`, `WHATSAPP_MCP_NAME`.

## Layout
```
bin/whatsapp-bridge         binario compilado (go build -o ../bin/whatsapp-bridge . en whatsapp-bridge/)
accounts.conf               <nombre> <puerto> por línea (ver accounts.conf.example; ignorado por git)
accounts/<nombre>/store/    sesión + messages.db de esa cuenta
accounts/<nombre>/bridge.log
exports/<nombre>/           chats/*.txt, all_messages.jsonl, index.md
scripts/wa.sh               start|stop|status|logs|pair por cuenta
scripts/backfill.sh         <cuenta> start|status|stop
scripts/full_export.sh      <cuenta>  — sync inicial → backfill total → merge backups → export
scripts/export_chats.py     <cuenta>  — solo el export a archivos
scripts/qr.html             visor de QR: python3 -m http.server 8090 y abrir /scripts/qr.html?account=X
```

## Agregar una cuenta nueva
1. Agregar `<nombre> <puerto>` a `accounts.conf`.
2. `scripts/wa.sh start <nombre>` → escanear `accounts/<nombre>/store/qr.png` (o `scripts/wa.sh pair <nombre> <telefono>`).
3. `scripts/full_export.sh <nombre>` (teléfono prendido con WhatsApp abierto).
4. Registrar el MCP:
   ```
   claude mcp add --scope user whatsapp-<nombre> \
     -e WHATSAPP_MCP_NAME=whatsapp-<nombre> \
     -e WHATSAPP_MESSAGES_DB=$PWD/accounts/<nombre>/store/messages.db \
     -e WHATSAPP_API_BASE_URL=http://localhost:<puerto>/api \
     -- /opt/homebrew/bin/uv --directory $PWD/whatsapp-mcp-server run main.py
   ```

## Notas
- Los bridges no arrancan solos al reiniciar la Mac: `scripts/wa.sh start-all`.
- La sesión vinculada puede caducar (~20 días sin uso del teléfono); si `wa.sh status` muestra la
  API caída y el log pide QR, volver a vincular (se conserva la DB).
- La DB contiene todo lo que hay en los chats, incluidos datos sensibles. No subir esta carpeta a git.
