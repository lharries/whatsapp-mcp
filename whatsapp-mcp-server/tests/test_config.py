"""WHATSAPP_API_BASE_URL / MESSAGES_DB_PATH must come from env, with sane defaults."""
import os


def test_api_base_url_defaults_to_bridge_service_name(load_whatsapp):
    wa = load_whatsapp()
    assert wa.WHATSAPP_API_BASE_URL == "http://whatsapp-bridge:8080/api"


def test_api_base_url_respects_env(load_whatsapp):
    wa = load_whatsapp(WHATSAPP_API_BASE_URL="http://custom-host:1234/api")
    assert wa.WHATSAPP_API_BASE_URL == "http://custom-host:1234/api"


def test_messages_db_path_defaults_next_to_bridge_store(load_whatsapp):
    wa = load_whatsapp()
    expected = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(wa.__file__)),
            "..",
            "whatsapp-bridge",
            "store",
            "messages.db",
        )
    )
    assert os.path.normpath(wa.MESSAGES_DB_PATH) == expected


def test_messages_db_path_respects_env(load_whatsapp, tmp_path):
    custom = str(tmp_path / "custom" / "messages.db")
    wa = load_whatsapp(MESSAGES_DB_PATH=custom)
    assert wa.MESSAGES_DB_PATH == custom
