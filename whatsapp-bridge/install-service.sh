#!/bin/bash
# Install the WhatsApp bridge as a self-healing launchd service — portable.
#
# Bundled with the app: run this once after downloading/building. It works from
# WHEREVER the app lives (no hardcoded paths or usernames) — it derives every
# path from this script's own location and the current user.
#
# What it installs:
#   1. com.kodi.whatsapp-bridge          — the bridge (KeepAlive + ThrottleInterval)
#   2. com.kodi.whatsapp-bridge-watchdog — probes /health every 15s and
#      `launchctl kickstart -k`s the bridge if it wedges (port-held-but-dead)
#
# Usage:  ./install-service.sh
# Undo:   ./uninstall-service.sh
set -euo pipefail

BRIDGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.kodi.whatsapp-bridge"
WATCHDOG_LABEL="${LABEL}-watchdog"
LA="$HOME/Library/LaunchAgents"
BIN="$BRIDGE_DIR/whatsapp-bridge"
WATCHDOG="$BRIDGE_DIR/watchdog.sh"

echo "WhatsApp bridge self-heal installer"
echo "  app dir : $BRIDGE_DIR"
echo "  user    : $(id -un) (uid $(id -u))"

# 1. Make sure the binary exists (build it if Go is available).
if [ ! -x "$BIN" ]; then
  if command -v go >/dev/null 2>&1; then
    echo "  binary  : not found — building with go…"
    ( cd "$BRIDGE_DIR" && go build -o whatsapp-bridge . )
  else
    echo "ERROR: $BIN is missing and Go isn't installed to build it." >&2
    echo "       Build it on a machine with Go, or ship the prebuilt binary." >&2
    exit 1
  fi
fi
chmod +x "$WATCHDOG" "$BIN"
mkdir -p "$LA"

# 2. Generate the bridge plist (paths resolved for THIS install).
cat > "$LA/$LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$BIN</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$BRIDGE_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>/tmp/whatsapp-bridge.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/whatsapp-bridge.err</string>
</dict>
</plist>
PLIST

# 3. Generate the watchdog plist.
cat > "$LA/$WATCHDOG_LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$WATCHDOG_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$WATCHDOG</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>15</integer>
    <key>StandardOutPath</key>
    <string>/tmp/whatsapp-bridge-watchdog.out</string>
    <key>StandardErrorPath</key>
    <string>/tmp/whatsapp-bridge-watchdog.err</string>
</dict>
</plist>
PLIST

# 4. (Re)load both agents.
echo "  loading launchd agents…"
launchctl unload "$LA/$LABEL.plist" 2>/dev/null || true
launchctl load   "$LA/$LABEL.plist"
launchctl unload "$LA/$WATCHDOG_LABEL.plist" 2>/dev/null || true
launchctl load   "$LA/$WATCHDOG_LABEL.plist"

# 5. Verify the bridge comes up healthy.
echo -n "  waiting for /health "
ok=""
for _ in $(seq 1 15); do
  code=$(curl -s -m4 -o /dev/null -w '%{http_code}' http://localhost:8080/health 2>/dev/null || echo 000)
  if [ "$code" = "200" ]; then ok=1; echo " ✓ 200"; break; fi
  echo -n "."
  sleep 2
done
if [ -z "$ok" ]; then
  echo " ✗"
  echo "Bridge did not report healthy. Check /tmp/whatsapp-bridge.err and /tmp/whatsapp-bridge.log" >&2
  exit 1
fi

echo
echo "Installed. The bridge now self-heals: if it wedges, the watchdog restarts it within ~30s."
echo "  health   : curl -s localhost:8080/health"
echo "  watchdog : tail -f /tmp/whatsapp-bridge-watchdog.log"
echo "  uninstall: $BRIDGE_DIR/uninstall-service.sh"
