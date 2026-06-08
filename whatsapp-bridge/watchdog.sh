#!/bin/bash
# WhatsApp bridge watchdog.
#
# The bridge can wedge in a way plain launchd KeepAlive cannot see: the process
# stays ALIVE and keeps the TCP port bound, but the HTTP server stops answering
# ("port held but socket dead"). KeepAlive only restarts on process *exit*, so a
# wedged-but-alive bridge sits there dead until someone relaunches it by hand.
#
# This script is run periodically by com.kodi.whatsapp-bridge-watchdog.plist.
# It probes the REAL /health endpoint (which proves the server is serving, not
# just holding the port). After THRESHOLD consecutive failures it force-restarts
# the bridge with `launchctl kickstart -k`, which SIGKILLs the wedged process
# (freeing the port) and relaunches it.
#
# No secrets live here. The probe is localhost-only. Safe to commit.

set -u

LABEL="com.kodi.whatsapp-bridge"
HEALTH_URL="http://localhost:8080/health"
STATE_FILE="/tmp/whatsapp-bridge-watchdog.fails"
LOG_FILE="/tmp/whatsapp-bridge-watchdog.log"
THRESHOLD=2          # consecutive failures before we force-restart
CURL_TIMEOUT=5       # seconds to wait for /health before calling it dead

ts()  { date '+%Y-%m-%dT%H:%M:%S%z'; }
logline() { echo "$(ts) $*" >> "$LOG_FILE"; }

# Probe the health endpoint. A wedged bridge makes this hang, so the timeout is
# what actually detects the dead socket.
code=$(curl -s -m "$CURL_TIMEOUT" -o /dev/null -w '%{http_code}' "$HEALTH_URL" 2>/dev/null || echo 000)

if [ "$code" = "200" ]; then
    # Healthy. Clear any failure streak.
    if [ -f "$STATE_FILE" ]; then
        rm -f "$STATE_FILE"
        logline "recovered: /health=200, failure counter cleared"
    fi
    exit 0
fi

# Unhealthy. Bump the consecutive-failure counter.
fails=0
[ -f "$STATE_FILE" ] && fails=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
case "$fails" in ''|*[!0-9]*) fails=0 ;; esac
fails=$((fails + 1))
echo "$fails" > "$STATE_FILE"

# Explicitly classify the dead-socket-with-port-held case: health is failing yet
# something is still LISTENing on 8080. That is precisely the wedge a kickstart
# fixes (and that plain KeepAlive never would).
port_state="port-free"
if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
    port_state="port-HELD-but-dead"
fi
logline "unhealthy: /health=$code ($port_state) consecutive_failures=$fails/$THRESHOLD"

if [ "$fails" -ge "$THRESHOLD" ]; then
    logline "force-restarting $LABEL via launchctl kickstart -k ($port_state)"
    launchctl kickstart -k "gui/$(id -u)/$LABEL" >> "$LOG_FILE" 2>&1
    # Reset the streak so the bridge gets a full grace window to come back up
    # before we would ever consider kicking it again (no kick-storms).
    rm -f "$STATE_FILE"
fi

exit 0
