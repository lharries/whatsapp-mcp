import os
import re
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

os.environ["BRIDGE_API_URL"] = "http://localhost:8080/api"
os.environ["SERVICE_KEY"] = "test-service-key"

from whatsapp import (
    get_user_db_path,
    validate_user_id,
    search_contacts,
    list_messages,
    list_chats,
    get_chat,
    get_direct_chat_by_contact,
    get_contact_chats,
    get_last_interaction,
    get_message_context,
)


class TestValidateUserId:
    """Tests for user_id validation (path traversal prevention)."""

    def test_valid_alphanumeric_user_id(self):
        result = validate_user_id("user123")
        assert result == "user123"

    def test_valid_with_dash(self):
        result = validate_user_id("user-123")
        assert result == "user-123"

    def test_valid_with_underscore(self):
        result = validate_user_id("user_123")
        assert result == "user_123"

    def test_valid_mixed(self):
        result = validate_user_id("my-user_123")
        assert result == "my-user_123"

    def test_valid_max_length(self):
        result = validate_user_id("a" * 64)
        assert len(result) == 64

    def test_empty_user_id_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            validate_user_id("")
        assert "Invalid user_id" in str(exc_info.value)

    def test_too_long_user_id_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_user_id("a" * 65)

    def test_invalid_special_chars_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_user_id("user/123")

    def test_invalid_dot_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_user_id("user.123")

    def test_invalid_path_separator_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_user_id("user\\123")

    def test_invalid_at_symbol_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_user_id("user@123")

    def test_none_user_id_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_user_id(None)


class TestGetUserDbPath:
    """Tests for database path construction."""

    def test_raises_on_invalid_user_id(self):
        with pytest.raises(ValueError):
            get_user_db_path("user/invalid")

    def test_raises_on_path_traversal_attempt(self):
        with pytest.raises(ValueError):
            get_user_db_path("../../../etc/passwd")

    @patch("os.path.dirname")
    @patch("os.path.abspath")
    @patch("os.path.join")
    def test_constructs_path_with_user_id(self, mock_join, mock_abspath, mock_dirname):
        mock_dirname.return_value = "/fake/path"
        mock_abspath.return_value = "/fake/path/whatsapp.py"
        mock_join.side_effect = lambda *args: "/".join(args)

        result = get_user_db_path("user123")

        assert "user123" in result
        assert "messages.db" in result


class TestSearchContacts:
    """Tests for search_contacts function."""

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_returns_empty_when_db_not_exists(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/nonexistent/path/messages.db"
        result = search_contacts("user123", "test")
        assert result == []

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_handles_db_connection_error(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/tmp/test.db"
        mock_connect.side_effect = sqlite3.Error("DB error")

        result = search_contacts("user123", "test")
        assert result == []


class TestListMessages:
    """Tests for list_messages function."""

    def test_raises_on_invalid_user_id(self):
        with pytest.raises(ValueError):
            list_messages("user/invalid", "test")

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_returns_empty_when_db_not_exists(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/nonexistent/path/messages.db"
        result = list_messages("user123", query="test")
        assert result == []

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_handles_db_connection_error(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/tmp/test.db"
        mock_connect.side_effect = sqlite3.Error("DB error")

        result = list_messages("user123", query="test")
        assert result == []


class TestListChats:
    """Tests for list_chats function."""

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_returns_empty_when_db_not_exists(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/nonexistent/path/messages.db"
        result = list_chats("user123")
        assert result == []

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_handles_db_connection_error(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/tmp/test.db"
        mock_connect.side_effect = sqlite3.Error("DB error")

        result = list_chats("user123")
        assert result == []


class TestGetChat:
    """Tests for get_chat function."""

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_returns_none_when_db_not_exists(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/nonexistent/path/messages.db"
        result = get_chat("user123", "123456@s.whatsapp.net")
        assert result is None


class TestGetDirectChatByContact:
    """Tests for get_direct_chat_by_contact function."""

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_returns_none_when_db_not_exists(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/nonexistent/path/messages.db"
        result = get_direct_chat_by_contact("user123", "123456789")
        assert result is None


class TestGetContactChats:
    """Tests for get_contact_chats function."""

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_returns_empty_when_db_not_exists(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/nonexistent/path/messages.db"
        result = get_contact_chats("user123", "123456@s.whatsapp.net")
        assert result == []


class TestGetLastInteraction:
    """Tests for get_last_interaction function."""

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_returns_none_when_db_not_exists(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/nonexistent/path/messages.db"
        result = get_last_interaction("user123", "123456@s.whatsapp.net")
        assert result is None


class TestGetMessageContext:
    """Tests for get_message_context function."""

    def test_raises_on_invalid_user_id(self):
        with pytest.raises(ValueError):
            get_message_context("msg123", "user/invalid")

    @patch("whatsapp.get_user_db_path")
    @patch("whatsapp.sqlite3.connect")
    def test_returns_empty_context_when_db_not_exists(self, mock_connect, mock_get_db_path):
        mock_get_db_path.return_value = "/nonexistent/path/messages.db"
        result = get_message_context("msg123", "user123")
        assert result.message.id == ""


class TestPathTraversalPrevention:
    """Tests for path traversal attack prevention."""

    def test_user_id_with_path_traversal_rejected(self):
        with pytest.raises(ValueError):
            validate_user_id("../../../etc/passwd")

    def test_user_id_with_null_byte_rejected(self):
        with pytest.raises(ValueError):
            validate_user_id("user\x00name")

    def test_user_id_with_newline_rejected(self):
        with pytest.raises(ValueError):
            validate_user_id("user\nname")


class TestWhatsappModuleEnvironment:
    """Tests for whatsapp module environment configuration."""

    def test_bridge_api_url_loaded(self):
        from whatsapp import BRIDGE_API_URL
        assert BRIDGE_API_URL == "http://localhost:8080/api"

    def test_service_key_loaded(self):
        from whatsapp import SERVICE_KEY
        assert SERVICE_KEY == "test-service-key"