# whatsapp-mcp — code & architecture digest

Reference source for planning. Describes the current implementation of this fork
(`frans-nekongo/whatsapp-mcp`, a fork of `lharries/whatsapp-mcp`).

## Components
- **Go bridge** (`whatsapp-bridge/main.go`) — a `whatsmeow` client linked to one
  WhatsApp account. Persists session to `store/whatsapp.db` and messages to
  `store/messages.db` (both SQLite, WAL + busy_timeout). Exposes a small REST API.
- **Python MCP server** (`whatsapp-mcp-server/`) — FastMCP stdio server that reads
  the SQLite stores and calls the bridge REST API. `main.py` defines the tools,
  `whatsapp.py` the logic, `audio.py` ffmpeg Opus conversion for voice notes.
- **Launcher** (`~/.local/bin/whatsapp-mcp`) — starts the bridge if port 8080 is
  closed, then execs the MCP server. A macOS LaunchAgent (`com.whatsapp.mcp.bridge`,
  KeepAlive) keeps the bridge running.

## REST API (bridge, bound to 127.0.0.1:8080)
- `POST /api/send` — `{recipient, message, media_path?}`. Resolves the recipient to
  its current canonical JID (PN→LID via `IsOnWhatsApp`; a LID is mapped back to its
  PN first), sends, and **persists the outgoing message** (is_from_me).
- `POST /api/download` — `{message_id, chat_jid}`; downloads media to a path
  confined to `store/` (sanitized components; no traversal).
- `GET /api/resolve_user?phone=<pn|lid>` — live registration + current canonical JID.

Network calls carry a 30s context timeout. Errors are JSON `{success,message}`.

## MCP tools (15)
send_message, send_file, send_audio_message, download_media, search_contacts,
resolve_contact, check_whatsapp, list_messages, list_chats, get_chat,
get_contact_chats, get_direct_chat_by_contact, get_message_context,
get_last_interaction, wait_for_reply.

## Storage schema
- `messages.db`
  - `chats(jid PRIMARY KEY, name, last_message_time)`
  - `messages(id, chat_jid, sender, content, timestamp, is_from_me, media_type,
    filename, url, media_key, file_sha256, file_enc_sha256, file_length,
    PRIMARY KEY(id, chat_jid))`
- `whatsapp.db` (whatsmeow store)
  - `whatsmeow_contacts(their_jid, full_name, first_name, push_name)`
  - `whatsmeow_lid_map(lid, pn)` — bidirectional LID↔phone mapping
  - device credentials, sessions, identity keys (the account's keys)

## Key behaviours learned this session
- **LID migration bug**: a contact who migrated accounts has a *stale* cached LID;
  sending to it reached the old account ("this number is connected to a new
  WhatsApp account"). Fix: resolve to the current canonical JID for PN *and* LID
  recipients, or send to the PN and let whatsmeow convert.
- **Outgoing messages were not stored** (whatsmeow doesn't echo API sends), which
  broke "reply to my last message" baselines. Now persisted on send.
- **wait_for_reply** baselines on the last outgoing message so an already-received
  reply returns at once; the blocking wait is capped (55s) under the MCP client's
  tool timeout (Command Code default 80s, `MCP_TOOL_TIMEOUT`).
- **Hardening**: loopback-only REST; WAL; LIKE-escaping; limit/page clamps (a
  negative SQL LIMIT means "no limit"); result caps.

## Known gaps (roadmap targets)
Multi-account (2 numbers), pair-by-link (QR/code over HTTP), webhook on inbound
messages, inbox/outbox ("needs reply"), human-in-the-loop approval, Linux/systemd
deployment, MCP Tasks for long waits.
