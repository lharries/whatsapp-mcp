import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load .env from project root (one level up from whatsapp-mcp-server/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# READ-ONLY companion server. All sending / typing / presence / read-receipt /
# polling tools have been removed — those live on the `whatsapp` channel server now.
# This server only exposes reconnaissance: search, chat history, and transcription.
from whatsapp import (
    search_contacts as whatsapp_search_contacts,
    list_chats as whatsapp_list_chats,
    get_chat as whatsapp_get_chat,
    get_direct_chat_by_contact as whatsapp_get_direct_chat_by_contact,
    download_media as whatsapp_download_media,
    get_chat_log as whatsapp_get_chat_log,
    transcribe_audio as whatsapp_transcribe_audio,
    resolve_contacts as whatsapp_resolve_contacts,
)

# Initialize FastMCP server
mcp = FastMCP("whatsapp-data")

@mcp.tool()
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number.

    Args:
        query: Search term to match against contact names or phone numbers
    """
    return whatsapp_search_contacts(query)

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
    return whatsapp_list_chats(
        query=query,
        limit=limit,
        page=page,
        include_last_message=include_last_message,
        sort_by=sort_by,
    )

@mcp.tool()
def get_chat(chat_jid: str, include_last_message: bool = True) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by JID.

    Args:
        chat_jid: The JID of the chat to retrieve
        include_last_message: Whether to include the last message (default True)
    """
    return whatsapp_get_chat(chat_jid, include_last_message)

@mcp.tool()
def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by sender phone number.

    Args:
        sender_phone_number: The phone number to search for
    """
    return whatsapp_get_direct_chat_by_contact(sender_phone_number)

@mcp.tool()
def get_chat_log(
    chat_jid: str,
    amount: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """Get conversation as a readable chat log. Optimized for LLM analysis.

    Returns messages as a plain-text chronological log, ~5x smaller than JSON.
    Use this for conversation analysis, reconnaissance, or context loading.

    Args:
        chat_jid: The JID of the chat to get messages from.
        amount: Maximum number of messages to fetch (default: 50).
        offset: Skip the N most recent messages (default: 0).
            Use for pagination: offset=0 gets latest, offset=50 gets older.

    Returns:
        Object with 'chat_jid', 'chat_name', 'log' (plain text),
        'count', 'offset', and 'has_more'.
    """
    return whatsapp_get_chat_log(chat_jid, amount, offset)

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
        return {"success": True, "message": "Media downloaded successfully", "file_path": file_path}
    return {"success": False, "message": "Failed to download media"}

@mcp.tool()
def transcribe_audio(message_id: str, chat_jid: str) -> Dict[str, Any]:
    """Transcribe a WhatsApp voice/audio message to text using OpenAI Whisper.

    Downloads the audio message and sends it to OpenAI's Whisper API for
    speech-to-text transcription. Requires OPENAI_API_KEY environment variable.

    Args:
        message_id: The ID of the message containing the audio/voice message.
        chat_jid: The JID of the chat containing the message.

    Returns:
        Object with 'success', 'text' (the transcription), 'file_path',
        'message_id', and 'chat_jid'.
    """
    return whatsapp_transcribe_audio(message_id, chat_jid)

@mcp.tool()
def resolve_contacts() -> Dict[str, Any]:
    """Bulk-resolve all unresolved contact names at once.

    Many contacts (especially LID-based ones) have numeric-only names in the
    database. This triggers the Go bridge to look up real names for all of
    them. Run once before searching contacts to ensure names are available.

    Returns:
        Object with 'resolved' count, 'unresolved' count, and 'total'.
    """
    return whatsapp_resolve_contacts()

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')
