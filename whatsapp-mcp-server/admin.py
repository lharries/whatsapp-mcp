"""Unfiltered chat lookups for building the whitelist.

These DELIBERATELY bypass the whitelist so you can discover the JIDs to allow.
They are used by the CLI and admin scripts only -- never exposed as MCP tools,
so an agent can never call them to enumerate your chats.
"""
import os
import sqlite3
from typing import List, Optional, Tuple

import whatsapp

Chat = Tuple[str, str, str]  # (jid, name, last_message_time)


def _db_path(db_path: Optional[str]) -> str:
    # Re-read the env here (not just whatsapp.MESSAGES_DB_PATH, which is fixed at
    # import) so tests and callers can point at a different DB after import.
    return db_path or os.environ.get("WHATSAPP_MESSAGES_DB", whatsapp.MESSAGES_DB_PATH)


def find_chats(query: Optional[str] = None, db_path: Optional[str] = None) -> List[Chat]:
    """All chats, or those whose name matches ``query`` (case-insensitive),
    most recently active first."""
    conn = sqlite3.connect(_db_path(db_path))
    try:
        sql = "SELECT jid, COALESCE(name, ''), COALESCE(last_message_time, '') FROM chats"
        params: tuple = ()
        if query:
            sql += " WHERE name LIKE ? COLLATE NOCASE"
            params = (f"%{query}%",)
        sql += " ORDER BY last_message_time DESC"
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def all_chats(db_path: Optional[str] = None) -> List[Chat]:
    return find_chats(None, db_path)
