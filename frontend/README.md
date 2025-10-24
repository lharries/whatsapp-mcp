# WhatsApp MCP Frontend

React client application for WhatsApp MCP Server.

## Status

🚧 **Under Development** - Frontend structure created, implementation pending.

## Planned Architecture

### Technology Stack
- **Framework**: React 18 with TypeScript
- **Build Tool**: Vite
- **State Management**: Redux Toolkit with slices
- **Styling**: Tailwind CSS
- **Routing**: React Router
- **HTTP Client**: Axios
- **MCP Client**: @modelcontextprotocol/sdk
- **WebSocket**: Native WebSocket API

### Structure

```
frontend/src/
├── component/          # React components
│   ├── layout/        # Layout components
│   ├── auth/          # Authentication (QR code display)
│   ├── chat/          # Chat components
│   ├── contact/       # Contact components
│   ├── media/         # Media upload/preview
│   └── setting/       # Settings
├── feature/           # Redux features (slices)
│   ├── auth/          # authSlice.ts
│   ├── chat/          # chatSlice.ts
│   ├── message/       # messageSlice.ts
│   └── ui/            # uiSlice.ts
├── store/             # Redux store configuration
├── api/               # API client and endpoints
├── hook/              # Custom React hooks
├── type/              # TypeScript type definitions
└── util/              # Utility functions
```

## Development

```bash
# Install dependencies (from root)
npm install

# Run frontend in dev mode
npm run dev -w frontend

# Build for production
npm run build -w frontend
```

## Features (Planned)

- [ ] QR code authentication UI
- [ ] Real-time connection status
- [ ] Chat list with search
- [ ] Message thread view
- [ ] Send text messages
- [ ] Upload and send media files
- [ ] Record and send voice messages
- [ ] Download media from messages
- [ ] Contact search
- [ ] Settings panel
- [ ] Dark mode support

## Integration

The frontend will connect to:
1. **Backend REST API** (http://localhost:8080) - HTTP requests
2. **WebSocket** (ws://localhost:8080) - Real-time updates
3. **MCP Server** (optional) - Direct MCP tool access

## Next Steps

1. Set up Redux store and slices
2. Create API client with Axios
3. Implement authentication flow
4. Build chat and message components
5. Add WebSocket integration
6. Implement media handling
7. Add comprehensive tests
