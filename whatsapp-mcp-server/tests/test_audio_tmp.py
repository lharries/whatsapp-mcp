"""Converted-audio temp files must land inside the shared store volume, not /tmp,
so a separate whatsapp-bridge container can see them.
"""
import os
import tempfile
from unittest.mock import MagicMock


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {"success": True, "message": "ok"}
    resp.text = "ok"
    return resp


def test_audio_tmp_dir_defaults_inside_store_dir(load_whatsapp, tmp_path):
    db_path = tmp_path / "store" / "messages.db"
    wa = load_whatsapp(MESSAGES_DB_PATH=str(db_path))

    expected = os.path.join(os.path.dirname(str(db_path)), "tmp")
    assert os.path.normpath(wa.AUDIO_TMP_DIR) == os.path.normpath(expected)
    assert os.path.normpath(wa.AUDIO_TMP_DIR) != os.path.normpath(tempfile.gettempdir())


def test_audio_tmp_dir_respects_env_override(load_whatsapp, tmp_path):
    custom = tmp_path / "custom-audio-tmp"
    wa = load_whatsapp(WHATSAPP_AUDIO_TMP_DIR=str(custom))
    assert os.path.normpath(wa.AUDIO_TMP_DIR) == os.path.normpath(str(custom))


def test_send_audio_message_converts_inside_audio_tmp_dir_and_cleans_up(load_whatsapp, monkeypatch, tmp_path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    wa = load_whatsapp(
        MESSAGES_DB_PATH=str(store_dir / "messages.db"),
        WHATSAPP_BRIDGE_TOKEN="secret-token",
    )

    input_file = tmp_path / "voice.mp3"
    input_file.write_bytes(b"fake-audio-bytes")

    captured = {}

    def fake_convert(input_path, bitrate="32k", sample_rate=24000, tmp_dir=None):
        captured["tmp_dir"] = tmp_dir
        os.makedirs(tmp_dir, exist_ok=True)
        out_path = os.path.join(tmp_dir, "converted.ogg")
        with open(out_path, "wb") as fh:
            fh.write(b"fake-ogg-bytes")
        captured["out_path"] = out_path
        return out_path

    monkeypatch.setattr(wa.audio, "convert_to_opus_ogg_temp", fake_convert)
    monkeypatch.setattr(wa.requests, "post", MagicMock(return_value=_mock_response()))

    success, message = wa.send_audio_message("5511999999999", str(input_file))

    assert success is True
    assert os.path.normpath(captured["tmp_dir"]) == os.path.normpath(wa.AUDIO_TMP_DIR)
    assert not os.path.exists(captured["out_path"]), "converted .ogg must be cleaned up after sending"


def test_send_audio_message_cleans_up_even_on_send_failure(load_whatsapp, monkeypatch, tmp_path):
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    wa = load_whatsapp(
        MESSAGES_DB_PATH=str(store_dir / "messages.db"),
        WHATSAPP_BRIDGE_TOKEN="secret-token",
    )

    input_file = tmp_path / "voice.mp3"
    input_file.write_bytes(b"fake-audio-bytes")

    captured = {}

    def fake_convert(input_path, bitrate="32k", sample_rate=24000, tmp_dir=None):
        os.makedirs(tmp_dir, exist_ok=True)
        out_path = os.path.join(tmp_dir, "converted.ogg")
        with open(out_path, "wb") as fh:
            fh.write(b"fake-ogg-bytes")
        captured["out_path"] = out_path
        return out_path

    monkeypatch.setattr(wa.audio, "convert_to_opus_ogg_temp", fake_convert)
    monkeypatch.setattr(wa.requests, "post", MagicMock(return_value=_mock_response(status_code=500)))

    success, message = wa.send_audio_message("5511999999999", str(input_file))

    assert success is False
    assert not os.path.exists(captured["out_path"])
