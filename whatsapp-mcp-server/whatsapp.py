import sqlite3
import time
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
import os.path
import requests
import json
import audio

MESSAGES_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'messages.db')
WHATSMEOW_DB_PATH = os.path.join(os.path.dirname(MESSAGES_DB_PATH), 'whatsapp.db')
WHATSAPP_API_BASE_URL = "http://localhost:8080/api"


def _load_lid_map() -> Dict[str, str]:
    """{lid_user: pn_user} from whatsmeow's authoritative LID<->phone table."""
    m: Dict[str, str] = {}
    try:
        conn = sqlite3.connect(f"file:{WHATSMEOW_DB_PATH}?mode=ro", uri=True)
        for lid, pn in conn.execute("SELECT lid, pn FROM whatsmeow_lid_map"):
            m[lid] = pn
        conn.close()
    except sqlite3.Error:
        pass
    return m


def alias_jids(jid: Optional[str]) -> List[str]:
    """Every equivalent chat JID for `jid`: itself plus its LID<->phone alias.
    WhatsApp addresses the same person by both a phone JID (…@s.whatsapp.net) and a
    LID (…@lid). Querying the union lets a lookup by EITHER key hit the same
    (possibly merged) thread — the two identifiers are mirrors of each other."""
    if not jid or '@' not in jid:
        return [jid] if jid else []
    user, _, server = jid.partition('@')
    out = [jid]
    lm = _load_lid_map()
    if server == 'lid':
        pn = lm.get(user)
        if pn:
            out.append(f"{pn}@s.whatsapp.net")
    elif server == 's.whatsapp.net':
        for lid, pn in lm.items():
            if pn == user:
                out.append(f"{lid}@lid")
                break
    return out


def _jid_in(col: str, jid: str) -> Tuple[str, List[str]]:
    """('col IN (?,?)', [aliases]) matching a chat column against every alias of jid."""
    aj = alias_jids(jid)
    if not aj:
        return f"{col} = ?", [jid]
    return f"{col} IN ({','.join('?' for _ in aj)})", aj

@dataclass
class Message:
    timestamp: datetime
    sender: str
    content: str
    is_from_me: bool
    chat_jid: str
    id: str
    chat_name: Optional[str] = None
    media_type: Optional[str] = None

@dataclass
class Chat:
    jid: str
    name: Optional[str]
    last_message_time: Optional[datetime]
    last_message: Optional[str] = None
    last_sender: Optional[str] = None
    last_is_from_me: Optional[bool] = None

    @property
    def is_group(self) -> bool:
        """Determine if chat is a group based on JID pattern."""
        return self.jid.endswith("@g.us")

@dataclass
class Contact:
    phone_number: str
    name: Optional[str]
    jid: str

@dataclass
class MessageContext:
    message: Message
    before: List[Message]
    after: List[Message]

def get_sender_name(sender_jid: str) -> str:
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # First try matching by exact JID (or its LID<->phone alias)
        _in, _p = _jid_in("jid", sender_jid)
        cursor.execute(f"""
            SELECT name
            FROM chats
            WHERE {_in} AND name IS NOT NULL AND name != ''
            LIMIT 1
        """, _p)
        
        result = cursor.fetchone()
        
        # If no result, try looking for the number within JIDs
        if not result:
            # Extract the phone number part if it's a JID
            if '@' in sender_jid:
                phone_part = sender_jid.split('@')[0]
            else:
                phone_part = sender_jid
                
            cursor.execute("""
                SELECT name
                FROM chats
                WHERE jid LIKE ?
                LIMIT 1
            """, (f"%{phone_part}%",))
            
            result = cursor.fetchone()
        
        if result and result[0]:
            return result[0]
        else:
            return sender_jid
        
    except sqlite3.Error as e:
        print(f"Database error while getting sender name: {e}")
        return sender_jid
    finally:
        if 'conn' in locals():
            conn.close()

def format_message(message: Message, show_chat_info: bool = True) -> None:
    """Print a single message with consistent formatting."""
    output = ""
    
    if show_chat_info and message.chat_name:
        output += f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] Chat: {message.chat_name} "
    else:
        output += f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] "
        
    content_prefix = ""
    if hasattr(message, 'media_type') and message.media_type:
        content_prefix = f"[{message.media_type} - Message ID: {message.id} - Chat JID: {message.chat_jid}] "
    
    try:
        sender_name = get_sender_name(message.sender) if not message.is_from_me else "Me"
        output += f"From: {sender_name}: {content_prefix}{message.content}\n"
    except Exception as e:
        print(f"Error formatting message: {e}")
    return output

def format_messages_list(messages: List[Message], show_chat_info: bool = True) -> None:
    output = ""
    if not messages:
        output += "No messages to display."
        return output
    
    for message in messages:
        output += format_message(message, show_chat_info)
    return output

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
) -> List[Message]:
    """Get messages matching the specified criteria with optional context."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # Build base query
        query_parts = ["SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type FROM messages"]
        query_parts.append("JOIN chats ON messages.chat_jid = chats.jid")
        where_clauses = []
        params = []
        
        # Add filters
        if after:
            try:
                after = datetime.fromisoformat(after)
            except ValueError:
                raise ValueError(f"Invalid date format for 'after': {after}. Please use ISO-8601 format.")
            
            where_clauses.append("messages.timestamp > ?")
            params.append(after)

        if before:
            try:
                before = datetime.fromisoformat(before)
            except ValueError:
                raise ValueError(f"Invalid date format for 'before': {before}. Please use ISO-8601 format.")
            
            where_clauses.append("messages.timestamp < ?")
            params.append(before)

        if sender_phone_number:
            where_clauses.append("messages.sender = ?")
            params.append(sender_phone_number)
            
        if chat_jid:
            _in, _p = _jid_in("messages.chat_jid", chat_jid)
            where_clauses.append(_in)
            params.extend(_p)
            
        if query:
            where_clauses.append("LOWER(messages.content) LIKE LOWER(?)")
            params.append(f"%{query}%")
            
        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))
            
        # Add pagination
        offset = page * limit
        query_parts.append("ORDER BY messages.timestamp DESC")
        query_parts.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        
        cursor.execute(" ".join(query_parts), tuple(params))
        messages = cursor.fetchall()
        
        result = []
        for msg in messages:
            message = Message(
                timestamp=datetime.fromisoformat(msg[0]),
                sender=msg[1],
                chat_name=msg[2],
                content=msg[3],
                is_from_me=msg[4],
                chat_jid=msg[5],
                id=msg[6],
                media_type=msg[7]
            )
            result.append(message)
            
        if include_context and result:
            # Add context for each message
            messages_with_context = []
            for msg in result:
                context = get_message_context(msg.id, context_before, context_after)
                messages_with_context.extend(context.before)
                messages_with_context.append(context.message)
                messages_with_context.extend(context.after)
            
            return format_messages_list(messages_with_context, show_chat_info=True)
            
        # Format and display messages without context
        return format_messages_list(result, show_chat_info=True)    
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()


def get_message_context(
    message_id: str,
    before: int = 5,
    after: int = 5
) -> MessageContext:
    """Get context around a specific message."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # Get the target message first
        cursor.execute("""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.chat_jid, messages.media_type
            FROM messages
            JOIN chats ON messages.chat_jid = chats.jid
            WHERE messages.id = ?
        """, (message_id,))
        msg_data = cursor.fetchone()
        
        if not msg_data:
            raise ValueError(f"Message with ID {message_id} not found")
            
        target_message = Message(
            timestamp=datetime.fromisoformat(msg_data[0]),
            sender=msg_data[1],
            chat_name=msg_data[2],
            content=msg_data[3],
            is_from_me=msg_data[4],
            chat_jid=msg_data[5],
            id=msg_data[6],
            media_type=msg_data[8]
        )
        
        # Get messages before
        cursor.execute("""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type
            FROM messages
            JOIN chats ON messages.chat_jid = chats.jid
            WHERE messages.chat_jid = ? AND messages.timestamp < ?
            ORDER BY messages.timestamp DESC
            LIMIT ?
        """, (msg_data[7], msg_data[0], before))
        
        before_messages = []
        for msg in cursor.fetchall():
            before_messages.append(Message(
                timestamp=datetime.fromisoformat(msg[0]),
                sender=msg[1],
                chat_name=msg[2],
                content=msg[3],
                is_from_me=msg[4],
                chat_jid=msg[5],
                id=msg[6],
                media_type=msg[7]
            ))
        
        # Get messages after
        cursor.execute("""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type
            FROM messages
            JOIN chats ON messages.chat_jid = chats.jid
            WHERE messages.chat_jid = ? AND messages.timestamp > ?
            ORDER BY messages.timestamp ASC
            LIMIT ?
        """, (msg_data[7], msg_data[0], after))
        
        after_messages = []
        for msg in cursor.fetchall():
            after_messages.append(Message(
                timestamp=datetime.fromisoformat(msg[0]),
                sender=msg[1],
                chat_name=msg[2],
                content=msg[3],
                is_from_me=msg[4],
                chat_jid=msg[5],
                id=msg[6],
                media_type=msg[7]
            ))
        
        return MessageContext(
            message=target_message,
            before=before_messages,
            after=after_messages
        )
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()


def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active"
) -> List[Chat]:
    """Get chats matching the specified criteria."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # Build base query
        query_parts = ["""
            SELECT 
                chats.jid,
                chats.name,
                chats.last_message_time,
                messages.content as last_message,
                messages.sender as last_sender,
                messages.is_from_me as last_is_from_me
            FROM chats
        """]
        
        if include_last_message:
            query_parts.append("""
                LEFT JOIN messages ON chats.jid = messages.chat_jid 
                AND chats.last_message_time = messages.timestamp
            """)
            
        where_clauses = []
        params = []
        
        if query:
            where_clauses.append("(LOWER(chats.name) LIKE LOWER(?) OR chats.jid LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
            
        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))
            
        # Add sorting
        order_by = "chats.last_message_time DESC" if sort_by == "last_active" else "chats.name"
        query_parts.append(f"ORDER BY {order_by}")
        
        # Add pagination
        offset = (page ) * limit
        query_parts.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        
        cursor.execute(" ".join(query_parts), tuple(params))
        chats = cursor.fetchall()
        
        result = []
        for chat_data in chats:
            chat = Chat(
                jid=chat_data[0],
                name=chat_data[1],
                last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
                last_message=chat_data[3],
                last_sender=chat_data[4],
                last_is_from_me=chat_data[5]
            )
            result.append(chat)
            
        return result
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()


def search_contacts(query: str) -> List[Contact]:
    """Search contacts by name or phone number."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # Split query into characters to support partial matching
        search_pattern = '%' +query + '%'
        
        cursor.execute("""
            SELECT DISTINCT 
                jid,
                name
            FROM chats
            WHERE 
                (LOWER(name) LIKE LOWER(?) OR LOWER(jid) LIKE LOWER(?))
                AND jid NOT LIKE '%@g.us'
            ORDER BY name, jid
            LIMIT 50
        """, (search_pattern, search_pattern))
        
        contacts = cursor.fetchall()

        # Load LID-to-phone mapping for resolving real phone numbers
        lid_map = {}
        try:
            wa_db_path = os.path.join(os.path.dirname(MESSAGES_DB_PATH), 'whatsapp.db')
            wa_conn = sqlite3.connect(wa_db_path)
            wa_cursor = wa_conn.cursor()
            wa_cursor.execute("SELECT lid, pn FROM whatsmeow_lid_map")
            for lid, pn in wa_cursor.fetchall():
                lid_map[lid] = pn
            wa_conn.close()
        except sqlite3.Error:
            pass

        result = []
        for contact_data in contacts:
            jid = contact_data[0]
            lid_part = jid.split('@')[0]
            phone = lid_map.get(lid_part, lid_part) if '@lid' in jid else lid_part
            contact = Contact(
                phone_number=phone,
                name=contact_data[1],
                jid=jid
            )
            result.append(contact)
            
        return result
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()


def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Chat]:
    """Get all chats involving the contact.
    
    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        cin, cp = _jid_in("c.jid", jid)
        cursor.execute("""
            SELECT DISTINCT
                c.jid,
                c.name,
                c.last_message_time,
                m.content as last_message,
                m.sender as last_sender,
                m.is_from_me as last_is_from_me
            FROM chats c
            JOIN messages m ON c.jid = m.chat_jid
            WHERE m.sender = ? OR {cin}
            ORDER BY c.last_message_time DESC
            LIMIT ? OFFSET ?
        """.format(cin=cin), (jid, *cp, limit, page * limit))
        
        chats = cursor.fetchall()
        
        result = []
        for chat_data in chats:
            chat = Chat(
                jid=chat_data[0],
                name=chat_data[1],
                last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
                last_message=chat_data[3],
                last_sender=chat_data[4],
                last_is_from_me=chat_data[5]
            )
            result.append(chat)
            
        return result
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()


def get_last_interaction(jid: str) -> str:
    """Get most recent message involving the contact."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        cin, cp = _jid_in("c.jid", jid)
        cursor.execute("""
            SELECT
                m.timestamp,
                m.sender,
                c.name,
                m.content,
                m.is_from_me,
                c.jid,
                m.id,
                m.media_type
            FROM messages m
            JOIN chats c ON m.chat_jid = c.jid
            WHERE m.sender = ? OR {cin}
            ORDER BY m.timestamp DESC
            LIMIT 1
        """.format(cin=cin), (jid, *cp))
        
        msg_data = cursor.fetchone()
        
        if not msg_data:
            return None
            
        message = Message(
            timestamp=datetime.fromisoformat(msg_data[0]),
            sender=msg_data[1],
            chat_name=msg_data[2],
            content=msg_data[3],
            is_from_me=msg_data[4],
            chat_jid=msg_data[5],
            id=msg_data[6],
            media_type=msg_data[7]
        )
        
        return format_message(message)
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()


def get_chat(chat_jid: str, include_last_message: bool = True) -> Optional[Chat]:
    """Get chat metadata by JID."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        query = """
            SELECT 
                c.jid,
                c.name,
                c.last_message_time,
                m.content as last_message,
                m.sender as last_sender,
                m.is_from_me as last_is_from_me
            FROM chats c
        """
        
        if include_last_message:
            query += """
                LEFT JOIN messages m ON c.jid = m.chat_jid 
                AND c.last_message_time = m.timestamp
            """
            
        _in, _p = _jid_in("c.jid", chat_jid)
        query += f" WHERE {_in}"

        cursor.execute(query, tuple(_p))
        chat_data = cursor.fetchone()
        
        if not chat_data:
            return None
            
        return Chat(
            jid=chat_data[0],
            name=chat_data[1],
            last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
            last_message=chat_data[3],
            last_sender=chat_data[4],
            last_is_from_me=chat_data[5]
        )
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()


def get_direct_chat_by_contact(sender_phone_number: str) -> Optional[Chat]:
    """Get chat metadata by sender phone number."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                c.jid,
                c.name,
                c.last_message_time,
                m.content as last_message,
                m.sender as last_sender,
                m.is_from_me as last_is_from_me
            FROM chats c
            LEFT JOIN messages m ON c.jid = m.chat_jid 
                AND c.last_message_time = m.timestamp
            WHERE c.jid LIKE ? AND c.jid NOT LIKE '%@g.us'
            LIMIT 1
        """, (f"%{sender_phone_number}%",))
        
        chat_data = cursor.fetchone()
        
        if not chat_data:
            return None
            
        return Chat(
            jid=chat_data[0],
            name=chat_data[1],
            last_message_time=datetime.fromisoformat(chat_data[2]) if chat_data[2] else None,
            last_message=chat_data[3],
            last_sender=chat_data[4],
            last_is_from_me=chat_data[5]
        )
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()

def send_message(recipient: str, message: str) -> Tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"
        
        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "message": message,
        }
        
        response = requests.post(url, json=payload)
        
        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"
            
    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def send_file(recipient: str, media_path: str) -> Tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"
        
        if not media_path:
            return False, "Media path must be provided"
        
        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"
        
        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "media_path": media_path
        }
        
        response = requests.post(url, json=payload)
        
        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"
            
    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def send_audio_message(recipient: str, media_path: str) -> Tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"
        
        if not media_path:
            return False, "Media path must be provided"
        
        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"

        if not media_path.endswith(".ogg"):
            try:
                media_path = audio.convert_to_opus_ogg_temp(media_path)
            except Exception as e:
                return False, f"Error converting file to opus ogg. You likely need to install ffmpeg: {str(e)}"
        
        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "media_path": media_path
        }
        
        response = requests.post(url, json=payload)
        
        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"
            
    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def download_media(message_id: str, chat_jid: str) -> Optional[str]:
    """Download media from a message and return the local file path.
    
    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message
    
    Returns:
        The local file path if download was successful, None otherwise
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/download"
        payload = {
            "message_id": message_id,
            "chat_jid": chat_jid
        }
        
        response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                path = result.get("path")
                print(f"Media downloaded successfully: {path}")
                return path
            else:
                print(f"Download failed: {result.get('message', 'Unknown error')}")
                return None
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return None
            
    except requests.RequestException as e:
        print(f"Request error: {str(e)}")
        return None
    except json.JSONDecodeError:
        print(f"Error parsing response: {response.text}")
        return None
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return None


def resync_chats(chat_jid: Optional[str] = None, count: int = 100) -> Dict[str, Any]:
    """Resync message history from WhatsApp servers.

    Two modes:
    - No chat_jid: FULL resync — clears DB, reconnects, WhatsApp re-pushes all history.
    - With chat_jid: On-demand — requests older messages for a specific chat.

    Args:
        chat_jid: Optional. Specific chat to fetch older messages for.
        count: Number of messages to request (default: 100). Only for on-demand mode.
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/resync"
        payload = {}
        if chat_jid:
            payload["chat_jid"] = chat_jid
            payload["count"] = count
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            return response.json()
        return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_events(
    chat_jid: str,
    after_timestamp: Optional[str] = None,
    event_types: Optional[List[str]] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get events (read receipts, typing indicators) for a chat.

    Args:
        chat_jid: The JID of the chat.
        after_timestamp: Only return events after this ISO timestamp.
        event_types: Filter by event types (e.g. ['read', 'typing', 'delivered']).
        limit: Max events to return.
    """
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        _in, _p = _jid_in("chat_jid", chat_jid)
        query = f"SELECT id, chat_jid, event_type, sender, timestamp, data FROM events WHERE {_in}"
        params = list(_p)

        if after_timestamp:
            query += " AND timestamp > ?"
            params.append(after_timestamp)

        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            query += f" AND event_type IN ({placeholders})"
            params.extend(event_types)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        events = []
        for row in rows:
            events.append({
                "id": row[0],
                "chat_jid": row[1],
                "event_type": row[2],
                "sender": row[3],
                "timestamp": row[4],
                "data": row[5],
            })
        return events

    except sqlite3.Error as e:
        return []
    finally:
        if 'conn' in locals():
            conn.close()


def mark_read(chat_jid: str, message_ids: List[str]) -> Dict[str, Any]:
    """Send read receipt (blue ticks) for specific messages. MANUAL ONLY.

    By default, we NEVER send read receipts. Call this explicitly when you
    want them to see blue ticks. Pure psychological warfare.
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/mark-read"
        payload = {"chat_jid": chat_jid, "message_ids": message_ids}
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return response.json()
        return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_typing(chat_jid: str, composing: bool = True, media: str = "text") -> Dict[str, Any]:
    """Send typing indicator. Show as typing or stop typing.

    Args:
        chat_jid: The chat to show typing in.
        composing: True = start typing, False = stop typing.
        media: "text" or "audio" (recording voice message indicator).
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/typing"
        payload = {"chat_jid": chat_jid, "composing": composing, "media": media}
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return response.json()
        return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def set_presence(available: bool = True) -> Dict[str, Any]:
    """Set online/offline presence.

    Args:
        available: True = appear online, False = appear offline.
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/presence"
        payload = {"available": available}
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return response.json()
        return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def resolve_contacts() -> Dict[str, Any]:
    """Bulk-resolve all unresolved contact names.

    LID-based contacts often have numeric-only names. This triggers
    the Go bridge to look up real names (PushName/FullName) for all
    unresolved contacts at once. Run this once before searching contacts.
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/resolve-contacts"
        response = requests.post(url)
        if response.status_code == 200:
            return response.json()
        return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_chat_log(
    chat_jid: str,
    amount: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """Get conversation as a readable chat log optimized for LLM analysis.

    Returns messages as plain-text chronological log, ~5x smaller than JSON.
    """
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        # Get chat name (match either the @lid or phone alias; prefer a real name)
        _in, _p = _jid_in("jid", chat_jid)
        cursor.execute(
            f"SELECT name FROM chats WHERE {_in} ORDER BY (name IS NULL OR name='') ASC LIMIT 1", _p)
        chat_result = cursor.fetchone()
        chat_name = chat_result[0] if chat_result and chat_result[0] else chat_jid

        # Fetch messages across all aliases (newest first, then reverse for chronological)
        _min, _mp = _jid_in("m.chat_jid", chat_jid)
        cursor.execute(f"""
            SELECT m.sender, m.content, m.timestamp, m.is_from_me, m.media_type, m.id
            FROM messages m
            WHERE {_min}
            ORDER BY m.timestamp DESC
            LIMIT ? OFFSET ?
        """, (*_mp, amount, offset))

        messages = cursor.fetchall()
        has_more = len(messages) >= amount

        # Reverse to chronological order (oldest first)
        messages.reverse()

        lines = []
        for msg in messages:
            sender_raw, content, timestamp, is_from_me, media_type, msg_id = msg

            sender = "YOU" if is_from_me else (get_sender_name(sender_raw) if sender_raw else "Unknown")

            # Trim timestamp to YYYY-MM-DD HH:MM
            ts = timestamp[:16] if timestamp else ""

            text = content or ""
            if media_type:
                media_tag = f"[{media_type}: msg_id={msg_id}, chat_jid={chat_jid}]"
                text = f"{media_tag} {text}" if text else media_tag

            if text:
                lines.append(f"[{ts}] {sender}: {text}")

        log_text = "\n".join(lines)

        return {
            "chat_jid": chat_jid,
            "chat_name": chat_name,
            "log": log_text,
            "count": len(lines),
            "offset": offset,
            "has_more": has_more,
        }

    except sqlite3.Error as e:
        return {"error": str(e)}
    finally:
        if 'conn' in locals():
            conn.close()


def wait_for_reply(
    chat_jid: str,
    timeout_minutes: int = 5,
    double_text_grace_period_seconds: int = 10
) -> Dict[str, Any]:
    """Block until a new message arrives in the chat or timeout.

    Polls the SQLite database for new messages (the Go bridge writes
    messages in real-time as they arrive from WhatsApp).

    Args:
        chat_jid: The JID of the chat to monitor.
        timeout_minutes: How long to wait before returning (default: 5).
        double_text_grace_period_seconds: Extra wait after first reply
            to catch rapid follow-up messages (default: 10).

    Returns:
        On reply: dict with 'success', 'new_messages' array, 'waited_seconds'.
        On timeout: dict with 'timeout', 'waited_seconds'.
    """
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    deadline = start_time + timeout_seconds

    # Alias set so a reply arriving under the phone JID still matches a @lid chat_jid.
    _aj = alias_jids(chat_jid)
    _ph = ",".join("?" for _ in _aj)

    # Get the current latest message timestamp as our baseline
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT MAX(timestamp) FROM messages WHERE chat_jid IN ({_ph})",
            tuple(_aj)
        )
        result = cursor.fetchone()
        baseline_timestamp = result[0] if result and result[0] else datetime.now().isoformat()
    except sqlite3.Error:
        baseline_timestamp = datetime.now().isoformat()
    finally:
        if 'conn' in locals():
            conn.close()

    collected_ids = set()
    messages = []
    manual_activity = []  # outgoing messages not sent by MCP (manual phone usage)
    last_message_time = None  # rolling: resets on every new message

    while time.time() < deadline:
        # Rolling grace period: wait N seconds after the LAST message, not the first
        if (
            last_message_time is not None
            and time.time() - last_message_time >= double_text_grace_period_seconds
        ):
            break

        try:
            conn = sqlite3.connect(MESSAGES_DB_PATH)
            cursor = conn.cursor()

            # Check for incoming messages
            cursor.execute(f"""
                SELECT m.id, m.sender, m.content, m.timestamp, m.media_type
                FROM messages m
                WHERE m.chat_jid IN ({_ph}) AND m.timestamp > ? AND m.is_from_me = 0
                ORDER BY m.timestamp ASC
            """, (*_aj, baseline_timestamp))

            new_rows = cursor.fetchall()

            # Also check for outgoing messages (manual activity detection)
            cursor.execute(f"""
                SELECT m.id, m.content, m.timestamp, m.media_type
                FROM messages m
                WHERE m.chat_jid IN ({_ph}) AND m.timestamp > ? AND m.is_from_me = 1
                ORDER BY m.timestamp ASC
            """, (*_aj, baseline_timestamp))

            outgoing_rows = cursor.fetchall()
            conn.close()

            for row in new_rows:
                msg_id, sender, content, timestamp, media_type = row
                if msg_id not in collected_ids:
                    collected_ids.add(msg_id)
                    d = {
                        "sender": get_sender_name(sender) if sender else "Unknown",
                        "text": content or "",
                        "timestamp": timestamp,
                    }
                    if media_type:
                        d["media_type"] = media_type
                    messages.append(d)

                    # Rolling: reset timer on every new message
                    last_message_time = time.time()

            for row in outgoing_rows:
                msg_id, content, timestamp, media_type = row
                if msg_id not in collected_ids:
                    collected_ids.add(msg_id)
                    d = {
                        "text": content or "",
                        "timestamp": timestamp,
                        "is_from_me": True,
                    }
                    if media_type:
                        d["media_type"] = media_type
                    manual_activity.append(d)

                    # Also reset grace timer on manual activity
                    last_message_time = time.time()

        except sqlite3.Error:
            pass

        time.sleep(1)

    waited = int(time.time() - start_time)
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Check for read/typing events during the wait
    seen = False
    typing = False
    try:
        evts = get_events(chat_jid, after_timestamp=baseline_timestamp, event_types=["read", "typing"])
        for evt in evts:
            if evt["event_type"] == "read":
                seen = True
            elif evt["event_type"] == "typing":
                typing = True
    except Exception:
        pass

    if not messages and not manual_activity:
        result = {
            "timeout": True,
            "waited_seconds": waited,
            "current_time": now_str,
        }
    else:
        result = {
            "success": True,
            "new_messages": messages,
            "waited_seconds": waited,
            "current_time": now_str,
        }

    if manual_activity:
        result["manual_activity"] = manual_activity
        result["manual_activity_warning"] = "User is actively typing on their phone. DO NOT send messages until they stop."
    if seen:
        result["seen"] = True
    if typing:
        result["typing"] = True

    return result


def send_and_check(
    recipient: str,
    message: str,
    sync_timeout_seconds: int = 15
) -> Dict[str, Any]:
    """Send a message and check for interjections. Use for natural double-texting.

    Combines three operations atomically:
    1. Record baseline (current latest message)
    2. Send your message
    3. Check if they sent anything while you were typing/sending

    Args:
        recipient: Phone number or JID to send to.
        message: Message text to send.
        sync_timeout_seconds: Max time to wait for interjection check (default: 15).

    Returns:
        success: Whether message was sent.
        has_interjection: True if they sent something since you started.
        interjection: Their message if has_interjection.
    """
    BASE_WINDOW = 3
    ABSOLUTE_CAP = min(sync_timeout_seconds, 15)

    # Determine chat_jid from recipient
    if '@' in recipient:
        chat_jid = recipient
    else:
        chat_jid = f"{recipient}@s.whatsapp.net"

    # Alias set so a reply under the phone JID matches a @lid recipient (and vice-versa).
    _aj = alias_jids(chat_jid)
    _ph = ",".join("?" for _ in _aj)

    # Record baseline BEFORE sending
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT MAX(timestamp) FROM messages WHERE chat_jid IN ({_ph})",
            tuple(_aj)
        )
        result = cursor.fetchone()
        baseline_timestamp = result[0] if result and result[0] else datetime.now().isoformat()
        conn.close()
    except sqlite3.Error:
        baseline_timestamp = datetime.now().isoformat()

    # Send the message
    success, status_message = send_message(recipient, message)
    if not success:
        return {"success": False, "error": status_message}

    # Check for interjections in a short window
    # Smart deadline extension: +2s if they read, +5s if they start typing
    SEEN_GRACE = 2
    TYPING_EXTEND = 5

    now = time.time()
    check_deadline = now + BASE_WINDOW
    cap = now + ABSOLUTE_CAP
    interjection = None
    seen = False
    typing = False

    while time.time() < check_deadline:
        # Check for messages
        try:
            conn = sqlite3.connect(MESSAGES_DB_PATH)
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT m.sender, m.content, m.timestamp, m.media_type
                FROM messages m
                WHERE m.chat_jid IN ({_ph}) AND m.timestamp > ? AND m.is_from_me = 0
                ORDER BY m.timestamp ASC
                LIMIT 1
            """, (*_aj, baseline_timestamp))

            msg_result = cursor.fetchone()
            conn.close()

            if msg_result:
                interjection = {
                    "sender": get_sender_name(msg_result[0]) if msg_result[0] else "Unknown",
                    "text": msg_result[1] or "",
                    "timestamp": msg_result[2],
                }
                if msg_result[3]:
                    interjection["media_type"] = msg_result[3]
                break

        except sqlite3.Error:
            pass

        # Check for read/typing events — extend deadline
        try:
            evts = get_events(chat_jid, after_timestamp=baseline_timestamp, event_types=["read", "typing"])
            for evt in evts:
                if evt["event_type"] == "read" and not seen:
                    seen = True
                    check_deadline = min(time.time() + SEEN_GRACE, cap)
                elif evt["event_type"] == "typing" and not typing:
                    typing = True
                    check_deadline = min(time.time() + TYPING_EXTEND, cap)
        except Exception:
            pass

        time.sleep(0.5)

    result = {
        "success": True,
        "has_interjection": interjection is not None,
        "current_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if interjection:
        result["interjection"] = interjection
    if seen:
        result["seen"] = True
    if typing:
        result["typing"] = True

    return result


def transcribe_audio(message_id: str, chat_jid: str) -> Dict[str, Any]:
    """Download and transcribe a voice/audio message using OpenAI Whisper.

    Args:
        message_id: The ID of the message containing the audio.
        chat_jid: The JID of the chat containing the message.

    Returns:
        dict with 'success', 'text' (transcription), 'file_path', etc.
    """
    # First download the media
    file_path = download_media(message_id, chat_jid)
    if not file_path:
        return {"success": False, "error": "Failed to download audio. Check message_id and chat_jid."}

    try:
        from openai import OpenAI
        client = OpenAI()

        with open(file_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )

        return {
            "success": True,
            "text": transcription.text,
            "file_path": file_path,
            "message_id": message_id,
            "chat_jid": chat_jid,
        }
    except ImportError:
        return {
            "success": False,
            "error": "OpenAI package not installed. Run: uv add openai",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
