from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
import time
import requests
import sys
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
    get_control_state as whatsapp_get_control_state,
    set_control_state as whatsapp_set_control_state
)

# Initialize FastMCP server
mcp = FastMCP("whatsapp")

def check_bridge_health(max_attempts=30, delay=1):
    """Check if the WhatsApp bridge is up and healthy
    
    Args:
        max_attempts: Maximum number of attempts to connect to bridge
        delay: Delay between attempts in seconds
    
    Returns:
        bool: True if bridge is healthy, False otherwise
    """
    print("Checking WhatsApp bridge health...")
    for attempt in range(max_attempts):
        try:
            # Try to connect to the health endpoint
            response = requests.get("http://localhost:8080/api/health", timeout=2)
            if response.status_code == 200 and response.json().get("healthy", False):
                print(f"WhatsApp bridge is healthy after {attempt+1} attempts")
                return True
        except requests.RequestException as e:
            print(f"Bridge health check attempt {attempt+1}/{max_attempts} failed: {e}")
        
        time.sleep(delay)
    
    print("Failed to connect to WhatsApp bridge after maximum attempts")
    return False

# Check if the bridge is running before continuing
if not check_bridge_health():
    print("ERROR: Could not connect to WhatsApp bridge API. Exiting...")
    sys.exit(1)

print("WhatsApp bridge is available, continuing...")

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

@mcp.tool()
def connect_whatsapp() -> Dict[str, Any]:
    """Initiate the WhatsApp connection process. 
    
    This will start the connection process in the WhatsApp bridge service. If a new login is required, 
    the tool will return a QR code that needs to be scanned with the WhatsApp mobile app.
    If a session already exists, the connection will be established automatically.
    
    Returns:
        A dictionary containing the connection status and additional information like QR code if required
    """
    # Set the connect_requested flag to true
    if not whatsapp_set_control_state("connect_requested", "true"):
        return {
            "status": "error",
            "message": "Failed to set connection request flag"
        }
    
    # Poll the connection status for up to 60 seconds
    max_attempts = 30
    attempt = 0
    
    while attempt < max_attempts:
        status = whatsapp_get_control_state("connection_status")
        
        if status == "needs_qr":
            # QR code is available, return it
            qr_code = whatsapp_get_control_state("qr_code")
            return {
                "status": "needs_qr",
                "message": "Please scan this QR code with your WhatsApp mobile app",
                "qr_code": qr_code
            }
        elif status == "connected":
            # Successfully connected
            return {
                "status": "connected",
                "message": "Successfully connected to WhatsApp"
            }
        elif status == "error":
            # Connection failed
            error_message = whatsapp_get_control_state("connection_error") or "Unknown error occurred"
            return {
                "status": "error",
                "message": f"Connection failed: {error_message}"
            }
        elif status == "connecting":
            # Still connecting, wait and try again
            attempt += 1
            time.sleep(2)
            continue
        else:
            # Unexpected status
            attempt += 1
            time.sleep(2)
            continue
    
    # If we've reached here, the connection process timed out
    return {
        "status": "timeout",
        "message": "Connection process timed out. Check get_whatsapp_status() for current status."
    }

@mcp.tool()
def get_whatsapp_status() -> Dict[str, Any]:
    """Check the current WhatsApp connection status.
    
    Returns:
        A dictionary containing the current connection status and additional information
    """
    status = whatsapp_get_control_state("connection_status")
    response = {"status": status}
    
    # Add additional information based on the status
    if status == "needs_qr":
        qr_code = whatsapp_get_control_state("qr_code")
        response["qr_code"] = qr_code
        response["message"] = "Please scan this QR code with your WhatsApp mobile app"
    elif status == "error":
        error_message = whatsapp_get_control_state("connection_error") or "Unknown error occurred"
        response["message"] = f"Connection error: {error_message}"
    elif status == "connected":
        response["message"] = "Connected to WhatsApp"
    elif status == "disconnected":
        response["message"] = "Not connected to WhatsApp"
    elif status == "connecting":
        response["message"] = "Connection in progress"
    else:
        response["message"] = f"Unknown status: {status}"
    
    return response

@mcp.tool()
def disconnect_whatsapp() -> Dict[str, Any]:
    """Disconnect from WhatsApp.
    
    This will close the current WhatsApp connection if one exists.
    
    Returns:
        A dictionary containing the result of the disconnect request
    """
    # Set the connect_requested flag to false to trigger disconnection
    if not whatsapp_set_control_state("connect_requested", "false"):
        return {
            "status": "error",
            "message": "Failed to set disconnect request flag"
        }
    
    # Give some time for the disconnect to take effect
    time.sleep(2)
    
    # Check the status after disconnect request
    status = whatsapp_get_control_state("connection_status")
    
    if status == "disconnected":
        return {
            "status": "success",
            "message": "Successfully disconnected from WhatsApp"
        }
    elif status == "disconnecting":
        return {
            "status": "pending",
            "message": "Disconnect in progress. Use get_whatsapp_status() to check current status."
        }
    else:
        return {
            "status": status,
            "message": f"Disconnect requested. Current status: {status}"
        }

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')