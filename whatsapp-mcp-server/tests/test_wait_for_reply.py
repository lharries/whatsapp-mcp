"""wait_for_reply tests: baseline semantics and the MCP-timeout cap.

Real temp SQLite database, no sleeping in the timeout paths (the cap is forced
to 0 so a timeout returns immediately).
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import whatsapp  # noqa: E402

LID = "212558418043069"
CHAT_JID = f"{LID}@lid"
OUTGOING = "2026-11-07 15:28:00+02:00"
REPLY_1 = "2026-11-07 15:29:06+02:00"
REPLY_2 = "2026-11-07 15:31:00+02:00"


class WaitForReplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        msg_db = os.path.join(self.tmp.name, "messages.db")
        conn = sqlite3.connect(msg_db)
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
                     (CHAT_JID, "Tysen", REPLY_2))
        rows = [
            ("m-out", CHAT_JID, LID, "yo", OUTGOING, 1, ""),
            ("m-in-1", CHAT_JID, LID, "yeah i know send money", REPLY_1, 0, ""),
            ("m-in-2", CHAT_JID, LID, "second later reply", REPLY_2, 0, ""),
        ]
        conn.executemany(
            "INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me, media_type) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()

        self._old_msg = whatsapp.MESSAGES_DB_PATH
        self._old_wa = whatsapp.WHATSAPP_DB_PATH
        self._old_cap = whatsapp.MAX_WAIT_SECONDS
        whatsapp.MESSAGES_DB_PATH = msg_db
        whatsapp.WHATSAPP_DB_PATH = os.path.join(self.tmp.name, "absent.db")

    def tearDown(self):
        whatsapp.MESSAGES_DB_PATH = self._old_msg
        whatsapp.WHATSAPP_DB_PATH = self._old_wa
        whatsapp.MAX_WAIT_SECONDS = self._old_cap
        self.tmp.cleanup()

    def test_already_received_reply_returns_immediately(self):
        # Baseline is our last message, so the reply that already arrived is
        # returned without waiting for a newer one.
        res = whatsapp.wait_for_reply(CHAT_JID, 0)
        self.assertEqual(res["status"], "received")
        self.assertEqual(res["content"], "yeah i know send money")
        self.assertEqual(res["next_after"], REPLY_1)

    def test_next_after_advances_to_the_following_reply(self):
        res = whatsapp.wait_for_reply(CHAT_JID, 0, after_timestamp=REPLY_1)
        self.assertEqual(res["status"], "received")
        self.assertEqual(res["content"], "second later reply")
        self.assertEqual(res["next_after"], REPLY_2)

    def test_timeout_after_the_last_reply_carries_the_baseline(self):
        res = whatsapp.wait_for_reply(CHAT_JID, 0, after_timestamp=REPLY_2)
        self.assertEqual(res["status"], "timeout")
        self.assertEqual(res["baseline_timestamp"], REPLY_2)

    def test_huge_timeout_is_capped(self):
        # With the cap forced to 0, a request for 9999s must still return at once.
        whatsapp.MAX_WAIT_SECONDS = 0
        res = whatsapp.wait_for_reply(CHAT_JID, 9999, after_timestamp=REPLY_2)
        self.assertEqual(res["status"], "timeout")

    def test_default_baseline_uses_our_last_message(self):
        # No after_timestamp: the baseline is the outgoing message, so both
        # replies are "after" it and the oldest one is returned.
        res = whatsapp.wait_for_reply(CHAT_JID, 0)
        self.assertEqual(res["id"], "m-in-1")


if __name__ == "__main__":
    unittest.main()
