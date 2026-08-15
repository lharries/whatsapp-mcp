"""CLI end-to-end tests against a synthetic DB and temp whitelist file."""
import json
import sqlite3

import pytest

import whitelist_cli

GROUP = "120363111@g.us"


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "messages.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP)")
    conn.executemany(
        "INSERT INTO chats VALUES (?,?,?)",
        [
            (GROUP, "Hiking Group", "2026-01-03T10:00:00"),
            ("491701@s.whatsapp.net", "Anna", "2026-01-02T10:00:00"),
            ("491702@s.whatsapp.net", "Annabel", "2026-01-01T10:00:00"),
        ],
    )
    conn.commit()
    conn.close()
    wl = tmp_path / "whitelist.json"
    monkeypatch.setenv("WHATSAPP_MESSAGES_DB", str(db))
    monkeypatch.setenv("WHATSAPP_WHITELIST_PATH", str(wl))
    return wl


def _allowed(wl):
    return json.loads(wl.read_text())["allowed_jids"]


def test_add_single_match_writes_whitelist(env):
    rc = whitelist_cli.main(["add", "hiking", "-y"])
    assert rc == 0
    assert _allowed(env) == [GROUP]


def test_add_no_match_errors_and_writes_nothing(env):
    rc = whitelist_cli.main(["add", "zzzz", "-y"])
    assert rc != 0
    assert not env.exists()


def test_add_ambiguous_without_selection_errors(env, capsys):
    # "anna" matches both Anna and Annabel; non-interactive can't guess.
    rc = whitelist_cli.main(["add", "anna", "-y"])
    assert rc != 0
    out = capsys.readouterr().out.lower()
    assert "anna" in out and "annabel" in out  # lists the candidates


def test_remove_drops_entry(env):
    whitelist_cli.main(["add", "hiking", "-y"])
    rc = whitelist_cli.main(["remove", "hiking", "-y"])
    assert rc == 0
    assert _allowed(env) == []


def test_list_shows_current_whitelist_with_names(env, capsys):
    whitelist_cli.main(["add", "hiking", "-y"])
    capsys.readouterr()
    rc = whitelist_cli.main(["list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert GROUP in out and "Hiking Group" in out


def test_chats_marks_whitelisted(env, capsys):
    whitelist_cli.main(["add", "hiking", "-y"])
    capsys.readouterr()
    rc = whitelist_cli.main(["chats"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Hiking Group" in out and "Anna" in out  # lists all
