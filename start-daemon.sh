#!/usr/bin/env bash
#
# Start WhatsApp Bridge + Claude Daemon
# Usage: ./start-daemon.sh
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_DIR="$SCRIPT_DIR/whatsapp-bridge"
DAEMON_SCRIPT="$SCRIPT_DIR/whatsapp-daemon.py"

BRIDGE_PID=""
DAEMON_PID=""

cleanup() {
    echo ""
    echo "[daemon] Shutting down..."
    [ -n "$DAEMON_PID" ] && kill "$DAEMON_PID" 2>/dev/null
    [ -n "$BRIDGE_PID" ] && kill "$BRIDGE_PID" 2>/dev/null
    wait 2>/dev/null
    echo "[daemon] Stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Prerequisites
if [ ! -f "$BRIDGE_DIR/whatsapp-bridge" ]; then
    echo "[daemon] Building Go bridge..."
    (cd "$BRIDGE_DIR" && go build -o whatsapp-bridge .) || exit 1
fi
command -v python3 &>/dev/null || { echo "[daemon] ERROR: python3 not found"; exit 1; }
command -v claude &>/dev/null  || { echo "[daemon] ERROR: claude CLI not found"; exit 1; }
python3 -c "import requests" 2>/dev/null || pip3 install requests

# Kill stale processes on our ports
echo "[daemon] Cleaning up stale processes..."
lsof -ti:8080 2>/dev/null | xargs kill 2>/dev/null || true
lsof -ti:9090 2>/dev/null | xargs kill 2>/dev/null || true
sleep 1

# Start bridge
echo "[daemon] Starting WhatsApp bridge..."
(cd "$BRIDGE_DIR" && exec ./whatsapp-bridge) &
BRIDGE_PID=$!

# Wait for bridge API (check port is open, don't send real messages)
echo "[daemon] Waiting for bridge API..."
for i in $(seq 1 30); do
    kill -0 "$BRIDGE_PID" 2>/dev/null || { echo "[daemon] ERROR: Bridge died"; exit 1; }
    lsof -ti:8080 >/dev/null 2>&1 && break
    sleep 1
done
echo "[daemon] Bridge API ready (port 8080)"

# Start daemon
echo "[daemon] Starting Claude daemon..."
python3 "$DAEMON_SCRIPT" &
DAEMON_PID=$!
sleep 1
kill -0 "$DAEMON_PID" 2>/dev/null || { echo "[daemon] ERROR: Daemon failed to start"; cleanup; }
echo "[daemon] Claude daemon ready (port 9090)"

echo ""
echo "========================================="
echo "  WhatsApp + Claude Daemon Running"
echo "  Bridge:  PID $BRIDGE_PID (port 8080)"
echo "  Daemon:  PID $DAEMON_PID (port 9090)"
echo "  Press Ctrl+C to stop"
echo "========================================="
echo ""

# Monitor — restart daemon if it dies, exit if bridge dies
while true; do
    if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
        echo "[daemon] Bridge exited unexpectedly"
        cleanup
    fi
    if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
        echo "[daemon] Daemon died, restarting..."
        python3 "$DAEMON_SCRIPT" &
        DAEMON_PID=$!
        sleep 1
    fi
    sleep 2
done
