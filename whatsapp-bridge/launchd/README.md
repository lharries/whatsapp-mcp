# WhatsApp bridge: self-healing launchd setup

The bridge used to wedge in a way nothing recovered automatically: the process
stayed **alive** and kept TCP port **8080 bound**, but the HTTP server stopped
answering. `launchctl`'s `KeepAlive` only restarts a service when the process
**exits**, so a wedged-but-alive bridge sat there dead — "held the port, stopped
answering" — until it was relaunched by hand.

This makes it self-heal, and ships as part of the app: one portable installer
wires everything up from wherever the app was downloaded to (no hardcoded paths).

## Install (one command)

```bash
cd whatsapp-bridge
./install-service.sh        # builds the binary if needed, installs + loads both agents, verifies /health
```

Undo any time:

```bash
./uninstall-service.sh
```

`install-service.sh` derives every path from its own location and the current
user, generates the two launchd plists into `~/Library/LaunchAgents/`, loads
them, and waits for `/health` to go green. Re-running it is safe (idempotent).

## What it installs

| Agent | Role |
|-------|------|
| `com.kodi.whatsapp-bridge` | The bridge. `RunAtLoad` + `KeepAlive` + `ThrottleInterval`. |
| `com.kodi.whatsapp-bridge-watchdog` | Runs `../watchdog.sh` every 15s. |

### 1. Real health endpoint (in the bridge)

`GET http://localhost:8080/health` → `200` with JSON:

```json
{"status":"ok","whatsapp_connected":true,"logged_in":true,"uptime_seconds":1234,"time":"2026-06-08T03:40:00Z"}
```

It runs on the same HTTP server as `/api/*`, so if the server is wedged the
probe **hangs and times out** — which is exactly how the watchdog detects a dead
socket. The listener also sets `SO_REUSEADDR` and real `http.Server` timeouts
(Read/Write/Idle), so a stuck client can't wedge the accept loop, and a fresh
instance can re-bind 8080 immediately after a forced restart.

### 2. Watchdog

`watchdog.sh` curls `/health` with a 5s timeout. On failure it bumps a counter in
`/tmp/whatsapp-bridge-watchdog.fails`; after **2 consecutive** failures it runs:

```
launchctl kickstart -k gui/<uid>/com.kodi.whatsapp-bridge
```

`-k` SIGKILLs the wedged process (**freeing the port**) and relaunches it. It
logs the dead-socket-with-port-held case (`port-HELD-but-dead`) to
`/tmp/whatsapp-bridge-watchdog.log` so the recurring pattern is visible.

## Verify

```bash
launchctl list | grep whatsapp                 # bridge has a PID; watchdog shows '-' between ticks
curl -s http://localhost:8080/health | python3 -m json.tool
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

To undo a wedge manually before the watchdog fires: `kill -CONT "$PID"`.

## Note on `whatsapp_get_status` (hosted mcp-router)

The hosted router's `whatsapp_get_status` tool probes `http://localhost:8080`
from **its own** host. When the router runs remotely (e.g. Railway) that
`localhost` is the router's container, not the machine running this bridge, so it
reports `bridge_unreachable` even when the bridge is perfectly healthy. That is a
router-config concern (point its `bridgeUrl` at a reachable address), independent
of this local self-heal. Local clients (the stdio `whatsapp` MCP server, `curl`,
`node fetch`) reach the bridge normally.
