"""All HTTP calls to the whatsapp-bridge must carry Authorization: Bearer <token>.

Missing WHATSAPP_BRIDGE_TOKEN must fail loudly and clearly instead of silently
sending an unauthenticated request.
"""
from unittest.mock import MagicMock


def _mock_response(status_code=200, json_data=None, text="ok"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {"success": True, "message": "ok"}
    resp.text = text
    return resp


def test_send_message_includes_bearer_token(load_whatsapp, monkeypatch):
    wa = load_whatsapp(WHATSAPP_BRIDGE_TOKEN="secret-token")
    mock_post = MagicMock(return_value=_mock_response())
    monkeypatch.setattr(wa.requests, "post", mock_post)

    wa.send_message("5511999999999", "hello")

    assert mock_post.called
    _, kwargs = mock_post.call_args
    assert kwargs.get("headers") == {"Authorization": "Bearer secret-token"}


def test_send_file_includes_bearer_token(load_whatsapp, monkeypatch, tmp_path):
    wa = load_whatsapp(WHATSAPP_BRIDGE_TOKEN="secret-token")
    media_file = tmp_path / "file.txt"
    media_file.write_text("data")

    mock_post = MagicMock(return_value=_mock_response())
    monkeypatch.setattr(wa.requests, "post", mock_post)

    wa.send_file("5511999999999", str(media_file))

    assert mock_post.called
    _, kwargs = mock_post.call_args
    assert kwargs.get("headers") == {"Authorization": "Bearer secret-token"}


def test_download_media_includes_bearer_token(load_whatsapp, monkeypatch):
    wa = load_whatsapp(WHATSAPP_BRIDGE_TOKEN="secret-token")
    mock_post = MagicMock(return_value=_mock_response(json_data={"success": True, "path": "/tmp/x.jpg"}))
    monkeypatch.setattr(wa.requests, "post", mock_post)

    wa.download_media("msg-1", "111@s.whatsapp.net")

    assert mock_post.called
    _, kwargs = mock_post.call_args
    assert kwargs.get("headers") == {"Authorization": "Bearer secret-token"}


def test_send_message_missing_token_fails_clearly(load_whatsapp, monkeypatch):
    wa = load_whatsapp()  # WHATSAPP_BRIDGE_TOKEN intentionally absent
    mock_post = MagicMock()
    monkeypatch.setattr(wa.requests, "post", mock_post)

    success, message = wa.send_message("5511999999999", "hello")

    assert success is False
    assert "WHATSAPP_BRIDGE_TOKEN" in message
    mock_post.assert_not_called()


def test_send_file_missing_token_fails_clearly(load_whatsapp, monkeypatch, tmp_path):
    wa = load_whatsapp()
    media_file = tmp_path / "file.txt"
    media_file.write_text("data")
    mock_post = MagicMock()
    monkeypatch.setattr(wa.requests, "post", mock_post)

    success, message = wa.send_file("5511999999999", str(media_file))

    assert success is False
    assert "WHATSAPP_BRIDGE_TOKEN" in message
    mock_post.assert_not_called()


def test_download_media_missing_token_fails_clearly(load_whatsapp, monkeypatch, capsys):
    wa = load_whatsapp()
    mock_post = MagicMock()
    monkeypatch.setattr(wa.requests, "post", mock_post)

    result = wa.download_media("msg-1", "111@s.whatsapp.net")

    assert result is None
    mock_post.assert_not_called()
    assert "WHATSAPP_BRIDGE_TOKEN" in capsys.readouterr().out
