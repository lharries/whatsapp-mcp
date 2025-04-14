#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Trap SIGTERM and SIGINT to gracefully shut down children
trap 'kill $(jobs -p); exit 0' SIGTERM SIGINT

# --- Configuration ---
# Ensure data directory structure exists (Go code also does this, but belt-and-suspenders)
mkdir -p /data/store
chown appuser:appgroup /data/store

# --- Start Go Bridge ---
echo "Starting Go WhatsApp Bridge..." >&2
# Run in background, redirect output to stderr
/app/whatsapp-bridge 2>&1 >&2 &
BRIDGE_PID=$!
echo "Go Bridge started with PID $BRIDGE_PID" >&2

# Wait a moment to ensure the API is available
sleep 2

# --- Start Python MCP Server ---
echo "Starting Python MCP Server..." >&2
# Activate virtual environment and run the Python script
# This runs in the foreground and handles MCP communication via stdio
. /app/venv/bin/activate
cd /app/whatsapp-mcp-server

# Run the MCP server in the foreground
# All diagnostic output is redirected to stderr to keep stdin/stdout clean for MCP protocol
exec python main.py