# WhatsApp MCP Server

This is a Model Context Protocol (MCP) server for WhatsApp.

With this you can search and read your personal Whatsapp messages (including images, videos, documents, and audio messages), search your contacts and send messages to either individuals or groups. You can also send media files including images, videos, documents, and audio messages.

It connects to your **personal WhatsApp account** directly via the Whatsapp web multidevice API (using the [whatsmeow](https://github.com/tulir/whatsmeow) library). All your messages are stored locally in a SQLite database and only sent to an LLM (such as Claude) when the agent accesses them through tools (which you control).

Here's an example of what you can do when it's connected to Claude.

![WhatsApp MCP](./example-use.png)

> To get updates on this and other projects I work on [enter your email here](https://docs.google.com/forms/d/1rTF9wMBTN0vPfzWuQa2BjfGKdKIpTbyeKxhPMcEzgyI/preview)

> *Caution:* as with many MCP servers, the WhatsApp MCP is subject to [the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/). This means that project injection could lead to private data exfiltration.

## Installation

### Prerequisites

- Go
- Python 3.6+
- Anthropic Claude Desktop app (or Cursor)
- UV (Python package manager), install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- FFmpeg (_optional_) - Only needed for audio messages. If you want to send audio files as playable WhatsApp voice messages, they must be in `.ogg` Opus format. With FFmpeg installed, the MCP server will automatically convert non-Opus audio files. Without FFmpeg, you can still send raw audio files using the `send_file` tool.

### Steps

1. **Clone this repository**

   ```bash
   git clone https://github.com/lharries/whatsapp-mcp.git
   cd whatsapp-mcp
   ```

2. **Authentication Setup**

   The WhatsApp MCP server now features **automatic bridge management**. You have two options:

   **Option A: Manual Bridge Startup (Traditional)**
   Navigate to the whatsapp-bridge directory and run the Go application:

   ```bash
   cd whatsapp-bridge
   go run main.go
   ```

   **Option B: Automatic Startup (Recommended)**
   Skip manual bridge startup! The MCP server will automatically start the bridge when you use any WhatsApp tool in Claude.

   #### Authentication Process
   - **First Time**: You'll need to scan a QR code to authenticate
   - **QR Code Access**: Visit `http://localhost:8080/qr` in your browser to see the QR code
   - **Mobile App**: Open WhatsApp → Settings → Linked Devices → Link a Device → Scan QR code
   - **Re-authentication**: After ~20 days, you may need to re-authenticate using the same process

   #### Bridge Status Monitoring
   - **Status Dashboard**: `http://localhost:8080/status` - Visual dashboard with real-time status
   - **QR Code Page**: `http://localhost:8080/qr` - Authentication QR code when needed
   - **API Status**: `http://localhost:8080/api/status` - JSON status data

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

#### Message and Chat Management
- **search_contacts**: Search for contacts by name or phone number
- **list_messages**: Retrieve messages with optional filters and context
- **list_chats**: List available chats with metadata
- **get_chat**: Get information about a specific chat
- **get_direct_chat_by_contact**: Find a direct chat with a specific contact
- **get_contact_chats**: List all chats involving a specific contact
- **get_last_interaction**: Get the most recent message with a contact
- **get_message_context**: Retrieve context around a specific message

#### Message Sending
- **send_message**: Send a WhatsApp message to a specified phone number or group JID
- **send_file**: Send a file (image, video, raw audio, document) to a specified recipient
- **send_audio_message**: Send an audio file as a WhatsApp voice message (requires the file to be an .ogg opus file or ffmpeg must be installed)

#### Media Management
- **download_media**: Download media from a WhatsApp message and get the local file path

#### Status Monitoring
- **get_sync_status**: Get comprehensive sync status including bridge health, database statistics, and last sync time
- **check_bridge_status**: Check the current status of the WhatsApp bridge and authentication

### MCP Resources

Claude can also access these resources for status information:

- **whatsapp://sync-status**: JSON resource providing real-time bridge and sync status
- **whatsapp://status-ui**: Rich HTML status display with visual indicators and statistics

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

### Status Monitoring Features

The WhatsApp MCP server includes comprehensive status monitoring capabilities:

#### Web Dashboard
Access a visual status dashboard at `http://localhost:8080/status` when the bridge is running:
- Real-time bridge and authentication status
- Database statistics (message count, chat count, database size)
- Last sync timestamp
- Auto-refresh every 30 seconds
- Visual status indicators with color-coded badges

#### MCP Status Tools
- **Bridge Health**: Check if the WhatsApp bridge process is running and responsive
- **Authentication Status**: Monitor WhatsApp authentication state and QR code availability
- **Sync Statistics**: View message counts, chat counts, and database metrics
- **Error Reporting**: Get detailed error messages and troubleshooting guidance

#### Automatic Bridge Management
- **Auto-startup**: All MCP tools automatically start the bridge if it's not running
- **Health Monitoring**: Continuous monitoring of bridge process and API responsiveness
- **Authentication Recovery**: Automatic QR code generation for re-authentication

#### Status Access Methods
1. **MCP Tools**: Call `get_sync_status` or `check_bridge_status` in Claude
2. **MCP Resources**: View `whatsapp://sync-status` or `whatsapp://status-ui` resources
3. **Web Interface**: Visit `http://localhost:8080/status` in your browser
4. **API Endpoint**: Access `http://localhost:8080/api/status` for JSON data

## Technical Details

1. Claude sends requests to the Python MCP server
2. The MCP server queries the Go bridge for WhatsApp data or directly to the SQLite database
3. The Go accesses the WhatsApp API and keeps the SQLite database up to date
4. Data flows back through the chain to Claude
5. When sending messages, the request flows from Claude through the MCP server to the Go bridge and to WhatsApp

## Troubleshooting

### General Issues
- If you encounter permission issues when running uv, you may need to add it to your PATH or use the full path to the executable.
- With automatic bridge management, you only need the Python MCP server running - the Go bridge will start automatically.

### Bridge and Connection Issues

#### Bridge Startup Problems
- **Auto-startup Fails**: Check the status dashboard at `http://localhost:8080/status` for detailed error information
- **Go Not Found**: Ensure Go is installed and available in PATH (`which go` should return a path)
- **Port Already in Use**: If port 8080 is busy, kill any existing processes: `pkill -f 'go run main.go'`
- **Permission Issues**: Ensure the MCP server has permission to start the Go bridge process

#### Status Monitoring
- **Check Bridge Status**: Use the `check_bridge_status` MCP tool in Claude for real-time diagnostics
- **Web Dashboard**: Visit `http://localhost:8080/status` for visual status monitoring
- **API Diagnostics**: Access `http://localhost:8080/api/status` for JSON status data

### Authentication Issues

- **QR Code Not Displaying**: 
  - Visit `http://localhost:8080/qr` in your browser instead of checking the terminal
  - If the page shows "no QR code available", restart the bridge or use a WhatsApp tool to trigger authentication
- **QR Code Expired**: Refresh the QR code page or restart the bridge to generate a new QR code
- **WhatsApp Already Logged In**: If your session is already active, the bridge will automatically reconnect without showing a QR code
- **Device Limit Reached**: WhatsApp limits linked devices. Remove an existing device: WhatsApp → Settings → Linked Devices
- **Authentication Timeout**: Try using the `check_bridge_status` tool which will attempt to restart the authentication process

### Data Sync Issues

- **No Messages Loading**: After initial authentication, it can take several minutes for message history to load
- **Missing Recent Messages**: The bridge syncs incrementally; recent messages should appear within a few seconds
- **WhatsApp Out of Sync**: Delete both database files and restart:
  ```bash
  rm whatsapp-bridge/store/messages.db whatsapp-bridge/store/whatsapp.db
  # Bridge will restart automatically when you use a WhatsApp tool
  ```

### Status Dashboard Issues

- **Dashboard Not Loading**: Ensure the bridge is running by calling a WhatsApp MCP tool first
- **Status Shows "Not Ready"**: Check individual status indicators for specific issues
- **Auto-refresh Not Working**: Browser may have JavaScript disabled; manually refresh the page

For additional Claude Desktop integration troubleshooting, see the [MCP documentation](https://modelcontextprotocol.io/quickstart/server#claude-for-desktop-integration-issues). The documentation includes helpful tips for checking logs and resolving common issues.

## Running in Docker

The WhatsApp MCP server supports containerized deployment using Docker and Docker Compose. The container includes both the Go bridge and Python MCP server in a single, optimized image that preserves all automatic bridge management features.

### Quick Start

1. **Build and start the container:**
   ```bash
   docker-compose up -d
   ```

2. **Access the QR code for authentication:**
   - Web interface: `http://localhost:8080/qr`
   - Status dashboard: `http://localhost:8080/status`

3. **Configure Claude Desktop** to use the containerized MCP server (see configuration below)

### Architecture

The Docker deployment uses a **combined container approach** that includes:
- **Go Bridge**: Compiled binary handling WhatsApp API communication
- **Go Runtime**: Available for automatic bridge process management
- **Python MCP Server**: Full MCP functionality with automatic bridge management
- **Shared Storage**: SQLite databases persisted via Docker volumes

This architecture ensures that all automatic bridge management features (startup, monitoring, QR code capture) work exactly as in local installations.

### MCP Transport Modes

The MCP server supports two transport modes, configurable via the `MCP_TRANSPORT` environment variable:

#### **STDIO Transport** (Default for local installations)
- **Use case:** Local development, direct MCP client connections
- **Characteristics:** 
  - Communication via standard input/output streams
  - Lower latency for local connections
  - Requires direct process management
- **Claude Configuration:**
  ```json
  {
    "mcpServers": {
      "whatsapp": {
        "command": "uv",
        "args": ["run", "main.py"],
        "cwd": "/path/to/whatsapp-mcp-server"
      }
    }
  }
  ```

#### **SSE Transport** (Default for Docker)
- **Use case:** Containerized deployments, web-based integrations
- **Characteristics:**
  - Communication via HTTP Server-Sent Events
  - Better suited for container environments
  - Enables web-based MCP client connections
  - Listens on port 3000 by default
- **Claude Configuration:**
  ```json
  {
    "mcpServers": {
      "whatsapp": {
        "command": "docker",
        "args": [
          "exec",
          "-i",
          "whatsapp-mcp-server",
          "uv",
          "run",
          "main.py"
        ]
      }
    }
  }
  ```

### Environment Variables

Configure the Docker deployment using these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `sse` (Docker), `stdio` (local) | MCP transport protocol |
| `WHATSAPP_BRIDGE_URL` | `http://localhost:8080` | Bridge API endpoint (localhost in combined container) |
| `DATABASE_PATH` | `/app/whatsapp-bridge/store/messages.db` | SQLite database path |
| `WHATSAPP_DB_PATH` | `/app/whatsapp-bridge/store` | Bridge database directory |

### Docker Compose Configuration

The provided `docker-compose.yml` includes:

- **Combined Container**: Single container with both Go bridge and Python MCP server
- **Automatic Bridge Management**: Full subprocess control and monitoring within container
- **Persistent Storage**: SQLite databases stored in Docker volume
- **Health Checks**: Container health monitoring via bridge API
- **Port Mapping**: Web interface (8080) and MCP server (3000)

### Customizing Transport Mode

To override the default SSE transport in Docker:

```bash
# Use STDIO transport in Docker (not recommended)
MCP_TRANSPORT=stdio docker-compose up

# Or set in docker-compose.yml
environment:
  - MCP_TRANSPORT=stdio
```

To use SSE transport locally:

```bash
# Set environment variable
export MCP_TRANSPORT=sse
uv run main.py
```

### Transport Mode Implications

| Aspect | STDIO | SSE |
|--------|-------|-----|
| **Latency** | Lower | Slightly higher |
| **Docker Support** | Limited | Excellent |
| **Web Integration** | Not suitable | Native support |
| **Process Management** | Direct | Via HTTP |
| **Debugging** | Terminal logs | HTTP logs + browser tools |
| **Scalability** | Single instance | Multiple clients possible |

### Recommended Configurations

- **Local Development**: Use STDIO transport with direct Python execution
- **Production Docker**: Use SSE transport with Docker Compose
- **CI/CD Pipelines**: Use Docker with SSE transport for testing
- **Development Docker**: Use SSE transport for consistency with production
