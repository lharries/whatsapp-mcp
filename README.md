# WhatsApp MCP Server

This is a fork of [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) with improved search and contact resolution.

With this you can search and read your personal Whatsapp messages (including images, videos, documents, and audio messages), search your contacts and send messages to either individuals or groups. You can also send media files including images, videos, documents, and audio messages.

It connects to your **personal WhatsApp account** directly via the Whatsapp web multidevice API (using the [whatsmeow](https://github.com/tulir/whatsmeow) library). All your messages are stored locally in a SQLite database and only sent to an LLM (such as Claude) when the agent accesses them through tools (which you control).

Here's an example of what you can do when it's connected to Claude.

![WhatsApp MCP](./example-use.png)

> *Caution:* as with many MCP servers, the WhatsApp MCP is subject to [the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/). This means that project injection could lead to private data exfiltration.

## Changes from upstream

### Full address book search

The upstream MCP only searches contacts that have been synced into the local `chats` table (typically a few hundred). This fork also searches the **full WhatsApp address book** stored by whatsmeow (often thousands of contacts), so you can find people you haven't recently messaged.

### LID (Linked ID) resolution

WhatsApp has been transitioning some contacts to use LID-based JIDs instead of phone-number-based JIDs. This fork resolves LIDs to real contact names using whatsmeow's `lid_map` table, so chats and messages from LID-based contacts show proper names instead of opaque numeric IDs.

### Accent- and case-insensitive search

Searching for "schroder" now finds "Schröder", "Munoz" finds "Muñoz", etc. All search operations normalize Unicode diacritics for comparison.

### On-demand chat sync

A new `/api/sync` endpoint on the Go bridge allows requesting history sync for specific chats. The bridge also sends presence on connect to help trigger pending sync data from WhatsApp.

## Installation

### Prerequisites

- Go
- Python 3.6+
- Anthropic Claude Desktop app (or Cursor)
- UV (Python package manager), install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- FFmpeg (_optional_) - Only needed for audio messages. If you want to send audio files as playable WhatsApp voice messages, they must be in `.ogg` Opus format. With FFmpeg installed, the MCP server will automatically convert non-Opus audio files. Without FFmpeg, you can still send raw audio files using `send_message` with `media_path`.

### Steps

1. **Clone this repository**

   ```bash
   git clone https://github.com/lharries/whatsapp-mcp.git
   cd whatsapp-mcp
   ```

2. **Run the WhatsApp bridge**

   Navigate to the whatsapp-bridge directory and run the Go application:

   ```bash
   cd whatsapp-bridge
   go run main.go
   ```

   The first time you run it, you will be prompted to scan a QR code. Scan the QR code with your WhatsApp mobile app to authenticate.

   After approximately 20 days, you will might need to re-authenticate.

   > **Tip:** Run the bridge (and optionally the MCP server) inside a [tmux](https://github.com/tmux/tmux/wiki) session so they keep running after you close your terminal:
   >
   > ```bash
   > tmux new-session -s whatsapp
   > cd whatsapp-bridge && go run main.go
   > # Detach with Ctrl-b d — reattach later with: tmux attach -t whatsapp
   > ```

3. **Connect to the MCP server**

   Copy the below json with the appropriate {{PATH}} values:

   ```json
   {
     "mcpServers": {
       "whatsapp": {
         "command": "{{PATH_TO_UV}}", // Run `which uv` and place the output here
         "args": [
           "--directory",
           "{{PATH_TO_SRC}}/whatsapp-mcp/whatsapp-mcp-server", // cd into the repo, run `pwd` and enter the output here + "/whatsapp-mcp-server"
           "run",
           "main.py"
         ]
       }
     }
   }
   ```

   For **Claude**, save this as `claude_desktop_config.json` in your Claude Desktop configuration directory at:

   ```
   ~/Library/Application Support/Claude/claude_desktop_config.json
   ```

   For **Cursor**, save this as `mcp.json` in your Cursor configuration directory at:

   ```
   ~/.cursor/mcp.json
   ```

4. **Restart Claude Desktop / Cursor**

   Open Claude Desktop and you should now see WhatsApp as an available integration.

   Or restart Cursor.

### Windows Compatibility

If you're running this project on Windows, be aware that `go-sqlite3` requires **CGO to be enabled** in order to compile and work properly. By default, **CGO is disabled on Windows**, so you need to explicitly enable it and have a C compiler installed.

#### Steps to get it working:

1. **Install a C compiler**  
   We recommend using [MSYS2](https://www.msys2.org/) to install a C compiler for Windows. After installing MSYS2, make sure to add the `ucrt64\bin` folder to your `PATH`.  
   → A step-by-step guide is available [here](https://code.visualstudio.com/docs/cpp/config-mingw).

2. **Enable CGO and run the app**

   ```bash
   cd whatsapp-bridge
   go env -w CGO_ENABLED=1
   go run main.go
   ```

Without this setup, you'll likely run into errors like:

> `Binary was compiled with 'CGO_ENABLED=0', go-sqlite3 requires cgo to work.`

## Remote MCP via fly.io (WebSocket proxy)

If you want to connect to your local MCP from a remote client (e.g. Claude on the web, a mobile app, or a server-side agent) you can deploy a lightweight WebSocket proxy on [fly.io](https://fly.io) that tunnels MCP traffic to your local machine.

### How it works

```
Remote client (Claude / agent)
        │  HTTPS / WSS
        ▼
  fly.io WebSocket proxy  ◄──── persistent outbound WS connection ────  Local machine
                                                                         (tmux session running
                                                                          whatsapp-bridge + MCP server)
```

1. Your local machine opens an **outbound** WebSocket connection to the fly.io app (no inbound firewall rules needed).
2. The fly.io app bridges that connection to remote MCP clients over a public HTTPS/WSS endpoint.
3. MCP messages flow transparently in both directions.

### Setup

1. **Install the fly CLI and log in**

   ```bash
   curl -L https://fly.io/install.sh | sh
   fly auth login
   ```

2. **Create the proxy app** — you can use any small WebSocket-relay server. A minimal example using [`mcp-remote`](https://github.com/geelen/mcp-remote) as a local-side forwarder:

   ```bash
   # On your local machine, install mcp-remote
   npm install -g mcp-remote

   # Start the local MCP server with stdio transport (as usual), then expose it:
   mcp-remote http://localhost:YOUR_MCP_PORT
   ```

   For the fly.io side, create a minimal Node/Bun WebSocket relay (see the [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) project for a ready-made Docker image) and deploy it:

   ```bash
   fly launch --image ghcr.io/sparfenyuk/mcp-proxy:latest --name my-whatsapp-mcp
   fly deploy
   ```

3. **Point the local bridge at fly.io** — on your local machine (ideally inside your tmux session) start the tunnel:

   ```bash
   # Replace <app-name> with your fly.io app name
   mcp-proxy --mode ws-client wss://<app-name>.fly.dev/mcp
   ```

   The proxy will maintain a persistent outbound WebSocket connection to fly.io so remote clients can reach your local MCP at any time.

4. **Configure your remote client** — add the fly.io WebSocket URL as an MCP server in your client config:

   ```json
   {
     "mcpServers": {
       "whatsapp": {
         "url": "wss://<app-name>.fly.dev/mcp"
       }
     }
   }
   ```

> **Note:** Keep the local bridge and the tunnel running in your tmux session (see the tmux tip above) so the remote MCP stays reachable.

---

## Architecture Overview

This application consists of two main components:

1. **Go WhatsApp Bridge** (`whatsapp-bridge/`): A Go application that connects to WhatsApp's web API, handles authentication via QR code, and stores message history in SQLite. It serves as the bridge between WhatsApp and the MCP server.

2. **Python MCP Server** (`whatsapp-mcp-server/`): A Python server implementing the Model Context Protocol (MCP), which provides standardized tools for Claude to interact with WhatsApp data and send/receive messages.

### Data Storage

- All message history is stored in a SQLite database within the `whatsapp-bridge/store/` directory
- The database maintains tables for chats and messages
- Messages are indexed for efficient searching and retrieval

## Usage

Once connected, you can interact with your WhatsApp contacts through Claude, leveraging Claude's AI capabilities in your WhatsApp conversations.

### MCP Tools

Claude can access the following tools to interact with WhatsApp:

- **search_contacts**: Search for contacts by name or phone number
- **list_messages**: Retrieve messages with optional filters (date range, sender, chat, contact, content query) and surrounding context. Use `contact_jid` to find any message involving a person (as sender or in their direct chat)
- **list_chats**: List available chats with metadata
- **get_chat**: Get chat metadata by JID, phone number, or contact. Provide one of `chat_jid` (exact lookup), `phone_number` (direct chat by phone), or `contact_jid` (all chats involving a person)
- **get_message_context**: Retrieve context around a specific message
- **send_message**: Send a text message, file, or voice message. Supports `message` (text), `media_path` (file attachment), and `as_audio` (convert to Opus voice message)
- **download_media**: Download media from a WhatsApp message and get the local file path

### Media Handling Features

The MCP server supports both sending and receiving various media types:

#### Media Sending

You can send various media types to your WhatsApp contacts using the unified `send_message` tool:

- **Images, Videos, Documents**: Use `send_message` with `media_path` to share any supported media type.
- **Voice Messages**: Use `send_message` with `media_path` and `as_audio=True` to send audio files as playable WhatsApp voice messages.
  - For optimal compatibility, audio files should be in `.ogg` Opus format.
  - With FFmpeg installed, the system will automatically convert other audio formats (MP3, WAV, etc.) to the required format.
  - Without FFmpeg, you can still send raw audio files with `as_audio=False`, but they won't appear as playable voice messages.

#### Media Downloading

By default, just the metadata of the media is stored in the local database. The message will indicate that media was sent. To access this media you need to use the download_media tool which takes the `message_id` and `chat_jid` (which are shown when printing messages containing the meda), this downloads the media and then returns the file path which can be then opened or passed to another tool.

## Technical Details

1. Claude sends requests to the Python MCP server
2. The MCP server queries the Go bridge for WhatsApp data or directly to the SQLite database
3. The Go accesses the WhatsApp API and keeps the SQLite database up to date
4. Data flows back through the chain to Claude
5. When sending messages, the request flows from Claude through the MCP server to the Go bridge and to WhatsApp

## Troubleshooting

- If you encounter permission issues when running uv, you may need to add it to your PATH or use the full path to the executable.
- Make sure both the Go application and the Python server are running for the integration to work properly.

### Authentication Issues

- **QR Code Not Displaying**: If the QR code doesn't appear, try restarting the authentication script. If issues persist, check if your terminal supports displaying QR codes.
- **WhatsApp Already Logged In**: If your session is already active, the Go bridge will automatically reconnect without showing a QR code.
- **Device Limit Reached**: WhatsApp limits the number of linked devices. If you reach this limit, you'll need to remove an existing device from WhatsApp on your phone (Settings > Linked Devices).
- **No Messages Loading**: After initial authentication, it can take several minutes for your message history to load, especially if you have many chats.
- **WhatsApp Out of Sync**: If your WhatsApp messages get out of sync with the bridge, delete both database files (`whatsapp-bridge/store/messages.db` and `whatsapp-bridge/store/whatsapp.db`) and restart the bridge to re-authenticate.

### Connection Issues

- **`Error reading from websocket: websocket: close 1006 (abnormal closure): unexpected EOF`**: This means WhatsApp closed the underlying web socket — usually a transient network blip or a routine keepalive timeout. The bridge enables whatsmeow's automatic reconnection and waits for a stable, logged-in session on startup (up to 3 minutes) instead of exiting on the first failed check, so an occasional 1006 in the logs is expected and recovers on its own. If the bridge logs the error repeatedly and never reaches `✓ Connected to WhatsApp!`, check that outbound traffic to WhatsApp's servers isn't blocked by a firewall, VPN, or proxy, and that your session hasn't been logged out from your phone (Settings > Linked Devices). If the session was removed, delete `whatsapp-bridge/store/whatsapp.db` and restart to re-scan the QR code.

For additional Claude Desktop integration troubleshooting, see the [MCP documentation](https://modelcontextprotocol.io/quickstart/server#claude-for-desktop-integration-issues). The documentation includes helpful tips for checking logs and resolving common issues.
