# WhatsApp bridge: self-healing launchd setup

The bridge used to wedge in a way nothing recovered automatically: the process
stayed **alive** and kept TCP port **8080 bound**, but the HTTP server stopped
answering. `launchctl`'s `KeepAlive` only restarts a service when the process
**exits**, so a wedged-but-alive bridge sat there dead — "held the port, stopped
answering" — until it was relaunched by hand.

This directory makes it self-heal.

## Pieces

| File | What it is |
|------|------------|
| `com.kodi.whatsapp-bridge.plist` | The bridge itself. `KeepAlive` + `ThrottleInterval`. |
| `com.kodi.whatsapp-bridge-watchdog.plist` | Periodic agent (every 15s) that runs `watchdog.sh`. |
| `../watchdog.sh` | Probes `/health`; force-restarts the bridge after 2 consecutive failures. |

### 1. Real health endpoint (in the bridge itself)

`GET http://localhost:8080/health` → `200` with JSON:

```json
{"status":"ok","whatsapp_connected":true,"logged_in":true,"uptime_seconds":1234,"time":"2026-06-08T03:40:00Z"}
```

It runs on the same HTTP server as `/api/*`, so if the server is wedged the
probe **hangs and times out** — which is exactly how the watchdog detects a dead
socket. The listener also now sets `SO_REUSEADDR` and real `http.Server` timeouts
(Read/Write/Idle), so a stuck client can't silently wedge the accept loop, and a
fresh instance can re-bind 8080 immediately after a forced restart.

### 2. Watchdog

`watchdog.sh` curls `/health` with a 5s timeout. On failure it bumps a counter in
`/tmp/whatsapp-bridge-watchdog.fails`; after **2 consecutive** failures it runs:

```
launchctl kickstart -k gui/<uid>/com.kodi.whatsapp-bridge
```

`-k` SIGKILLs the wedged process (**freeing the port**) and relaunches it. It
explicitly logs the dead-socket-with-port-held case (`port-HELD-but-dead`) so the
recurring pattern is visible in `/tmp/whatsapp-bridge-watchdog.log`.

## Install / update

```bash
cd /Users/kodikaraste/Projects/whatsapp-mcp/whatsapp-bridge

# 1. (re)build the bridge binary the plist points at
go build -o whatsapp-bridge .

# 2. copy the plists into place
cp launchd/com.kodi.whatsapp-bridge.plist          ~/Library/LaunchAgents/
cp launchd/com.kodi.whatsapp-bridge-watchdog.plist ~/Library/LaunchAgents/
chmod +x watchdog.sh

# 3. (re)load both agents
launchctl unload ~/Library/LaunchAgents/com.kodi.whatsapp-bridge.plist 2>/dev/null
launchctl load  ~/Library/LaunchAgents/com.kodi.whatsapp-bridge.plist
launchctl unload ~/Library/LaunchAgents/com.kodi.whatsapp-bridge-watchdog.plist 2>/dev/null
launchctl load  ~/Library/LaunchAgents/com.kodi.whatsapp-bridge-watchdog.plist
```

## Verify

```bash
# both agents loaded (PID in col 1 for the bridge; watchdog shows '-' between ticks)
launchctl list | grep whatsapp

# health is green
curl -s http://localhost:8080/health | python3 -m json.tool

# watchdog activity
tail -f /tmp/whatsapp-bridge-watchdog.log
```

## Test the self-heal (forced wedge)

`SIGSTOP` reproduces the exact "port held but socket dead" wedge — the process
freezes, keeps the port bound, answers nothing:

```bash
PID=$(launchctl list | awk '$3=="com.kodi.whatsapp-bridge"{print $1}')
kill -STOP "$PID"          # wedge it
# within ~30-45s the watchdog logs port-HELD-but-dead, runs kickstart -k,
# and a NEW pid comes up with /health=200. Confirm:
launchctl list | awk '$3=="com.kodi.whatsapp-bridge"{print "new pid",$1}'
curl -s http://localhost:8080/health
```

If you ever need to undo a wedge manually before the watchdog fires:
`kill -CONT "$PID"` (resumes it) or `launchctl kickstart -k gui/$(id -u)/com.kodi.whatsapp-bridge`.
