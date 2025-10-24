# WhatsApp MCP Server - TypeScript Full-Stack

> **🚀 TypeScript Rewrite In Progress** - This repository is being migrated from Go/Python to a unified TypeScript full-stack application.
>
> **Legacy Version**: For the original Go/Python implementation, see [README.legacy.md](./README.legacy.md)

A Model Context Protocol (MCP) server for WhatsApp that enables AI assistants like Claude to interact with your personal WhatsApp account - search messages, send messages, handle media, and more.

![WhatsApp MCP](./example-use.png)

## 🎯 Project Status

**Current Phase**: Backend Implementation Complete ✅
**Branch**: `claude/typescript-whatsapp-rewrite-011CUPU53kzDQSzMxCMWPiFb`

See [MIGRATION_STATUS.md](./MIGRATION_STATUS.md) for detailed progress.

## 🏗️ New Architecture

Complete TypeScript rewrite with modern full-stack architecture:

```
┌─────────────────────────────────────────┐
│           npm Workspaces                │
├─────────────────────────────────────────┤
│  📦 common/                              │
│  └─ Shared TypeScript types, schemas,   │
│     constants, and utilities            │
│                                          │
│  📦 backend/                    ✅ DONE │
│  ├─ MCP Server (13 tools)               │
│  ├─ WhatsApp Client (Baileys)           │
│  ├─ Data Store (JSON/SQLite/MongoDB)    │
│  ├─ Service Layer                       │
│  └─ Pino Logging                        │
│                                          │
│  📦 frontend/              🚧 PENDING   │
│  ├─ React + TypeScript                  │
│  ├─ Redux Toolkit                       │
│  ├─ Tailwind CSS                        │
│  └─ REST API + WebSocket Client         │
└─────────────────────────────────────────┘
```

### Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | TypeScript 5.5+ (strict mode) |
| Runtime | Node.js 20+ |
| Package Manager | npm workspaces |
| WhatsApp | @whiskeysockets/baileys |
| MCP SDK | @modelcontextprotocol/sdk |
| Backend | Express (planned) |
| Frontend | React 18 + Vite |
| State Mgmt | Redux Toolkit |
| Storage | JSON (default), SQLite, MongoDB |
| Testing | Vitest |
| Logging | Pino |

## 🚀 Quick Start (TypeScript Version)

### Prerequisites

- Node.js 20+ and npm 10+
- WhatsApp account for QR code authentication
- Claude Desktop or Cursor IDE

### Installation

```bash
# Clone and navigate
git clone https://github.com/lharries/whatsapp-mcp.git
cd whatsapp-mcp

# Install dependencies
npm install

# Build common package
npm run build -w common

# Build backend
npm run build -w backend
```

### Run Backend

```bash
cd backend
cp .env.example .env
# Edit .env if needed

# Development mode
npm run dev

# Production mode
npm run build && npm start
```

First run: Scan QR code with WhatsApp mobile app to authenticate.

### MCP Integration

**Claude Desktop** - Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "whatsapp": {
      "command": "node",
      "args": ["/absolute/path/to/whatsapp-mcp/backend/dist/index.js"]
    }
  }
}
```

**Cursor** - Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "whatsapp": {
      "command": "node",
      "args": ["/absolute/path/to/whatsapp-mcp/backend/dist/index.js"]
    }
  }
}
```

Restart Claude Desktop or Cursor after configuration.

## 📚 MCP Tools (All 13 Implemented)

1. **search_contacts** - Search by name or phone
2. **list_messages** - Retrieve messages with filters
3. **list_chats** - List chats with sorting
4. **get_chat** - Get specific chat info
5. **get_direct_chat_by_contact** - Find chat by phone
6. **get_contact_chats** - All chats with a contact
7. **get_last_interaction** - Most recent message
8. **get_message_context** - Surrounding messages
9. **send_message** - Send text message
10. **send_file** - Send media files
11. **send_audio_message** - Send voice messages
12. **download_media** - Download media
13. **get_auth_status** - Connection status

## 📁 Project Structure

```
whatsapp-mcp/
├── backend/              ✅ TypeScript MCP server (COMPLETE)
│   ├── src/
│   │   ├── mcp/         # MCP server + tools
│   │   ├── whatsapp/    # Baileys client
│   │   ├── store/       # Data abstraction
│   │   ├── service/     # Business logic
│   │   ├── config/      # Configuration
│   │   └── util/        # Logging, utilities
│   └── data/            # Runtime data (gitignored)
│
├── frontend/            🚧 React client (PENDING)
│   ├── src/
│   │   ├── component/   # UI components
│   │   ├── feature/     # Redux slices
│   │   └── store/       # Redux store
│   └── public/
│
├── common/              ✅ Shared code (COMPLETE)
│   └── src/
│       ├── type/        # TypeScript types
│       ├── schema/      # Zod schemas
│       ├── constant/    # Constants
│       └── util/        # Utilities
│
├── whatsapp-bridge/     ⚠️ LEGACY (to be removed)
└── whatsapp-mcp-server/ ⚠️ LEGACY (to be removed)
```

## 💾 Data Storage

### JSON Store (Default) ✅
- **Path**: `backend/data/json/`
- **Files**: chats.json, messages.json, contacts.json, media.json
- **Pros**: Simple, no dependencies
- **Config**: `DATA_STORE_TYPE=json`

### SQLite 🚧 (Planned)
- **Path**: `backend/data/whatsapp.db`
- **Pros**: Fast, indexed
- **Config**: `DATA_STORE_TYPE=sqlite`

### MongoDB 🚧 (Planned)
- **Connection**: Via URI
- **Pros**: Scalable, flexible
- **Config**: `DATA_STORE_TYPE=mongodb`

## 🎨 Naming Convention

**Singular nouns** with semantic suffixes:

```typescript
// ✅ Correct
const messageList: Message[] = [];
const chatCollection: Chat[] = [];
const contactGroup: Contact[] = [];

// ❌ Avoid
const messages: Message[] = [];
const chats: Chat[] = [];
```

**Directories**: Singular (e.g., `message/`, `chat/`, `component/`)

## 🗺️ Migration Roadmap

### ✅ Phase 1-2: Backend (COMPLETE)
- [x] npm workspaces setup
- [x] Common types and schemas
- [x] WhatsApp client (Baileys)
- [x] JSON data store
- [x] MCP server (13 tools)
- [x] Service layer
- [x] Pino logging

### 🚧 Phase 3: Backend API (Next)
- [ ] Express REST API
- [ ] WebSocket real-time updates
- [ ] JWT authentication
- [ ] SQLite & MongoDB stores

### 📋 Phase 4: Frontend
- [ ] React + Redux setup
- [ ] Chat UI components
- [ ] QR authentication UI
- [ ] Media handling

### 📋 Phase 5-7: Polish
- [ ] Comprehensive tests
- [ ] API documentation
- [ ] Docker deployment
- [ ] CI/CD pipeline

## 🔐 Privacy

- All messages stored **locally**
- Only sent to AI when explicitly accessed
- No cloud dependencies
- WhatsApp session encrypted

> ⚠️ **Security Note**: This project is subject to [the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) - be cautious of project injection risks.

## 📖 Documentation

- **[Backend README](./backend/README.md)** - Backend architecture
- **[Frontend README](./frontend/README.md)** - Frontend structure
- **[Migration Status](./MIGRATION_STATUS.md)** - Detailed progress
- **[Legacy README](./README.legacy.md)** - Original Go/Python docs

## 🤝 Contributing

Project under active development. Contributions welcome after Phase 3.

## 📝 License

MIT License - see [LICENSE](./LICENSE)

## 🙏 Credits

- **Legacy**: [whatsmeow](https://github.com/tulir/whatsmeow) (Go)
- **New**: [@whiskeysockets/baileys](https://github.com/WhiskeySockets/Baileys) (TypeScript)
- **MCP SDK**: [@modelcontextprotocol/sdk](https://github.com/modelcontextprotocol/typescript-sdk)

---

**Status**: 🟢 Backend Complete | 🟡 Frontend Pending
**Last Updated**: 2025-10-23
**Branch**: `claude/typescript-whatsapp-rewrite-011CUPU53kzDQSzMxCMWPiFb`
