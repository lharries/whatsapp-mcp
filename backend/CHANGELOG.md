# Changelog

## [2.0.0] - 2025-10-23

### Added - Phase 3: REST API & WebSocket

#### REST API Server
- Complete Express-based REST API with 20+ endpoints
- Authentication endpoints (status, QR code, logout)
- Chat management (list, get, search, filter)
- Message operations (list, send, context, media)
- Contact search and listing
- Comprehensive error handling with custom ApiError class
- Zod validation middleware for request validation
- CORS support for frontend integration
- Pino request logging

#### WebSocket Server
- Real-time message broadcasting to connected clients
- Connection status update broadcasts
- Chat update notifications
- Heartbeat mechanism with 30-second intervals
- Automatic client connection management
- Event-driven architecture

#### WhatsApp Client Enhancements
- Event listener pattern for real-time updates
- `addEventListener` and `removeEventListener` methods
- Event emissions: `onMessage`, `onChatUpdate`, `onConnectionUpdate`
- Automatic broadcasting of WhatsApp events

#### Controllers
- `AuthController` - Authentication operations
- `ChatController` - Chat management with filtering
- `MessageController` - Message CRUD and media handling
- `ContactController` - Contact search and listing

#### Routes
- `/api/auth/*` - 3 authentication endpoints
- `/api/chats/*` - 4 chat management endpoints
- `/api/messages/*` - 6 message operation endpoints
- `/api/contacts/*` - 2 contact endpoints

#### Middleware
- Error handling middleware with ApiError support
- Zod validation middleware (body, query, params)
- Request logger middleware
- 404 not found handler

#### Documentation
- Comprehensive API.md with all endpoint documentation
- Request/response examples for all endpoints
- WebSocket event format documentation
- curl and JavaScript usage examples
- Updated backend README with API information

### Changed

#### Main Entry Point
- Updated to initialize and run three servers simultaneously:
  - MCP Server (stdio transport)
  - REST API Server (HTTP on port 8080)
  - WebSocket Server (WS on /ws path)
- Integrated WhatsApp event listeners with WebSocket broadcasts
- Enhanced graceful shutdown to handle all servers

#### WhatsApp Client
- Added event emitter capabilities
- Enhanced with event listener management
- Emits events on message receipt, chat updates, and connection changes

#### Backend README
- Added REST API section with endpoint overview
- Added WebSocket section with event types
- Updated architecture diagram
- Added API.md reference

### Technical Details

**New Files**: 15
- Controllers: 4 files (~600 lines)
- Routes: 4 files (~200 lines)
- Middleware: 2 files (~150 lines)
- API Server: 1 file (~200 lines)
- WebSocket Server: 1 file (~200 lines)
- Documentation: 1 file (~450 lines)

**Modified Files**: 3
- `backend/src/index.ts` - Integrated all servers
- `backend/src/whatsapp/client.ts` - Added event emitters
- `backend/README.md` - Added API documentation

**Total New Lines**: ~1,800

### Architecture

```
WhatsApp MCP Backend
├── MCP Server (stdio) ───────────→ Claude Desktop/Cursor
├── REST API (HTTP:8080) ─────────→ React Frontend (planned)
└── WebSocket (WS:8080/ws) ───────→ Real-time client updates

All three interfaces share:
├── WhatsApp Client (Baileys)
├── Data Store (JSON/SQLite/MongoDB)
├── Service Layer (Message, Chat, Contact)
└── Business Logic
```

### Dependencies

No new dependencies added. All functionality built with existing stack:
- Express (already included)
- ws (already included)
- Zod (already included)

### Breaking Changes

None. This release is purely additive. Existing MCP functionality unchanged.

### Migration Notes

If upgrading from v1.0.0:
1. Pull latest code
2. Run `npm install` (no new dependencies, but ensures ws is installed)
3. Rebuild: `npm run build`
4. Restart server: `npm run dev` or `npm start`

The server now listens on port 8080 for HTTP/WebSocket in addition to MCP stdio.

### Next Steps (Phase 4+)

- [ ] React frontend application
- [ ] Redux state management integration
- [ ] Frontend WebSocket client
- [ ] JWT authentication
- [ ] SQLite and MongoDB store implementations
- [ ] Comprehensive testing suite
- [ ] Docker containerization

---

## [1.0.0] - 2025-10-23 (Initial Release)

### Added - Phase 1 & 2: Backend Foundation

#### Project Structure
- npm workspaces monorepo (backend, frontend, common)
- TypeScript 5.5+ with strict mode
- Comprehensive tsconfig for each workspace
- ESLint and Prettier configuration

#### Common Package
- 7 TypeScript type definition files
- 3 Zod validation schemas
- Shared constants and utilities
- Validator and formatter utilities

#### Backend Package
- MCP Server with 13 tools
- WhatsApp Client using Baileys
- Data store abstraction (JSON implementation)
- Service layer (Message, Chat, Contact services)
- Pino logger with pretty printing
- Environment-based configuration

#### MCP Tools (13 total)
1. search_contacts
2. list_messages
3. list_chats
4. get_chat
5. get_direct_chat_by_contact
6. get_contact_chats
7. get_last_interaction
8. get_message_context
9. send_message
10. send_file
11. send_audio_message
12. download_media
13. get_auth_status

#### WhatsApp Integration
- QR code authentication
- Connection management with auto-reconnect
- Message sending/receiving
- Media handling (images, videos, audio, documents)
- Chat and contact synchronization

#### Data Storage
- JSON file-based storage (default)
- Abstract interface for extensibility
- Support for chats, messages, contacts, media metadata

### Technical Stack

- Node.js 20+
- TypeScript 5.5+
- @modelcontextprotocol/sdk v1.0.4
- @whiskeysockets/baileys v6.7.7
- Express v4.19.2
- Pino v9.2.0
- Zod v3.23.8
