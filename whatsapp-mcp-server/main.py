from typing import List, Dict, Any, Optional
import json
from datetime import datetime
from fastmcp import FastMCP

# MCP-UI SDK is currently only available for TypeScript/Node.js and Ruby
# Python implementation doesn't exist yet, so we'll use HTML-based MCP resources
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
    ensure_bridge_ready,
    get_bridge_status,
    MESSAGES_DB_PATH,
    
)
import sqlite3
import os

# Initialize FastMCP server
mcp = FastMCP("whatsapp")

def with_bridge_check(func):
    """Decorator to ensure bridge is ready before executing MCP tools."""
    import functools
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Check bridge readiness
        success, message, qr_url = ensure_bridge_ready()
        
        if not success:
            if qr_url:
                # Return QR URL for authentication
                return {
                    "error": "WhatsApp Authentication Required",
                    "message": message,
                    "qr_url": qr_url,
                    "instructions": [
                        "1. Open the QR code page in your browser:",
                        f"   {qr_url}",
                        "2. Open WhatsApp on your phone",
                        "3. Go to Settings > Linked Devices",
                        "4. Tap 'Link a Device'",
                        "5. Scan the QR code displayed on the web page",
                        "6. Wait for authentication to complete",
                        "7. Try your request again"
                    ]
                }
            else:
                # Return error message
                return {
                    "error": "WhatsApp Bridge Error",
                    "message": message,
                    "troubleshooting": [
                        "• Ensure Go is installed on your system",
                        "• Check that the bridge directory exists",
                        "• Verify network connectivity",
                        "• Try restarting the MCP server"
                    ]
                }
        
        # Bridge is ready, execute the original function
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return {
                "error": "Tool Execution Error",
                "message": str(e),
                "suggestion": "Please try again or check the bridge status"
            }
    
    return wrapper

@mcp.tool()
@with_bridge_check
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number.
    
    Args:
        query: Search term to match against contact names or phone numbers
    """
    contacts = whatsapp_search_contacts(query)
    return contacts

@mcp.tool()
@with_bridge_check
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
@with_bridge_check
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
@with_bridge_check
def get_chat(chat_jid: str, include_last_message: bool = True) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by JID.
    
    Args:
        chat_jid: The JID of the chat to retrieve
        include_last_message: Whether to include the last message (default True)
    """
    chat = whatsapp_get_chat(chat_jid, include_last_message)
    return chat

@mcp.tool()
@with_bridge_check
def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by sender phone number.
    
    Args:
        sender_phone_number: The phone number to search for
    """
    chat = whatsapp_get_direct_chat_by_contact(sender_phone_number)
    return chat

@mcp.tool()
@with_bridge_check
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
@with_bridge_check
def get_last_interaction(jid: str) -> str:
    """Get most recent WhatsApp message involving the contact.
    
    Args:
        jid: The JID of the contact to search for
    """
    message = whatsapp_get_last_interaction(jid)
    return message

@mcp.tool()
@with_bridge_check
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
@with_bridge_check
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
@with_bridge_check
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
@with_bridge_check
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
@with_bridge_check
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

@mcp.resource("whatsapp://sync-status")
def get_sync_status_resource() -> str:
    """Resource showing the current sync status and last activity."""
    try:
        # Get bridge status
        bridge_status = get_bridge_status()
        
        # Get database stats
        message_count = 0
        last_sync_time = None
        chat_count = 0
        
        if os.path.exists(MESSAGES_DB_PATH):
            conn = sqlite3.connect(MESSAGES_DB_PATH)
            cursor = conn.cursor()
            
            # Get message count
            cursor.execute("SELECT COUNT(*) FROM messages")
            message_count = cursor.fetchone()[0]
            
            # Get last message time as proxy for last sync
            cursor.execute("SELECT MAX(timestamp) FROM messages")
            last_sync_result = cursor.fetchone()[0]
            if last_sync_result:
                last_sync_time = datetime.fromisoformat(last_sync_result)
            
            # Get chat count
            cursor.execute("SELECT COUNT(*) FROM chats")
            chat_count = cursor.fetchone()[0]
            
            conn.close()
        
        # Format the status report
        status_report = {
            "timestamp": datetime.now().isoformat(),
            "bridge_status": {
                "running": bridge_status.is_running,
                "authenticated": bridge_status.is_authenticated,
                "api_responsive": bridge_status.api_responsive,
                "overall": "Ready" if (bridge_status.is_running and bridge_status.api_responsive and bridge_status.is_authenticated) else "Not Ready"
            },
            "sync_stats": {
                "total_messages": message_count,
                "total_chats": chat_count,
                "last_sync_time": last_sync_time.isoformat() if last_sync_time else None,
                "database_exists": os.path.exists(MESSAGES_DB_PATH)
            },
            "errors": bridge_status.error_message if bridge_status.error_message else None
        }
        
        return json.dumps(status_report, indent=2)
        
    except Exception as e:
        error_report = {
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "status": "Error retrieving sync status"
        }
        return json.dumps(error_report, indent=2)

# MCP-UI SDK implementation would go here when the package becomes available
# For now, we'll use the HTML-based status resource below

@mcp.resource("whatsapp://status-ui")
def get_status_ui_html() -> str:
    """HTML-based status UI resource as fallback if MCP-UI SDK is not available."""
    try:
        # Get current status data
        bridge_status = get_bridge_status()
        
        # Get database stats
        message_count = 0
        last_sync_time = None
        chat_count = 0
        db_size_mb = 0
        
        if os.path.exists(MESSAGES_DB_PATH):
            conn = sqlite3.connect(MESSAGES_DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM messages")
            message_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM chats")
            chat_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT MAX(timestamp) FROM messages")
            last_sync_result = cursor.fetchone()[0]
            if last_sync_result:
                last_sync_time = datetime.fromisoformat(last_sync_result)
            
            db_size_mb = round(os.path.getsize(MESSAGES_DB_PATH) / (1024 * 1024), 2)
            conn.close()
        
        # Create HTML status display
        overall_status = "Ready" if (bridge_status.is_running and bridge_status.api_responsive and bridge_status.is_authenticated) else "Not Ready"
        status_color = "#4CAF50" if overall_status == "Ready" else "#f44336"
        
        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin: 10px 0;">
                <h2 style="margin: 0 0 10px 0; color: #333;">WhatsApp MCP Status</h2>
                <p style="margin: 0 0 15px 0; color: #666; font-size: 14px;">Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <div style="display: inline-block; padding: 4px 12px; border-radius: 16px; background: {status_color}; color: white; font-size: 14px; font-weight: 500;">
                    {overall_status}
                </div>
            </div>
            
            <div style="background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin: 10px 0;">
                <h3 style="margin: 0 0 15px 0; color: #333;">Bridge Status</h3>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px;">
                    <div>
                        <div style="font-weight: 500; margin-bottom: 5px;">Process Running</div>
                        <div style="color: {'#4CAF50' if bridge_status.is_running else '#f44336'}">{'✅ Yes' if bridge_status.is_running else '❌ No'}</div>
                    </div>
                    <div>
                        <div style="font-weight: 500; margin-bottom: 5px;">Authenticated</div>
                        <div style="color: {'#4CAF50' if bridge_status.is_authenticated else '#f44336'}">{'✅ Yes' if bridge_status.is_authenticated else '❌ No'}</div>
                    </div>
                    <div>
                        <div style="font-weight: 500; margin-bottom: 5px;">API Responsive</div>
                        <div style="color: {'#4CAF50' if bridge_status.api_responsive else '#f44336'}">{'✅ Yes' if bridge_status.api_responsive else '❌ No'}</div>
                    </div>
                </div>
            </div>
            
            <div style="background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin: 10px 0;">
                <h3 style="margin: 0 0 15px 0; color: #333;">Sync Statistics</h3>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 15px; margin-bottom: 15px;">
                    <div>
                        <div style="font-weight: 500; margin-bottom: 5px;">Total Messages</div>
                        <div style="font-size: 24px; color: #007AFF; font-weight: 600;">{message_count:,}</div>
                    </div>
                    <div>
                        <div style="font-weight: 500; margin-bottom: 5px;">Total Chats</div>
                        <div style="font-size: 24px; color: #007AFF; font-weight: 600;">{chat_count}</div>
                    </div>
                    <div>
                        <div style="font-weight: 500; margin-bottom: 5px;">Database Size</div>
                        <div style="font-size: 24px; color: #007AFF; font-weight: 600;">{db_size_mb} MB</div>
                    </div>
                </div>
                <div>
                    <div style="font-weight: 500; margin-bottom: 5px;">Last Sync Time</div>
                    <div style="color: #666;">{last_sync_time.strftime('%Y-%m-%d %H:%M:%S') if last_sync_time else 'Never'}</div>
                </div>
            </div>
            
            {f'''<div style="background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin: 10px 0;">
                <h3 style="margin: 0 0 15px 0; color: #333;">Error Details</h3>
                <div style="color: #f44336; padding: 10px; background: #ffebee; border-radius: 6px;">
                    {bridge_status.error_message}
                </div>
            </div>''' if bridge_status.error_message else ''}
        </div>
        """
        
        return html
        
    except Exception as e:
        return f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <h2 style="margin: 0 0 10px 0; color: #f44336;">Status Error</h2>
                <p style="color: #666;">Failed to load status: {str(e)}</p>
            </div>
        </div>
        """

# UI action handler would be here when MCP-UI SDK becomes available

@mcp.tool()
@with_bridge_check
def get_sync_status() -> Dict[str, Any]:
    """Get comprehensive sync status including last sync time and statistics.
    
    Returns:
        A dictionary with sync status, timing, and database statistics
    """
    try:
        # Get bridge status
        bridge_status = get_bridge_status()
        
        # Get database stats and sync timing
        stats = {
            "message_count": 0,
            "chat_count": 0,
            "last_sync_time": None,
            "database_size_mb": 0,
            "database_exists": False
        }
        
        if os.path.exists(MESSAGES_DB_PATH):
            stats["database_exists"] = True
            stats["database_size_mb"] = round(os.path.getsize(MESSAGES_DB_PATH) / (1024 * 1024), 2)
            
            conn = sqlite3.connect(MESSAGES_DB_PATH)
            cursor = conn.cursor()
            
            # Get counts
            cursor.execute("SELECT COUNT(*) FROM messages")
            stats["message_count"] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM chats")
            stats["chat_count"] = cursor.fetchone()[0]
            
            # Get last activity (most recent message timestamp)
            cursor.execute("SELECT MAX(timestamp) FROM messages")
            last_message = cursor.fetchone()[0]
            if last_message:
                stats["last_sync_time"] = last_message
                
            conn.close()
        
        return {
            "sync_status": "Active" if bridge_status.is_running and bridge_status.is_authenticated else "Inactive",
            "bridge_status": {
                "running": bridge_status.is_running,
                "authenticated": bridge_status.is_authenticated,
                "api_responsive": bridge_status.api_responsive
            },
            "statistics": stats,
            "last_check": datetime.now().isoformat(),
            "error": bridge_status.error_message
        }
        
    except Exception as e:
        return {
            "sync_status": "Error",
            "error": str(e),
            "last_check": datetime.now().isoformat()
        }

@mcp.tool()
@with_bridge_check
def check_bridge_status() -> Dict[str, Any]:
    """Check the current status of the WhatsApp bridge and authentication.
    
    Returns:
        A dictionary containing the bridge status, authentication state, and any error messages
    """
    status = get_bridge_status()
    
    return {
        "bridge_running": status.is_running,
        "api_responsive": status.api_responsive,
        "authenticated": status.is_authenticated,
        "status": "Ready" if (status.is_running and status.api_responsive and status.is_authenticated) else "Not Ready",
        "error_message": status.error_message,
        "details": {
            "bridge_process": "Running" if status.is_running else "Stopped",
            "api_server": "Responsive" if status.api_responsive else "Not responding",
            "whatsapp_auth": "Authenticated" if status.is_authenticated else "Not authenticated"
        }
    }

if __name__ == "__main__":
    # Get transport mode from environment variable
    # Default to 'stdio' for backward compatibility with local installations
    # Docker environments should set MCP_TRANSPORT=sse
    transport_mode = os.environ.get('MCP_TRANSPORT', 'stdio')
    
    # Validate transport mode
    valid_transports = ['stdio', 'sse']
    if transport_mode not in valid_transports:
        print(f"Warning: Invalid MCP_TRANSPORT '{transport_mode}', defaulting to 'stdio'")
        transport_mode = 'stdio'
    
    print(f"Starting WhatsApp MCP server with {transport_mode} transport...")
    
    # Initialize and run the server
    if transport_mode == 'sse':
        # For SSE transport, specify port 3000 to avoid conflicts
        port = int(os.environ.get('MCP_PORT', 3000))
        print(f"SSE transport listening on port {port}")
    
    # Initialize and run the server
    mcp.run(transport=transport_mode, host="127.0.0.1", port=port)