# Deploying the bridge

Two supported ways to run the bridge headless: **systemd** (bare metal / VPS) or
**Docker**. Both run **one process per account** — the whatsmeow-recommended way
to host several numbers. Each account gets its own store dir (its own keys) and
its own port.

## systemd

```bash
sudo ./deploy/install.sh
sudo systemctl enable --now wa-bridge@main
curl -s localhost:8080/healthz
```

Then link the phone. The server has no terminal to show a QR code, so the bridge
serves one at `http://127.0.0.1:8080/pair`:

```bash
ssh -L 8080:127.0.0.1:8080 user@server   # tunnel it, or use Tailscale
# open http://127.0.0.1:8080/pair and scan (or request a pairing code)
```

Add a second number:

```bash
sudo cp /etc/whatsapp-mcp/main.env /etc/whatsapp-mcp/second.env
sudo sed -i 's/WA_ACCOUNT=main/WA_ACCOUNT=second/; s/WA_PORT=8080/WA_PORT=8081/; s/^WA_TOKEN=.*/WA_TOKEN='"$(openssl rand -hex 32)"'/' /etc/whatsapp-mcp/second.env
sudo systemctl enable --now wa-bridge@second
```

## Docker

```bash
cp deploy/env.example deploy/main.env   # fill in WA_TOKEN etc.
docker compose -f deploy/docker-compose.yml up -d --build
```

## Configuration (env)

| Var | Meaning |
|---|---|
| `WA_ACCOUNT` | label for this account (`main`, `second`, …) |
| `WA_PORT` | REST port (each account needs a different one) |
| `WA_DB_DIR` | store directory (keys + messages) — persist it |
| `WA_TOKEN` | bearer token required on every `/api/*` and `/pair` call |
| `WEBHOOK_URL` / `WEBHOOK_SECRET` | inbound-message webhook + HMAC signing |
| `WA_OWNER_JID` | your JID for reply approval |

## Security notes

- The API binds to `127.0.0.1`. Expose it only through an authenticated proxy
  (Tailscale, or nginx/Caddy with TLS + the bearer token).
- The store holds the account's keys: back up `*-wal` and `*-shm` with the DB,
  keep it out of git and out of images, and treat backups as secrets.
- Never run two processes against one store — WhatsApp silently drops one.

## Failure modes to watch

- `logged_out` (device unlinked): re-pair via `/pair`.
- `temporary_ban`: WhatsApp refused the connection; stop sending, wait for it to
  expire, then restart. Causes are almost always send rate.
- Silent disconnect (another process took the session): `/healthz` stays
  `connected:false`. Point an uptime monitor at it.
