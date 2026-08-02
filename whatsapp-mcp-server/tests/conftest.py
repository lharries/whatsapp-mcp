"""Shared pytest fixtures for the whatsapp-mcp-server test suite."""
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

# whatsapp.py / main.py / audio.py live at the package root (no src/ layout),
# make sure it is importable regardless of where pytest is invoked from.
SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

ENV_VARS_UNDER_TEST = (
    "WHATSAPP_API_BASE_URL",
    "MESSAGES_DB_PATH",
    "WHATSAPP_BRIDGE_TOKEN",
    "WHATSAPP_AUDIO_TMP_DIR",
    "MCP_HOST",
    "MCP_PORT",
    "SQLITE_TIMEOUT",
)

SCHEMA_SQL = """
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
    filename TEXT,
    url TEXT,
    media_key BLOB,
    file_sha256 BLOB,
    file_enc_sha256 BLOB,
    file_length INTEGER,
    PRIMARY KEY (id, chat_jid),
    FOREIGN KEY (chat_jid) REFERENCES chats(jid)
);
"""


@pytest.fixture
def clean_env(monkeypatch):
    """Ensure no whatsapp-mcp related env var leaks in from the host shell."""
    for var in ENV_VARS_UNDER_TEST:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _reload_whatsapp():
    import whatsapp
    return importlib.reload(whatsapp)


@pytest.fixture
def load_whatsapp(clean_env):
    """Return a loader that (re)imports whatsapp.py with a given env.

    Usage: wa = load_whatsapp(WHATSAPP_BRIDGE_TOKEN="secret")
    Called with no kwargs it reloads with an already-clean environment,
    exercising the documented defaults.
    """
    def _load(**env):
        for key, value in env.items():
            clean_env.setenv(key, value)
        return _reload_whatsapp()

    yield _load

    # Leave the module in a clean state for whichever test runs next.
    _reload_whatsapp()


@pytest.fixture
def seeded_db(tmp_path):
    """A temporary sqlite database using the real whatsapp-bridge schema,
    seeded with a couple of chats/messages usable across query tests."""
    db_path = tmp_path / "messages.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.executemany(
        "INSERT INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)",
        [
            ("111@s.whatsapp.net", "Alice", "2024-01-01T10:05:00"),
            ("222@g.us", "Team Group", "2024-01-01T09:00:00"),
        ],
    )
    conn.executemany(
        """INSERT INTO messages
           (id, chat_jid, sender, content, timestamp, is_from_me, media_type)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            ("m1", "111@s.whatsapp.net", "111@s.whatsapp.net", "Hi", "2024-01-01T10:00:00", 0, None),
            ("m2", "111@s.whatsapp.net", "me", "Hello back", "2024-01-01T10:03:00", 1, None),
            ("m3", "111@s.whatsapp.net", "111@s.whatsapp.net", "How are you", "2024-01-01T10:05:00", 0, None),
            ("m4", "222@g.us", "333@s.whatsapp.net", "Team update", "2024-01-01T09:00:00", 0, None),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def seeded_wa(load_whatsapp, seeded_db):
    """whatsapp.py reloaded so MESSAGES_DB_PATH points at the seeded db."""
    return load_whatsapp(MESSAGES_DB_PATH=str(seeded_db))
