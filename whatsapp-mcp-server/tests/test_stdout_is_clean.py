"""main.py serves MCP over `mcp.run(transport='stdio')`, so stdout carries the
JSON-RPC frames. Any diagnostic that whatsapp.py writes to stdout is injected
between those frames and corrupts the protocol, so diagnostics must go to
stderr instead.

Uses a synthetic, table-less database to force the sqlite error paths.
"""
import sqlite3

import pytest

import whatsapp

ALICE = "111111@s.whatsapp.net"


@pytest.fixture(autouse=True)
def broken_db(tmp_path, monkeypatch):
    """A valid sqlite file with no tables: every query raises sqlite3.Error."""
    path = tmp_path / "messages.db"
    sqlite3.connect(path).close()
    monkeypatch.setattr(whatsapp, "MESSAGES_DB_PATH", str(path))
    return path


@pytest.mark.parametrize(
    "call",
    [
        lambda: whatsapp.list_chats(),
        lambda: whatsapp.list_messages(include_context=False),
        lambda: whatsapp.search_contacts("a"),
        lambda: whatsapp.get_chat(ALICE),
        lambda: whatsapp.get_direct_chat_by_contact("111111"),
        lambda: whatsapp.get_contact_chats(ALICE),
        lambda: whatsapp.get_last_interaction(ALICE),
    ],
    ids=[
        "list_chats",
        "list_messages",
        "search_contacts",
        "get_chat",
        "get_direct_chat_by_contact",
        "get_contact_chats",
        "get_last_interaction",
    ],
)
def test_database_errors_never_write_to_stdout(call, capsys):
    try:
        call()
    except sqlite3.Error:
        pass  # raising is fine; writing to stdout is not
    captured = capsys.readouterr()
    assert captured.out == "", f"wrote to the MCP stdio channel: {captured.out!r}"
    assert captured.err != "", "the diagnostic should still be reported, on stderr"
