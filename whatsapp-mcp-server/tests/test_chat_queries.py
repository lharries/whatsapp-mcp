"""Regression tests for list_chats / get_chat and the include_last_message flag.

Uses a synthetic SQLite database with fabricated JIDs and message content.
"""
import sqlite3

import pytest

import whatsapp

ALICE = "111111@s.whatsapp.net"
GROUP = "120363111111@g.us"


@pytest.fixture(autouse=True)
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
    conn.executemany(
        "INSERT INTO chats VALUES (?,?,?)",
        [
            (ALICE, "Alice", "2026-01-01T10:00:00"),
            (GROUP, "Hiking Group", "2026-01-01T12:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
        [
            ("m_alice", ALICE, ALICE, "hello there", "2026-01-01T10:00:00", 0, None),
            ("m_group", GROUP, ALICE, "see you sunday", "2026-01-01T12:00:00", 0, None),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(whatsapp, "MESSAGES_DB_PATH", str(path))
    return path


# --- list_chats -----------------------------------------------------------

def test_list_chats_with_last_message_includes_content():
    chats = whatsapp.list_chats(include_last_message=True)
    assert {c.jid for c in chats} == {ALICE, GROUP}
    assert {c.last_message for c in chats} == {"hello there", "see you sunday"}


def test_list_chats_without_last_message_still_returns_chats():
    chats = whatsapp.list_chats(include_last_message=False)
    assert {c.jid for c in chats} == {ALICE, GROUP}
    assert all(c.last_message is None for c in chats)


def test_list_chats_returns_same_chats_regardless_of_include_last_message():
    with_msg = [c.jid for c in whatsapp.list_chats(include_last_message=True)]
    without = [c.jid for c in whatsapp.list_chats(include_last_message=False)]
    assert with_msg == without


# --- get_chat -------------------------------------------------------------

def test_get_chat_with_last_message_includes_content():
    chat = whatsapp.get_chat(ALICE, include_last_message=True)
    assert chat is not None
    assert chat.last_message == "hello there"


def test_get_chat_without_last_message_still_returns_chat():
    chat = whatsapp.get_chat(ALICE, include_last_message=False)
    assert chat is not None
    assert chat.jid == ALICE
    assert chat.name == "Alice"
    assert chat.last_message is None
