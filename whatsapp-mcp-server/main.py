import os
from typing import List, Dict, Any, Optional, Union
from mcp.server.fastmcp import FastMCP, Image
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
from worker_client import transcribe as transcribe_file
from media import extract_frames, format_timestamp, load_image, probe as probe_video

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
def transcribe_audio(
    message_id: str,
    chat_jid: str,
    language: Optional[str] = None,
    translate_to_english: bool = False,
    with_timestamps: bool = False,
    model_size: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe a WhatsApp voice message or audio file to text, locally.

    Downloads the message media if needed, then runs speech-to-text with
    faster-whisper. The first call loads the model and may take a while.

    Args:
        message_id: The ID of the message containing the voice/audio
        chat_jid: The JID of the chat containing the message
        language: Optional ISO code hint (e.g. "ru", "en", "kk"); auto-detected if omitted
        translate_to_english: Return an English translation instead of the original language
        with_timestamps: Include per-segment start/end times
        model_size: Override the whisper model (e.g. "small", "large-v3")

    Returns:
        A dictionary with the transcript, detected language and run details
    """
    file_path = whatsapp_download_media(message_id, chat_jid)
    if not file_path:
        return {"success": False, "message": "Failed to download audio from the message"}

    result = transcribe_file(
        file_path,
        language=language,
        translate_to_english=translate_to_english,
        model_size=model_size,
        with_timestamps=with_timestamps,
    )
    result["file_path"] = file_path
    return result


@mcp.tool()
def transcribe_audio_file(
    audio_path: str,
    language: Optional[str] = None,
    translate_to_english: bool = False,
    with_timestamps: bool = False,
    model_size: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe a local audio file to text, without going through WhatsApp.

    Args:
        audio_path: Absolute path to an audio file (any format ffmpeg can read)
        language: Optional ISO code hint (e.g. "ru", "en", "kk"); auto-detected if omitted
        translate_to_english: Return an English translation instead of the original language
        with_timestamps: Include per-segment start/end times
        model_size: Override the whisper model (e.g. "small", "large-v3")

    Returns:
        A dictionary with the transcript, detected language and run details
    """
    return transcribe_file(
        audio_path,
        language=language,
        translate_to_english=translate_to_english,
        model_size=model_size,
        with_timestamps=with_timestamps,
    )


def _render_image(path: str, max_dimension: int) -> List[Union[str, Image]]:
    try:
        loaded = load_image(path, max_dimension=max_dimension)
    except Exception as e:
        return [f"Could not read the image: {e}"]

    size = (f"{loaded['width']}x{loaded['height']}"
            if loaded["width"] else "unknown size")
    return [f"Image ({size}, shown at up to {max_dimension}px):",
            Image(data=loaded["jpeg"], format="jpeg")]


def _render_video(path: str, max_frames: int, interval_seconds: Optional[float],
                  max_dimension: int, transcribe: bool, language: Optional[str],
                  mode: str) -> List[Union[str, Image]]:
    """Build the mixed text/image reply that lets the model actually watch a video."""
    result = extract_frames(
        path,
        max_frames=max_frames,
        interval_seconds=interval_seconds,
        max_dimension=max_dimension,
        mode=mode,
    )

    header = (
        f"Video: {result['duration_seconds']}s, {result['width']}x{result['height']}, "
        f"{result['fps']} fps. Showing {result['frame_count']} frames "
        f"({'at scene changes' if result['sampling'] == 'scenes' else 'sampled evenly'})."
    )
    parts: List[Union[str, Image]] = [header]

    if transcribe:
        if result["has_audio"]:
            spoken = transcribe_file(path, language=language)
            if spoken.get("success") and spoken.get("text"):
                parts.append(f"Transcript ({spoken['language']}): {spoken['text']}")
            elif spoken.get("success"):
                parts.append("Transcript: no speech detected.")
            else:
                parts.append(f"Transcript failed: {spoken.get('message')}")
        else:
            parts.append("This video has no audio track.")

    for frame in result["frames"]:
        parts.append(f"[{format_timestamp(frame['time'])}]")
        parts.append(Image(data=frame["jpeg"], format="jpeg"))

    if not result["frames"]:
        parts.append("No frames could be decoded from this video.")
    return parts


@mcp.tool()
def view_video(
    message_id: str,
    chat_jid: str,
    max_frames: int = 8,
    interval_seconds: Optional[float] = None,
    max_dimension: int = 640,
    transcribe: bool = True,
    language: Optional[str] = None,
    mode: str = "auto",
) -> List[Union[str, Image]]:
    """Watch a video message: returns frames as images plus a transcript of its audio.

    Frames are returned as image content rather than file paths, so the video can
    be seen directly. By default frames are taken at scene changes, falling back
    to even sampling for static or long videos.

    Args:
        message_id: The ID of the message containing the video
        chat_jid: The JID of the chat containing the message
        max_frames: Maximum number of frames to return (each one costs context)
        interval_seconds: Force a fixed interval between frames instead of automatic selection
        max_dimension: Longest side of each frame in pixels
        transcribe: Also transcribe the video's audio track locally
        language: Optional ISO code hint for the transcript (e.g. "ru", "en")
        mode: "auto", "scenes" or "interval" frame selection

    Returns:
        A list of text labels and frame images, in chronological order
    """
    file_path = whatsapp_download_media(message_id, chat_jid)
    if not file_path:
        return ["Failed to download the video from that message."]

    try:
        return _render_video(file_path, max_frames, interval_seconds, max_dimension,
                             transcribe, language, mode)
    except Exception as e:
        return [f"Could not inspect the video: {e}"]


@mcp.tool()
def view_video_file(
    video_path: str,
    max_frames: int = 8,
    interval_seconds: Optional[float] = None,
    max_dimension: int = 640,
    transcribe: bool = True,
    language: Optional[str] = None,
    mode: str = "auto",
) -> List[Union[str, Image]]:
    """Watch a local video file: returns frames as images plus a transcript of its audio.

    Args:
        video_path: Absolute path to a video file
        max_frames: Maximum number of frames to return (each one costs context)
        interval_seconds: Force a fixed interval between frames instead of automatic selection
        max_dimension: Longest side of each frame in pixels
        transcribe: Also transcribe the video's audio track locally
        language: Optional ISO code hint for the transcript (e.g. "ru", "en")
        mode: "auto", "scenes" or "interval" frame selection

    Returns:
        A list of text labels and frame images, in chronological order
    """
    if not os.path.isfile(video_path):
        return [f"File not found: {video_path}"]
    try:
        return _render_video(video_path, max_frames, interval_seconds, max_dimension,
                             transcribe, language, mode)
    except Exception as e:
        return [f"Could not inspect the video: {e}"]


@mcp.tool()
def view_image(
    message_id: str,
    chat_jid: str,
    max_dimension: int = 1024,
) -> List[Union[str, Image]]:
    """Look at an image message: returns the picture itself, not a file path.

    Args:
        message_id: The ID of the message containing the image
        chat_jid: The JID of the chat containing the message
        max_dimension: Longest side of the returned image in pixels

    Returns:
        A short description followed by the image
    """
    file_path = whatsapp_download_media(message_id, chat_jid)
    if not file_path:
        return ["Failed to download the image from that message."]
    return _render_image(file_path, max_dimension)


@mcp.tool()
def view_image_file(
    image_path: str,
    max_dimension: int = 1024,
) -> List[Union[str, Image]]:
    """Look at a local image file: returns the picture itself, not a file path.

    Args:
        image_path: Absolute path to an image file
        max_dimension: Longest side of the returned image in pixels

    Returns:
        A short description followed by the image
    """
    if not os.path.isfile(image_path):
        return [f"File not found: {image_path}"]
    return _render_image(image_path, max_dimension)


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')