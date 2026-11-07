#!/usr/bin/env bash
# Install the WhatsApp bridge on a Linux server. Idempotent; safe to re-run.
#
#   sudo ./deploy/install.sh            # build + install units (no start)
#   sudo systemctl enable --now wa-bridge@main
#
# Then link the phone by opening http://127.0.0.1:8080/pair (over an SSH tunnel,
# Tailscale, or an authenticated reverse proxy).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_USER="wa"
CONF_DIR="/etc/whatsapp-mcp"
STATE_DIR="/var/lib/whatsapp-mcp"
BRIDGE_DIR="$REPO_DIR/whatsapp-bridge"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This installer targets Linux (systemd). On macOS use whatsapp-service." >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

echo "==> Building the bridge"
( cd "$BRIDGE_DIR" && CGO_ENABLED=1 go build -o wa-bridge . )

echo "==> Creating service user and directories"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$STATE_DIR"
install -d -m 0750 "$CONF_DIR"

echo "==> Installing the systemd template unit"
install -m 0644 "$REPO_DIR/deploy/wa-bridge@.service" /etc/systemd/system/wa-bridge@.service

if [[ ! -f "$CONF_DIR/main.env" ]]; then
  echo "==> Seeding $CONF_DIR/main.env"
  install -m 0640 "$REPO_DIR/deploy/env.example" "$CONF_DIR/main.env"
  sed -i "s/^WA_TOKEN=$/WA_TOKEN=$(openssl rand -hex 32)/" "$CONF_DIR/main.env"
  chown root:"$SERVICE_USER" "$CONF_DIR/main.env"
fi

systemctl daemon-reload
cat <<EOF

Done. Next:
  sudo systemctl enable --now wa-bridge@main
  curl -s localhost:8080/healthz            # {"connected":false,...} until paired
  # link the phone (via SSH tunnel):  ssh -L 8080:127.0.0.1:8080 this-host
  # then open http://127.0.0.1:8080/pair

A second number is just another instance + env file:
  sudo cp $CONF_DIR/main.env $CONF_DIR/second.env   # set WA_PORT=8081, WA_ACCOUNT=second, a new token
  sudo systemctl enable --now wa-bridge@second
EOF
