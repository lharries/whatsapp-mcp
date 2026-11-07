"""Recipient-resolution tests.

These build real (temp) SQLite databases with the same schemas and shapes the
live bridge writes, including a migrated-account row, and assert the resolver
sends to the phone-number JID rather than a stale LID.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import whatsapp  # noqa: E402

PN = "264817721286"
STALE_LID = "41635530444913"
CURRENT_LID = "212558418043069"
GROUP_JID = "120363000000000000@g.us"


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        wa_db = os.path.join(self.tmp.name, "whatsapp.db")
        msg_db = os.path.join(self.tmp.name, "messages.db")

        wa = sqlite3.connect(wa_db)
        wa.executescript(
            """
            CREATE TABLE whatsmeow_contacts (
                their_jid TEXT PRIMARY KEY,
                full_name TEXT,
                first_name TEXT,
                push_name TEXT
            );
            CREATE TABLE whatsmeow_lid_map (
                lid TEXT PRIMARY KEY,
                pn TEXT
            );
            """
        )
        # A contact whose cached LID is stale (he migrated accounts).
        wa.execute(
            "INSERT INTO whatsmeow_contacts (their_jid, full_name, first_name, push_name) VALUES (?,?,?,?)",
            (f"{PN}@s.whatsapp.net", "Tysen", "Tysen", "Tysen"),
        )
        wa.execute(
            "INSERT INTO whatsmeow_lid_map (lid, pn) VALUES (?,?)",
            (STALE_LID, PN),
        )
        wa.commit()
        wa.close()

        msg = sqlite3.connect(msg_db)
        msg.executescript(
            """
            CREATE TABLE chats (
                jid TEXT PRIMARY KEY,
                name TEXT,
                last_message_time TIMESTAMP
            );
            CREATE TABLE messages (
                id TEXT,
                chat_jid TEXT,
                sender TEXT,
                content TEXT,
                timestamp TIMESTAMP,
                is_from_me BOOLEAN,
                media_type TEXT,
                PRIMARY KEY (id, chat_jid)
            );
            """
        )
        msg.execute(
            "INSERT INTO chats (jid, name, last_message_time) VALUES (?,?,?)",
            (f"{STALE_LID}@lid", "Tysen", "2026-07-01 10:00:00"),
        )
        msg.commit()
        msg.close()

        self._old_wa = whatsapp.WHATSAPP_DB_PATH
        self._old_msg = whatsapp.MESSAGES_DB_PATH
        whatsapp.WHATSAPP_DB_PATH = wa_db
        whatsapp.MESSAGES_DB_PATH = msg_db

        self._old_post = whatsapp.requests.post
        self._old_get = whatsapp.requests.get

    def tearDown(self):
        whatsapp.WHATSAPP_DB_PATH = self._old_wa
        whatsapp.MESSAGES_DB_PATH = self._old_msg
        whatsapp.requests.post = self._old_post
        whatsapp.requests.get = self._old_get
        self.tmp.cleanup()

    def test_sender_name_resolves_a_bare_lid(self):
        # messages.sender stores the LID without the '@lid' suffix.
        self.assertEqual(whatsapp.get_sender_name(STALE_LID), "Tysen")

    def test_sender_name_resolves_a_lid_jid(self):
        self.assertEqual(whatsapp.get_sender_name(f"{STALE_LID}@lid"), "Tysen")

    def test_resolve_recipient_still_finds_both_ids_for_history(self):
        _, name, all_jids = whatsapp.resolve_recipient("Tysen")
        self.assertEqual(name, "Tysen")
        self.assertIn(f"{PN}@s.whatsapp.net", all_jids)
        self.assertIn(f"{STALE_LID}@lid", all_jids)

    def test_send_target_prefers_phone_number_for_name(self):
        jid, name = whatsapp.resolve_send_target("Tysen")
        self.assertEqual(jid, f"{PN}@s.whatsapp.net")
        self.assertEqual(name, "Tysen")

    def test_send_target_normalises_local_number(self):
        jid, _ = whatsapp.resolve_send_target("0817721286")
        self.assertEqual(jid, f"{PN}@s.whatsapp.net")

    def test_send_target_accepts_international_number(self):
        jid, _ = whatsapp.resolve_send_target("+264 81 772 1286")
        self.assertEqual(jid, f"{PN}@s.whatsapp.net")

    def test_send_target_reverse_maps_a_stale_lid_to_the_phone_number(self):
        jid, _ = whatsapp.resolve_send_target(f"{STALE_LID}@lid")
        self.assertEqual(jid, f"{PN}@s.whatsapp.net")

    def test_send_target_passes_through_group_jid(self):
        jid, _ = whatsapp.resolve_send_target(GROUP_JID)
        self.assertEqual(jid, GROUP_JID)

    def test_send_target_unresolvable_returns_none(self):
        jid, _ = whatsapp.resolve_send_target("")
        self.assertIsNone(jid)

    def test_send_message_posts_the_phone_jid(self):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse(200, {"success": True, "message": "ok"})

        whatsapp.requests.post = fake_post
        ok, msg = whatsapp.send_message("Tysen", "hello")
        self.assertTrue(ok, msg)
        self.assertTrue(captured["payload"]["recipient"].endswith("@s.whatsapp.net"))
        self.assertEqual(captured["payload"]["recipient"], f"{PN}@s.whatsapp.net")
        self.assertEqual(captured["payload"]["message"], "hello")

    def test_check_whatsapp_parses_bridge_response(self):
        def fake_get(url, params=None, timeout=None):
            self.assertEqual(params["phone"], PN)
            return FakeResponse(200, {"success": True, "results": [
                {"Query": PN, "JID": f"{CURRENT_LID}@lid", "IsIn": True,
                 "PhoneNumber": f"{PN}@s.whatsapp.net"}
            ]})

        whatsapp.requests.get = fake_get
        res = whatsapp.check_whatsapp("0817721286")
        self.assertTrue(res["on_whatsapp"])
        self.assertEqual(res["jid"], f"{CURRENT_LID}@lid")

    def test_resolve_contact_surfaces_current_account(self):
        def fake_get(url, params=None, timeout=None):
            return FakeResponse(200, {"success": True, "results": [
                {"Query": PN, "JID": f"{CURRENT_LID}@lid", "IsIn": True,
                 "PhoneNumber": f"{PN}@s.whatsapp.net"}
            ]})

        whatsapp.requests.get = fake_get
        res = whatsapp.resolve_contact("Tysen")
        self.assertEqual(res["phone_number"], PN)
        self.assertEqual(res["cached_lid"], STALE_LID)
        self.assertEqual(res["current_lid"], CURRENT_LID)
        self.assertTrue(res["on_whatsapp"])
        self.assertNotEqual(res["cached_lid"], res["current_lid"])


if __name__ == "__main__":
    unittest.main()
