#!/bin/bash
# Remove the WhatsApp bridge self-healing launchd service (bridge + watchdog).
set -euo pipefail

LABEL="com.kodi.whatsapp-bridge"
WATCHDOG_LABEL="${LABEL}-watchdog"
LA="$HOME/Library/LaunchAgents"

for lbl in "$WATCHDOG_LABEL" "$LABEL"; do
  if [ -f "$LA/$lbl.plist" ]; then
    echo "unloading + removing $lbl"
    launchctl unload "$LA/$lbl.plist" 2>/dev/null || true
    rm -f "$LA/$lbl.plist"
  fi
done

echo "Removed. The bridge will no longer auto-start or self-heal."
echo "(The bridge binary, store/, and logs are left untouched.)"
