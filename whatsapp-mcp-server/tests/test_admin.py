"""admin.py provides UNFILTERED chat lookups for building the whitelist.
It must ignore the whitelist entirely (that's the whole point) and never be
reachable as an MCP tool."""
import sqlite3

import pytest

import admin


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "messages.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP)")
    conn.executemany(
        "INSERT INTO chats VALUES (?,?,?)",
        [
            ("120363111@g.us", "Hiking Group", "2026-01-03T10:00:00"),
            ("491701@s.whatsapp.net", "Anna", "2026-01-02T10:00:00"),
            ("491702@s.whatsapp.net", "Bob", "2026-01-01T10:00:00"),
        ],
    )
    conn.commit()
    conn.close()
    return str(path)


def test_all_chats_returns_everything(db):
    rows = admin.all_chats(db_path=db)
    assert {r[0] for r in rows} == {"120363111@g.us", "491701@s.whatsapp.net", "491702@s.whatsapp.net"}


def test_all_chats_sorted_by_recency(db):
    rows = admin.all_chats(db_path=db)
    assert [r[1] for r in rows] == ["Hiking Group", "Anna", "Bob"]


def test_find_chats_filters_by_name_case_insensitive(db):
    rows = admin.find_chats("hiking", db_path=db)
    assert [r[0] for r in rows] == ["120363111@g.us"]


def test_find_chats_no_match_returns_empty(db):
    assert admin.find_chats("nonexistent", db_path=db) == []
