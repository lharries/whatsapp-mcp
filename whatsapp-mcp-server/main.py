import asyncio
import json
import logging
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

import httpx
from pydantic import AnyUrl
from mcp.server.fastmcp import FastMCP
from mcp.server.session import ServerSession
from whatsapp import (
    search_contacts as whatsapp_search_contacts,
    list_messages as whatsapp_list_messages,
    list_messages_raw as whatsapp_list_messages_raw,
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

logger = logging.getLogger(__name__)

BRIDGE_EVENTS_URL = "http://localhost:8181/api/events"
BRIDGE_QR_URL = "http://localhost:8181/api/qr"
INBOX_RESOURCE_URI = "whatsapp://messages/inbox"

# Holds the active MCP session so background tasks can send notifications.
# Set when a client subscribes to a resource (subscribe_resource handler).
_active_session: Optional[ServerSession] = None


async def sse_listener():
    """Connect to the WhatsApp bridge SSE endpoint and send MCP resource
    updated notifications when new messages arrive.

    The bridge streams Server-Sent Events for each incoming WhatsApp message.
    When we receive one, we notify connected MCP clients that the inbox
    resource has been updated, so they can re-read it without polling."""
    global _active_session
    while True:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
                async with client.stream("GET", BRIDGE_EVENTS_URL) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data:") and _active_session:
                            try:
                                await _active_session.send_resource_updated(
                                    AnyUrl(INBOX_RESOURCE_URI)
                                )
                            except Exception:
                                # Session closed or disconnected
                                _active_session = None
        except httpx.ConnectError:
            await asyncio.sleep(5)
        except Exception as e:
            logger.debug(f"SSE listener error: {e}, reconnecting in 5s...")
            await asyncio.sleep(5)


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Start the SSE listener as a background task during server lifetime."""
    task = asyncio.create_task(sse_listener())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# Initialize FastMCP server with lifespan for SSE event streaming
mcp = FastMCP("whatsapp", lifespan=app_lifespan)


# Capture the MCP session when a client subscribes to a resource.
# This allows our background SSE listener to send notifications.
@mcp._mcp_server.subscribe_resource()
async def on_subscribe(req):
    global _active_session
    try:
        ctx = mcp._mcp_server.request_context
        _active_session = ctx.session
    except LookupError:
        pass


# Force subscribe capability to True so MCP clients know they can subscribe.
# The MCP SDK hardcodes subscribe=False in get_capabilities; we patch it here.
_original_get_capabilities = mcp._mcp_server.get_capabilities

def _patched_get_capabilities(notification_options, experimental_capabilities):
    caps = _original_get_capabilities(notification_options, experimental_capabilities)
    if caps.resources is not None:
        caps.resources.subscribe = True
    return caps

mcp._mcp_server.get_capabilities = _patched_get_capabilities


# --- Resources ---

@mcp.resource(INBOX_RESOURCE_URI)
def get_inbox() -> str:
    """Recent WhatsApp messages as JSON array. Subscribe to this resource to
    receive real-time notifications when new messages arrive."""
    messages = whatsapp_list_messages_raw(limit=20)
    return json.dumps(messages)


# --- Tools ---

@mcp.tool()
def get_auth_status() -> Dict[str, Any]:
    """Get WhatsApp authentication status. Returns status ('unpaired', 'pairing', 'paired'),
    auth type ('qr'), and QR code data as base64 PNG when available.

    This follows a generic auth convention: any MCP server needing authentication
    can expose this tool with {status, type, data} fields.
    """
    try:
        import requests
        response = requests.get(BRIDGE_QR_URL, timeout=5)
        if response.status_code == 200:
            return response.json()
        return {"status": "error", "message": f"Bridge returned {response.status_code}"}
    except requests.ConnectionError:
        return {"status": "error", "message": "WhatsApp bridge not running. Start it first with: cd whatsapp-bridge && go run main.go"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def get_qr_code() -> str:
    """Get WhatsApp QR code for pairing. Returns base64 PNG image data or status message."""
    status = get_auth_status()
    if status.get("status") == "paired":
        return "Already paired!"
    if status.get("data"):
        return f"![QR Code]({status['data']})"
    return f"Status: {status.get('status', 'unknown')}. {status.get('message', '')}"

@mcp.tool()
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number.

    Args:
        query: Search term to match against contact names or phone numbers
    """
    contacts = whatsapp_search_contacts(query)
    return contacts

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
) -> List[Dict[str, Any]]:
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
        after=after,
        before=before,
        sender_phone_number=sender_phone_number,
        chat_jid=chat_jid,
        query=query,
        limit=limit,
        page=page,
        include_context=include_context,
        context_before=context_before,
        context_after=context_after
    )
    return messages

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
        query=query,
        limit=limit,
        page=page,
        include_last_message=include_last_message,
        sort_by=sort_by
    )
    return chats

@mcp.tool()
def get_chat(chat_jid: str, include_last_message: bool = True) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by JID.

    Args:
        chat_jid: The JID of the chat to retrieve
        include_last_message: Whether to include the last message (default True)
    """
    chat = whatsapp_get_chat(chat_jid, include_last_message)
    return chat

@mcp.tool()
def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by sender phone number.

    Args:
        sender_phone_number: The phone number to search for
    """
    chat = whatsapp_get_direct_chat_by_contact(sender_phone_number)
    return chat

@mcp.tool()
def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Dict[str, Any]]:
    """Get all WhatsApp chats involving the contact.

    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    chats = whatsapp_get_contact_chats(jid, limit, page)
    return chats

@mcp.tool()
def get_last_interaction(jid: str) -> str:
    """Get most recent WhatsApp message involving the contact.

    Args:
        jid: The JID of the contact to search for
    """
    message = whatsapp_get_last_interaction(jid)
    return message

@mcp.tool()
def get_message_context(
    message_id: str,
    before: int = 5,
    after: int = 5
) -> Dict[str, Any]:
    """Get context around a specific WhatsApp message.

    Args:
        message_id: The ID of the message to get context for
        before: Number of messages to include before the target message (default 5)
        after: Number of messages to include after the target message (default 5)
    """
    context = whatsapp_get_message_context(message_id, before, after)
    return context

@mcp.tool()
def send_message(
    recipient: str,
    message: str
) -> Dict[str, Any]:
    """Send a WhatsApp message to a person or group. For group chats use the JID.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        message: The message text to send

    Returns:
        A dictionary containing success status and a status message
    """
    # Validate input
    if not recipient:
        return {
            "success": False,
            "message": "Recipient must be provided"
        }

    # Call the whatsapp_send_message function with the unified recipient parameter
    success, status_message = whatsapp_send_message(recipient, message)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def send_file(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send a file such as a picture, raw audio, video or document via WhatsApp to the specified recipient. For group messages use the JID.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        media_path: The absolute path to the media file to send (image, video, document)

    Returns:
        A dictionary containing success status and a status message
    """

    # Call the whatsapp_send_file function
    success, status_message = whatsapp_send_file(recipient, media_path)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def send_audio_message(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send any audio file as a WhatsApp audio message to the specified recipient. For group messages use the JID. If it errors due to ffmpeg not being installed, use send_file instead.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        media_path: The absolute path to the audio file to send (will be converted to Opus .ogg if it's not a .ogg file)

    Returns:
        A dictionary containing success status and a status message
    """
    success, status_message = whatsapp_audio_voice_message(recipient, media_path)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def download_media(message_id: str, chat_jid: str) -> Dict[str, Any]:
    """Download media from a WhatsApp message and get the local file path.

    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message

    Returns:
        A dictionary containing success status, a status message, and the file path if successful
    """
    file_path = whatsapp_download_media(message_id, chat_jid)

    if file_path:
        return {
            "success": True,
            "message": "Media downloaded successfully",
            "file_path": file_path
        }
    else:
        return {
            "success": False,
            "message": "Failed to download media"
        }

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')
