import os
import sys
import argparse
from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response
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

# Initialize FastMCP server
# Try to disable DNS rebinding protection (MCP 1.26+) for tunnel access
try:
    from mcp.server.transport_security import TransportSecuritySettings
    mcp = FastMCP(
        "whatsapp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
except (ImportError, TypeError):
    # Older MCP versions don't have this setting
    mcp = FastMCP("whatsapp")


def _to_dict(obj):
    """Convert objects to dicts for MCP 1.26+ output validation."""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if hasattr(obj, '__dict__'):
        return {k: v for k, v in vars(obj).items() if not k.startswith('_')}
    return obj


# --- Pure ASGI Auth Middleware (does NOT break SSE streaming) ---
class APIKeyAuthASGI:
    """Pure ASGI middleware that validates API key without interfering with streaming."""
    
    # Paths that should bypass auth (OAuth discovery, health checks)
    BYPASS_PATHS = {"/.well-known/oauth-authorization-server", "/.well-known/openid-configuration", "/health"}
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # WebSocket or lifespan — pass through
            await self.app(scope, receive, send)
            return
        
        path = scope.get("path", "")
        
        # Bypass auth for discovery/health endpoints
        if path in self.BYPASS_PATHS:
            await self.app(scope, receive, send)
            return
        
        api_key = os.environ.get("WHATSAPP_MCP_API_KEY", "")
        if not api_key:
            # No key configured — allow all
            await self.app(scope, receive, send)
            return

        # Extract Authorization header from ASGI scope
        headers = dict(scope.get("headers", []))
        auth_value = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
        
        if auth_value == f"Bearer {api_key}":
            await self.app(scope, receive, send)
            return
        
        # Unauthorized — send 401
        async def send_401(send):
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"Unauthorized"})
        
        await send_401(send)


# --- Tools (unchanged) ---

@mcp.tool()
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number.
    Args:
        query: Search term to match against contact names or phone numbers
    """
    contacts = whatsapp_search_contacts(query)
    return _to_dict(contacts)

@mcp.tool()
def list_messages(
    after: Optional[str] = None,
    before: Optional[str] = None,
    sender_phone_number: Optional[str] = None,
    chat_jid: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_context: bool = True,
    context_before: int = 1,
    context_after: int = 1
) -> str:
    """Get WhatsApp messages matching specified criteria with optional context.
    Args:
        after: Optional ISO-8601 formatted string to only return messages after this date
        before: Optional ISO-8601 formatted string to only return messages before this date
        sender_phone_number: Optional phone number to filter messages by sender
        chat_jid: Optional chat JID to filter messages by chat
        query: Optional search term to filter messages by content
        limit: Maximum number of messages to return (default 20)
        page: Page number for pagination (default 0)
        include_context: Whether to include messages before and after matches (default True)
        context_before: Number of messages to include before each match (default 1)
        context_after: Number of messages to include after each match (default 1)
    """
    messages = whatsapp_list_messages(
        after=after, before=before,
        sender_phone_number=sender_phone_number,
        chat_jid=chat_jid, query=query,
        limit=limit, page=page,
        include_context=include_context,
        context_before=context_before,
        context_after=context_after
    )
    return _to_dict(messages)

@mcp.tool()
def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active"
) -> List[Dict[str, Any]]:
    """Get WhatsApp chats matching specified criteria.
    Args:
        query: Optional search term to filter chats by name or JID
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
        include_last_message: Whether to include the last message in each chat (default True)
        sort_by: Field to sort results by, either "last_active" or "name" (default "last_active")
    """
    chats = whatsapp_list_chats(
        query=query, limit=limit, page=page,
        include_last_message=include_last_message, sort_by=sort_by
    )
    return _to_dict(chats)

@mcp.tool()
def get_chat(chat_jid: str, include_last_message: bool = True) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by JID.
    Args:
        chat_jid: The JID of the chat to retrieve
        include_last_message: Whether to include the last message (default True)
    """
    chat = whatsapp_get_chat(chat_jid, include_last_message)
    return _to_dict(chat)

@mcp.tool()
def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by sender phone number.
    Args:
        sender_phone_number: The phone number to search for
    """
    chat = whatsapp_get_direct_chat_by_contact(sender_phone_number)
    return _to_dict(chat)

@mcp.tool()
def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Dict[str, Any]]:
    """Get all WhatsApp chats involving the contact.
    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    chats = whatsapp_get_contact_chats(jid, limit, page)
    return _to_dict(chats)

@mcp.tool()
def get_last_interaction(jid: str) -> str:  # already correct type
    """Get most recent WhatsApp message involving the contact.
    Args:
        jid: The JID of the contact to search for
    """
    message = whatsapp_get_last_interaction(jid)
    return _to_dict(message)

@mcp.tool()
def get_message_context(message_id: str, before: int = 5, after: int = 5) -> Dict[str, Any]:
    """Get context around a specific WhatsApp message.
    Args:
        message_id: The ID of the message to get context for
        before: Number of messages to include before the target message (default 5)
        after: Number of messages to include after the target message (default 5)
    """
    context = whatsapp_get_message_context(message_id, before, after)
    return _to_dict(context)

@mcp.tool()
def send_message(recipient: str, message: str) -> Dict[str, Any]:
    """Send a WhatsApp message to a person or group. For group chats use the JID.
    Args:
        recipient: The recipient - phone number with country code (no + or symbols),
                 or a JID (e.g., "123456789@s.whatsapp.net" or group JID "123456789@g.us")
        message: The message text to send
    """
    if not recipient:
        return {"success": False, "message": "Recipient must be provided"}
    success, status_message = whatsapp_send_message(recipient, message)
    return {"success": success, "message": status_message}

@mcp.tool()
def send_file(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send a file (picture, audio, video, document) via WhatsApp. For group messages use the JID.
    Args:
        recipient: The recipient - phone number or JID
        media_path: The absolute path to the media file to send
    """
    success, status_message = whatsapp_send_file(recipient, media_path)
    return {"success": success, "message": status_message}

@mcp.tool()
def send_audio_message(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send audio file as WhatsApp audio message. For group messages use the JID.
    Args:
        recipient: The recipient - phone number or JID
        media_path: The absolute path to the audio file (converted to Opus .ogg if needed)
    """
    success, status_message = whatsapp_audio_voice_message(recipient, media_path)
    return {"success": success, "message": status_message}

@mcp.tool()
def download_media(message_id: str, chat_jid: str) -> Dict[str, Any]:
    """Download media from a WhatsApp message and get the local file path.
    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message
    """
    file_path = whatsapp_download_media(message_id, chat_jid)
    if file_path:
        return {"success": True, "message": "Media downloaded successfully", "file_path": file_path}
    return {"success": False, "message": "Failed to download media"}


# --- Entrypoint: supports stdio, sse, and streamable-http ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WhatsApp MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "sse", "streamable-http"], default="stdio",
        help="Transport mode: stdio (local), sse (legacy remote), streamable-http (recommended remote)"
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port for HTTP modes (default: 8000)"
    )
    args = parser.parse_args()

    if args.transport in ("sse", "streamable-http"):
        import uvicorn
        
        if args.transport == "streamable-http":
            app = mcp.streamable_http_app()
        else:
            app = mcp.sse_app()
        
        # Wrap with pure ASGI auth middleware (doesn't break streaming)
        app = APIKeyAuthASGI(app)
        
        print(f"WhatsApp MCP Server running in {args.transport} mode on port {args.port}")
        print(f"Auth: {'ENABLED' if os.environ.get('WHATSAPP_MCP_API_KEY') else 'DISABLED'}")
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        # Default: stdio for Claude Desktop chat
        mcp.run(transport='stdio')
