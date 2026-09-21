#!/usr/bin/env bash
# Manage one WhatsApp bridge per account.
# accounts.conf lines: <name> <port>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$ROOT/accounts.conf"
BIN="$ROOT/bin/whatsapp-bridge"

usage() {
  cat <<USAGE
Usage: wa.sh <command> [args]
  pair   <name> <phone>   start bridge and print an 8-char pairing code (first login)
  start  <name>           start bridge in background (already-paired account)
  start-all               start every account in accounts.conf
  stop   <name> | stop-all
  status                  show running state + API health per account
  logs   <name> [n]       tail bridge log
USAGE
  exit 1
}

port_of() { awk -v n="$1" '$1==n {print $2}' "$CONF"; }
names()   { awk 'NF && $1 !~ /^#/ {print $1}' "$CONF"; }

is_running() {
  local pidf="$ROOT/accounts/$1/bridge.pid"
  [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null
}

start_one() {
  local name="$1" phone="${2:-}"
  local port; port="$(port_of "$name")"
  [ -n "$port" ] || { echo "unknown account '$name' (not in accounts.conf)"; exit 1; }
  local dir="$ROOT/accounts/$name"
  mkdir -p "$dir/store"
  if is_running "$name"; then echo "$name already running (pid $(cat "$dir/bridge.pid"))"; return; fi
  (
    cd "$dir"
    export WHATSAPP_PORT="$port"
    [ -n "$phone" ] && export WHATSAPP_PAIR_PHONE="$phone"
    nohup "$BIN" >"$dir/bridge.log" 2>&1 &
    echo $! >"$dir/bridge.pid"
  )
  echo "$name started on port $port (pid $(cat "$dir/bridge.pid"))"
}

stop_one() {
  local name="$1" pidf="$ROOT/accounts/$1/bridge.pid"
  if is_running "$name"; then kill "$(cat "$pidf")" && echo "$name stopped"; else echo "$name not running"; fi
  rm -f "$pidf"
}

cmd="${1:-}"; shift || true
case "$cmd" in
  pair)
    [ $# -eq 2 ] || usage
    name="$1"; phone="$(echo "$2" | tr -cd '0-9')"
    rm -f "$ROOT/accounts/$name/store/pair_code.txt"
    start_one "$name" "$phone"
    echo "waiting for pairing code..."
    for _ in $(seq 1 30); do
      f="$ROOT/accounts/$name/store/pair_code.txt"
      if [ -f "$f" ]; then echo; echo "PAIRING CODE ($name / +$phone): $(cat "$f")"; echo; exit 0; fi
      if ! is_running "$name"; then echo "bridge exited:"; tail -20 "$ROOT/accounts/$name/bridge.log"; exit 1; fi
      sleep 1
    done
    echo "no pairing code after 30s, log:"; tail -20 "$ROOT/accounts/$name/bridge.log"; exit 1 ;;
  start)     [ $# -eq 1 ] || usage; start_one "$1" ;;
  start-all) for n in $(names); do start_one "$n"; done ;;
  stop)      [ $# -eq 1 ] || usage; stop_one "$1" ;;
  stop-all)  for n in $(names); do stop_one "$n"; done ;;
  status)
    for n in $(names); do
      port="$(port_of "$n")"
      if is_running "$n"; then
        if curl -sf -m 2 -o /dev/null -X POST "http://localhost:$port/api/send" -d '{}' 2>/dev/null || [ "$(curl -s -m 2 -o /dev/null -w '%{http_code}' -X POST "http://localhost:$port/api/send" -d '{}')" != "000" ]; then api="api up"; else api="api DOWN"; fi
        echo "$n  port $port  running (pid $(cat "$ROOT/accounts/$n/bridge.pid"))  $api"
      else
        echo "$n  port $port  stopped"
      fi
    done ;;
  logs)      [ $# -ge 1 ] || usage; tail -n "${2:-40}" "$ROOT/accounts/$1/bridge.log" ;;
  *) usage ;;
esac
