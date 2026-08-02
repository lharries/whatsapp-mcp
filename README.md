# WhatsApp MCP Server

This is a Model Context Protocol (MCP) server for WhatsApp.

With this you can search and read your personal Whatsapp messages (including images, videos, documents, and audio messages), search your contacts and send messages to either individuals or groups. You can also send media files including images, videos, documents, and audio messages.

It connects to your **personal WhatsApp account** directly via the Whatsapp web multidevice API (using the [whatsmeow](https://github.com/tulir/whatsmeow) library). All your messages are stored locally in a SQLite database and only sent to an LLM (such as Claude) when the agent accesses them through tools (which you control).

Here's an example of what you can do when it's connected to Claude.

![WhatsApp MCP](./example-use.png)

> To get updates on this and other projects I work on [enter your email here](https://docs.google.com/forms/d/1rTF9wMBTN0vPfzWuQa2BjfGKdKIpTbyeKxhPMcEzgyI/preview)

> *Caution:* as with many MCP servers, the WhatsApp MCP is subject to [the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/). This means that prompt injection could lead to private data exfiltration.

## Architecture Overview

This application consists of two components, packaged and run as **two Docker services built from the same image**:

1. **`whatsapp-bridge`** (Go, `whatsapp-bridge/`): connects to WhatsApp's web API, handles authentication via QR code, and stores message/chat history in SQLite. Exposes a small REST API (`/api/send`, `/api/download`) that only the `whatsapp-mcp` service talks to, over the internal Docker network.
2. **`whatsapp-mcp`** (Python, `whatsapp-mcp-server/`): implements the Model Context Protocol over **streamable HTTP**, exposing the tools an MCP client (Claude Code, Claude Desktop, Cursor, ...) uses to read and send WhatsApp data. It reads the bridge's SQLite database directly and calls the bridge's REST API for send/download operations.

Both services run from the single image built by the root `Dockerfile`; `docker-compose.yml` selects the role via the container `command:` (`bridge` or `mcp`), dispatched by `entrypoint.sh`.

### Why not `docker exec` per client anymore

Earlier versions of this project ran the Python MCP server over stdio, spun up per client connection with `docker exec -i` into a running container. That pattern leaks: `docker exec` does not propagate the death of the outer process to the exec'd one, so every disconnected client left an orphaned Python process behind inside the container. On a long-running host these accumulated — about 155 orphaned processes were found in practice — and eventually caused an out-of-memory condition on a 6 GB host. The MCP server is now a single long-lived HTTP service (`stateless_http=True` in `whatsapp-mcp-server/main.py`) instead of a process-per-connection model, which removes this failure mode entirely. Don't reintroduce `docker exec -i` per connection.

### Data Storage

- All message history is stored in a SQLite database (`messages.db`) inside the `whatsapp-store` Docker volume, mounted at `/app/whatsapp-bridge/store` in both containers.
- The database has `chats` and `messages` tables.
- Messages are indexed for efficient searching and retrieval: `idx_messages_chat_time` on `messages(chat_jid, timestamp DESC)` and `idx_chats_last_message_time` on `chats(last_message_time DESC)` (see `whatsapp-bridge/main.go`).

## Security

A few properties are load-bearing and should not be casually changed:

- **The bridge's REST API requires a bearer token.** Every request needs `Authorization: Bearer <WHATSAPP_BRIDGE_TOKEN>`. The bridge is **fail-closed**: if `WHATSAPP_BRIDGE_TOKEN` is not set (or empty), the REST server refuses to start at all (`startRESTServer` in `whatsapp-bridge/main.go`).
- **The bridge does not publish any port.** `docker-compose.yml` deliberately has no `ports:` entry for `whatsapp-bridge`; `whatsapp-mcp` reaches it over the internal compose network at `http://whatsapp-bridge:8080`. An authorized pentest confirmed that exposing this API on the LAN (e.g. `8080:8080`) allowed sending WhatsApp messages as the logged-in user and reading arbitrary files from the container. Do not add a `ports:` mapping for this service.
- **The MCP endpoint (`/mcp`) has no authentication of its own.** FastMCP's `allowed_hosts` setting only guards against DNS-rebinding; it is not access control. The only barrier protecting every WhatsApp message and the ability to send as the logged-in user is that `whatsapp-mcp`'s port is published as `127.0.0.1:8081:8081` (loopback only) plus an SSH tunnel for remote clients. Treat the loopback bind + tunnel as the actual security boundary, not an implementation detail — never change the port mapping to `8081:8081` (all interfaces).
- **Containers run as a non-root user** (uid/gid `10001`, `appuser`), with `cap_drop: ALL`, `no-new-privileges`, and a **read-only root filesystem** (`read_only: true`, with `/tmp` as the only writable `tmpfs` mount). See `Dockerfile` and `docker-compose.yml`.

## Installation

### Prerequisites

- Docker and Docker Compose (recommended path), **or**, for running without containers:
  - Go
  - Python 3.11+
  - [UV](https://docs.astral.sh/uv/) (Python package manager), install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- An MCP client: Claude Code, Claude Desktop, or Cursor
- FFmpeg (_optional_) — only needed to send audio files as playable WhatsApp voice messages when they aren't already in `.ogg` Opus format. Without it, you can still send raw audio files using the `send_file` tool. The Docker image already includes FFmpeg.

### Steps

1. **Clone this repository**

   ```bash
   git clone https://github.com/lharries/whatsapp-mcp.git
   cd whatsapp-mcp
   ```

2. **Configure the shared bridge token**

   ```bash
   cp .env.example .env
   # generate a token and paste it into .env as WHATSAPP_BRIDGE_TOKEN
   openssl rand -hex 32
   ```

   `.env` is gitignored. Never commit the real token or paste it into an issue tracker, chat, or CI log.

3. **Build and start both services**

   ```bash
   docker compose up -d --build
   ```

4. **Scan the QR code (first run only)**

   The bridge needs to pair with your phone on first start. Watch its logs:

   ```bash
   docker compose logs -f whatsapp-bridge
   ```

   Scan the printed QR code with your WhatsApp mobile app (**Settings > Linked Devices**). After approximately 20 days you may need to re-authenticate the same way.

5. **Connect your MCP client** — see [Connecting a client](#connecting-a-client) below.

### Running without containers

The bridge and the MCP server can still run as two local processes instead of containers.

**Bridge** (from `whatsapp-bridge/`):

```bash
cd whatsapp-bridge
WHATSAPP_BRIDGE_TOKEN=<same token as below> go run main.go
```

Relevant env vars (all optional except the token):

- `WHATSAPP_BRIDGE_TOKEN` — **required**; the bridge refuses to start its REST API without it.
- `WHATSAPP_BRIDGE_ADDR` — REST API bind address, defaults to `:8080`.

**MCP server** (from `whatsapp-mcp-server/`):

```bash
cd whatsapp-mcp-server
WHATSAPP_BRIDGE_TOKEN=<same token as above> \
WHATSAPP_API_BASE_URL=http://localhost:8080/api \
uv run main.py
```

Relevant env vars:

- `WHATSAPP_BRIDGE_TOKEN` — **required**; must match the value used to start the bridge.
- `WHATSAPP_API_BASE_URL` — defaults to `http://whatsapp-bridge:8080/api` (the Docker service name), so it **must** be overridden to `http://localhost:8080/api` (or wherever the bridge is reachable) when not running under compose.
- `MESSAGES_DB_PATH` — defaults to `../whatsapp-bridge/store/messages.db` relative to `whatsapp-mcp-server/`, which is correct when both processes run from the same checkout.
- `MCP_HOST` / `MCP_PORT` — default `0.0.0.0` / `8081`.
- `WHATSAPP_AUDIO_TMP_DIR` — defaults to a `tmp/` directory next to the messages database.

The first time you run the bridge this way, you will be prompted to scan a QR code directly in the terminal.

### Windows Compatibility

If you're running the bridge on Windows without Docker, be aware that `go-sqlite3` requires **CGO to be enabled** in order to compile and work properly. By default, **CGO is disabled on Windows**, so you need to explicitly enable it and have a C compiler installed.

1. **Install a C compiler** — we recommend using [MSYS2](https://www.msys2.org/) to install a C compiler for Windows. After installing MSYS2, make sure to add the `ucrt64\bin` folder to your `PATH`. A step-by-step guide is available [here](https://code.visualstudio.com/docs/cpp/config-mingw).

2. **Enable CGO and run the app**

   ```bash
   cd whatsapp-bridge
   go env -w CGO_ENABLED=1
   go run main.go
   ```

Without this setup, you'll likely run into errors like:

> `Binary was compiled with 'CGO_ENABLED=0', go-sqlite3 requires cgo to work.`

This also applies to `go test ./...` locally on Windows — see [Testing](#testing) for a Docker-based alternative that sidesteps the local CGO/gcc setup entirely.

## Connecting a client

The MCP server is a **streamable-http** service bound to `127.0.0.1:8081` (loopback only — see [Security](#security)), serving the MCP endpoint at `/mcp`. There is no `docker exec` step anymore.

### Local machine

If the Docker host is your own machine, point your client directly at `http://127.0.0.1:8081/mcp`.

### Remote host

If `whatsapp-mcp` runs on a remote host, open an SSH tunnel first and connect your client to the tunnel's local end:

```bash
ssh -N -L 8081:127.0.0.1:8081 <user>@<host>
```

Keep this running for as long as you want the MCP client connected.

### Claude Code

```bash
claude mcp add --transport http whatsapp http://127.0.0.1:8081/mcp
```

(Run `claude mcp add --help` to confirm the current flag names for your installed version.)

### Claude Desktop / Cursor

Use an HTTP-transport entry pointing at the tunnel instead of the old `command`/`args` stdio entry. The exact key names depend on your client version — consult its MCP documentation — but the shape is:

```json
{
  "mcpServers": {
    "whatsapp": {
      "type": "http",
      "url": "http://127.0.0.1:8081/mcp"
    }
  }
}
```

For **Claude Desktop**, this goes in `claude_desktop_config.json` in your Claude Desktop configuration directory. For **Cursor**, this goes in `mcp.json` in your Cursor configuration directory (`~/.cursor/mcp.json`).

Restart the client afterwards so it picks up the new configuration.

## Migrating an existing volume to the non-root container

*(This is the section referenced by the `Dockerfile` comment as "Migrando o volume existente para o usuario nao-root".)*

If you ran an older version of this project where the containers ran as root, the `.db` files in the `whatsapp-store` volume are owned by root. Since the containers now run as uid `10001`, the bridge will crash-loop with an error like `attempt to write a readonly database` until the volume's ownership is fixed. Do this once, before starting the new containers:

1. **Stop the stack**

   ```bash
   docker compose down
   ```

2. **Re-own the volume** (replace `<volume>` with your actual volume name, e.g. `whatsapp-mcp_whatsapp-store` — check with `docker volume ls`):

   ```bash
   docker run --rm -v <volume>:/data busybox chown -R 10001:10001 /data
   ```

3. **Verify** the ownership changed (optional):

   ```bash
   docker run --rm -v <volume>:/data busybox ls -lan /data
   ```

   The listed owner/group should be `10001 10001`.

4. **Start the stack again**

   ```bash
   docker compose up -d
   ```

This only needs to be done once per pre-existing volume. A brand-new volume created by `docker compose up` on a fresh install is already seeded with the correct ownership (see the `Dockerfile`).

## Usage

Once connected, you can interact with your WhatsApp contacts through Claude, leveraging Claude's AI capabilities in your WhatsApp conversations.

### MCP Tools

Claude can access the following tools to interact with WhatsApp:

- **search_contacts**: Search for contacts by name or phone number
- **list_messages**: Retrieve messages with optional filters and context
- **list_chats**: List available chats with metadata
- **get_chat**: Get information about a specific chat
- **get_direct_chat_by_contact**: Find a direct chat with a specific contact
- **get_contact_chats**: List all chats involving a specific contact
- **get_last_interaction**: Get the most recent message with a contact
- **get_message_context**: Retrieve context around a specific message
- **send_message**: Send a WhatsApp message to a specified phone number or group JID
- **send_file**: Send a file (image, video, raw audio, document) to a specified recipient
- **send_audio_message**: Send an audio file as a WhatsApp voice message (requires the file to be an .ogg opus file or ffmpeg must be installed)
- **download_media**: Download media from a WhatsApp message and get the local file path

### Media Handling Features

The MCP server supports both sending and receiving various media types:

#### Media Sending

You can send various media types to your WhatsApp contacts:

- **Images, Videos, Documents**: Use the `send_file` tool to share any supported media type.
- **Voice Messages**: Use the `send_audio_message` tool to send audio files as playable WhatsApp voice messages.
  - For optimal compatibility, audio files should be in `.ogg` Opus format.
  - With FFmpeg installed, the system will automatically convert other audio formats (MP3, WAV, etc.) to the required format.
  - Without FFmpeg, you can still send raw audio files using the `send_file` tool, but they won't appear as playable voice messages.

#### Media Downloading

By default, just the metadata of the media is stored in the local database. The message will indicate that media was sent. To access this media you need to use the download_media tool which takes the `message_id` and `chat_jid` (which are shown when printing messages containing the meda), this downloads the media and then returns the file path which can be then opened or passed to another tool.

## Testing

### Python (`whatsapp-mcp-server`)

```bash
cd whatsapp-mcp-server
uv run pytest
```

This runs the suite in `whatsapp-mcp-server/tests/` — 31 tests covering config/env handling, the FastMCP transport setup (stateless streamable-http, host/port env vars, allowed hosts), the audio tmp-dir logic, and the SQLite query helpers in `whatsapp.py`.

### Go (`whatsapp-bridge`)

`go-sqlite3` needs CGO, which in turn needs a C compiler. On a machine without gcc set up (including plain Windows), run the tests inside the same Go image the `Dockerfile` uses to build the bridge:

```bash
docker run --rm -v "<path-to>/whatsapp-bridge":/src -w /src golang:1.25-bookworm go test ./...
```

On Git Bash on Windows, path conversion mangles the bind-mount and `-w` arguments, so run it as:

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "<path-to>/whatsapp-bridge":/src -w //src golang:1.25-bookworm go test ./...
```

`whatsapp-bridge/main_test.go` covers bearer-token auth (`requireAuth`), the fail-closed startup behavior when no token is set, request body size limits, media path traversal protection, error message sanitization, and the schema/index/pragma setup in `NewMessageStoreAt`.

If you do have a working C toolchain locally (e.g. via MSYS2, see [Windows Compatibility](#windows-compatibility)), `cd whatsapp-bridge && go test ./...` works directly.

## Technical Details

1. Claude sends requests to the Python MCP server over HTTP
2. The MCP server queries the Go bridge's SQLite database directly for reads, or calls the bridge's authenticated REST API for sends/downloads
3. The Go bridge accesses the WhatsApp API and keeps the SQLite database up to date
4. Data flows back through the chain to Claude
5. When sending messages, the request flows from Claude through the MCP server to the Go bridge and to WhatsApp

## Troubleshooting

- Make sure both services (`whatsapp-bridge` and `whatsapp-mcp`) are healthy: `docker compose ps`.
- If you're missing WhatsApp data, check the bridge's logs first: `docker compose logs whatsapp-bridge`.
- `attempt to write a readonly database` right after upgrading from an older, root-based deployment usually means the volume needs re-owning — see [Migrating an existing volume to the non-root container](#migrating-an-existing-volume-to-the-non-root-container).

### Authentication Issues

- **QR Code Not Displaying**: If the QR code doesn't appear, try restarting the bridge (`docker compose restart whatsapp-bridge`) and re-tailing its logs. If issues persist, check if your terminal supports displaying QR codes.
- **WhatsApp Already Logged In**: If your session is already active, the Go bridge will automatically reconnect without showing a QR code.
- **Device Limit Reached**: WhatsApp limits the number of linked devices. If you reach this limit, you'll need to remove an existing device from WhatsApp on your phone (Settings > Linked Devices).
- **No Messages Loading**: After initial authentication, it can take several minutes for your message history to load, especially if you have many chats.
- **WhatsApp Out of Sync**: If your WhatsApp messages get out of sync with the bridge, stop the stack, delete both database files in the `whatsapp-store` volume (`messages.db` and `whatsapp.db`, plus their `-wal`/`-shm` companions) and restart the bridge to re-authenticate.

For additional Claude Desktop integration troubleshooting, see the [MCP documentation](https://modelcontextprotocol.io/quickstart/server#claude-for-desktop-integration-issues). The documentation includes helpful tips for checking logs and resolving common issues.
