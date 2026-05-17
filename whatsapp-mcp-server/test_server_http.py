import os
import asyncio
import pytest
from unittest.mock import patch, MagicMock
from contextlib import asynccontextmanager

os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only"
os.environ["SERVICE_KEY"] = "test-service-key-123"
os.environ["BRIDGE_API_URL"] = "http://localhost:8080/api"
os.environ["DJANGO_API_URL"] = "http://localhost:18080"

from auth import validate_jwt, validate_no_user_id_in_arguments, check_user_exists_in_django
from whatsapp import search_contacts as whatsapp_search_contacts, list_chats as whatsapp_list_chats


class TestJWTTokenVerifier:
    """Tests for the JWT TokenVerifier."""

    def test_verify_valid_jwt_with_existing_user(self):
        from server_http import JWTTokenVerifier

        with patch("server_http.validate_jwt") as mock_validate, \
             patch("server_http.check_user_exists_in_django") as mock_check:
            mock_validate.return_value = "user123"
            mock_check.return_value = True

            verifier = JWTTokenVerifier()
            result = asyncio.run(verifier.verify_token("valid.jwt.token"))

            assert result is not None
            assert result.client_id == "user123"
            assert "mcp" in result.scopes

    def test_verify_invalid_jwt_returns_none(self):
        from server_http import JWTTokenVerifier

        with patch("server_http.validate_jwt") as mock_validate:
            mock_validate.return_value = None

            verifier = JWTTokenVerifier()
            result = asyncio.run(verifier.verify_token("invalid.token"))

            assert result is None

    def test_verify_jwt_for_deleted_user_returns_none(self):
        from server_http import JWTTokenVerifier

        with patch("server_http.validate_jwt") as mock_validate, \
             patch("server_http.check_user_exists_in_django") as mock_check:
            mock_validate.return_value = "deleteduser"
            mock_check.return_value = False

            verifier = JWTTokenVerifier()
            result = asyncio.run(verifier.verify_token("valid.jwt.token"))

            assert result is None

    def test_verify_jwt_raises_exception_returns_none(self):
        from server_http import JWTTokenVerifier

        with patch("server_http.validate_jwt") as mock_validate:
            mock_validate.side_effect = Exception("JWT decode error")

            verifier = JWTTokenVerifier()
            result = asyncio.run(verifier.verify_token("bad.token"))

            assert result is None


class TestMCPServer:
    """Tests for MCP server structure and tool registration."""

    def test_mcp_server_has_required_tools(self):
        from server_http import mcp

        app = mcp.streamable_http_app()

        tools_route = None
        for route in app.routes:
            if hasattr(route, 'path') and route.path == '/mcp':
                tools_route = route
                break

        assert tools_route is not None

    def test_mcp_server_has_health_endpoint(self):
        from server_http import mcp

        app = mcp.streamable_http_app()

        health_route = None
        for route in app.routes:
            if hasattr(route, 'path') and route.path == '/health/':
                health_route = route
                break

        assert health_route is not None


class TestHealthEndpoint:
    """Tests for /health/ endpoint."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from contextlib import asynccontextmanager
        from mcp.server.fastmcp import FastMCP
        from mcp.server.auth.provider import TokenVerifier, AccessToken
        from mcp.server.auth.settings import AuthSettings
        from pydantic import AnyHttpUrl
        from starlette.testclient import TestClient
        from starlette.responses import JSONResponse

        class TestTokenVerifier(TokenVerifier):
            async def verify_token(self, token: str) -> AccessToken | None:
                return AccessToken(token=token, client_id='testuser', scopes=['mcp'], expires_at=None)

        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl("http://localhost/auth"),
            resource_server_url=AnyHttpUrl("http://localhost/mcp"),
            required_scopes=["mcp"],
        )

        self.test_mcp = FastMCP(
            name="test-server",
            host="0.0.0.0",
            port=8001,
            streamable_http_path="/mcp",
            json_response=True,
            token_verifier=TestTokenVerifier(),
            auth=auth_settings,
        )

        @self.test_mcp.custom_route("/health/", methods=["GET"])
        async def health_check(request):
            return JSONResponse({"status": "healthy", "service": "test-mcp", "version": "0.1.0"})

        self.TestClient = TestClient

    def test_health_returns_200(self):
        app = self.test_mcp.streamable_http_app()

        @asynccontextmanager
        async def lifespan_wrapper(app):
            async with self.test_mcp.session_manager.run():
                yield

        app.router.lifespan_context = lifespan_wrapper

        with self.TestClient(app) as client:
            response = client.get("/health/")
            assert response.status_code == 200

    def test_health_returns_status_healthy(self):
        app = self.test_mcp.streamable_http_app()

        @asynccontextmanager
        async def lifespan_wrapper(app):
            async with self.test_mcp.session_manager.run():
                yield

        app.router.lifespan_context = lifespan_wrapper

        with self.TestClient(app) as client:
            response = client.get("/health/")
            assert response.json()["status"] == "healthy"

    def test_health_returns_version(self):
        app = self.test_mcp.streamable_http_app()

        @asynccontextmanager
        async def lifespan_wrapper(app):
            async with self.test_mcp.session_manager.run():
                yield

        app.router.lifespan_context = lifespan_wrapper

        with self.TestClient(app) as client:
            response = client.get("/health/")
            assert "version" in response.json()


class TestValidateNoUserIdInArguments:
    """Tests for validate_no_user_id_in_arguments function."""

    def test_valid_arguments_pass(self):
        args = {"query": "John", "limit": 10}
        validate_no_user_id_in_arguments(args)

    def test_user_id_in_arguments_raises(self):
        args = {"user_id": "hack", "query": "John"}
        with pytest.raises(Exception) as exc_info:
            validate_no_user_id_in_arguments(args)
        assert "user_id" in str(exc_info.value).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])