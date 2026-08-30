from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from whatsapp import (
    search_contacts as whatsapp_search_contacts,
    list_messages as whatsapp_list_messages,
    list_chats as whatsapp_list_chats,
    get_chat as whatsapp_get_chat,
    get_message_context as whatsapp_get_message_context,
    send_message as whatsapp_send_message,
    download_media as whatsapp_download_media
)

# Initialize FastMCP server
mcp = FastMCP("whatsapp")

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
    phone_number: Optional[str] = None,
    sender_phone_number: Optional[str] = None,
    chat_jid: Optional[str] = None,
    contact_jid: Optional[str] = None,
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
        phone_number: Optional phone number to filter messages by a person (matches their chat or messages they sent)
        sender_phone_number: Optional phone number to filter messages by sender only
        chat_jid: Optional chat JID to filter messages by chat
        contact_jid: Optional contact JID to find any message involving this person (as sender or in their direct chat)
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
        phone_number=phone_number,
        sender_phone_number=sender_phone_number,
        chat_jid=chat_jid,
        contact_jid=contact_jid,
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
def get_chat(
    chat_jid: Optional[str] = None,
    phone_number: Optional[str] = None,
    contact_jid: Optional[str] = None,
    include_last_message: bool = True,
    limit: int = 20,
    page: int = 0
) -> List[Dict[str, Any]]:
    """Get WhatsApp chat metadata. Provide exactly one of chat_jid, phone_number, or contact_jid.

    Args:
        chat_jid: Exact JID lookup for a specific chat
        phone_number: Phone number to find a direct (non-group) chat by pattern match
        contact_jid: Contact JID to find all chats involving this person (as sender or chat participant)
        include_last_message: Whether to include the last message (default True)
        limit: Maximum number of chats to return when using contact_jid (default 20)
        page: Page number for pagination when using contact_jid (default 0)
    """
    chats = whatsapp_get_chat(
        chat_jid=chat_jid,
        phone_number=phone_number,
        contact_jid=contact_jid,
        include_last_message=include_last_message,
        limit=limit,
        page=page
    )
    return chats

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
    message: Optional[str] = None,
    media_path: Optional[str] = None,
    as_audio: bool = False
) -> Dict[str, Any]:
    """Send a WhatsApp message, file, or audio to a person or group.

    At least one of message or media_path must be provided. For group chats use the JID.

    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        message: Optional text message to send
        media_path: Optional absolute path to a media file to send (image, video, document, audio)
        as_audio: If True and media_path is provided, send as a voice message (converts to Opus .ogg if needed). If it errors due to ffmpeg not being installed, set as_audio to False.

    Returns:
        A dictionary containing success status and a status message
    """
    if not recipient:
        return {
            "success": False,
            "message": "Recipient must be provided"
        }

    success, status_message = whatsapp_send_message(recipient, message, media_path, as_audio)
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
