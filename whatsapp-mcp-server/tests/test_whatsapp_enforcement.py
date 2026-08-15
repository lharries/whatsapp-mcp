"""Integration tests: the whitelist must gate every whatsapp.py data path.

Uses a synthetic SQLite database with fabricated JIDs and message content —
no real WhatsApp data. Whitelisted: Alice (individual) + a group. Bob is NOT
whitelisted; his messages/chat must never surface, and sends to him must be
refused before any network call.
"""
import json
import sqlite3

import pytest

import whatsapp

ALICE = "111111@s.whatsapp.net"
BOB = "222222@s.whatsapp.net"
GROUP = "120363111111@g.us"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Synthetic messages.db pointed to by whatsapp.MESSAGES_DB_PATH."""
    path = tmp_path / "messages.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP);
        CREATE TABLE messages (
            id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TIMESTAMP,
            is_from_me BOOLEAN, media_type TEXT, PRIMARY KEY (id, chat_jid)
        );
        """
    )
    chats = [
        (ALICE, "Alice", "2026-01-01T10:00:00"),
        (BOB, "Bob", "2026-01-01T11:00:00"),
        (GROUP, "Family", "2026-01-01T12:00:00"),
    ]
    msgs = [
        ("m_alice", ALICE, ALICE, "ALICE_SECRET", "2026-01-01T10:00:00", 0, None),
        ("m_bob", BOB, BOB, "BOB_SECRET", "2026-01-01T11:00:00", 0, None),
        ("m_group", GROUP, ALICE, "GROUP_SECRET", "2026-01-01T12:00:00", 0, "image"),
    ]
    conn.executemany("INSERT INTO chats VALUES (?,?,?)", chats)
    conn.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", msgs)
    conn.commit()
    conn.close()
    monkeypatch.setattr(whatsapp, "MESSAGES_DB_PATH", str(path))
    return path


@pytest.fixture
def whitelist_alice_and_group(tmp_path, monkeypatch):
    wl = tmp_path / "whitelist.json"
    wl.write_text(json.dumps({"allowed_jids": [ALICE, GROUP]}))
    monkeypatch.setenv("WHATSAPP_WHITELIST_PATH", str(wl))


@pytest.fixture
def capture_post(monkeypatch):
    """Replace requests.post; record calls so we can assert no network for blocked sends."""
    calls = []

    class FakeResp:
        status_code = 200

        def json(self):
            return {"success": True, "message": "sent"}

    def fake_post(url, json=None, **kwargs):
        calls.append({"url": url, "json": json})
        return FakeResp()

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    return calls


pytestmark = pytest.mark.usefixtures("db", "whitelist_alice_and_group")


# --- reads: no leakage of non-whitelisted chats ---------------------------

def test_list_chats_excludes_non_whitelisted():
    jids = {c.jid for c in whatsapp.list_chats()}
    assert jids == {ALICE, GROUP}


def test_list_messages_never_contains_non_whitelisted_content():
    out = whatsapp.list_messages(include_context=False)
    assert "ALICE_SECRET" in out
    assert "BOB_SECRET" not in out


def test_search_contacts_excludes_non_whitelisted():
    jids = {c.jid for c in whatsapp.search_contacts("")}
    assert BOB not in jids
    assert ALICE in jids


def test_get_chat_returns_none_for_non_whitelisted():
    assert whatsapp.get_chat(BOB) is None
    assert whatsapp.get_chat(ALICE) is not None


def test_get_message_context_hidden_for_non_whitelisted():
    with pytest.raises(ValueError):
        whatsapp.get_message_context("m_bob")
    ctx = whatsapp.get_message_context("m_alice")
    assert ctx.message.content == "ALICE_SECRET"


def test_get_last_interaction_none_for_non_whitelisted():
    assert whatsapp.get_last_interaction(BOB) is None
    assert whatsapp.get_last_interaction(ALICE) is not None


def test_get_direct_chat_by_contact_none_for_non_whitelisted():
    assert whatsapp.get_direct_chat_by_contact("222222") is None
    assert whatsapp.get_direct_chat_by_contact("111111") is not None


def test_get_contact_chats_excludes_non_whitelisted():
    assert whatsapp.get_contact_chats(BOB) == []


# --- sends: refuse non-whitelisted BEFORE any network call ----------------

def test_send_message_blocked_for_non_whitelisted(capture_post):
    ok, _ = whatsapp.send_message(BOB, "hi")
    assert ok is False
    assert capture_post == []  # no network call at all


def test_send_message_allowed_for_whitelisted(capture_post):
    ok, _ = whatsapp.send_message(ALICE, "hi")
    assert ok is True
    assert len(capture_post) == 1


def test_send_message_allowed_for_whitelisted_group(capture_post):
    ok, _ = whatsapp.send_message(GROUP, "hi")
    assert ok is True
    assert len(capture_post) == 1


def test_send_file_blocked_for_non_whitelisted(capture_post, tmp_path):
    media = tmp_path / "photo.jpg"
    media.write_bytes(b"fake")
    ok, _ = whatsapp.send_file(BOB, str(media))
    assert ok is False
    assert capture_post == []


def test_send_audio_message_blocked_for_non_whitelisted(capture_post, tmp_path):
    media = tmp_path / "voice.ogg"
    media.write_bytes(b"fake")
    ok, _ = whatsapp.send_audio_message(BOB, str(media))
    assert ok is False
    assert capture_post == []


def test_download_media_blocked_for_non_whitelisted(capture_post):
    assert whatsapp.download_media("m_bob", BOB) is None
    assert capture_post == []


def test_fail_closed_when_whitelist_file_missing(monkeypatch, capture_post, tmp_path):
    # Override the module's whitelist fixture with a non-existent path.
    monkeypatch.setenv("WHATSAPP_WHITELIST_PATH", str(tmp_path / "nope.json"))
    assert whatsapp.list_chats() == []           # reads expose nothing
    assert "ALICE_SECRET" not in whatsapp.list_messages(include_context=False)
    ok, _ = whatsapp.send_message(ALICE, "hi")   # even a normally-allowed JID
    assert ok is False
    assert capture_post == []
