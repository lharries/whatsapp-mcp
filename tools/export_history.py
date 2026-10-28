#!/usr/bin/env python3
"""Export the WhatsApp MCP bridge's local SQLite history to private CSV/JSONL files.

This script is read-only: it does not alter the WhatsApp database or send messages.
Run it only against a database for an account you are authorized to access.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


MESSAGE_COLUMNS = (
    "id", "chat_jid", "sender", "content", "timestamp",
    "is_from_me", "media_type", "filename", "url", "file_length",
)
CHAT_COLUMNS = ("jid", "name", "last_message_time")


def read_rows(db_path: Path, table: str, columns: tuple[str, ...]) -> list[dict]:
    # URI-encode the path and open SQLite in read-only mode.
    uri = "file:" + quote(str(db_path.resolve()), safe="/:") + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not present:
            raise RuntimeError(f"Table {table!r} is missing from {db_path}")
        selected = [column for column in columns if column in present]
        query = f"SELECT {', '.join(selected)} FROM {table}"
        if table == "messages" and "timestamp" in present:
            query += " ORDER BY timestamp, chat_jid, id"
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]


def write_csv(path: Path, rows: list[dict], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [column for column in columns if rows and column in rows[0]]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=Path("whatsapp-bridge/store/messages.db"),
        help="Path to the already-synced messages.db (default: %(default)s)",
    )
    parser.add_argument(
        "--out", type=Path,
        default=Path("private-export") / datetime.now().strftime("%Y%m%d-%H%M%S"),
        help="Output directory (default: a timestamped private-export folder)",
    )
    args = parser.parse_args()

    if not args.db.is_file():
        parser.error(f"Database not found: {args.db}. Start/link the bridge and let it sync first.")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error(f"Output directory is not empty: {args.out}")

    chats = read_rows(args.db, "chats", CHAT_COLUMNS)
    messages = read_rows(args.db, "messages", MESSAGE_COLUMNS)
    args.out.mkdir(parents=True, exist_ok=True)

    write_csv(args.out / "chats.csv", chats, CHAT_COLUMNS)
    write_csv(args.out / "messages.csv", messages, MESSAGE_COLUMNS)
    with (args.out / "messages.jsonl").open("w", encoding="utf-8") as handle:
        for row in messages:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    summary = {
        "database": str(args.db),
        "exported_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "chat_count": len(chats),
        "message_count": len(messages),
        "note": "Export contains only records present in the local bridge database; it cannot recover messages that WhatsApp has not synced to this database.",
    }
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    print(f"Private export written to: {args.out.resolve()}")
    print("Keep this folder private. Do not commit or upload it to a public repository.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
