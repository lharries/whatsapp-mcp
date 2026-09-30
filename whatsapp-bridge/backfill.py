#!/usr/bin/env python3
"""Pull older history for selected chats until a target date is reached.

Usage: python3 backfill.py <target-date YYYY-MM-DD> <chat_jid> [<chat_jid> ...]

Requires the bridge to be running on :8080. Each call to /api/backfill asks WhatsApp for
messages older than the oldest one stored for the chat; the bridge stores the reply in
store/messages.db, and this script keeps asking until the oldest stored message is on or
before the target date or the server stops returning older messages.
"""
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parent / "store" / "messages.db"
BRIDGE = "http://localhost:8080"


def oldest(chat):
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = db.execute(
        "SELECT min(timestamp), count(*) FROM messages WHERE chat_jid = ? AND id != ''", (chat,)
    ).fetchone()
    db.close()
    return (row[0] or ""), row[1]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    target, chats = sys.argv[1], sys.argv[2:]
    for chat in chats:
        stale = 0
        while True:
            before, n_before = oldest(chat)
            if before and before[:10] <= target:
                print(f"{chat}: reached {before[:10]} ({n_before} messages)")
                break
            url = BRIDGE + "/api/backfill?" + urllib.parse.urlencode({"chat": chat, "count": 200})
            try:
                with urllib.request.urlopen(url, timeout=90) as r:
                    json.loads(r.read())
            except Exception as e:
                print(f"{chat}: request failed: {e}")
                break
            time.sleep(12)  # give the phone time to answer and the bridge time to store the batch
            after, n_after = oldest(chat)
            print(f"{chat}: oldest {before[:19]} -> {after[:19]} (+{n_after - n_before} messages)", flush=True)
            if n_after == n_before:
                stale += 1
                if stale >= 2:
                    print(f"{chat}: no more history available (stopped at {after[:10]})")
                    break
            else:
                stale = 0


if __name__ == "__main__":
    main()
