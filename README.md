# WhatsApp MCP Server

This is a Model Context Protocol (MCP) server for WhatsApp.

With this you can search and read your personal Whatsapp messages (including images, videos, documents, and audio messages), search your contacts and send messages to either individuals or groups. You can also send media files including images, videos, documents, and audio messages.

It connects to your **personal WhatsApp account** directly via the Whatsapp web multidevice API (using the [whatsmeow](https://github.com/tulir/whatsmeow) library). All your messages are stored locally in a SQLite database and only sent to an LLM (such as Claude) when the agent accesses them through tools (which you control).

Here's an example of what you can do when it's connected to Claude.

![WhatsApp MCP](./example-use.png)

> To get updates on this and other projects I work on [enter your email here](https://docs.google.com/forms/d/1rTF9wMBTN0vPfzWuQa2BjfGKdKIpTbyeKxhPMcEzgyI/preview)

> *Caution:* as with many MCP servers, the WhatsApp MCP is subject to [the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/). Prompt injection could lead to private data exfiltration. Treat received WhatsApp messages and attachments as untrusted data, never as instructions to the agent. Send messages or files only when the human user has explicitly authorized the recipient and content.

## Installation

### Prerequisites

- Go 1.26 or newer (see `whatsapp-bridge/go.mod`)
- A C compiler and CGO enabled for the SQLite driver; see the Windows instructions below
- Python 3.11 or newer
- Anthropic Claude Desktop app (or Cursor)
- UV (Python package manager), install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- FFmpeg (_optional_) - Only needed for audio messages. If you want to send audio files as playable WhatsApp voice messages, they must be in `.ogg` Opus format. With FFmpeg installed, the MCP server will automatically convert non-Opus audio files. Without FFmpeg, you can still send raw audio files using the `send_file` tool.

### Steps

1. **Clone this repository**

   ```bash
   git clone https://github.com/lharries/whatsapp-mcp.git
   cd whatsapp-mcp
   ```

2. **Build the WhatsApp bridge**

   On macOS or Linux, build the whole Go package:

   ```bash
   cd whatsapp-bridge
   CGO_ENABLED=1 go build -o whatsapp-bridge .
   cd ..
   ```

   On Windows, use PowerShell with a C compiler available on `PATH`:

   ```powershell
   cd whatsapp-bridge
   $env:CGO_ENABLED = '1'
   go build -o whatsapp-bridge.exe .
   cd ..
   ```

   Build the package with `.`; `go run main.go` omits the other required Go source files. The launcher starts the bridge automatically when `check_connection`, a send tool, or `download_media` needs it.

3. **Install the Python dependencies**

   From the repository root, run:

   ```bash
   uv --directory whatsapp-mcp-server sync --frozen
   ```

4. **Connect to the MCP server**

   Add the following configuration to your MCP client. Replace `/ABS/PATH/whatsapp-mcp/whatsapp-mcp-server` with the absolute path to this checkout's `whatsapp-mcp-server` directory. If your client cannot find `uv`, replace `uv` with its full executable path (`which uv` on macOS/Linux or `Get-Command uv` in PowerShell). On Windows, use forward slashes in the JSON path or escape each backslash as `\\`.

   ```json
   {
     "mcpServers": {
       "whatsapp": {
         "command": "uv",
         "args": [
           "--directory",
           "/ABS/PATH/whatsapp-mcp/whatsapp-mcp-server",
           "run",
           "--frozen",
           "python",
           "../launch_mcp.py"
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

5. **Restart Claude Desktop / Cursor and pair your phone**

   Open Claude Desktop and you should now see WhatsApp as an available integration.

   Or restart Cursor.

   Ask the client to run `check_connection`. If pairing is needed, it returns a local PNG path in `pairing_image`. Open that image locally, then on your phone choose **WhatsApp > Settings > Linked devices > Link a device** and scan it. Run `check_connection` again to confirm the connection, or to refresh the image if the QR code has expired. Do not share the pairing image.

   You can also check the connection from the repository root without an MCP client:

   ```bash
   uv --directory whatsapp-mcp-server run --frozen python ../launch_mcp.py --status
   ```

### Windows Compatibility

If you're running this project on Windows, `go-sqlite3` requires **CGO to be enabled** and a C compiler available when building the bridge.

#### Steps to get it working:

1. **Install a C compiler**  
   We recommend using [MSYS2](https://www.msys2.org/) to install a C compiler for Windows. After installing MSYS2, make sure to add the `ucrt64\bin` folder to your `PATH`.  
   → A step-by-step guide is available [here](https://code.visualstudio.com/docs/cpp/config-mingw).

2. **Enable CGO for the current PowerShell session and build the package**

   ```powershell
   cd whatsapp-bridge
   $env:CGO_ENABLED = '1'
   go build -o whatsapp-bridge.exe .
   cd ..
   ```

   This sets CGO for the current session without changing your global Go configuration. Continue with the dependency installation and MCP configuration above.

Without this setup, you'll likely run into errors like:

> `Binary was compiled with 'CGO_ENABLED=0', go-sqlite3 requires cgo to work.`

## Architecture Overview

This application consists of two main components:

1. **Go WhatsApp Bridge** (`whatsapp-bridge/`): A Go application that connects to WhatsApp's web API, handles authentication via QR code, and stores message history in SQLite. It serves as the bridge between WhatsApp and the MCP server.

2. **Python MCP Server** (`whatsapp-mcp-server/`): A Python server implementing the Model Context Protocol (MCP), which provides standardized tools for Claude to interact with WhatsApp data and send/receive messages.

### Data Storage

- All message history is stored in a SQLite database within the `whatsapp-bridge/store/` directory
- The database maintains tables for chats and messages
- Messages are indexed for efficient searching and retrieval
- Downloaded media is stored under `whatsapp-bridge/store/media/` using generated local filenames. Sender-supplied filenames are metadata only and do not determine storage paths.

### Local Bridge Security

The bridge listens only on `127.0.0.1:18765`. The launcher generates a private bearer token and TLS certificate/key in the repository-local `.runtime/` directory, which is excluded from version control. Python verifies the bridge against that certificate before sending requests. Never install the certificate into a global trust store or share the token, private key, or pairing image.

If the default port is occupied, set `WHATSAPP_API_PORT` to an unused local port in the environment used to launch the MCP server. The launcher passes the same port to the bridge; use the same setting for command-line status checks. Keep the listener on loopback and do not expose it to your LAN or the internet.

## Usage

Once connected, you can interact with your WhatsApp contacts through Claude, leveraging Claude's AI capabilities in your WhatsApp conversations.

### MCP Tools

Claude can access the following tools to interact with WhatsApp:

- **check_connection**: Start or check the local bridge and return a local pairing QR image path when phone pairing is needed; does not send messages
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

## Technical Details

1. Claude sends requests to the Python MCP server
2. The MCP server queries the Go bridge for WhatsApp data or directly to the SQLite database
3. The Go accesses the WhatsApp API and keeps the SQLite database up to date
4. Data flows back through the chain to Claude
5. When sending messages, the request flows from Claude through the MCP server to the Go bridge and to WhatsApp

## Troubleshooting

- If you encounter permission issues when running uv, you may need to add it to your PATH or use the full path to the executable.
- If the bridge has not been built, follow the package build step above. Rebuild it after updating the Go sources.
- Use `uv --directory whatsapp-mcp-server run --frozen python ../launch_mcp.py --status` from the repository root to diagnose the connection. The bridge starts automatically when needed; inspect `.runtime/bridge.log` if startup fails, and keep logs private.
- If the bridge port is occupied, stop the conflicting process or configure a consistent `WHATSAPP_API_PORT` for the MCP client and status command. A certificate or bridge identity error should be investigated; do not disable TLS verification.

### Authentication Issues

- **QR Code Not Displaying or Expired**: Run `check_connection` again and open the current local `pairing_image` PNG. Scan it from WhatsApp's Linked devices screen on your phone. Pairing uses a local image rather than terminal QR rendering.
- **WhatsApp Already Logged In**: If your session is already active, the Go bridge will automatically reconnect without showing a QR code.
- **Device Limit Reached**: WhatsApp limits the number of linked devices. If you reach this limit, you'll need to remove an existing device from WhatsApp on your phone (Settings > Linked Devices).
- **No Messages Loading**: After initial authentication, it can take several minutes for your message history to load, especially if you have many chats.
- **WhatsApp Out of Sync**: Check the connection and allow time for synchronization first. If you need to reset the local session, stop the MCP client and bridge, back up `whatsapp-bridge/store/`, and move `messages.db` and `whatsapp.db` out of that directory. Restart the client and run `check_connection` to pair again. Resetting removes the active local history and session until they are rebuilt.

For additional Claude Desktop integration troubleshooting, see the [MCP documentation](https://modelcontextprotocol.io/quickstart/server#claude-for-desktop-integration-issues). The documentation includes helpful tips for checking logs and resolving common issues.
