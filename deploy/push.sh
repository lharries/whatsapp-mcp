#!/usr/bin/env bash
# Runs from your Mac — syncs both repos to the instance then runs setup
# Usage: bash deploy/push.sh

set -euo pipefail

HOST="ec2-user@34.242.181.49"
KEY="$HOME/.ssh/games-server.pem"
SSH="ssh -i $KEY -p 40285 -o StrictHostKeyChecking=accept-new"

echo "==> Syncing whatsapp-mcp..."
rsync -az --delete \
    --exclude='.git' --exclude='.venv' \
    --exclude='whatsapp-bridge/store' \
    --exclude='whatsapp-bridge/whatsapp-bridge' \
    "$(dirname "$0")/../" \
    -e "ssh -i $KEY -p 40285" \
    "$HOST:/opt/whatsapp-mcp/"

echo "==> Syncing luke_stuff..."
rsync -az --delete \
    --exclude='.git' --exclude='__pycache__' \
    -e "ssh -i $KEY -p 40285" \
    /Users/robdickinson/code/luke_stuff/ \
    "$HOST:/opt/luke_stuff/"

echo "==> Running setup on instance..."
$SSH "$HOST" "sudo bash /opt/whatsapp-mcp/deploy/setup.sh"
