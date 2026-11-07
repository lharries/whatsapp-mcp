"""Inbox/outbox, handled-state, accounts, and reply approval. Real temp DB."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import whatsapp  # noqa: E402

A = "111@lid"      # needs reply (last message incoming)
B = "222@lid"      # replied already (last message outgoing)
C = "333@lid"      # incoming but marked handled


class InboxOutboxTest(unittest.TestCase):
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
        conn.execute("INSERT INTO chats VALUES (?,?,?)", (A, "Alice", "2026-11-07 10:02:00+02:00"))
        conn.execute("INSERT INTO chats VALUES (?,?,?)", (B, "Bob", "2026-11-07 10:04:00+02:00"))
        conn.execute("INSERT INTO chats VALUES (?,?,?)", (C, "Cara", "2026-11-07 10:06:00+02:00"))
        conn.executemany(
            "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
            [
                ("m1", A, "111", "hey are you around?", "2026-11-07 10:00:00+02:00", 0, ""),
                ("m2", A, "999", "yes", "2026-11-07 10:01:00+02:00", 1, ""),
                ("m3", A, "111", "cool, quick question", "2026-11-07 10:02:00+02:00", 0, ""),
                ("m4", B, "222", "sent you the file", "2026-11-07 10:03:00+02:00", 0, ""),
                ("m5", B, "999", "got it thanks", "2026-11-07 10:04:00+02:00", 1, ""),
                ("m6", C, "333", "lol", "2026-11-07 10:06:00+02:00", 0, ""),
            ],
        )
        conn.commit()
        conn.close()

        self._old_msg = whatsapp.MESSAGES_DB_PATH
        self._old_wa = whatsapp.WHATSAPP_DB_PATH
        self._old_post = whatsapp.requests.post
        self._old_owner = os.environ.pop("WA_OWNER_JID", None)
        whatsapp.MESSAGES_DB_PATH = msg_db
        whatsapp.WHATSAPP_DB_PATH = os.path.join(self.tmp.name, "absent.db")

    def tearDown(self):
        whatsapp.MESSAGES_DB_PATH = self._old_msg
        whatsapp.WHATSAPP_DB_PATH = self._old_wa
        whatsapp.requests.post = self._old_post
        if self._old_owner is not None:
            os.environ["WA_OWNER_JID"] = self._old_owner
        else:
            os.environ.pop("WA_OWNER_JID", None)
        self.tmp.cleanup()

    def test_outbox_lists_only_unanswered_incoming(self):
        out = whatsapp.list_outbox()
        ids = {c["chat_jid"] for c in out}
        self.assertIn(A, ids)
        self.assertNotIn(B, ids)  # last message was ours
        self.assertIn(C, ids)     # still unanswered
        a = next(c for c in out if c["chat_jid"] == A)
        self.assertTrue(a["needs_reply"])
        self.assertEqual(a["last_message"], "cool, quick question")

    def test_inbox_reports_who_spoke_last(self):
        inbox = {c["chat_jid"]: c for c in whatsapp.list_inbox()}
        self.assertTrue(inbox[A]["needs_reply"])
        self.assertFalse(inbox[B]["needs_reply"])
        self.assertTrue(inbox[B]["last_from_me"])

    def test_mark_handled_removes_and_restores(self):
        whatsapp.mark_handled(C, True)
        self.assertNotIn(C, {c["chat_jid"] for c in whatsapp.list_outbox()})
        whatsapp.mark_handled(C, False)
        self.assertIn(C, {c["chat_jid"] for c in whatsapp.list_outbox()})

    def test_get_thread_returns_messages(self):
        thread = whatsapp.get_thread(A, limit=10)
        self.assertEqual(len(thread), 3)
        self.assertEqual(thread[0]["content"], "cool, quick question")

    def test_list_accounts_default(self):
        self.assertEqual(whatsapp.list_accounts()[0]["account"], "main")

    def test_use_account_unknown_raises(self):
        with self.assertRaises(ValueError):
            whatsapp.use_account("does-not-exist")

    def test_request_reply_approval_without_owner(self):
        self.assertEqual(whatsapp.request_reply_approval("Tysen", "hi")["sent"], False)

    def test_request_reply_approval_sends_to_owner(self):
        os.environ["WA_OWNER_JID"] = "264817721286"
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["payload"] = json
            return type("R", (), {"status_code": 200, "json": staticmethod(lambda: {"success": True})})()

        whatsapp.requests.post = fake_post
        res = whatsapp.request_reply_approval("Tysen", "yes let's meet at 3")
        self.assertTrue(res["sent"])
        self.assertEqual(captured["payload"]["recipient"], "264817721286@s.whatsapp.net")
        self.assertIn("yes let's meet at 3", captured["payload"]["message"])


if __name__ == "__main__":
    unittest.main()
