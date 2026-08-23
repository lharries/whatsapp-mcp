"""Reproduce MCP HTTP 1.12 failures: SQL swallow + dataclass payloads."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import whatsapp  # noqa: E402
from whatsapp import Chat, Contact, Message  # noqa: E402


SCHEMA_CHATS = """
CREATE TABLE chats (
    jid TEXT PRIMARY KEY,
    name TEXT,
    last_message_time TIMESTAMP
)
"""
SCHEMA_MESSAGES = """
CREATE TABLE messages (
    id TEXT,
    chat_jid TEXT,
    sender TEXT,
    content TEXT,
    timestamp TIMESTAMP,
    is_from_me BOOLEAN,
    media_type TEXT,
    filename TEXT,
    url TEXT,
    media_key BLOB,
    file_sha256 BLOB,
    file_enc_sha256 BLOB,
    file_length INTEGER,
    message_proto BLOB,
    PRIMARY KEY (id, chat_jid)
)
"""


class WhatsAppQueryAndSerializeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "messages.db"
        conn = sqlite3.connect(self.db)
        conn.execute(SCHEMA_CHATS)
        conn.execute(SCHEMA_MESSAGES)
        ts = "2026-08-01T12:00:00"
        conn.execute(
            "INSERT INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)",
            ("111@s.whatsapp.net", "Alice Test", ts),
        )
        conn.execute(
            "INSERT INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)",
            ("999@g.us", "Group Test", ts),
        )
        conn.execute(
            """INSERT INTO messages
               (id, chat_jid, sender, content, timestamp, is_from_me)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("mid1", "111@s.whatsapp.net", "111@s.whatsapp.net", "hello", ts, 0),
        )
        conn.commit()
        conn.close()
        self._old_path = whatsapp.MESSAGES_DB_PATH
        whatsapp.MESSAGES_DB_PATH = str(self.db)

    def tearDown(self):
        whatsapp.MESSAGES_DB_PATH = self._old_path
        self.tmp.cleanup()

    def test_list_chats_without_last_message_does_not_swallow_sql(self):
        chats = whatsapp.list_chats(include_last_message=False, limit=10)
        self.assertEqual(len(chats), 2)
        names = {c.name for c in chats}
        self.assertIn("Alice Test", names)
        self.assertIn("Group Test", names)

    def test_list_chats_with_last_message(self):
        chats = whatsapp.list_chats(include_last_message=True, limit=10)
        alice = next(c for c in chats if c.name == "Alice Test")
        self.assertEqual(alice.last_message, "hello")

    def test_search_contacts_skips_groups(self):
        found = whatsapp.search_contacts("Alice")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, "Alice Test")
        self.assertTrue(found[0].jid.endswith("@s.whatsapp.net"))

    def test_jsonable_contact_is_plain_dict(self):
        c = Contact(phone_number="111", name="Alice Test", jid="111@s.whatsapp.net")
        payload = whatsapp.to_jsonable(c)
        self.assertIsInstance(payload, dict)
        json.dumps(payload)
        self.assertEqual(payload["name"], "Alice Test")
        self.assertEqual(payload["jid"], "111@s.whatsapp.net")

    def test_jsonable_chat_datetime_is_isoformat(self):
        ts = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        chat = Chat(jid="111@s.whatsapp.net", name="Alice Test", last_message_time=ts)
        payload = whatsapp.to_jsonable(chat)
        self.assertIsInstance(payload["last_message_time"], str)
        self.assertTrue(payload["last_message_time"].startswith("2026-08-01"))

    def test_jsonable_list_of_messages(self):
        msg = Message(
            timestamp=datetime(2026, 8, 1, 12, 0),
            sender="111@s.whatsapp.net",
            content="hello",
            is_from_me=False,
            chat_jid="111@s.whatsapp.net",
            id="mid1",
        )
        payload = whatsapp.to_jsonable([msg])
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["content"], "hello")
        self.assertIsInstance(payload[0]["timestamp"], str)

    def test_pydantic_accepts_serialized_contact_not_dataclass(self):
        from pydantic import TypeAdapter, ValidationError

        c = Contact(phone_number="111", name="Alice Test", jid="111@s.whatsapp.net")
        adapter = TypeAdapter(list[dict])
        adapter.validate_python([whatsapp.to_jsonable(c)])
        with self.assertRaises(ValidationError):
            adapter.validate_python([c])


if __name__ == "__main__":
    unittest.main()
