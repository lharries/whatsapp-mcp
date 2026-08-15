"""The messages DB path must be overridable so tests (and alternate installs)
never touch the real WhatsApp store."""
import importlib
import os


def test_messages_db_path_defaults_next_to_bridge(monkeypatch):
    monkeypatch.delenv("WHATSAPP_MESSAGES_DB", raising=False)
    import whatsapp
    importlib.reload(whatsapp)
    assert whatsapp.MESSAGES_DB_PATH.endswith(os.path.join("whatsapp-bridge", "store", "messages.db"))


def test_messages_db_path_env_override(monkeypatch, tmp_path):
    custom = str(tmp_path / "custom.db")
    monkeypatch.setenv("WHATSAPP_MESSAGES_DB", custom)
    import whatsapp
    try:
        importlib.reload(whatsapp)
        assert whatsapp.MESSAGES_DB_PATH == custom
    finally:
        os.environ.pop("WHATSAPP_MESSAGES_DB", None)
        importlib.reload(whatsapp)
