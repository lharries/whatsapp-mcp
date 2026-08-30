import sqlite3
import unicodedata
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple
import os.path
import requests
import json
import audio


def normalize_text(text: str) -> str:
    """Strip accents/diacritics and lowercase for search comparison.
    e.g. 'Götze' -> 'gotze', 'Piñol' -> 'pinol'
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.category(c).startswith('M')).lower()

MESSAGES_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'messages.db')
WHATSMEOW_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'whatsapp.db')
WHATSAPP_API_BASE_URL = "http://localhost:8080/api"


def _get_whatsmeow_contacts() -> dict:
    """Load all contacts from whatsmeow's contact store.
    Returns dict mapping JID -> best available name.
    Also resolves LID-based JIDs using the lid_map table.
    """
    try:
        conn = sqlite3.connect(WHATSMEOW_DB_PATH)
        cursor = conn.cursor()

        # Load LID -> phone number mapping
        lid_to_pn = {}
        try:
            cursor.execute("SELECT lid, pn FROM whatsmeow_lid_map")
            for lid, pn in cursor.fetchall():
                lid_to_pn[lid] = pn
        except sqlite3.Error:
            pass

        # Load all contacts (both phone and LID based)
        cursor.execute("""
            SELECT their_jid, first_name, full_name, push_name, business_name
            FROM whatsmeow_contacts
        """)
        contacts = {}
        for row in cursor.fetchall():
            jid, first_name, full_name, push_name, business_name = row
            name = full_name or business_name or push_name or first_name or ""
            if not name:
                continue

            if jid.endswith("@s.whatsapp.net"):
                contacts[jid] = name
            elif jid.endswith("@lid"):
                # Store under LID JID so LID-based chats get resolved
                contacts[jid] = name
                # Also map to phone JID
                lid_num = jid.split("@")[0]
                if lid_num in lid_to_pn:
                    phone_jid = lid_to_pn[lid_num] + "@s.whatsapp.net"
                    if phone_jid not in contacts:
                        contacts[phone_jid] = name
        return contacts
    except sqlite3.Error:
        return {}
    finally:
        if 'conn' in locals():
            conn.close()


def _get_lid_map() -> dict:
    """Load LID -> phone number mapping from whatsmeow.
    Returns dict mapping LID JID -> phone JID.
    """
    try:
        conn = sqlite3.connect(WHATSMEOW_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT lid, pn FROM whatsmeow_lid_map")
        result = {}
        for lid, pn in cursor.fetchall():
            result[f"{lid}@lid"] = f"{pn}@s.whatsapp.net"
        return result
    except sqlite3.Error:
        return {}
    finally:
        if 'conn' in locals():
            conn.close()

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

        # First try matching by exact JID in chats table
        cursor.execute("""
            SELECT name
            FROM chats
            WHERE jid = ?
            LIMIT 1
        """, (sender_jid,))

        result = cursor.fetchone()

        # If no result, try looking for the number within JIDs
        if not result:
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

        if result and result[0] and not result[0].isdigit():
            return result[0]

        # Fall back to whatsmeow contacts (address book)
        # Try multiple JID formats: exact, @s.whatsapp.net, @lid, and LID->phone mapping
        if '@' in sender_jid:
            jids_to_try = [sender_jid]
        else:
            jids_to_try = [f"{sender_jid}@s.whatsapp.net", f"{sender_jid}@lid"]
        try:
            wconn = sqlite3.connect(WHATSMEOW_DB_PATH)
            wcursor = wconn.cursor()
            for jid_to_lookup in jids_to_try:
                wcursor.execute("""
                    SELECT full_name, push_name, business_name, first_name
                    FROM whatsmeow_contacts
                    WHERE their_jid = ?
                    LIMIT 1
                """, (jid_to_lookup,))
                wresult = wcursor.fetchone()
                if wresult:
                    name = wresult[0] or wresult[1] or wresult[2] or wresult[3]
                    if name:
                        return name
            # Also try LID map: if sender is a LID, resolve to phone and look up contact
            lid_num = sender_jid.split("@")[0] if "@" in sender_jid else sender_jid
            wcursor.execute("SELECT pn FROM whatsmeow_lid_map WHERE lid = ? LIMIT 1", (lid_num,))
            lid_result = wcursor.fetchone()
            if lid_result:
                phone_jid = lid_result[0] + "@s.whatsapp.net"
                wcursor.execute("""
                    SELECT full_name, push_name, business_name, first_name
                    FROM whatsmeow_contacts
                    WHERE their_jid = ?
                    LIMIT 1
                """, (phone_jid,))
                wresult = wcursor.fetchone()
                if wresult:
                    name = wresult[0] or wresult[1] or wresult[2] or wresult[3]
                    if name:
                        return name
        except sqlite3.Error:
            pass
        finally:
            if 'wconn' in locals():
                wconn.close()

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

        if phone_number:
            # Match messages in the person's DM chat or sent by them in any chat
            phone_pattern = f"%{phone_number}%"
            where_clauses.append("(messages.sender LIKE ? OR chats.jid LIKE ?)")
            params.extend([phone_pattern, phone_pattern])

        if sender_phone_number:
            # Use LIKE to handle both bare numbers and full JID formats
            phone_pattern = f"%{sender_phone_number}%"
            where_clauses.append("messages.sender LIKE ?")
            params.append(phone_pattern)

        if chat_jid:
            where_clauses.append("messages.chat_jid = ?")
            params.append(chat_jid)

        if contact_jid:
            where_clauses.append("(messages.sender = ? OR chats.jid = ?)")
            params.extend([contact_jid, contact_jid])
            
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
            # Add context for each message, deduplicating by both ID and timestamp+sender
            # to handle duplicate DB entries from history sync vs real-time with different IDs
            messages_with_context = []
            seen_ids = set()
            seen_ts = set()
            for msg in result:
                context = get_message_context(msg.id, context_before, context_after, chat_jid=msg.chat_jid)
                for ctx_msg in context.before + [context.message] + context.after:
                    id_key = (ctx_msg.id, ctx_msg.chat_jid)
                    ts_key = (ctx_msg.timestamp, ctx_msg.sender, ctx_msg.chat_jid)
                    if id_key not in seen_ids and ts_key not in seen_ts:
                        seen_ids.add(id_key)
                        seen_ts.add(ts_key)
                        messages_with_context.append(ctx_msg)

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
    after: int = 5,
    chat_jid: Optional[str] = None
) -> MessageContext:
    """Get context around a specific message."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        # Get the target message first
        if chat_jid:
            cursor.execute("""
                SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.chat_jid, messages.media_type
                FROM messages
                JOIN chats ON messages.chat_jid = chats.jid
                WHERE messages.id = ? AND messages.chat_jid = ?
            """, (message_id, chat_jid))
        else:
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
            
        params = []

        # Load whatsmeow contacts for name enrichment (always, to resolve LID names)
        whatsmeow_contacts = _get_whatsmeow_contacts()
        lid_map = _get_lid_map()

        # Add sorting
        order_by = "chats.last_message_time DESC" if sort_by == "last_active" else "chats.name"
        query_parts.append(f"ORDER BY {order_by}")

        if query:
            # Fetch all chats and filter in Python for accent-insensitive multi-word matching
            cursor.execute(" ".join(query_parts), tuple(params))
            all_chats = cursor.fetchall()

            query_words = normalize_text(query).split()
            filtered = []
            for chat_data in all_chats:
                jid = chat_data[0]
                # Enrich name from whatsmeow contacts (handles both phone and LID JIDs)
                name = whatsmeow_contacts.get(jid) or chat_data[1] or ""
                # For LID chats, also include the mapped phone number in search
                phone_jid = lid_map.get(jid, "")
                searchable = normalize_text(name) + " " + jid.lower() + " " + phone_jid.lower()
                if all(word in searchable for word in query_words):
                    chat_data = (chat_data[0], name) + chat_data[2:]
                    filtered.append(chat_data)

            offset = page * limit
            chats = filtered[offset:offset + limit]
        else:
            offset = page * limit
            query_parts.append("LIMIT ? OFFSET ?")
            params.extend([limit, offset])
            cursor.execute(" ".join(query_parts), tuple(params))
            chats = cursor.fetchall()

        result = []
        for chat_data in chats:
            jid = chat_data[0]
            # Enrich name from whatsmeow contacts (especially for LID-based chats)
            name = whatsmeow_contacts.get(jid) or chat_data[1] or jid
            chat = Chat(
                jid=jid,
                name=name,
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
    """Search contacts by name or phone number.

    Searches both the chats table (synced conversations) and whatsmeow's
    full contact store (phone address book). Supports accent-insensitive
    and multi-word matching.
    """
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        # Fetch all non-group contacts from chats table
        cursor.execute("""
            SELECT DISTINCT jid, name
            FROM chats
            WHERE jid NOT LIKE '%@g.us'
        """)
        chat_contacts = {row[0]: row[1] for row in cursor.fetchall()}

        # Merge with whatsmeow contacts (address book)
        whatsmeow_contacts = _get_whatsmeow_contacts()

        # Build merged contact list: whatsmeow name takes priority since
        # chats table may have stale names or just phone numbers
        all_contacts = {}
        for jid, name in chat_contacts.items():
            all_contacts[jid] = whatsmeow_contacts.get(jid) or name or ""
        for jid, name in whatsmeow_contacts.items():
            if jid not in all_contacts:
                all_contacts[jid] = name

        # Normalize query words for accent-insensitive matching
        query_words = normalize_text(query).split()

        result = []
        for jid, name in sorted(all_contacts.items(), key=lambda x: x[1] or x[0]):
            name_normalized = normalize_text(name)
            jid_lower = jid.lower()
            searchable = name_normalized + " " + jid_lower

            if all(word in searchable for word in query_words):
                result.append(Contact(
                    phone_number=jid.split('@')[0],
                    name=name,
                    jid=jid
                ))

            if len(result) >= 50:
                break

        return result
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()


def get_chat(
    chat_jid: Optional[str] = None,
    phone_number: Optional[str] = None,
    contact_jid: Optional[str] = None,
    include_last_message: bool = True,
    limit: int = 20,
    page: int = 0
) -> List[Chat]:
    """Get chat metadata by JID, phone number, or contact JID.

    Exactly one of chat_jid, phone_number, or contact_jid must be provided.
    - chat_jid: exact JID lookup, returns a single chat
    - phone_number: pattern match on direct (non-group) chats
    - contact_jid: all chats where contact is a sender or the chat itself
    """
    identifiers = [v for v in (chat_jid, phone_number, contact_jid) if v]
    if len(identifiers) != 1:
        raise ValueError("Exactly one of chat_jid, phone_number, or contact_jid must be provided")

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        def _to_chat(row):
            return Chat(
                jid=row[0],
                name=row[1],
                last_message_time=datetime.fromisoformat(row[2]) if row[2] else None,
                last_message=row[3],
                last_sender=row[4],
                last_is_from_me=row[5]
            )

        if chat_jid:
            query = """
                SELECT c.jid, c.name, c.last_message_time,
                       m.content, m.sender, m.is_from_me
                FROM chats c
            """
            if include_last_message:
                query += " LEFT JOIN messages m ON c.jid = m.chat_jid AND c.last_message_time = m.timestamp"
            query += " WHERE c.jid = ?"
            cursor.execute(query, (chat_jid,))
            row = cursor.fetchone()
            return [_to_chat(row)] if row else []

        elif phone_number:
            cursor.execute("""
                SELECT c.jid, c.name, c.last_message_time,
                       m.content, m.sender, m.is_from_me
                FROM chats c
                LEFT JOIN messages m ON c.jid = m.chat_jid AND c.last_message_time = m.timestamp
                WHERE c.jid LIKE ? AND c.jid NOT LIKE '%@g.us'
                LIMIT 1
            """, (f"%{phone_number}%",))
            row = cursor.fetchone()
            return [_to_chat(row)] if row else []

        else:  # contact_jid
            cursor.execute("""
                SELECT DISTINCT c.jid, c.name, c.last_message_time,
                       m.content, m.sender, m.is_from_me
                FROM chats c
                JOIN messages m ON c.jid = m.chat_jid
                WHERE m.sender = ? OR c.jid = ?
                ORDER BY c.last_message_time DESC
                LIMIT ? OFFSET ?
            """, (contact_jid, contact_jid, limit, page * limit))
            return [_to_chat(row) for row in cursor.fetchall()]

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()

def send_message(recipient: str, message: Optional[str] = None, media_path: Optional[str] = None, as_audio: bool = False) -> Tuple[bool, str]:
    try:
        if not recipient:
            return False, "Recipient must be provided"

        if not message and not media_path:
            return False, "At least one of message or media_path must be provided"

        if media_path:
            if not os.path.isfile(media_path):
                return False, f"Media file not found: {media_path}"

            if as_audio and not media_path.endswith(".ogg"):
                try:
                    media_path = audio.convert_to_opus_ogg_temp(media_path)
                except Exception as e:
                    return False, f"Error converting file to opus ogg. You likely need to install ffmpeg: {str(e)}"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {"recipient": recipient}
        if message:
            payload["message"] = message
        if media_path:
            payload["media_path"] = media_path

        response = requests.post(url, json=payload)

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
