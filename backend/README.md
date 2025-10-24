# WhatsApp MCP Backend

TypeScript backend implementation for WhatsApp Model Context Protocol server.

## Architecture

This backend replaces the previous Go + Python hybrid architecture with a unified TypeScript solution.

### Core Components

1. **MCP Server** (`src/mcp/server.ts`)
   - Implements Model Context Protocol with stdio transport
   - Exposes 13 tools for WhatsApp interaction
   - Built with official `@modelcontextprotocol/sdk`

2. **REST API Server** (`src/api/server.ts`) ✨ NEW
   - Express-based HTTP API
   - Full CRUD operations for chats, messages, contacts
   - Authentication status endpoints
   - CORS enabled for frontend integration

3. **WebSocket Server** (`src/api/websocket.ts`) ✨ NEW
   - Real-time message updates
   - Connection status broadcasts
   - Chat update notifications
   - Heartbeat mechanism

4. **WhatsApp Client** (`src/whatsapp/`)
   - Uses `@whiskeysockets/baileys` library
   - Handles QR code authentication
   - Processes incoming/outgoing messages
   - Manages media (images, videos, audio, documents)
   - Event emitter for real-time updates

5. **Data Store** (`src/store/`)
   - Abstracted interface supporting multiple backends
   - Default: JSON files (simple, no dependencies)
   - Extensible: SQLite and MongoDB (to be implemented)

6. **Services** (`src/service/`)
   - Business logic layer
   - MessageService, ChatService, ContactService

7. **Configuration** (`src/config/`)
   - Environment-based configuration
   - Supports development and production modes

## Installation

```bash
# Install dependencies
npm install

# Copy environment file
cp .env.example .env

# Edit .env with your settings
nano .env
```

## Development

```bash
# Run in development mode with hot reload
npm run dev

# Build for production
npm run build

# Start production build
npm start

# Run tests
npm test
```

## REST API

The backend now includes a complete REST API with WebSocket support!

### API Endpoints

**Base URL**: `http://localhost:8080`

- **Authentication**: `/api/auth/*` - Status, QR code, logout
- **Chats**: `/api/chats/*` - List, get, search chats
- **Messages**: `/api/messages/*` - List, send, download media
- **Contacts**: `/api/contacts/*` - List, search contacts

### WebSocket

**URL**: `ws://localhost:8080/ws`

Real-time events:
- New messages
- Chat updates
- Connection status changes
- Heartbeat pings

See [API.md](./API.md) for complete API documentation with examples.

## MCP Tools

All 13 tools from the original Python implementation:

1. `search_contacts` - Search contacts by name or phone
2. `list_messages` - List messages with filters
3. `list_chats` - List available chats
4. `get_chat` - Get specific chat info
5. `get_direct_chat_by_contact` - Get direct chat by phone
6. `get_contact_chats` - Get all chats with a contact
7. `get_last_interaction` - Get most recent message
8. `get_message_context` - Get surrounding messages
9. `send_message` - Send text message
10. `send_file` - Send media file
11. `send_audio_message` - Send voice message
12. `download_media` - Download media from message
13. `get_auth_status` - Get authentication status

## Data Storage

### JSON Store (Default)

Data stored in `./data/json/`:
- `chats.json` - Chat metadata
- `messages.json` - Message history
- `contacts.json` - Contact information
- `media.json` - Media metadata

### Authentication

WhatsApp session stored in `./data/auth/`

### Media Files

Downloaded media stored in `./data/media/`

## Environment Variables

See `.env.example` for all available configuration options.

Key variables:
- `NODE_ENV` - Environment (development/production)
- `DATA_STORE_TYPE` - Storage backend (json/sqlite/mongodb)
- `WHATSAPP_AUTH_PATH` - WhatsApp session directory
- `LOG_LEVEL` - Logging level (debug/info/warn/error)

## Project Structure

```
backend/
├── src/
│   ├── config/           # Configuration management
│   ├── mcp/              # MCP server implementation
│   ├── whatsapp/         # WhatsApp client & handlers
│   ├── store/            # Data store abstraction
│   ├── service/          # Business logic services
│   ├── util/             # Utilities (logger, etc.)
│   └── index.ts          # Entry point
├── data/                 # Runtime data (gitignored)
├── .env.example          # Environment template
└── package.json
```

## Migration from Go/Python

This backend replaces:
- `whatsapp-bridge/main.go` → `src/whatsapp/client.ts`
- `whatsapp-mcp-server/main.py` → `src/mcp/server.ts`
- SQLite storage → Abstracted store with JSON default

All functionality is preserved with improved:
- Type safety (TypeScript)
- Code organization
- Extensibility
- Developer experience

## Next Steps

- [ ] Implement REST API for React client
- [ ] Add WebSocket for real-time updates
- [ ] Implement SQLite and MongoDB stores
- [ ] Add comprehensive tests
- [ ] Add HTTP SSE transport for MCP
