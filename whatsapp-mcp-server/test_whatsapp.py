"""Tests for WhatsApp MCP server - reaction functionality."""
import pytest
from unittest.mock import patch, MagicMock
import json


class TestReactToMessage:
    """Tests for the react_to_message function."""

    @patch('whatsapp.requests.post')
    def test_react_to_message_success(self, mock_post):
        """Test successful reaction to a message."""
        from whatsapp import react_to_message

        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "message": "Reaction sent"}
        mock_post.return_value = mock_response

        success, message = react_to_message(
            message_id="ABC123",
            chat_jid="14699991654@s.whatsapp.net",
            emoji="❤️"
        )

        assert success is True
        assert "Reaction sent" in message
        mock_post.assert_called_once()

        # Verify the payload
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        assert payload['message_id'] == "ABC123"
        assert payload['chat_jid'] == "14699991654@s.whatsapp.net"
        assert payload['emoji'] == "❤️"

    @patch('whatsapp.requests.post')
    def test_react_to_message_removes_reaction_with_empty_emoji(self, mock_post):
        """Test removing a reaction by passing empty emoji."""
        from whatsapp import react_to_message

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "message": "Reaction removed"}
        mock_post.return_value = mock_response

        success, message = react_to_message(
            message_id="ABC123",
            chat_jid="14699991654@s.whatsapp.net",
            emoji=""
        )

        assert success is True

    @patch('whatsapp.requests.post')
    def test_react_to_message_api_error(self, mock_post):
        """Test handling of API errors."""
        from whatsapp import react_to_message

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_post.return_value = mock_response

        success, message = react_to_message(
            message_id="ABC123",
            chat_jid="14699991654@s.whatsapp.net",
            emoji="👍"
        )

        assert success is False
        assert "500" in message

    def test_react_to_message_missing_message_id(self):
        """Test that missing message_id returns error."""
        from whatsapp import react_to_message

        success, message = react_to_message(
            message_id="",
            chat_jid="14699991654@s.whatsapp.net",
            emoji="❤️"
        )

        assert success is False
        assert "message" in message.lower() and "id" in message.lower()

    def test_react_to_message_missing_chat_jid(self):
        """Test that missing chat_jid returns error."""
        from whatsapp import react_to_message

        success, message = react_to_message(
            message_id="ABC123",
            chat_jid="",
            emoji="❤️"
        )

        assert success is False
        assert "chat" in message.lower() and "jid" in message.lower()


# Note: MCP tool wrapper tests require the mcp module which is only
# available in the proper runtime environment. The core whatsapp.py
# tests above cover the main functionality.
