#!/usr/bin/env python3
"""Export every chat of an account from the bridge SQLite DB to text + JSONL files.

Usage: export_chats.py <account>
Output: exports/<account>/chats/<name>__<jid>.txt, exports/<account>/all_messages.jsonl, exports/<account>/index.md
Re-runnable: files are rewritten from the current DB state.
"""
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE).strip(" ._")
    return name[:80] or "chat"


def fmt_ts(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return ts


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    account = sys.argv[1]
    db_path = ROOT / "accounts" / account / "store" / "messages.db"
    if not db_path.exists():
        print(f"no database for account {account!r}: {db_path}")
        return 1

    out = ROOT / "exports" / account
    chats_dir = out / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    contacts = {r["jid"].split("@")[0]: r["name"] for r in con.execute("SELECT jid, name FROM chats WHERE name != ''")}

    def sender_label(sender: str, is_from_me: bool) -> str:
        if is_from_me:
            return "Yo"
        user = sender.split("@")[0]
        return contacts.get(user, user)

    chats = con.execute(
        "SELECT c.jid, c.name, c.last_message_time, COUNT(m.id) AS n, MIN(m.timestamp) AS first_ts "
        "FROM chats c LEFT JOIN messages m ON m.chat_jid = c.jid "
        "GROUP BY c.jid ORDER BY c.last_message_time DESC"
    ).fetchall()

    index_rows = []
    total = 0
    with (out / "all_messages.jsonl").open("w", encoding="utf-8") as jsonl:
        for chat in chats:
            if chat["n"] == 0:
                continue
            rows = con.execute(
                "SELECT id, sender, content, timestamp, is_from_me, media_type, filename "
                "FROM messages WHERE chat_jid = ? ORDER BY timestamp ASC",
                (chat["jid"],),
            ).fetchall()
            fname = f"{safe_name(chat['name'] or chat['jid'])}__{chat['jid'].replace('@', '_at_')}.txt"
            with (chats_dir / fname).open("w", encoding="utf-8") as f:
                f.write(f"# {chat['name'] or chat['jid']}\n# JID: {chat['jid']}\n# Mensajes: {len(rows)}\n\n")
                for m in rows:
                    who = sender_label(m["sender"], bool(m["is_from_me"]))
                    body = m["content"] or ""
                    if m["media_type"]:
                        tag = f"<{m['media_type']}{': ' + m['filename'] if m['filename'] else ''}>"
                        body = f"{tag} {body}".strip()
                    f.write(f"[{fmt_ts(m['timestamp'])}] {who}: {body}\n")
                    jsonl.write(json.dumps({
                        "chat_jid": chat["jid"], "chat_name": chat["name"], "id": m["id"],
                        "timestamp": m["timestamp"], "sender": m["sender"], "from_me": bool(m["is_from_me"]),
                        "content": m["content"], "media_type": m["media_type"], "filename": m["filename"],
                    }, ensure_ascii=False) + "\n")
            total += len(rows)
            index_rows.append((chat["name"] or chat["jid"], chat["jid"], len(rows), chat["first_ts"], chat["last_message_time"], fname))

    with (out / "index.md").open("w", encoding="utf-8") as f:
        f.write(f"# Export WhatsApp — cuenta `{account}`\n\n")
        f.write(f"Generado: {datetime.now():%Y-%m-%d %H:%M}. Chats: {len(index_rows)}. Mensajes: {total}.\n\n")
        f.write("| Chat | Mensajes | Desde | Hasta | Archivo |\n|---|---:|---|---|---|\n")
        for name, jid, n, first, last, fname in index_rows:
            f.write(f"| {name} | {n} | {fmt_ts(first or '')} | {fmt_ts(last or '')} | chats/{fname} |\n")

    print(f"{account}: {len(index_rows)} chats, {total} mensajes -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
