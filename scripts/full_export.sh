#!/usr/bin/env bash
# full_export.sh <account>
# Exports everything the phone will give for one account:
#   1. waits for the initial history sync to settle
#   2. runs the on-demand backfill over every chat until the phone has nothing older
#   3. merges any previous store backups (accounts/<name>/store.bak-*) into the DB
#   4. writes exports/<account>/ (one .txt per chat, all_messages.jsonl, index.md)
# Re-runnable; the bridge for the account must be running and paired.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
name="${1:?account}"
port="$(awk -v n="$name" '$1==n {print $2}' "$ROOT/accounts.conf")"
[ -n "$port" ] || { echo "unknown account $name"; exit 1; }
dir="$ROOT/accounts/$name"
db="$dir/store/messages.db"
log="$dir/bridge.log"

count() { sqlite3 "$db" "select count(*) from messages" 2>/dev/null || echo 0; }
oldest() { sqlite3 "$db" "select min(timestamp) from messages" 2>/dev/null; }
say() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*"; }

curl -sf -m 3 "localhost:$port/api/backfill/status" >/dev/null || { echo "bridge for $name not reachable on port $port (scripts/wa.sh start $name)"; exit 1; }

say "1/4 waiting for initial history sync to settle (no new messages for 2 min)..."
last="$(count)"; idle=0
while [ "$idle" -lt 4 ]; do
  sleep 30
  now="$(count)"
  if [ "$now" = "$last" ]; then idle=$((idle+1)); else idle=0; fi
  last="$now"
  say "   messages: $now  oldest: $(oldest)"
done

say "2/4 backfill: asking the phone for older messages, chat by chat..."
if ! curl -s "localhost:$port/api/backfill/status" | grep -q '"running":true'; then
  curl -s -X POST "localhost:$port/api/backfill" -d '{"batch":50}' >/dev/null
fi
while curl -s "localhost:$port/api/backfill/status" | grep -q '"running":true'; do
  sleep 60
  "$ROOT/scripts/backfill.sh" "$name" status | head -1 | sed 's/^/   /'
done
"$ROOT/scripts/backfill.sh" "$name" status | tail -3 | sed 's/^/   /'

say "3/4 merging previous store backups (if any)..."
for bak in "$dir"/store.bak-*/messages.db; do
  [ -f "$bak" ] || continue
  before="$(count)"
  sqlite3 "$db" "ATTACH '$bak' AS old;
    INSERT OR IGNORE INTO chats SELECT * FROM old.chats;
    INSERT OR IGNORE INTO messages SELECT * FROM old.messages;
    DETACH old;"
  say "   merged $(basename "$(dirname "$bak")"): +$(( $(count) - before )) messages"
done

say "4/4 exporting..."
python3 "$ROOT/scripts/export_chats.py" "$name"
say "done. total messages: $(count), oldest: $(oldest)"
