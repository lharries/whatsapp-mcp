# Contributing

Thank you for your interest in contributing to WhatsApp MCP Server!

## Development Setup

1. Clone the repo and follow the [Installation](README.md#installation) steps.
2. Python dependencies are managed with [uv](https://github.com/astral-sh/uv):
   ```bash
   cd whatsapp-mcp-server
   uv sync
   ```
3. The Go bridge is a standard Go module:
   ```bash
   cd whatsapp-bridge
   go build ./...
   ```

## Making Changes

- **Python MCP server** lives in `whatsapp-mcp-server/`. Entry point: `main.py`; all DB logic: `whatsapp.py`.
- **Go bridge** lives in `whatsapp-bridge/`. It stores messages in a local SQLite database at `store/messages.db`.
- If you run both a personal and a business bridge, the business one goes in `whatsapp-bridge-business/` — the MCP server auto-detects it.

### SQLite Search

All text search in `whatsapp.py` uses `instr()` instead of `LOWER()+LIKE`. Please keep it that way — SQLite's `LOWER()` only handles ASCII, which silently breaks searches in Hebrew, Arabic, CJK, or any non-Latin script.

## Pull Requests

1. Fork the repository and create a branch from `main`.
2. Keep changes focused — one logical change per PR.
3. Test against a real WhatsApp session when possible.
4. Update the README if you change user-visible behaviour or add env vars.

## Reporting Issues

Open a GitHub issue with:
- What you did
- What you expected
- What actually happened
- Your OS, Go version, and Python version
