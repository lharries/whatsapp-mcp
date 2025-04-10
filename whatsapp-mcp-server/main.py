from typing import List, Dict, Any, Optional, Tuple
from mcp.server.fastmcp import FastMCP
from datetime import datetime
from whatsapp import (
    search_contacts as whatsapp_search_contacts,
    list_messages as whatsapp_list_messages,
    list_chats as whatsapp_list_chats,
    get_chat as whatsapp_get_chat,
    get_direct_chat_by_contact as whatsapp_get_direct_chat_by_contact,
    get_contact_chats as whatsapp_get_contact_chats,
    get_last_interaction as whatsapp_get_last_interaction,
    get_message_context as whatsapp_get_message_context,
    send_message as whatsapp_send_message
)

# Initialize FastMCP server
mcp = FastMCP("whatsapp")
WHATSAPP_API_BASE_URL = "http://localhost:8080/api"

@mcp.tool()
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number.
    
    Args:
        query: Search term to match against contact names or phone numbers
    Returns:
        List of contacts with name, phone_number, and jid
    """
    try:
        # First, try local database (existing implementation)
        contacts = whatsapp_search_contacts(query)
        
        # If no results or partial results, query the Go bridge for all contacts
        if not contacts:
            response = requests.get(f"{WHATSAPP_API_BASE_URL}/contacts", params={"query": query})
            if response.status_code == 200:
                api_contacts = response.json().get("contacts", [])
                contacts.extend([
                    {"name": c.get("name"), "phone_number": c.get("phone"), "jid": c.get("jid")}
                    for c in api_contacts
                ])
        
        return contacts
    except Exception as e:
        print(f"Error in search_contacts: {e}")
        return []

@mcp.tool()
def list_messages(
    date_range: Optional[Tuple[datetime, datetime]] = None,
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
        date_range: Optional tuple of (start_date, end_date) to filter messages by date
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
        date_range=date_range,
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
def get_last_interaction(jid: str) -> Dict[str, Any]:
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
def send_message(recipient: str, message: str) -> Dict[str, Any]:
    """Send a WhatsApp message to a person or group. Supports name, phone number, or JID.

    Args:
        recipient: The recipient - either a contact name, phone number (country code, no +), 
                  or JID (e.g., "123456789@s.whatsapp.net" or "123456789@g.us")
        message: The message text to send
    
    Returns:
        A dictionary containing success status and a status message
    """
    if not recipient:
        return {"success": False, "message": "Recipient must be provided"}

    # Check if recipient is already a JID
    if recipient.endswith(("@s.whatsapp.net", "@g.us")):
        success, status_message = whatsapp_send_message(recipient, message)
        return {"success": success, "message": status_message}

    # Try to resolve as a phone number
    if recipient.isdigit():
        jid = f"{recipient}@s.whatsapp.net"
        success, status_message = whatsapp_send_message(jid, message)
        return {"success": success, "message": status_message}

    # Try to resolve as a contact name
    contacts = search_contacts(recipient)
    if not contacts:
        return {"success": False, "message": f"No contact found for '{recipient}'"}
    
    # Filter for exact or best match (case-insensitive)
    matching_contacts = [c for c in contacts if c.get("name", "").lower() == recipient.lower()]
    if not matching_contacts and contacts:
        matching_contacts = [contacts[0]]  # Fallback to first match if no exact match
    
    if len(matching_contacts) > 1:
        return {"success": False, "message": f"Multiple contacts found for '{recipient}'. Please use phone number or JID."}
    
    contact = matching_contacts[0]
    jid = contact.get("jid")
    if not jid:
        return {"success": False, "message": f"No JID available for contact '{recipient}'"}
    
    success, status_message = whatsapp_send_message(jid, message)
    return {"success": success, "message": status_message}

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')