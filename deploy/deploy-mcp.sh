#!/usr/bin/env bash
# Quick deploy: sync Python MCP server code and restart the service.
# Usage: bash deploy/deploy-mcp.sh
set -euo pipefail

HOST="ec2-user@34.242.181.49"
KEY="$HOME/.ssh/games-server.pem"
RSYNC="rsync -az --exclude='.git' --exclude='.venv' --exclude='__pycache__' -e 'ssh -i $KEY -p 40285'"

echo "==> Syncing whatsapp-mcp-server..."
rsync -az \
  --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
  -e "ssh -i $KEY -p 40285" \
  "$(dirname "$0")/../whatsapp-mcp-server/" \
  "$HOST:/opt/whatsapp-mcp/whatsapp-mcp-server/"

echo "==> Restarting whatsapp-mcp..."
ssh -i "$KEY" -p 40285 "$HOST" "sudo systemctl restart whatsapp-mcp"

echo "==> Done."
