#!/usr/bin/env python3
"""
MCP Server with JWT authentication using MCP SDK's FastMCP.

This implementation uses MCP SDK's streamable-http transport which is fully
MCP protocol compliant. JWT authentication is handled via a custom TokenVerifier.
"""

import os
import logging
from typing import Any

from starlette.responses import JSONResponse
from starlette.requests import Request
from pydantic import AnyHttpUrl

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.auth.provider import TokenVerifier, AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.middleware.auth_context import auth_context_var

from auth import validate_jwt, check_user_exists_in_django, validate_no_user_id_in_arguments
from whatsapp import (
    search_contacts as whatsapp_search_contacts,
    list_messages as whatsapp_list_messages,
    list_chats as whatsapp_list_chats,
    get_chat as whatsapp_get_chat,
    get_direct_chat_by_contact as whatsapp_get_direct_chat_by_contact,
    get_contact_chats as whatsapp_get_contact_chats,
    get_last_interaction as whatsapp_get_last_interaction,
    get_message_context as whatsapp_get_message_context,
    send_message as whatsapp_send_message,
    send_file as whatsapp_send_file,
    send_audio_message as whatsapp_audio_voice_message,
    download_media as whatsapp_download_media
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRIDGE_API_URL = os.environ.get("BRIDGE_API_URL", "http://localhost:8080/api")
SERVICE_KEY = os.environ.get("SERVICE_KEY", "")


def get_user_id_from_context() -> str | None:
    """Extract user_id from the current request's auth context."""
    user = auth_context_var.get()
    if user and hasattr(user, 'access_token') and user.access_token:
        return user.access_token.client_id
    return None


class JWTTokenVerifier(TokenVerifier):
    """TokenVerifier that validates JWTs and checks user existence."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """
        Verify a bearer token and return access info if valid.

        Returns AccessToken with client_id set to our user_id, or None if invalid.
        """
        try:
            user_id = validate_jwt(token)
            if not user_id:
                return None

            if not check_user_exists_in_django(user_id):
                return None

            return AccessToken(
                token=token,
                client_id=user_id,
                scopes=["mcp"],
                expires_at=None
            )
        except Exception as e:
            logger.warning(f"JWT validation failed: {e}")
            return None


auth_settings = AuthSettings(
    issuer_url=AnyHttpUrl("http://localhost/auth"),
    resource_server_url=AnyHttpUrl("http://localhost/mcp"),
    required_scopes=["mcp"],
)

mcp = FastMCP(
    name="whatsapp-mcp-server",
    instructions="WhatsApp MCP Server with multi-tenant support via JWT authentication",
    host="0.0.0.0",
    port=int(os.environ.get("MCP_PORT", "8001")),
    streamable_http_path="/mcp",
    json_response=True,
    token_verifier=JWTTokenVerifier(),
    auth=auth_settings,
)


@mcp.custom_route("/health/", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({
        "status": "healthy",
        "service": "whatsapp-mcp",
        "version": "0.1.0"
    })


@mcp.tool()
async def search_contacts(query: str, ctx: Context = None) -> str:
    """Search WhatsApp contacts by name or phone number."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"query": query})
    result = whatsapp_search_contacts(user_id, query)
    return str(result)


@mcp.tool()
async def list_messages(
    after: str | None = None,
    before: str | None = None,
    sender_phone_number: str | None = None,
    chat_jid: str | None = None,
    query: str | None = None,
    limit: int = 20,
    page: int = 0,
    include_context: bool = True,
    context_before: int = 1,
    context_after: int = 1
) -> str:
    """Get WhatsApp messages matching specified criteria."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({
        "after": after, "before": before, "sender_phone_number": sender_phone_number,
        "chat_jid": chat_jid, "query": query, "limit": limit, "page": page
    })
    result = whatsapp_list_messages(
        user_id=user_id, after=after, before=before,
        sender_phone_number=sender_phone_number, chat_jid=chat_jid, query=query,
        limit=limit, page=page, include_context=include_context,
        context_before=context_before, context_after=context_after
    )
    return str(result)


@mcp.tool()
async def list_chats(
    query: str | None = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active"
) -> str:
    """Get WhatsApp chats matching specified criteria."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({
        "query": query, "limit": limit, "page": page, "include_last_message": include_last_message, "sort_by": sort_by
    })
    result = whatsapp_list_chats(
        user_id=user_id, query=query, limit=limit, page=page,
        include_last_message=include_last_message, sort_by=sort_by
    )
    return str(result)


@mcp.tool()
async def get_chat(chat_jid: str, include_last_message: bool = True) -> str:
    """Get WhatsApp chat metadata by JID."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"chat_jid": chat_jid})
    result = whatsapp_get_chat(user_id=user_id, chat_jid=chat_jid, include_last_message=include_last_message)
    return str(result)


@mcp.tool()
async def get_direct_chat_by_contact(sender_phone_number: str) -> str:
    """Get WhatsApp chat metadata by sender phone number."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"sender_phone_number": sender_phone_number})
    result = whatsapp_get_direct_chat_by_contact(user_id=user_id, sender_phone_number=sender_phone_number)
    return str(result)


@mcp.tool()
async def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> str:
    """Get all WhatsApp chats involving a contact."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"jid": jid, "limit": limit, "page": page})
    result = whatsapp_get_contact_chats(user_id=user_id, jid=jid, limit=limit, page=page)
    return str(result)


@mcp.tool()
async def get_last_interaction(jid: str) -> str:
    """Get most recent WhatsApp message involving a contact."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"jid": jid})
    result = whatsapp_get_last_interaction(user_id=user_id, jid=jid)
    return str(result)


@mcp.tool()
async def get_message_context(message_id: str, before: int = 5, after: int = 5) -> str:
    """Get context around a specific WhatsApp message."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"message_id": message_id, "before": before, "after": after})
    result = whatsapp_get_message_context(message_id=message_id, user_id=user_id, before=before, after=after)
    return str(result)


@mcp.tool()
async def send_message(recipient: str, message: str) -> str:
    """Send a WhatsApp message to a person or group."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"recipient": recipient, "message": message})
    result = whatsapp_send_message(user_id=user_id, recipient=recipient, message=message)
    return str(result)


@mcp.tool()
async def send_file(recipient: str, media_path: str) -> str:
    """Send a file via WhatsApp."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"recipient": recipient, "media_path": media_path})
    result = whatsapp_send_file(user_id=user_id, recipient=recipient, media_path=media_path)
    return str(result)


@mcp.tool()
async def send_audio_message(recipient: str, media_path: str) -> str:
    """Send an audio file as WhatsApp voice message."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"recipient": recipient, "media_path": media_path})
    result = whatsapp_audio_voice_message(user_id=user_id, recipient=recipient, media_path=media_path)
    return str(result)


@mcp.tool()
async def download_media(message_id: str, chat_jid: str) -> str:
    """Download media from a WhatsApp message."""
    user_id = get_user_id_from_context()
    if not user_id:
        return '{"error": "Authentication required"}'
    validate_no_user_id_in_arguments({"message_id": message_id, "chat_jid": chat_jid})
    result = whatsapp_download_media(user_id=user_id, message_id=message_id, chat_jid=chat_jid)
    return str(result)


if __name__ == "__main__":
    import sys
    transport = sys.argv[1] if len(sys.argv) > 1 else "streamable-http"
    mcp.run(transport=transport)