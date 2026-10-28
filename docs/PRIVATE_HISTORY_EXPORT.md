# Private WhatsApp history export

This repository's bridge stores messages in `whatsapp-bridge/store/messages.db`. The export script reads that local database in **read-only** mode and creates:

- `chats.csv`
- `messages.csv` (spreadsheet-friendly UTF-8 with BOM)
- `messages.jsonl` (one JSON object per message)
- `summary.json` (counts and limitations)

## Important limits

- The script exports only records that already exist in the local SQLite database. It cannot force WhatsApp to provide messages that were never synced to the linked device.
- The official WhatsApp mobile app must be linked to the bridge by scanning the QR code from **WhatsApp > Settings > Linked Devices**. This requires a one-time action by the account owner; no Meta Cloud API key is needed for this bridge.
- Let the bridge finish syncing before exporting. Large accounts may take time. Compare exported counts and date ranges against WhatsApp before treating the archive as complete.
- Media files are not embedded in these CSV/JSONL files. The database may contain media metadata; use the project's media download functionality when authorized and needed.
- Do not put a WhatsApp database, exports, media, QR codes, session credentials, or personal message content in GitHub, Codespaces logs, issues, or pull requests. Keep the export on private storage with a backup.
- This community project connects through WhatsApp Web's multi-device protocol and is not an official WhatsApp export API. Use at your own risk and only for accounts/data you are authorized to access.

## Run

From the repository root, after the bridge has been linked and the database has synced:

```bash
python3 tools/export_history.py
```

To select a database and output folder explicitly:

```bash
python3 tools/export_history.py --db whatsapp-bridge/store/messages.db --out /path/to/private-whatsapp-archive
```

The exporter opens the database read-only and deliberately excludes cryptographic media-key columns from exported output. Keep the output directory private.
