#!/usr/bin/env bash
# backfill.sh <account> [start|status|stop]   — on-demand history backfill via the bridge API
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
name="${1:?account}"; cmd="${2:-status}"
port="$(awk -v n="$name" '$1==n {print $2}' "$ROOT/accounts.conf")"
[ -n "$port" ] || { echo "unknown account $name"; exit 1; }
case "$cmd" in
  start)  curl -s -X POST "localhost:$port/api/backfill" -d '{"batch":50}'; echo ;;
  stop)   curl -s -X POST "localhost:$port/api/backfill/stop"; echo ;;
  status) curl -s "localhost:$port/api/backfill/status" | python3 "$ROOT/scripts/backfill_status.py" ;;
  *) echo "usage: backfill.sh <account> start|status|stop"; exit 1 ;;
esac
