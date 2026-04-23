# Docker Setup for WhatsApp MCP

This setup runs the WhatsApp MCP server in Docker containers with persistent storage.

## Architecture

- **whatsapp-bridge**: Go application that connects to WhatsApp via QR code, stores messages in SQLite
- **whatsapp-mcp-server**: Python MCP server that provides tools for Claude to interact with WhatsApp
- **whatsapp-store volume**: Docker volume that persists SQLite databases and media files across container restarts

## Prerequisites

- Docker
- Docker Compose

## Quick Start

1. **Build and start the containers:**
   ```bash
   docker-compose up -d --build
   ```

2. **View the bridge logs to get the QR code:**
   ```bash
   docker-compose logs -f whatsapp-bridge
   ```

3. **Scan the QR code** with your WhatsApp mobile app to authenticate

4. **Configure Claude Desktop** to use the Dockerized MCP server:
   ```json
   {
     "mcpServers": {
       "whatsapp": {
         "command": "docker",
         "args": [
           "compose",
           "run",
           "--rm",
           "whatsapp-mcp-server"
         ],
         "env": {
           "WHATSAPP_API_BASE_URL": "http://host.docker.internal:8080/api"
         }
       }
     }
   }
   ```
   Save this to `~/Library/Application Support/Claude/claude_desktop_config.json`

   **Note**: We use `host.docker.internal` so the MCP server container can reach the bridge running on the host network.

5. **Restart Claude Desktop**

## Persistence

The `whatsapp-store` Docker volume persists:
- `store/whatsapp.db` - WhatsApp session/authentication data
- `store/messages.db` - Message history
- `store/{chat_jid}/` - Media files for each chat

This means your authentication and message history will survive container restarts.

## Commands

- **Start containers**: `docker-compose up -d`
- **Stop containers**: `docker-compose down`
- **View logs**: `docker-compose logs -f [service-name]`
- **Rebuild**: `docker-compose up -d --build`
- **Remove volumes** (deletes all data): `docker-compose down -v`

## Troubleshooting

### Bridge not connecting
- Check logs: `docker-compose logs whatsapp-bridge`
- Ensure the QR code was scanned within the time limit
- You may need to re-authenticate after ~20 days

### MCP server can't reach bridge
- The MCP server uses `WHATSAPP_API_BASE_URL` environment variable
- In Docker Compose, it's set to `http://whatsapp-bridge:8080/api` (internal network)
- For Claude Desktop config, use `http://host.docker.internal:8080/api`

### Data not persisting
- Check volume exists: `docker volume ls`
- Inspect volume: `docker volume inspect whatsapp-mcp_whatsapp-store`
