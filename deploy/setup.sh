#!/usr/bin/env bash
# Runs ON the EC2 instance (Amazon Linux 2023) as ec2-user via sudo
# Called by push.sh — do not run directly unless you know what you're doing

set -euo pipefail

APP_DIR="/opt/whatsapp-mcp"
GAMES_DIR="/opt/games"
HOSTNAME="34.242.181.49.nip.io"

echo "==> Installing system packages"
dnf update -y -q
dnf install -y -q git golang nginx python3.11 sqlite certbot python3-certbot-nginx xz

echo "==> Installing ffmpeg (static binary — not in AL2023 default repos)"
curl -sL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
    | tar -xJ --strip-components=1 -C /usr/local/bin --wildcards '*/ffmpeg' '*/ffprobe'

echo "==> Installing uv"
su - ec2-user -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "==> Building Go bridge"
cd "$APP_DIR/whatsapp-bridge"
sudo -u ec2-user go build -mod=vendor -o whatsapp-bridge .

echo "==> Setting up Python venv"
cd "$APP_DIR/whatsapp-mcp-server"
sudo -u ec2-user /home/ec2-user/.local/bin/uv sync

echo "==> Writing .env from SSM"
SECRET=$(aws ssm get-parameter --name /whatsapp-mcp/client-secret --with-decryption --query Parameter.Value --output text)
cat > "$APP_DIR/.env" <<EOF
MCP_CLIENT_ID=claude
MCP_CLIENT_SECRET=$SECRET
MCP_TOKEN_TTL=3600
EOF
chmod 600 "$APP_DIR/.env"
chown ec2-user:ec2-user "$APP_DIR/.env"

echo "==> Installing systemd services"
cp "$APP_DIR/deploy/whatsapp-bridge.service" /etc/systemd/system/
cp "$APP_DIR/deploy/whatsapp-mcp.service" /etc/systemd/system/

# Games server: move from port 80 to 8080 behind nginx
cp /opt/luke_stuff/deploy/games-server.service /etc/systemd/system/
# Stop whatever is currently holding port 80
fuser -k 80/tcp 2>/dev/null || true
pkill -f 'server.py' 2>/dev/null || true
systemctl stop nginx 2>/dev/null || true

systemctl daemon-reload
systemctl enable games-server whatsapp-bridge whatsapp-mcp

echo "==> Obtaining TLS certificate"
certbot certonly --standalone -d "$HOSTNAME" --non-interactive --agree-tos -m "admin@$HOSTNAME"

echo "==> Configuring nginx"
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/conf.d/combined.conf
rm -f /etc/nginx/conf.d/default.conf /etc/nginx/sites-enabled/default 2>/dev/null || true
nginx -t
systemctl enable nginx
systemctl start nginx

echo "==> Starting games server on port 8080"
systemctl start games-server

echo ""
echo "==> Starting WhatsApp bridge — scan the QR code with your phone"
systemctl start whatsapp-bridge
echo "   (watching logs — press Ctrl+C once you've scanned)"
journalctl -u whatsapp-bridge -f &
JOURNAL_PID=$!
read -rp "   Press Enter after scanning..."
kill $JOURNAL_PID 2>/dev/null || true

echo "==> Starting MCP server"
systemctl start whatsapp-mcp
systemctl reload nginx

echo ""
echo "==> Done! Services running:"
systemctl is-active games-server whatsapp-bridge whatsapp-mcp nginx
echo ""
echo "MCP SSE URL:   https://$HOSTNAME/sse"
echo "OAuth token:   https://$HOSTNAME/oauth/token"
echo "Games server:  https://$HOSTNAME/"
