from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
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
    download_media as whatsapp_download_media,
    wait_for_reply as whatsapp_wait_for_reply,
    resolve_contact as whatsapp_resolve_contact,
    check_whatsapp as whatsapp_check_whatsapp
)

# Initialize FastMCP server
mcp = FastMCP("whatsapp")

@mcp.tool()
def search_contacts(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number across both the address book (2300+ contacts) and chat history.
    
    Args:
        query: Search term to match against contact names or phone numbers (e.g., 'Tysen', 'Mom', '0817721286')
        limit: Max contacts to return (default 50)
    """
    return whatsapp_search_contacts(query, limit)

@mcp.tool()
def resolve_contact(query: str) -> Dict[str, Any]:
    """Resolve a name, phone number, JID or LID to its identity AND its CURRENT
    WhatsApp account (resolved live). Call this before sending to a number that
    may have migrated accounts, to confirm which account a message will reach.

    Args:
        query: Contact name ('Tysen', 'Hilka Mom'), phone number ('0817721286',
               '+264817721286'), or JID/LID.
    """
    return whatsapp_resolve_contact(query)

@mcp.tool()
def check_whatsapp(number: str) -> Dict[str, Any]:
    """Check whether a phone number is registered on WhatsApp and get its current
    canonical account (JID). Use to verify a number before sending.

    Args:
        number: Phone number in local ('0817721286') or international
                ('+264817721286') form.
    """
    return whatsapp_check_whatsapp(number)

@mcp.tool()
def send_message(
    recipient: str,
    message: str
) -> Dict[str, Any]:
    """Send a WhatsApp message. Recipient can be a contact name, phone number, JID, or LID.
    
    Args:
        recipient: Contact name (e.g. 'Tysen', 'Hilka Mom'), phone number (e.g. '0817721286', '+264817721286'),
                   personal JID/LID ('212558418043069@lid'), or group JID ('120363...@g.us').
        message: The text message content to send.
    
    Returns:
        A dictionary containing delivery status, resolved recipient, and status message.
    """
    if not recipient:
        return {"success": False, "message": "Recipient must be provided"}
    
    success, status_message = whatsapp_send_message(recipient, message)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def list_messages(
    chat_or_contact: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    after: Optional[str] = None,
    before: Optional[str] = None,
    sender_phone_number: Optional[str] = None,
    chat_jid: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get WhatsApp messages as clean, structured objects. Pass chat_or_contact to read conversation with someone.
    
    Args:
        chat_or_contact: Contact name ('Tysen'), phone number ('0817721286'), or JID/LID to filter messages for.
        query: Optional search term to filter message content.
        limit: Max messages to return (default 20).
        page: Page number for pagination (default 0).
        after: Optional ISO-8601 formatted date string for messages after date.
        before: Optional ISO-8601 formatted date string for messages before date.
        sender_phone_number: Optional phone number filter for sender.
        chat_jid: Direct chat JID filter.
    """
    return whatsapp_list_messages(
        chat_or_contact=chat_or_contact,
        query=query,
        limit=limit,
        page=page,
        after=after,
        before=before,
        sender_phone_number=sender_phone_number,
        chat_jid=chat_jid
    )

@mcp.tool()
def get_last_interaction(contact: str) -> Dict[str, Any]:
    """Get the most recent WhatsApp message exchanged with a contact. Accepts contact name, phone, or JID.
    
    Args:
        contact: Contact name ('Tysen'), phone number ('0817721286'), or JID/LID.
    """
    interaction = whatsapp_get_last_interaction(contact)
    if not interaction:
        return {"found": False, "message": f"No messages found involving '{contact}'"}
    interaction["found"] = True
    return interaction

@mcp.tool()
def wait_for_reply(
    recipient: str,
    timeout_seconds: int = 30,
    after_timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """Wait for the next incoming reply from a contact. Resolves names, numbers, or JIDs.

    Returns immediately if the contact already replied after your last message.
    The wait is capped (55s) so it returns before the client's tool timeout — call
    it again to keep waiting. Resumes from the returned ``next_after`` if given.

    Args:
        recipient: Contact name ('Tysen'), phone number ('0817721286'), or JID/LID to wait for.
        timeout_seconds: Maximum seconds to wait (default 30, capped at 55).
        after_timestamp: Only return messages after this timestamp (defaults to your
            last message's time). Pass the previous call's ``next_after`` to continue.
    """
    return whatsapp_wait_for_reply(recipient, timeout_seconds, after_timestamp)

@mcp.tool()
def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    sort_by: str = "last_active"
) -> List[Dict[str, Any]]:
    """Get WhatsApp chats and groups matching specified criteria.
    
    Args:
        query: Optional search term to filter chats by name or JID.
        limit: Maximum number of chats to return (default 20).
        page: Page number for pagination (default 0).
        sort_by: Field to sort by ('last_active' or 'name').
    """
    return whatsapp_list_chats(
        query=query,
        limit=limit,
        page=page,
        include_last_message=True,
        sort_by=sort_by
    )

@mcp.tool()
def get_chat(chat_jid: str, include_last_message: bool = True) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by JID.
    
    Args:
        chat_jid: The JID of the chat to retrieve.
        include_last_message: Whether to include the last message (default True).
    """
    chat = whatsapp_get_chat(chat_jid, include_last_message)
    return chat or {"found": False, "message": f"Chat not found: {chat_jid}"}

@mcp.tool()
def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by sender phone number or contact name.
    
    Args:
        sender_phone_number: The phone number or name to search for.
    """
    chat = whatsapp_get_direct_chat_by_contact(sender_phone_number)
    return chat or {"found": False, "message": f"Chat not found for {sender_phone_number}"}

@mcp.tool()
def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Dict[str, Any]]:
    """Get all WhatsApp chats involving the contact.
    
    Args:
        jid: The contact's name, phone number, or JID.
        limit: Maximum number of chats to return (default 20).
        page: Page number for pagination (default 0).
    """
    return whatsapp_get_contact_chats(jid, limit, page)

@mcp.tool()
def get_message_context(
    message_id: str,
    before: int = 5,
    after: int = 5
) -> Dict[str, Any]:
    """Get context messages before and after a specific message ID.
    
    Args:
        message_id: The ID of the message to get context for.
        before: Number of messages before (default 5).
        after: Number of messages after (default 5).
    """
    return whatsapp_get_message_context(message_id, before, after)

@mcp.tool()
def send_file(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send a file (image, video, document) via WhatsApp. Recipient can be contact name, phone, or JID.
    
    Args:
        recipient: Contact name (e.g. 'Tysen'), phone number, JID, or group JID.
        media_path: Absolute local file path to the file to send.
    """
    success, status_message = whatsapp_send_file(recipient, media_path)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def send_audio_message(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send an audio file as a WhatsApp voice message. Recipient can be contact name, phone, or JID.
    
    Args:
        recipient: Contact name (e.g. 'Tysen'), phone number, JID, or group JID.
        media_path: Absolute local path to audio file (auto-converted to Opus .ogg if needed).
    """
    success, status_message = whatsapp_audio_voice_message(recipient, media_path)
    return {
        "success": success,
        "message": status_message
    }

@mcp.tool()
def download_media(message_id: str, chat_jid: str) -> Dict[str, Any]:
    """Download media from a WhatsApp message to local disk.
    
    Args:
        message_id: The ID of the message containing media.
        chat_jid: The JID of the chat containing the message.
    """
    file_path = whatsapp_download_media(message_id, chat_jid)
    if file_path:
        return {
            "success": True,
            "message": "Media downloaded successfully",
            "file_path": file_path
        }
    return {
        "success": False,
        "message": "Failed to download media"
    }

if __name__ == "__main__":
    mcp.run(transport='stdio')
