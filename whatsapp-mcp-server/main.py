from dataclasses import asdict
from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from whatsapp import (
    search_contacts as whatsapp_search_contacts,
    resolve_recipient as whatsapp_resolve_recipient,
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
    revoke_message as whatsapp_revoke_message,
    download_media as whatsapp_download_media,
)

# Initialize FastMCP server
mcp = FastMCP("whatsapp")

@mcp.tool()
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number.

    Returns ranked candidates from whatsmeow's canonical address book first, then local chats.
    Each result includes `confidence` (0-100), `in_address_book`, and `is_lid` — always check
    these before using a result as a send target. `is_lid: true` means it's an opaque linked-ID
    rather than a real phone JID and is the most common cause of wrong-person sends.
    """
    contacts = whatsapp_search_contacts(query)
    return [asdict(c) for c in contacts]


@mcp.tool()
def resolve_recipient(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Resolve a name or phone number to ranked WhatsApp recipient candidates.

    Use this BEFORE any send_message call when the user gives a name like "Soup" or "Mom"
    rather than a JID. Inspect the top candidate's `confidence`, `in_address_book`, and
    `is_lid` fields — confirm with the user if confidence < 80 or is_lid is true.

    Args:
        query: Name, partial name, or phone number to resolve
        limit: Maximum number of candidates to return (default 20)
    """
    contacts = whatsapp_resolve_recipient(query, limit)
    return [asdict(c) for c in contacts]

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
    message: str,
    confirm_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a WhatsApp text message — TWO-PHASE: bridge always requires a confirm-token round-trip.

    Phase 1 (no confirm_token): the bridge resolves the recipient and returns
        {success: false, needs_confirmation: true, confirm_token: "<hex>", resolved: {...candidate}, other_candidates: [...]}
      DO NOT silently retry. Show `resolved` (push_name, full_name, phone, is_lid, in_address_book,
      confidence, last_message_at, chat_display_name) to the human; if confidence < 80 or is_lid is
      true, also surface `other_candidates` and ask the user to pick.

    Phase 2 (with confirm_token from phase 1): re-call with the SAME recipient + message AND the
      token. Bridge dispatches and returns {success: true, message: "...", resolved: {...}}.

    Tokens expire 60s after issue and are payload-bound — changing recipient/message rejects.

    Args:
        recipient:      Name, phone (digits-only with country code), or full JID. Names use the new
                        resolver (whatsmeow address book + chats fallback).
        message:        The text to send.
        confirm_token:  Pass the token returned from phase 1 to actually send. Omit on first call.
    """
    if not recipient:
        return {"success": False, "message": "Recipient must be provided"}
    return whatsapp_send_message(recipient, message, confirm_token)


@mcp.tool()
def send_file(
    recipient: str,
    media_path: str,
    confirm_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a file (image, video, document) via WhatsApp — same two-phase confirm flow as send_message.

    See send_message for the confirm-token protocol. Tokens are payload-bound, so changing
    media_path between phase 1 and phase 2 rejects.
    """
    return whatsapp_send_file(recipient, media_path, confirm_token)


@mcp.tool()
def send_audio_message(
    recipient: str,
    media_path: str,
    confirm_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Send a WhatsApp voice/audio message — same two-phase confirm flow as send_message.

    If ffmpeg isn't installed and the file isn't already .ogg, this errors before phase 1.
    """
    return whatsapp_audio_voice_message(recipient, media_path, confirm_token)


@mcp.tool()
def revoke_message(
    chat_jid: str,
    message_id: str,
    sender_jid: str = "",
) -> Dict[str, Any]:
    """Revoke ("delete for everyone") a WhatsApp message you previously sent.

    Recipients see "this message was deleted". The row is also dropped from the local
    bridge DB so list_messages reflects it immediately. WhatsApp only allows revoking
    your own messages (or others' messages if you're a group admin), and the server
    enforces a ~2-day age limit.

    Args:
        chat_jid:   The chat the message lives in. From list_messages.chat_jid (e.g.
                    "1234567890@s.whatsapp.net" for a 1-on-1, "...@g.us" for a group).
        message_id: The ID of the message to revoke. From list_messages.id.
        sender_jid: Original sender JID. Leave empty (default) to revoke your own message;
                    only set when revoking someone else's message in a group you admin.
    """
    return whatsapp_revoke_message(chat_jid, message_id, sender_jid)

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