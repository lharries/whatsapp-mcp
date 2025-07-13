#!/bin/bash

# Start the Go WhatsApp bridge in the background
cd /app/whatsapp-bridge
./whatsapp-bridge &

# Start the Python MCP server
cd /app/whatsapp-mcp-server
uv run main.py

# Keep the container running
wait