"""Hardening tests: input guards, LIKE escaping, graceful degradation.

Real temp SQLite databases; no network.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import whatsapp  # noqa: E402

CHAT = "212558418043069@lid"


class HardeningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.msg_db = os.path.join(self.tmp.name, "messages.db")
        conn = sqlite3.connect(self.msg_db)
        conn.executescript(
            """
            CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP);
            CREATE TABLE messages (
                id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TIMESTAMP,
                is_from_me BOOLEAN, media_type TEXT, PRIMARY KEY (id, chat_jid)
            );
            """
        )
        conn.execute("INSERT INTO chats (jid, name, last_message_time) VALUES (?,?,?)",
                     (CHAT, "Tysen", "2026-11-07 16:00:00+02:00"))
        conn.execute("INSERT INTO chats (jid, name, last_message_time) VALUES (?,?,?)",
                     ("111@lid", "100% done", "2026-11-07 15:00:00+02:00"))
        # 300 rows so the limit clamp is observable.
        rows = [(f"m{i}", CHAT, "212558418043069",
                 "discount 50% off" if i % 10 == 0 else f"message number {i}",
                 f"2026-11-07 10:{i % 60:02d}:{i % 60:02d}+02:00", 0, "") for i in range(300)]
        conn.executemany(
            "INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me, media_type) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()

        self._old_msg = whatsapp.MESSAGES_DB_PATH
        self._old_wa = whatsapp.WHATSAPP_DB_PATH
        self._old_post = whatsapp.requests.post
        whatsapp.MESSAGES_DB_PATH = self.msg_db
        whatsapp.WHATSAPP_DB_PATH = os.path.join(self.tmp.name, "absent.db")

    def tearDown(self):
        whatsapp.MESSAGES_DB_PATH = self._old_msg
        whatsapp.WHATSAPP_DB_PATH = self._old_wa
        whatsapp.requests.post = self._old_post
        self.tmp.cleanup()

    def test_negative_limit_does_not_dump_everything(self):
        res = whatsapp.list_messages(chat_jid=CHAT, limit=-1)
        # Falls back to the default (20), never the whole 300-row history.
        self.assertEqual(len(res), 20)

    def test_zero_limit_does_not_dump_everything(self):
        res = whatsapp.list_messages(chat_jid=CHAT, limit=0)
        self.assertEqual(len(res), 20)

    def test_huge_limit_is_capped(self):
        res = whatsapp.list_messages(chat_jid=CHAT, limit=100000)
        self.assertEqual(len(res), whatsapp.MAX_LIMIT)

    def test_negative_page_clamps_to_zero(self):
        newest = whatsapp.list_messages(chat_jid=CHAT, limit=1)
        clamped = whatsapp.list_messages(chat_jid=CHAT, limit=1, page=-5)
        self.assertEqual(newest[0]["id"], clamped[0]["id"])

    def test_like_wildcard_in_query_is_literal(self):
        res = whatsapp.list_messages(chat_jid=CHAT, query="%", limit=200)
        # Only the 30 rows containing a literal '%', not all 300.
        self.assertEqual(len(res), 30)
        self.assertTrue(all("%" in r["content"] for r in res))

    def test_like_wildcard_in_chat_search_is_literal(self):
        res = whatsapp.list_chats(query="%")
        names = [c["name"] for c in res]
        self.assertIn("100% done", names)
        self.assertNotIn("Tysen", names)

    def test_search_contacts_limit_is_capped(self):
        # No contacts seeded; just prove the clamp path runs without error.
        self.assertEqual(whatsapp.search_contacts("x", limit=10 ** 6), [])

    def test_missing_db_degrades_gracefully(self):
        whatsapp.MESSAGES_DB_PATH = os.path.join(self.tmp.name, "nope.db")
        self.assertEqual(whatsapp.list_messages(chat_jid=CHAT), [])

    def test_message_context_clamps_window(self):
        res = whatsapp.get_message_context("m150", before=99999, after=99999)
        self.assertIsNotNone(res["target"])
        self.assertLessEqual(len(res["before"]), 50)
        self.assertLessEqual(len(res["after"]), 50)

    def test_unicode_and_emoji_round_trip(self):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["payload"] = json
            return type("R", (), {"status_code": 200, "json": staticmethod(lambda: {"success": True})})()

        whatsapp.requests.post = fake_post
        text = "hello 👋 ǁîb ge ra ǃgâi, 50% done ✓"
        whatsapp.send_message("+264817721286", text)
        self.assertEqual(captured["payload"]["message"], text)


if __name__ == "__main__":
    unittest.main()
