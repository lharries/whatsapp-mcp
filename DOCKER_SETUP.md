# Docker Setup for WhatsApp MCP

This document describes the Docker-based deployment that enables multi-client MCP access via SSE (Server-Sent Events) transport.

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│   MCP Clients   │────▶│   Nginx Proxy        │────▶│  WhatsApp MCP       │
│   (Claude, etc) │     │   (Port 9000)        │     │  Server (Port 8000) │
└─────────────────┘     │   /mcp/whatsapp/     │     └──────────┬──────────┘
                        └──────────────────────┘                │
                                                                │
                                                   ┌────────────▼────────────┐
                                                   │   WhatsApp Bridge       │
                                                   │   (Port 8080)           │
                                                   │   Go + whatsmeow        │
                                                   └─────────────────────────┘
```

## Services

### 1. whatsapp-bridge
- **Technology**: Go with whatsmeow library
- **Port**: 8080 (internal)
- **Purpose**: Connects to WhatsApp via the whatsmeow library, stores messages in SQLite, exposes REST API for sending messages and downloading media
- **Volumes**: `whatsapp-store:/app/store` - persists WhatsApp session and message database

### 2. whatsapp-mcp-server
- **Technology**: Python with FastMCP, uvicorn, Starlette
- **Port**: 8000 (internal only, not exposed externally)
- **Purpose**: MCP server providing WhatsApp tools (search contacts, list messages, send messages, etc.)
- **Transport**: SSE (Server-Sent Events) for multi-client support
- **Volumes**: `whatsapp-store:/app/store` - shares message database with bridge

### 3. nginx-mcp-proxy
- **Technology**: Nginx Alpine
- **Port**: 9000 (external)
- **Purpose**: Reverse proxy with path-based routing and SSE support
- **Path**: `/mcp/whatsapp/` - routes to MCP server with prefix stripping

## Quick Start

### 1. Build and Start Services

```bash
docker-compose up -d --build
```

### 2. Authenticate WhatsApp

On first run, you need to scan the QR code to authenticate:

```bash
docker-compose logs -f whatsapp-bridge
```

Scan the QR code with your WhatsApp mobile app (Settings > Linked Devices > Link a Device).

### 3. Verify Services

```bash
# Check all services are running
docker-compose ps

# Test MCP endpoint
curl http://localhost:9000/mcp/whatsapp/sse
```

## MCP Client Configuration

### Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "whatsapp": {
      "url": "http://localhost:9000/mcp/whatsapp/sse"
    }
  }
}
```

### Claude Code

Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "whatsapp": {
      "url": "http://localhost:9000/mcp/whatsapp/sse"
    }
  }
}
```

## Configuration

### Environment Variables

The MCP server supports the following environment variables (configured in docker-compose.yml):

| Variable | Default | Description |
|----------|---------|-------------|
| `WHATSAPP_API_BASE_URL` | `http://localhost:8080/api` | URL of the WhatsApp bridge API |
| `MESSAGES_DB_PATH` | `../whatsapp-bridge/store/messages.db` | Path to the SQLite message database |

### Volumes

- `whatsapp-store`: Shared volume containing:
  - `whatsapp.db` - WhatsApp session data (whatsmeow)
  - `messages.db` - Message history database
  - Downloaded media files

## Development

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f whatsapp-mcp-server
```

### Rebuild a Single Service

```bash
docker-compose up -d --build whatsapp-mcp-server
```

### Stop Services

```bash
docker-compose down
```

### Reset Everything (including data)

```bash
docker-compose down -v
```

## Nginx Configuration

The nginx proxy is configured for SSE streaming:

- Proxies `/mcp/whatsapp/` to the MCP server
- Strips the `/mcp/whatsapp` prefix before forwarding
- Disables buffering for real-time SSE streams
- Rewrites response URLs to include the prefix
- Long timeout (24h) for persistent connections

## Troubleshooting

### QR Code Not Appearing

```bash
# Ensure the bridge container is running
docker-compose ps whatsapp-bridge

# Check logs for errors
docker-compose logs whatsapp-bridge
```

### MCP Connection Failed

```bash
# Verify nginx is proxying correctly
curl -v http://localhost:9000/mcp/whatsapp/sse

# Check MCP server logs
docker-compose logs whatsapp-mcp-server
```

### Messages Not Syncing

The WhatsApp bridge syncs message history on connection. Check:

```bash
docker-compose logs whatsapp-bridge | grep "history sync"
```

## Available MCP Tools

Once connected, the following tools are available via MCP:

- `search_contacts` - Search WhatsApp contacts by name or phone
- `list_messages` - Get messages with filtering and pagination
- `list_chats` - Get chat list with last message info
- `get_chat` - Get specific chat metadata
- `get_direct_chat_by_contact` - Find chat by phone number
- `get_contact_chats` - Get all chats involving a contact
- `get_last_interaction` - Get most recent message with a contact
- `get_message_context` - Get messages around a specific message
- `send_message` - Send a text message
- `send_file` - Send an image, video, or document
- `send_audio_message` - Send an audio message (voice note)
- `download_media` - Download media from a message
