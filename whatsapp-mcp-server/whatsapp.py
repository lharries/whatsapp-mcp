import sqlite3
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple
import os.path
import requests
import json

MESSAGES_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'messages.db')
STORE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'whatsapp.db')
WHATSAPP_API_BASE_URL = "http://localhost:8080/api"

def _normalize_phone(phone: str) -> str:
    """Strip +, spaces, dashes from a phone number."""
    return phone.replace('+', '').replace(' ', '').replace('-', '')

def _resolve_phone_to_jids(phone: str) -> List[str]:
    """Given a phone number, return all JIDs (regular + LID) that match.

    Uses exact match first, then suffix match to handle WhatsApp's
    varying phone number formats (e.g. 15550001234 vs 115550001234).
    """
    phone = _normalize_phone(phone)
    jids = [f"{phone}@s.whatsapp.net"]
    try:
        conn = sqlite3.connect(STORE_DB_PATH)
        # Exact match first
        row = conn.execute(
            "SELECT lid, pn FROM whatsmeow_lid_map WHERE pn = ?", (phone,)
        ).fetchone()
        # If not found, try suffix match (handles prefix variations)
        if not row:
            suffix = phone[-10:]  # last 10 digits
            row = conn.execute(
                "SELECT lid, pn FROM whatsmeow_lid_map WHERE pn LIKE ?",
                (f"%{suffix}",)
            ).fetchone()
        if row:
            lid, stored_pn = row
            jids.append(f"{lid}@lid")
            # Also add the stored number format as @s.whatsapp.net
            if stored_pn != phone:
                jids.append(f"{stored_pn}@s.whatsapp.net")
        conn.close()
    except Exception:
        pass
    return jids

def _get_contact_name(phone: str) -> Optional[str]:
    """Look up contact name in whatsapp.db by phone number."""
    phone = _normalize_phone(phone)
    try:
        conn = sqlite3.connect(STORE_DB_PATH)
        row = conn.execute(
            """SELECT full_name, push_name FROM whatsmeow_contacts
               WHERE their_jid = ? OR their_jid LIKE ?""",
            (f"{phone}@s.whatsapp.net", f"{phone}%")
        ).fetchone()
        conn.close()
        if row:
            return row[0] or row[1]
    except Exception:
        pass
    return None

@dataclass
class Message:
    timestamp: datetime
    sender: str
    content: str
    is_from_me: bool
    chat_jid: str
    id: str
    chat_name: Optional[str] = None

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

def print_message(message: Message, show_chat_info: bool = True) -> None:
    """Print a single message with consistent formatting."""
    direction = "→" if message.is_from_me else "←"
    
    if show_chat_info and message.chat_name:
        print(f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] {direction} Chat: {message.chat_name} ({message.chat_jid})")
    else:
        print(f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] {direction}")
        
    print(f"From: {'Me' if message.is_from_me else message.sender}")
    print(f"Message: {message.content}")
    print("-" * 100)

def print_messages_list(messages: List[Message], title: str = "", show_chat_info: bool = True) -> None:
    """Print a list of messages with a title and consistent formatting."""
    if not messages:
        print("No messages to display.")
        return
        
    if title:
        print(f"\n{title}")
        print("-" * 100)
    
    for message in messages:
        print_message(message, show_chat_info)

def print_chat(chat: Chat) -> None:
    """Print a single chat with consistent formatting."""
    print(f"Chat: {chat.name} ({chat.jid})")
    if chat.last_message_time:
        print(f"Last active: {chat.last_message_time:%Y-%m-%d %H:%M:%S}")
        direction = "→" if chat.last_is_from_me else "←"
        sender = "Me" if chat.last_is_from_me else chat.last_sender
        print(f"Last message: {direction} {sender}: {chat.last_message}")
    print("-" * 100)

def print_chats_list(chats: List[Chat], title: str = "") -> None:
    """Print a list of chats with a title and consistent formatting."""
    if not chats:
        print("No chats to display.")
        return
        
    if title:
        print(f"\n{title}")
        print("-" * 100)
    
    for chat in chats:
        print_chat(chat)

def print_paginated_messages(messages: List[Message], page: int, total_pages: int, chat_name: str) -> None:
    """Print a paginated list of messages with navigation hints."""
    print(f"\nMessages for chat: {chat_name}")
    print(f"Page {page} of {total_pages}")
    print("-" * 100)
    
    print_messages_list(messages, show_chat_info=False)
    
    # Print pagination info
    if page > 1:
        print(f"Use page={page-1} to see newer messages")
    if page < total_pages:
        print(f"Use page={page+1} to see older messages")

"""
CREATE TABLE messages (
			id TEXT,
			chat_jid TEXT,
			sender TEXT,
			content TEXT,
			timestamp TIMESTAMP,
			is_from_me BOOLEAN,
			PRIMARY KEY (id, chat_jid),
			FOREIGN KEY (chat_jid) REFERENCES chats(jid)
		)

CREATE TABLE chats (
			jid TEXT PRIMARY KEY,
			name TEXT,
			last_message_time TIMESTAMP
		)
"""

def print_recent_messages(limit=10) -> List[Message]:
    try:
        # Connect to the SQLite database
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # Query recent messages with chat info
        query = """
        SELECT 
            m.timestamp,
            m.sender,
            c.name,
            m.content,
            m.is_from_me,
            c.jid,
            m.id
        FROM messages m
        JOIN chats c ON m.chat_jid = c.jid
        ORDER BY m.timestamp DESC
        LIMIT ?
        """
        
        cursor.execute(query, (limit,))
        messages = cursor.fetchall()
        
        if not messages:
            print("No messages found in the database.")
            return []
            
        result = []
        
        # Convert to Message objects
        for msg in messages:
            message = Message(
                timestamp=datetime.fromisoformat(msg[0]),
                sender=msg[1],
                chat_name=msg[2] or "Unknown Chat",
                content=msg[3],
                is_from_me=msg[4],
                chat_jid=msg[5],
                id=msg[6]
            )
            result.append(message)
        
        # Print messages using helper function
        print_messages_list(result, title=f"Last {limit} messages:")
        return result
            
    except sqlite3.Error as e:
        print(f"Error accessing database: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()


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
) -> List[Message]:
    """Get messages matching the specified criteria with optional context."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # Build base query
        query_parts = ["SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id FROM messages"]
        query_parts.append("JOIN chats ON messages.chat_jid = chats.jid")
        where_clauses = []
        params = []
        
        # Add filters
        if date_range:
            where_clauses.append("messages.timestamp BETWEEN ? AND ?")
            params.extend([date_range[0].isoformat(), date_range[1].isoformat()])
            
        if sender_phone_number:
            jids = _resolve_phone_to_jids(sender_phone_number)
            # For direct chats, filter by chat_jid (avoids duplicates from group msgs)
            jid_placeholders = ','.join('?' * len(jids))
            where_clauses.append(
                f"(messages.chat_jid IN ({jid_placeholders}) AND messages.chat_jid NOT LIKE '%@g.us')"
            )
            params.extend(jids)
            
        if chat_jid:
            where_clauses.append("messages.chat_jid = ?")
            params.append(chat_jid)
            
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
                id=msg[6]
            )
            result.append(message)
            
        if include_context and result and not sender_phone_number:
            # Add context for each message (skip when filtering by phone: already full chat)
            seen_ids = set()
            messages_with_context = []
            for msg in result:
                context = get_message_context(msg.id, context_before, context_after)
                for m in context.before + [context.message] + context.after:
                    if m.id not in seen_ids:
                        seen_ids.add(m.id)
                        messages_with_context.append(m)
            return messages_with_context
            
        return result
        
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
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.chat_jid
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
            id=msg_data[6]
        )
        
        # Get messages before
        cursor.execute("""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id
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
                id=msg[6]
            ))
        
        # Get messages after
        cursor.execute("""
            SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id
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
                id=msg[6]
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
    search_pattern = f'%{query}%'
    result = []
    seen_jids = set()

    # 1. Search whatsapp.db contacts (has real names including LID contacts)
    try:
        conn = sqlite3.connect(STORE_DB_PATH)
        rows = conn.execute("""
            SELECT their_jid, full_name, push_name, redacted_phone
            FROM whatsmeow_contacts
            WHERE (LOWER(full_name) LIKE LOWER(?)
                   OR LOWER(push_name) LIKE LOWER(?)
                   OR their_jid LIKE ?)
              AND their_jid NOT LIKE '%@g.us'
            ORDER BY full_name, push_name
            LIMIT 50
        """, (search_pattern, search_pattern, search_pattern)).fetchall()
        for row in rows:
            jid, full_name, push_name, _ = row
            name = full_name or push_name
            # Resolve phone number: for LID JIDs look up the real number
            raw = jid.split('@')[0]
            if jid.endswith('@lid'):
                pn_row = conn.execute(
                    "SELECT pn FROM whatsmeow_lid_map WHERE lid = ?", (raw,)
                ).fetchone()
                phone = pn_row[0] if pn_row else raw
            else:
                phone = raw
            if jid not in seen_jids:
                seen_jids.add(jid)
                result.append(Contact(phone_number=phone, name=name, jid=jid))
        conn.close()
    except Exception as e:
        print(f"Store DB error: {e}")

    # 2. Fallback: also search messages.db chats (catches contacts not in store)
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        rows = conn.execute("""
            SELECT DISTINCT jid, name FROM chats
            WHERE (LOWER(name) LIKE LOWER(?) OR LOWER(jid) LIKE LOWER(?))
              AND jid NOT LIKE '%@g.us'
            ORDER BY name, jid LIMIT 50
        """, (search_pattern, search_pattern)).fetchall()
        for row in rows:
            jid, name = row
            if jid not in seen_jids:
                seen_jids.add(jid)
                result.append(Contact(
                    phone_number=jid.split('@')[0], name=name, jid=jid
                ))
        conn.close()
    except Exception as e:
        print(f"Messages DB error: {e}")

    return result


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
            WHERE m.sender = ? OR c.jid = ?
            ORDER BY c.last_message_time DESC
            LIMIT ? OFFSET ?
        """, (jid, jid, limit, page * limit))
        
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


def get_last_interaction(jid: str) -> Optional[Message]:
    """Get most recent message involving the contact."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                m.timestamp,
                m.sender,
                c.name,
                m.content,
                m.is_from_me,
                c.jid,
                m.id
            FROM messages m
            JOIN chats c ON m.chat_jid = c.jid
            WHERE m.sender = ? OR c.jid = ?
            ORDER BY m.timestamp DESC
            LIMIT 1
        """, (jid, jid))
        
        msg_data = cursor.fetchone()
        
        if not msg_data:
            return None
            
        return Message(
            timestamp=datetime.fromisoformat(msg_data[0]),
            sender=msg_data[1],
            chat_name=msg_data[2],
            content=msg_data[3],
            is_from_me=msg_data[4],
            chat_jid=msg_data[5],
            id=msg_data[6]
        )
        
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
            
        query += " WHERE c.jid = ?"
        
        cursor.execute(query, (chat_jid,))
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
    """Get chat metadata by sender phone number (handles LID contacts)."""
    jids = _resolve_phone_to_jids(sender_phone_number)
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(jids))
        cursor.execute(f"""
            SELECT
                c.jid, c.name, c.last_message_time,
                m.content, m.sender, m.is_from_me
            FROM chats c
            LEFT JOIN messages m ON c.jid = m.chat_jid
                AND c.last_message_time = m.timestamp
            WHERE c.jid IN ({placeholders}) AND c.jid NOT LIKE '%@g.us'
            LIMIT 1
        """, jids)
        chat_data = cursor.fetchone()
        if not chat_data:
            return None
        # Resolve name: try store DB with all phone variants
        stored_name = chat_data[1]
        if not stored_name or stored_name.replace('@lid','').isdigit():
            stored_name = _get_contact_name(sender_phone_number)
            # Also try with the stored phone variants from lid_map
            if not stored_name:
                for jid in jids:
                    pn = jid.split('@')[0]
                    stored_name = _get_contact_name(pn)
                    if stored_name:
                        break
        name = stored_name
        return Chat(
            jid=chat_data[0],
            name=name,
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
    """Send a WhatsApp message to the specified recipient. For group messages use the JID.
    
    Args:
        recipient: The recipient - either a phone number with country code but no + or other symbols,
                  or a JID (e.g., "123456789@s.whatsapp.net" or a group JID like "123456789@g.us").
        message: The message text to send
        
    Returns:
        Tuple[bool, str]: A tuple containing success status and a status message
    """
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"
        
        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "message": message
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
