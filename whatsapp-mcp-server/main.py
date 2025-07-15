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
    download_media as whatsapp_download_media
)
import re
import uuid
import time

# Initialize FastMCP server
mcp = FastMCP("whatsapp")

# Global storage for pending messages (in production, use persistent storage)
_pending_messages = {}
_pending_files = {}
_pending_audio = {}

# Configuration
REQUIRE_CONFIRMATION = True  # Set to False to disable confirmation requirement

@mcp.tool()
def search_contacts(query: str) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number.
    
    Args:
        query: Search term to match against contact names or phone numbers
    """
    contacts = whatsapp_search_contacts(query)
    
    # Convert Contact dataclass objects to dictionaries
    result = []
    for contact in contacts:
        contact_dict = {
            "phone_number": contact.phone_number,
            "name": contact.name,
            "jid": contact.jid
        }
        result.append(contact_dict)
    
    return result

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
    
    # Convert Message dataclass objects to dictionaries
    result = []
    for message in messages:
        message_dict = {
            "timestamp": message.timestamp.isoformat(),
            "sender": message.sender,
            "content": message.content,
            "is_from_me": message.is_from_me,
            "chat_jid": message.chat_jid,
            "id": message.id,
            "chat_name": message.chat_name,
            "media_type": message.media_type
        }
        result.append(message_dict)
    
    return result

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
    
    # Convert Chat dataclass objects to dictionaries and enhance with group type information
    result = []
    for chat in chats:
        # Convert Chat dataclass to dictionary
        chat_dict = {
            "jid": chat.jid,
            "name": chat.name,
            "last_message_time": chat.last_message_time.isoformat() if chat.last_message_time else None,
            "last_message": chat.last_message,
            "last_sender": chat.last_sender,
            "last_is_from_me": chat.last_is_from_me,
            "is_group": chat.is_group
        }
        
        # Add group compatibility information
        compatibility_info = check_group_compatibility(chat.jid)
        chat_dict["group_type"] = compatibility_info["type"]
        chat_dict["compatible"] = compatibility_info["compatible"]
        chat_dict["group_description"] = compatibility_info["description"]
        
        result.append(chat_dict)
    
    return result

@mcp.tool()
def get_chat(chat_jid: str, include_last_message: bool = True) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by JID.
    
    Args:
        chat_jid: The JID of the chat to retrieve
        include_last_message: Whether to include the last message (default True)
    """
    chat = whatsapp_get_chat(chat_jid, include_last_message)
    if chat is None:
        return {
            "success": False,
            "message": f"Chat with JID {chat_jid} not found"
        }
    
    # Convert Chat dataclass to dictionary
    chat_dict = {
        "jid": chat.jid,
        "name": chat.name,
        "last_message_time": chat.last_message_time.isoformat() if chat.last_message_time else None,
        "last_message": chat.last_message,
        "last_sender": chat.last_sender,
        "last_is_from_me": chat.last_is_from_me,
        "is_group": chat.is_group
    }
    
    # Add group compatibility information
    compatibility_info = check_group_compatibility(chat.jid)
    chat_dict["group_type"] = compatibility_info["type"]
    chat_dict["compatible"] = compatibility_info["compatible"]
    chat_dict["group_description"] = compatibility_info["description"]
    
    return chat_dict

@mcp.tool()
def get_direct_chat_by_contact(sender_phone_number: str) -> Dict[str, Any]:
    """Get WhatsApp chat metadata by sender phone number.
    
    Args:
        sender_phone_number: The phone number to search for
    """
    chat = whatsapp_get_direct_chat_by_contact(sender_phone_number)
    if chat is None:
        return {
            "success": False,
            "message": f"Chat with contact {sender_phone_number} not found"
        }
    
    # Convert Chat dataclass to dictionary
    chat_dict = {
        "jid": chat.jid,
        "name": chat.name,
        "last_message_time": chat.last_message_time.isoformat() if chat.last_message_time else None,
        "last_message": chat.last_message,
        "last_sender": chat.last_sender,
        "last_is_from_me": chat.last_is_from_me,
        "is_group": chat.is_group
    }
    
    # Add group compatibility information
    compatibility_info = check_group_compatibility(chat.jid)
    chat_dict["group_type"] = compatibility_info["type"]
    chat_dict["compatible"] = compatibility_info["compatible"]
    chat_dict["group_description"] = compatibility_info["description"]
    
    return chat_dict

@mcp.tool()
def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Dict[str, Any]]:
    """Get all WhatsApp chats involving the contact.
    
    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    chats = whatsapp_get_contact_chats(jid, limit, page)
    
    # Convert Chat dataclass objects to dictionaries
    result = []
    for chat in chats:
        chat_dict = {
            "jid": chat.jid,
            "name": chat.name,
            "last_message_time": chat.last_message_time.isoformat() if chat.last_message_time else None,
            "last_message": chat.last_message,
            "last_sender": chat.last_sender,
            "last_is_from_me": chat.last_is_from_me,
            "is_group": chat.is_group
        }
        
        # Add group compatibility information
        compatibility_info = check_group_compatibility(chat.jid)
        chat_dict["group_type"] = compatibility_info["type"]
        chat_dict["compatible"] = compatibility_info["compatible"]
        chat_dict["group_description"] = compatibility_info["description"]
        
        result.append(chat_dict)
    
    return result

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
    try:
        context = whatsapp_get_message_context(message_id, before, after)
        
        # Convert MessageContext dataclass to dictionary
        def message_to_dict(msg):
            return {
                "timestamp": msg.timestamp.isoformat(),
                "sender": msg.sender,
                "content": msg.content,
                "is_from_me": msg.is_from_me,
                "chat_jid": msg.chat_jid,
                "id": msg.id,
                "chat_name": msg.chat_name,
                "media_type": msg.media_type
            }
        
        return {
            "success": True,
            "message": message_to_dict(context.message),
            "before": [message_to_dict(msg) for msg in context.before],
            "after": [message_to_dict(msg) for msg in context.after]
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error getting message context: {str(e)}"
        }

def _get_recipient_info(recipient: str) -> Dict[str, Any]:
    """Get human-readable information about a recipient."""
    # Try to get contact info
    try:
        if "@" not in recipient:
            # Phone number format - try to find contact name
            contacts = whatsapp_search_contacts(recipient)
            if contacts:
                contact = contacts[0]
                # contact is a Contact dataclass object
                return {
                    "display_name": contact.name if contact.name else f"Unknown ({recipient})",
                    "jid": contact.jid,
                    "phone": recipient
                }
        else:
            # JID format - try to get chat info
            chat = whatsapp_get_chat(recipient, include_last_message=False)
            if chat:
                # chat is a Chat dataclass object
                return {
                    "display_name": chat.name if chat.name else "Unknown Chat",
                    "jid": recipient,
                    "phone": recipient.split("@")[0] if "@s.whatsapp.net" in recipient else None
                }
    except:
        pass
    
    # Fallback to basic info
    if "@s.whatsapp.net" in recipient:
        phone = recipient.split("@")[0]
        return {
            "display_name": f"Contact ({phone})",
            "jid": recipient,
            "phone": phone
        }
    elif "@g.us" in recipient:
        return {
            "display_name": "Group Chat",
            "jid": recipient,
            "phone": None
        }
    else:
        return {
            "display_name": f"Contact ({recipient})",
            "jid": f"{recipient}@s.whatsapp.net",
            "phone": recipient
        }

@mcp.tool()
def preview_message(
    recipient: str,
    message: str
) -> Dict[str, Any]:
    """Preview a WhatsApp message before sending. Shows what will be sent and to whom.
    
    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        message: The message text to send
    
    Returns:
        A preview of the message with recipient information and next steps
    """
    if not recipient:
        return {
            "success": False,
            "message": "Recipient must be provided"
        }
    
    if not message:
        return {
            "success": False,
            "message": "Message must be provided"
        }
    
    # Get recipient information
    recipient_info = _get_recipient_info(recipient)
    
    # Check group compatibility
    compatibility = check_group_compatibility(recipient_info["jid"])
    
    # Generate preview ID
    preview_id = str(uuid.uuid4())[:8]
    
    # Store pending message
    _pending_messages[preview_id] = {
        "recipient": recipient,
        "message": message,
        "recipient_info": recipient_info,
        "timestamp": time.time()
    }
    
    # Clean up old pending messages (older than 5 minutes)
    current_time = time.time()
    expired_keys = [k for k, v in _pending_messages.items() if current_time - v["timestamp"] > 300]
    for key in expired_keys:
        del _pending_messages[key]
    
    return {
        "success": True,
        "preview_id": preview_id,
        "recipient_display": recipient_info["display_name"],
        "recipient_jid": recipient_info["jid"],
        "recipient_phone": recipient_info["phone"],
        "message_preview": message,
        "group_compatibility": compatibility,
        "instructions": f"To send this message, use confirm_and_send_message with preview_id: {preview_id}",
        "warning": "⚠️  Message will be sent immediately after confirmation!"
    }

@mcp.tool()
def confirm_and_send_message(preview_id: str) -> Dict[str, Any]:
    """Confirm and send a previously previewed WhatsApp message.
    
    Args:
        preview_id: The preview ID from preview_message
    
    Returns:
        Result of sending the message
    """
    if preview_id not in _pending_messages:
        return {
            "success": False,
            "message": f"Preview ID {preview_id} not found or expired. Please use preview_message first."
        }
    
    pending = _pending_messages[preview_id]
    
    # Remove from pending (can only be used once)
    del _pending_messages[preview_id]
    
    # Send the message
    success, status_message = whatsapp_send_message(pending["recipient"], pending["message"])
    
    return {
        "success": success,
        "message": status_message,
        "sent_to": pending["recipient_info"]["display_name"],
        "sent_message": pending["message"]
    }

@mcp.tool()
def list_pending_messages() -> Dict[str, Any]:
    """List all pending messages waiting for confirmation.
    
    Returns:
        List of pending messages with their preview IDs
    """
    if not _pending_messages:
        return {
            "success": True,
            "pending_count": 0,
            "message": "No pending messages"
        }
    
    pending_list = []
    for preview_id, pending in _pending_messages.items():
        pending_list.append({
            "preview_id": preview_id,
            "recipient": pending["recipient_info"]["display_name"],
            "message_preview": pending["message"][:100] + ("..." if len(pending["message"]) > 100 else ""),
            "created_ago_seconds": int(time.time() - pending["timestamp"])
        })
    
    return {
        "success": True,
        "pending_count": len(pending_list),
        "pending_messages": pending_list
    }

@mcp.tool()
def cancel_pending_message(preview_id: str) -> Dict[str, Any]:
    """Cancel a pending message.
    
    Args:
        preview_id: The preview ID to cancel
    
    Returns:
        Confirmation of cancellation
    """
    if preview_id not in _pending_messages:
        return {
            "success": False,
            "message": f"Preview ID {preview_id} not found"
        }
    
    pending = _pending_messages[preview_id]
    del _pending_messages[preview_id]
    
    return {
        "success": True,
        "message": f"Cancelled pending message to {pending['recipient_info']['display_name']}"
    }

@mcp.tool()
def send_message(
    recipient: str,
    message: str
) -> Dict[str, Any]:
    """Send a WhatsApp message to a person or group. For group chats use the JID.
    
    ⚠️  SAFETY WARNING: This function requires explicit confirmation before sending!
    
    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        message: The message text to send
    
    Returns:
        Instructions to preview and confirm the message before sending
    """
    # Always use preview system for safety
    if REQUIRE_CONFIRMATION:
        preview_result = preview_message(recipient, message)
        if preview_result["success"]:
            return {
                "success": True,
                "message": "Message prepared for sending. Please review the details below and confirm.",
                "preview": preview_result,
                "next_step": f"Use 'confirm_and_send_message' with preview_id '{preview_result['preview_id']}' to send",
                "safety_note": "⚠️  This prevents accidental message sending. The message will only be sent after explicit confirmation."
            }
        else:
            return preview_result
    else:
        # Direct sending (when confirmation is disabled)
        if not recipient:
            return {
                "success": False,
                "message": "Recipient must be provided"
            }
        
        success, status_message = whatsapp_send_message(recipient, message)
        return {
            "success": success,
            "message": status_message
        }

@mcp.tool()
def preview_file(
    recipient: str,
    media_path: str
) -> Dict[str, Any]:
    """Preview a file sending operation before sending.
    
    Args:
        recipient: The recipient - either a phone number or JID
        media_path: The absolute path to the media file to send
    
    Returns:
        A preview of the file sending operation
    """
    if not recipient:
        return {
            "success": False,
            "message": "Recipient must be provided"
        }
    
    if not media_path:
        return {
            "success": False,
            "message": "Media path must be provided"
        }
    
    import os
    if not os.path.isfile(media_path):
        return {
            "success": False,
            "message": f"Media file not found: {media_path}"
        }
    
    # Get recipient information
    recipient_info = _get_recipient_info(recipient)
    
    # Check group compatibility
    compatibility = check_group_compatibility(recipient_info["jid"])
    
    # Generate preview ID
    preview_id = str(uuid.uuid4())[:8]
    
    # Store pending file
    _pending_files[preview_id] = {
        "recipient": recipient,
        "media_path": media_path,
        "recipient_info": recipient_info,
        "timestamp": time.time()
    }
    
    # Clean up old pending files
    current_time = time.time()
    expired_keys = [k for k, v in _pending_files.items() if current_time - v["timestamp"] > 300]
    for key in expired_keys:
        del _pending_files[key]
    
    # Get file info
    file_size = os.path.getsize(media_path)
    file_name = os.path.basename(media_path)
    
    return {
        "success": True,
        "preview_id": preview_id,
        "recipient_display": recipient_info["display_name"],
        "recipient_jid": recipient_info["jid"],
        "file_path": media_path,
        "file_name": file_name,
        "file_size_bytes": file_size,
        "file_size_mb": round(file_size / (1024 * 1024), 2),
        "group_compatibility": compatibility,
        "instructions": f"To send this file, use confirm_and_send_file with preview_id: {preview_id}",
        "warning": "⚠️  File will be sent immediately after confirmation!"
    }

@mcp.tool()
def confirm_and_send_file(preview_id: str) -> Dict[str, Any]:
    """Confirm and send a previously previewed file.
    
    Args:
        preview_id: The preview ID from preview_file
    
    Returns:
        Result of sending the file
    """
    if preview_id not in _pending_files:
        return {
            "success": False,
            "message": f"Preview ID {preview_id} not found or expired. Please use preview_file first."
        }
    
    pending = _pending_files[preview_id]
    
    # Remove from pending (can only be used once)
    del _pending_files[preview_id]
    
    # Send the file
    success, status_message = whatsapp_send_file(pending["recipient"], pending["media_path"])
    
    return {
        "success": success,
        "message": status_message,
        "sent_to": pending["recipient_info"]["display_name"],
        "sent_file": pending["media_path"]
    }

@mcp.tool()
def send_file(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send a file such as a picture, raw audio, video or document via WhatsApp to the specified recipient. For group messages use the JID.
    
    ⚠️  SAFETY WARNING: This function requires explicit confirmation before sending!
    
    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        media_path: The absolute path to the media file to send (image, video, document)
    
    Returns:
        Instructions to preview and confirm the file before sending
    """
    # Always use preview system for safety
    if REQUIRE_CONFIRMATION:
        preview_result = preview_file(recipient, media_path)
        if preview_result["success"]:
            return {
                "success": True,
                "message": "File prepared for sending. Please review the details below and confirm.",
                "preview": preview_result,
                "next_step": f"Use 'confirm_and_send_file' with preview_id '{preview_result['preview_id']}' to send",
                "safety_note": "⚠️  This prevents accidental file sending. The file will only be sent after explicit confirmation."
            }
        else:
            return preview_result
    else:
        # Direct sending (when confirmation is disabled)
        success, status_message = whatsapp_send_file(recipient, media_path)
        return {
            "success": success,
            "message": status_message
        }

@mcp.tool()
def send_audio_message(recipient: str, media_path: str) -> Dict[str, Any]:
    """Send any audio file as a WhatsApp audio message to the specified recipient. For group messages use the JID. If it errors due to ffmpeg not being installed, use send_file instead.
    
    ⚠️  SAFETY WARNING: This function requires explicit confirmation before sending!
    
    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                 or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us")
        media_path: The absolute path to the audio file to send (will be converted to Opus .ogg if it's not a .ogg file)
    
    Returns:
        Instructions to preview and confirm the audio before sending
    """
    # Always use preview system for safety
    if REQUIRE_CONFIRMATION:
        # Use the same preview system as files, but for audio
        preview_result = preview_file(recipient, media_path)
        if preview_result["success"]:
            # Store as audio instead of file
            preview_id = preview_result["preview_id"]
            if preview_id in _pending_files:
                _pending_audio[preview_id] = _pending_files[preview_id]
                del _pending_files[preview_id]
            
            return {
                "success": True,
                "message": "Audio file prepared for sending. Please review the details below and confirm.",
                "preview": preview_result,
                "next_step": f"Use 'confirm_and_send_audio' with preview_id '{preview_id}' to send",
                "safety_note": "⚠️  This prevents accidental audio sending. The audio will only be sent after explicit confirmation.",
                "audio_note": "Audio will be converted to Opus .ogg format if needed."
            }
        else:
            return preview_result
    else:
        # Direct sending (when confirmation is disabled)
        success, status_message = whatsapp_audio_voice_message(recipient, media_path)
        return {
            "success": success,
            "message": status_message
        }

@mcp.tool()
def confirm_and_send_audio(preview_id: str) -> Dict[str, Any]:
    """Confirm and send a previously previewed audio file.
    
    Args:
        preview_id: The preview ID from send_audio_message
    
    Returns:
        Result of sending the audio
    """
    if preview_id not in _pending_audio:
        return {
            "success": False,
            "message": f"Preview ID {preview_id} not found or expired. Please use send_audio_message first."
        }
    
    pending = _pending_audio[preview_id]
    
    # Remove from pending (can only be used once)
    del _pending_audio[preview_id]
    
    # Send the audio
    success, status_message = whatsapp_audio_voice_message(pending["recipient"], pending["media_path"])
    
    return {
        "success": success,
        "message": status_message,
        "sent_to": pending["recipient_info"]["display_name"],
        "sent_audio": pending["media_path"]
    }

@mcp.tool()
def get_safety_status() -> Dict[str, Any]:
    """Get the current safety configuration and pending operations status.
    
    Returns:
        Current safety settings and pending operations summary
    """
    pending_counts = {
        "messages": len(_pending_messages),
        "files": len(_pending_files),
        "audio": len(_pending_audio)
    }
    
    total_pending = sum(pending_counts.values())
    
    return {
        "confirmation_required": REQUIRE_CONFIRMATION,
        "safety_mode": "ENABLED" if REQUIRE_CONFIRMATION else "DISABLED",
        "pending_operations": pending_counts,
        "total_pending": total_pending,
        "description": {
            "ENABLED": "All send operations require explicit preview and confirmation",
            "DISABLED": "Send operations execute immediately (NOT RECOMMENDED)"
        }[("ENABLED" if REQUIRE_CONFIRMATION else "DISABLED")],
        "available_tools": [
            "preview_message + confirm_and_send_message",
            "preview_file + confirm_and_send_file", 
            "send_audio_message + confirm_and_send_audio",
            "list_pending_messages",
            "cancel_pending_message"
        ] if REQUIRE_CONFIRMATION else [
            "send_message (direct)",
            "send_file (direct)",
            "send_audio_message (direct)"
        ]
    }

@mcp.tool()
def toggle_safety_mode() -> Dict[str, Any]:
    """Toggle the safety confirmation requirement on/off.
    
    Returns:
        New safety status
    """
    global REQUIRE_CONFIRMATION
    REQUIRE_CONFIRMATION = not REQUIRE_CONFIRMATION
    
    # Clear pending operations when disabling safety
    if not REQUIRE_CONFIRMATION:
        cleared_counts = {
            "messages": len(_pending_messages),
            "files": len(_pending_files),
            "audio": len(_pending_audio)
        }
        _pending_messages.clear()
        _pending_files.clear()
        _pending_audio.clear()
        
        return {
            "success": True,
            "new_mode": "DISABLED",
            "warning": "⚠️  SAFETY DISABLED: Send operations will execute immediately!",
            "cleared_pending": cleared_counts,
            "recommendation": "Consider re-enabling safety mode for production use"
        }
    else:
        return {
            "success": True,
            "new_mode": "ENABLED", 
            "message": "✅ SAFETY ENABLED: All send operations now require confirmation",
            "benefit": "This prevents accidental message sending"
        }

@mcp.tool()
def clear_all_pending() -> Dict[str, Any]:
    """Clear all pending operations (messages, files, audio).
    
    Returns:
        Summary of cleared operations
    """
    cleared_counts = {
        "messages": len(_pending_messages),
        "files": len(_pending_files),
        "audio": len(_pending_audio)
    }
    
    _pending_messages.clear()
    _pending_files.clear()
    _pending_audio.clear()
    
    total_cleared = sum(cleared_counts.values())
    
    return {
        "success": True,
        "message": f"Cleared {total_cleared} pending operations",
        "cleared": cleared_counts
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
def check_group_compatibility(jid: str) -> Dict[str, Any]:
    """Check WhatsApp group/chat compatibility and identify the type.
    
    Args:
        jid: The JID (e.g., "123456789@s.whatsapp.net" or "123456789@g.us") to check
    
    Returns:
        Information about the group type and compatibility status
    """
    
    # Parse the JID to determine type
    if "@s.whatsapp.net" in jid:
        return {
            "type": "personal",
            "compatible": True,
            "description": "Individual WhatsApp contact",
            "jid": jid,
            "recommendations": ["This is a personal chat and should work reliably"]
        }
    elif "@g.us" in jid:
        user_part = jid.split("@")[0]
        
        # Check for WhatsApp Community format
        if user_part.startswith("120363"):
            return {
                "type": "community",
                "compatible": False,
                "description": "WhatsApp Community (newer group format)",
                "jid": jid,
                "recommendations": [
                    "Communities with this format may not work reliably",
                    "Try creating a traditional WhatsApp group instead",
                    "Send messages to individual members as a workaround",
                    "Check for whatsmeow library updates"
                ]
            }
        elif "-" in user_part:
            return {
                "type": "traditional_group",
                "compatible": True,
                "description": "Traditional WhatsApp group",
                "jid": jid,
                "recommendations": ["This is a traditional group and should work reliably"]
            }
        else:
            return {
                "type": "unknown_group",
                "compatible": False,
                "description": "Unknown group format",
                "jid": jid,
                "recommendations": ["Unknown group format - proceed with caution"]
            }
    else:
        return {
            "type": "unknown",
            "compatible": False,
            "description": "Unknown JID format",
            "jid": jid,
            "recommendations": ["Unknown JID format - this may not be a valid WhatsApp identifier"]
        }

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')