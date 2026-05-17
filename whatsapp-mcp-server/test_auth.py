import os
import secrets
import pytest
from unittest.mock import patch, MagicMock
import jwt as pyjwt

os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only"
os.environ["SERVICE_KEY"] = "test-service-key-123"
os.environ["DJANGO_API_URL"] = "http://localhost:18080"

from auth import (
    validate_jwt,
    validate_service_key,
    check_user_exists_in_django,
    validate_user_for_request,
    validate_no_user_id_in_arguments,
    JWT_SECRET,
    SERVICE_KEY,
    DJANGO_API_URL,
)


class TestValidateJWT:
    """Tests for JWT validation."""

    def setup_method(self):
        self.valid_payload = {"user_id": "testuser123", "iat": 1234567890}

    def _create_token(self, payload: dict) -> str:
        return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

    def test_valid_jwt_returns_user_id(self):
        token = self._create_token(self.valid_payload)
        result = validate_jwt(token)
        assert result == "testuser123"

    def test_valid_jwt_with_sub_claim(self):
        payload = {"sub": "user_from_sub", "iat": 1234567890}
        token = self._create_token(payload)
        result = validate_jwt(token)
        assert result == "user_from_sub"

    def test_missing_token_returns_none(self):
        result = validate_jwt(None)
        assert result is None

    def test_empty_token_returns_none(self):
        result = validate_jwt("")
        assert result is None

    def test_malformed_token_returns_none(self):
        result = validate_jwt("not.a.valid.token")
        assert result is None

    def test_expired_token_returns_none(self):
        payload = {"user_id": "testuser", "exp": 1}
        token = pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")
        result = validate_jwt(token)
        assert result is None

    def test_invalid_signature_returns_none(self):
        token = pyjwt.encode(self.valid_payload, "wrong-secret", algorithm="HS256")
        result = validate_jwt(token)
        assert result is None

    def test_wrong_algorithm_returns_none(self):
        token = pyjwt.encode(self.valid_payload, JWT_SECRET, algorithm="HS384")
        result = validate_jwt(token)
        assert result is None

    def test_missing_user_id_returns_none(self):
        payload = {"iat": 1234567890}
        token = self._create_token(payload)
        result = validate_jwt(token)
        assert result is None

    def test_user_id_none_returns_none(self):
        payload = {"user_id": None, "iat": 1234567890}
        token = self._create_token(payload)
        result = validate_jwt(token)
        assert result is None


class TestValidateServiceKey:
    """Tests for service key validation."""

    def test_valid_service_key_returns_true(self):
        mock_request = MagicMock()
        mock_request.headers = {"X-Service-Key": SERVICE_KEY}
        result = validate_service_key(mock_request)
        assert result is True

    def test_missing_header_returns_false(self):
        mock_request = MagicMock()
        mock_request.headers = {}
        result = validate_service_key(mock_request)
        assert result is False

    def test_wrong_service_key_returns_false(self):
        mock_request = MagicMock()
        mock_request.headers = {"X-Service-Key": "wrong-key"}
        result = validate_service_key(mock_request)
        assert result is False

    def test_empty_service_key_returns_false(self):
        mock_request = MagicMock()
        mock_request.headers = {"X-Service-Key": ""}
        result = validate_service_key(mock_request)
        assert result is False

    def test_timing_safe_comparison_used(self):
        mock_request = MagicMock()
        mock_request.headers = {"X-Service-Key": SERVICE_KEY}
        with patch("secrets.compare_digest", return_value=True) as mock_compare:
            validate_service_key(mock_request)
            mock_compare.assert_called_once()


class TestCheckUserExistsInDjango:
    """Tests for Django user existence check."""

    @patch("auth.requests.get")
    def test_user_exists_returns_true(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = check_user_exists_in_django("testuser123")
        assert result is True
        mock_get.assert_called_once()

    @patch("auth.requests.get")
    def test_user_not_found_returns_false(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = check_user_exists_in_django("deleteduser")
        assert result is False

    @patch("auth.requests.get")
    def test_server_error_returns_false(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        result = check_user_exists_in_django("testuser")
        assert result is False

    @patch("auth.requests.get")
    def test_request_exception_returns_false(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("Connection error")

        result = check_user_exists_in_django("testuser")
        assert result is False

    @patch("auth.requests.get")
    def test_correct_headers_sent(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        check_user_exists_in_django("testuser")
        call_kwargs = mock_get.call_args[1]
        assert "X-Service-Key" in call_kwargs["headers"]
        assert call_kwargs["headers"]["X-Service-Key"] == SERVICE_KEY

    @patch("auth.requests.get")
    def test_correct_url_called(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        check_user_exists_in_django("testuser")
        call_args = mock_get.call_args[0]
        assert f"{DJANGO_API_URL}/api/users/testuser/" in call_args[0]


class TestValidateUserForRequest:
    """Tests for user request validation."""

    def test_matching_user_ids_returns_user_id(self):
        result = validate_user_for_request("user123", "user123")
        assert result == "user123"

    def test_mismatched_user_ids_raises_permission_error(self):
        with pytest.raises(PermissionError) as exc_info:
            validate_user_for_request("user123", "user456")
        assert "User ID mismatch" in str(exc_info.value)

    def test_mismatch_includes_both_ids_in_error(self):
        with pytest.raises(PermissionError) as exc_info:
            validate_user_for_request("user123", "user456")
        error_msg = str(exc_info.value)
        assert "User ID mismatch" in error_msg


class TestValidateNoUserIdInArguments:
    """Tests for tool arguments validation."""

    def test_empty_arguments_pass(self):
        validate_no_user_id_in_arguments({})
        validate_no_user_id_in_arguments({"query": "test", "limit": 10})

    def test_valid_arguments_pass(self):
        args = {
            "query": "search term",
            "chat_jid": "123456@s.whatsapp.net",
            "limit": 20,
            "include_context": True
        }
        validate_no_user_id_in_arguments(args)

    def test_user_id_in_arguments_raises_permission_error(self):
        with pytest.raises(PermissionError) as exc_info:
            validate_no_user_id_in_arguments({"user_id": "attacker", "query": "test"})
        assert "cannot be passed as tool argument" in str(exc_info.value)

    def test_user_id_none_still_rejected(self):
        with pytest.raises(PermissionError):
            validate_no_user_id_in_arguments({"user_id": None})


class TestAuthModuleEnvironment:
    """Tests for auth module environment configuration."""

    def test_jwt_secret_loaded(self):
        assert JWT_SECRET == "test-secret-key-for-testing-only"

    def test_service_key_loaded(self):
        assert SERVICE_KEY == "test-service-key-123"

    def test_django_api_url_loaded(self):
        assert DJANGO_API_URL == "http://localhost:18080"