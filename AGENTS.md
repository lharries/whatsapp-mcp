# AGENTS.md

Project-standards file read by AI coding assistants (Claude Code, etc.) at
session start. Keep it concise — the goal is to restore context fast, not to
duplicate code or git history.

## Layout

- `whatsapp-bridge/` — Go service (whatsmeow client). All bridge code lives in
  one file: `main.go`. SQLite store at `whatsapp-bridge/store/messages.db`
  (messages + chats) and `whatsapp-bridge/store/whatsapp.db` (whatsmeow session).
- `whatsapp-mcp-server/` — Python MCP server that reads the SQLite store and
  exposes tools to Claude Desktop / Claude Code.

## Build & run

From `whatsapp-bridge/`:

- `go build ./...` — must always succeed; this is the merge contract.
- `go vet ./...` — should also be clean.
- `go run .` — interactive run; prints a QR code on first pairing.
- Background on Windows: see *Running in background on Windows* below.

### Prerequisite: cgo + C compiler

`github.com/mattn/go-sqlite3` is a cgo package. Builds require:

- `CGO_ENABLED=1` (Go defaults to `0` on Windows when no C compiler is found)
- `gcc.exe` on PATH. On Windows install MinGW-w64 via MSYS2
  (`winget install --id MSYS2.MSYS2`, then in the MSYS2 MinGW64 shell:
  `pacman -S --needed mingw-w64-x86_64-gcc`) and add `C:\msys64\mingw64\bin`
  to PATH. WinLibs (`winget search mingw`) is an alternative.

Symptom if missing: `Binary was compiled with 'CGO_ENABLED=0', go-sqlite3
requires cgo to work. This is a stub`.

`start-bridge.ps1` pre-checks for `gcc.exe` and sets `CGO_ENABLED=1`
automatically. For interactive `go run .`, set it yourself:
`$env:CGO_ENABLED='1'; go run .`

## Schema rules

- `messages` primary key is composite: `(id, chat_jid)`.
- `INSERT OR REPLACE INTO messages …` is the standard write path. New code
  should reuse `MessageStore.StoreMessage` rather than crafting its own SQL —
  the replace-on-conflict behavior is load-bearing (e.g. placeholder rows for
  undecryptable messages are overwritten by the real content when the resend
  arrives).
- `MessageStore.StoreMessage` early-returns when both `content` and `mediaType`
  are empty. Placeholder writers must supply non-empty content.

## Event handler conventions

The whatsmeow library auto-retries undecryptable messages. The bridge handles
the events:

- `*events.Message` — normal text/media; calls `handleMessage`.
- `*events.UndecryptableMessage` — writes a placeholder row via
  `handleUndecryptableMessage`. Do **not** drop these — WhatsApp Business
  accounts arrive through this path and would otherwise be lost forever if the
  resend fails.
- `*events.HistorySync` — backfill on first connect.
- `*events.Connected` / `*events.LoggedOut` — connection lifecycle.

When adding a new event case, mirror the existing pattern: extract `Info.ID`,
`Info.Chat.String()`, `Info.Sender.User`, call `StoreChat` then `StoreMessage`.

`extractTextContent` and `extractMediaInfo` must understand the common
business-account payload types (`TemplateMessage`, `InteractiveMessage`,
`ButtonsMessage`, `ListMessage`) and recursively unwrap the envelope types
(`EphemeralMessage`, `ViewOnceMessage(V2/V2Extension)`, `DeviceSentMessage`).
When `handleMessage` finds neither text nor media it logs the set protobuf
field names — grep `bridge.out.log` for `proto fields set:` to discover new
payload types and extend the extractors rather than adding new handlers.

## Running in background on Windows

After completing the QR pairing once with `go run .`, use the scripts in
`whatsapp-bridge/scripts/`:

| Script | Purpose |
| --- | --- |
| `start-bridge.ps1` | Build (if needed) and launch `whatsapp-bridge.exe` hidden; logs to `whatsapp-bridge/logs/`, PID to `whatsapp-bridge/run/bridge.pid`. |
| `stop-bridge.ps1` | Stop the process recorded in the PID file. |
| `status-bridge.ps1` | Show running / stopped state and tail of the log. |
| `install-bridge-task.ps1` | Register a per-user Scheduled Task that runs `start-bridge.ps1` at logon (no admin). |
| `uninstall-bridge-task.ps1` | Remove the Scheduled Task. |

The scripts refuse to start if `store/whatsapp.db` does not exist — first-time
pairing must happen interactively so the QR code is visible.

## Inspecting the message store

`store/messages.db` is plain SQLite. Install the CLI on Windows with
`winget install --id SQLite.SQLite` (close and reopen PowerShell so `sqlite3`
lands on PATH). The bridge can keep running while you read.

Interactive session:

```powershell
cd C:\Users\wittr\Documents\GitHub\whatsapp-mcp\whatsapp-bridge
sqlite3 store\messages.db
# sqlite>  ← file is already open
.tables
SELECT COUNT(*) FROM messages;
.headers on
.mode column
SELECT datetime(timestamp), jid, name FROM chats ORDER BY last_message_time DESC LIMIT 10;
.exit
```

Notes:

- Use `.exit` or `.quit` (leading dot) to leave the shell — `quit;` / `exit;`
  are SQL keywords and produce a parse error.
- Read-only while the bridge writes: `sqlite3 -readonly store\messages.db`.
- One-shot from PowerShell: `sqlite3 store\messages.db "SELECT COUNT(*) FROM messages;"`.
- Check whether the undecryptable-message fix has stored any placeholders yet:
  `sqlite3 store\messages.db "SELECT id, chat_jid, sender, datetime(timestamp) FROM messages WHERE content LIKE '[message unavailable%' ORDER BY timestamp DESC;"`.

## Review checklist (before opening a PR)

- `go build ./... && go vet ./...` are clean from `whatsapp-bridge/`.
- No secrets, tokens, real phone numbers, or production JIDs in committed files
  or commit messages. Sanitize log examples in docs.
  Local-only secrets belong in `PRIVATE.md` (gitignored), never in this repo.
- Edits to `main.go` are minimal and additive where possible — the file is
  large and shared across features.
- Documentation: update `CHANGES.md` for user-visible changes; update this
  file (`AGENTS.md`) when adding new conventions, scripts, build steps, or
  event handlers.
- Commits are created by a human reviewer, not by AI assistants. Agents
  produce the patch and the diff; humans review and commit.

## Cross-references

- Change log: [CHANGES.md](CHANGES.md)
- User-facing docs: [README.md](README.md)
