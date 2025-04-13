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
echo "Starting Go WhatsApp Bridge..."
# Run in background, redirect output if needed
/app/whatsapp-bridge &
BRIDGE_PID=$!
echo "Go Bridge started with PID $BRIDGE_PID"

# Wait a moment to ensure the API is available
sleep 2

# --- Start Python MCP Server ---
echo "Starting Python MCP Server..."
# Activate virtual environment and run the Python script
# This runs in the foreground and handles MCP communication via stdio
. /app/venv/bin/activate
cd /app/whatsapp-mcp-server
python main.py &
MCP_PID=$!
echo "Python MCP Server started with PID $MCP_PID"

# Wait for either process to exit
wait -n $BRIDGE_PID $MCP_PID

# If one exits, send signal to the other to ensure cleanup
if kill -0 $BRIDGE_PID 2>/dev/null; then
    echo "MCP Server exited, stopping Go Bridge..."
    kill $BRIDGE_PID
fi
if kill -0 $MCP_PID 2>/dev/null; then
    echo "Go Bridge exited, stopping MCP Server..."
    kill $MCP_PID
fi

# Wait for remaining process to terminate
wait
echo "Both processes stopped. Exiting."

exit 0