import sqlite3
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, List, Tuple, Dict, Any
import os.path
import re
import time
import requests
import json
import audio

MESSAGES_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'messages.db')
WHATSAPP_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'whatsapp.db')
WHATSAPP_API_BASE_URL = "http://localhost:8080/api"

# MCP clients abort a tool call that runs too long (Command Code's default is 80s,
# overridable via MCP_TOOL_TIMEOUT). A blocking wait must always return before
# that, so it is capped here and the caller polls again.
MAX_WAIT_SECONDS = 55

# Upper bound on rows a single tool call can return, so a large/negative limit
# cannot dump the whole history into the model's context.
MAX_LIMIT = 200


def _clamp_limit_page(limit: Any, page: Any, default_limit: int = 20) -> Tuple[int, int]:
    """Clamp limit to [1, MAX_LIMIT] and page to >= 0.

    SQLite treats a negative LIMIT as 'no limit', so an unguarded -1 would return
    the entire message history.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = default_limit
    if limit < 1:
        # A negative or zero limit is nonsense (and SQLite reads negative as
        # "no limit"); fall back to the default rather than the whole history.
        limit = default_limit
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 0
    return min(limit, MAX_LIMIT), max(0, page)


def _like(term: str) -> str:
    """Build a LIKE pattern that treats %, _ and \\ in the term as literals."""
    escaped = str(term).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# --- Accounts -------------------------------------------------------------
# Each WhatsApp account is its own bridge process with its own store dir + port.
# WA_ACCOUNTS maps them for the tools:
#   WA_ACCOUNTS="main|http://127.0.0.1:8080|/var/lib/whatsapp-mcp/main;second|http://127.0.0.1:8081|/var/lib/whatsapp-mcp/second"
# With it unset there is a single account, "main", using the local store.

DEFAULT_ACCOUNT = "main"
CURRENT_ACCOUNT = DEFAULT_ACCOUNT


def _load_accounts() -> Dict[str, Dict[str, str]]:
    default = {"url": WHATSAPP_API_BASE_URL, "messages_db": MESSAGES_DB_PATH, "whatsapp_db": WHATSAPP_DB_PATH}
    raw = os.environ.get("WA_ACCOUNTS", "").strip()
    if not raw:
        return {DEFAULT_ACCOUNT: default}
    accounts: Dict[str, Dict[str, str]] = {}
    for spec in raw.split(";"):
        parts = [p.strip() for p in spec.split("|")]
        if not parts or not parts[0]:
            continue
        name = parts[0]
        url = parts[1] if len(parts) > 1 and parts[1] else WHATSAPP_API_BASE_URL
        dbdir = parts[2] if len(parts) > 2 and parts[2] else ""
        mdb = os.path.join(dbdir, "messages.db") if dbdir else MESSAGES_DB_PATH
        wdb = os.path.join(dbdir, "whatsapp.db") if dbdir else WHATSAPP_DB_PATH
        accounts[name] = {"url": url, "messages_db": mdb, "whatsapp_db": wdb}
    return accounts or {DEFAULT_ACCOUNT: default}


ACCOUNTS = _load_accounts()


def use_account(account: str = "") -> str:
    """Point the data access at a given account. Called by the MCP tool wrappers,
    so every tool can take an `account` argument. Returns the account in use."""
    global MESSAGES_DB_PATH, WHATSAPP_DB_PATH, WHATSAPP_API_BASE_URL, CURRENT_ACCOUNT
    acct = account or CURRENT_ACCOUNT or DEFAULT_ACCOUNT
    cfg = ACCOUNTS.get(acct)
    if not cfg:
        raise ValueError(f"unknown account {acct!r}; known: {', '.join(ACCOUNTS)}")
    MESSAGES_DB_PATH = cfg["messages_db"]
    WHATSAPP_DB_PATH = cfg["whatsapp_db"]
    WHATSAPP_API_BASE_URL = cfg["url"]
    CURRENT_ACCOUNT = acct
    return acct


def list_accounts() -> List[Dict[str, Any]]:
    """The configured accounts (one WhatsApp number each)."""
    return [
        {"account": name, "api": cfg["url"], "messages_db": cfg["messages_db"]}
        for name, cfg in ACCOUNTS.items()
    ]

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
    lid: Optional[str] = None

@dataclass
class MessageContext:
    message: Message
    before: List[Message]
    after: List[Message]

def resolve_recipient(recipient_input: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Resolves any contact name, phone number (local/intl), JID or LID into:
    (primary_target_jid, display_name, all_associated_jids)
    
    `all_associated_jids` includes both LID and phone JID if mapped, enabling full-history search.
    """
    if not recipient_input or not recipient_input.strip():
        return None, None, []
    
    recipient = recipient_input.strip()
    all_jids: List[str] = []
    display_name: Optional[str] = None

    # Case 1: Already an explicit JID or LID (contains '@')
    if '@' in recipient:
        primary_jid = recipient
        all_jids.append(primary_jid)
        
        # If it's a phone JID, see if there is a mapped LID in whatsapp.db
        if '@s.whatsapp.net' in primary_jid and os.path.exists(WHATSAPP_DB_PATH):
            pn = primary_jid.split('@')[0]
            try:
                conn_wa = sqlite3.connect(WHATSAPP_DB_PATH)
                c_wa = conn_wa.cursor()
                row = c_wa.execute("SELECT lid FROM whatsmeow_lid_map WHERE pn = ?", (pn,)).fetchone()
                if row and row[0]:
                    lid_jid = f"{row[0]}@lid"
                    all_jids.append(lid_jid)
                    primary_jid = lid_jid
                # Look up contact name
                c_row = c_wa.execute(
                    "SELECT COALESCE(NULLIF(full_name, ''), NULLIF(first_name, ''), push_name) FROM whatsmeow_contacts WHERE their_jid = ?",
                    (recipient,)
                ).fetchone()
                if c_row and c_row[0]:
                    display_name = c_row[0]
                conn_wa.close()
            except Exception:
                pass
        elif '@lid' in primary_jid and os.path.exists(WHATSAPP_DB_PATH):
            lid = primary_jid.split('@')[0]
            try:
                conn_wa = sqlite3.connect(WHATSAPP_DB_PATH)
                c_wa = conn_wa.cursor()
                row = c_wa.execute("SELECT pn FROM whatsmeow_lid_map WHERE lid = ?", (lid,)).fetchone()
                if row and row[0]:
                    pn_jid = f"{row[0]}@s.whatsapp.net"
                    all_jids.append(pn_jid)
                    c_row = c_wa.execute(
                        "SELECT COALESCE(NULLIF(full_name, ''), NULLIF(first_name, ''), push_name) FROM whatsmeow_contacts WHERE their_jid = ?",
                        (pn_jid,)
                    ).fetchone()
                    if c_row and c_row[0]:
                        display_name = c_row[0]
                conn_wa.close()
            except Exception:
                pass
                
        return primary_jid, display_name, all_jids

    # Case 2: Phone number (digits, plus sign, spaces, dashes) without letters
    digits = re.sub(r'[^\d]', '', recipient)
    if digits and len(digits) >= 7 and not re.search(r'[a-zA-Z]', recipient):
        # Normalize local Namibian numbers if starting with 081 / 81
        if digits.startswith('0') and len(digits) == 10:
            digits = '264' + digits[1:]
        elif len(digits) == 9 and digits.startswith('81'):
            digits = '264' + digits
            
        phone_jid = f"{digits}@s.whatsapp.net"
        primary_jid = phone_jid
        all_jids.append(phone_jid)
        
        if os.path.exists(WHATSAPP_DB_PATH):
            try:
                conn_wa = sqlite3.connect(WHATSAPP_DB_PATH)
                c_wa = conn_wa.cursor()
                row = c_wa.execute("SELECT lid FROM whatsmeow_lid_map WHERE pn = ?", (digits,)).fetchone()
                if row and row[0]:
                    lid_jid = f"{row[0]}@lid"
                    all_jids.append(lid_jid)
                    primary_jid = lid_jid
                c_row = c_wa.execute(
                    "SELECT COALESCE(NULLIF(full_name, ''), NULLIF(first_name, ''), push_name) FROM whatsmeow_contacts WHERE their_jid = ?",
                    (phone_jid,)
                ).fetchone()
                if c_row and c_row[0]:
                    display_name = c_row[0]
                conn_wa.close()
            except Exception:
                pass
        return primary_jid, display_name, all_jids

    # Case 3: Contact Name query (e.g., "Tysen", "Mom", "Fran The Human")
    pattern = f"%{recipient}%"
    
    # Check whatsmeow_contacts first (2,300+ phonebook contacts)
    if os.path.exists(WHATSAPP_DB_PATH):
        try:
            conn_wa = sqlite3.connect(WHATSAPP_DB_PATH)
            c_wa = conn_wa.cursor()
            row = c_wa.execute("""
                SELECT their_jid, COALESCE(NULLIF(full_name, ''), NULLIF(first_name, ''), push_name, their_jid)
                FROM whatsmeow_contacts
                WHERE full_name LIKE ? OR first_name LIKE ? OR push_name LIKE ?
                ORDER BY 
                    CASE 
                        WHEN LOWER(full_name) = LOWER(?) THEN 1
                        WHEN LOWER(first_name) = LOWER(?) THEN 2
                        WHEN LOWER(push_name) = LOWER(?) THEN 3
                        ELSE 4 
                    END
                LIMIT 1
            """, (pattern, pattern, pattern, recipient, recipient, recipient)).fetchone()
            
            if row:
                their_jid, contact_name = row[0], row[1]
                pn = their_jid.split('@')[0] if '@' in their_jid else their_jid
                lid_row = c_wa.execute("SELECT lid FROM whatsmeow_lid_map WHERE pn = ?", (pn,)).fetchone()
                
                all_jids.append(their_jid)
                if lid_row and lid_row[0]:
                    lid_jid = f"{lid_row[0]}@lid"
                    all_jids.append(lid_jid)
                    conn_wa.close()
                    return lid_jid, contact_name, all_jids
                
                conn_wa.close()
                return their_jid, contact_name, all_jids
            conn_wa.close()
        except Exception:
            pass

    # Fallback to chats in messages.db
    if os.path.exists(MESSAGES_DB_PATH):
        try:
            conn_m = sqlite3.connect(MESSAGES_DB_PATH)
            c_m = conn_m.cursor()
            row = c_m.execute("""
                SELECT jid, name 
                FROM chats 
                WHERE name LIKE ? 
                ORDER BY 
                    CASE WHEN LOWER(name) = LOWER(?) THEN 1 ELSE 2 END,
                    last_message_time DESC 
                LIMIT 1
            """, (pattern, recipient)).fetchone()
            if row:
                chat_jid, chat_name = row[0], row[1]
                all_jids.append(chat_jid)
                conn_m.close()
                return chat_jid, chat_name, all_jids
            conn_m.close()
        except Exception:
            pass

    # Could not resolve
    return recipient, None, [recipient]


def _normalise_phone(digits: str) -> str:
    """Normalise a local Namibian number to international form (no symbols)."""
    if digits.startswith('0') and len(digits) == 10:
        return '264' + digits[1:]
    if len(digits) == 9 and digits.startswith('81'):
        return '264' + digits
    return digits


def _pn_for_lid(lid: str) -> Optional[str]:
    """Reverse-map a LID to its phone number using the local whatsmeow store."""
    if not lid or not os.path.exists(WHATSAPP_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(WHATSAPP_DB_PATH)
        row = conn.execute("SELECT pn FROM whatsmeow_lid_map WHERE lid = ?", (lid,)).fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return None


def resolve_send_target(recipient_input: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a recipient to the JID to SEND to, preferring the phone-number JID.

    WhatsApp addresses users by both phone number (``@s.whatsapp.net``) and LID
    (``@lid``). A LID cached locally can be stale once the contact has migrated
    accounts, and sending to a stale LID reaches the OLD account (WhatsApp then
    warns "this number is connected to a new WhatsApp account"). Sending to the PN
    and letting the bridge re-resolve the live account is the reliable path, so a
    cached LID is converted back to its phone number here.

    Returns ``(jid, display_name)``.
    """
    primary_jid, display_name, _ = resolve_recipient(recipient_input)
    if not primary_jid:
        return None, None

    if '@' in primary_jid:
        if '@s.whatsapp.net' in primary_jid:
            return primary_jid, display_name
        if '@lid' in primary_jid:
            pn = _pn_for_lid(primary_jid.split('@')[0])
            if pn:
                return f"{pn}@s.whatsapp.net", display_name
        # Could not recover a phone number; let the bridge re-resolve the LID.
        return primary_jid, display_name

    digits = re.sub(r'[^\d]', '', primary_jid)
    if digits:
        return f"{_normalise_phone(digits)}@s.whatsapp.net", display_name
    return primary_jid, display_name


def check_whatsapp(number: str) -> Dict[str, Any]:
    """Ask the live bridge whether a phone number is registered on WhatsApp and
    return its CURRENT canonical JID (catches migrated accounts)."""
    digits = _normalise_phone(re.sub(r'[^\d]', '', number or ''))
    if not digits:
        return {"on_whatsapp": False, "error": f"could not parse a phone number from {number!r}"}
    try:
        resp = requests.get(f"{WHATSAPP_API_BASE_URL}/resolve_user", params={"phone": digits}, timeout=20)
        if resp.status_code != 200:
            return {"on_whatsapp": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
        results = resp.json().get("results") or []
        if not results:
            return {"on_whatsapp": False, "phone_number": digits}
        r = results[0]
        return {
            "on_whatsapp": bool(r.get("IsIn")),
            "phone_number": r.get("PhoneNumber") or f"{digits}@s.whatsapp.net",
            "jid": r.get("JID"),
        }
    except requests.RequestException as e:
        return {"on_whatsapp": False, "error": f"Request error: {str(e)}"}
    except Exception as e:
        return {"on_whatsapp": False, "error": f"Unexpected error: {str(e)}"}


def resolve_contact(query: str) -> Dict[str, Any]:
    """Resolve a name, phone number, JID or LID to its identity, including the
    CURRENT account resolved live from WhatsApp. Use before sending to a number
    that may have migrated accounts."""
    primary_jid, display_name, all_jids = resolve_recipient(query)

    phone_number: Optional[str] = None
    cached_lid: Optional[str] = None
    for j in all_jids:
        if j.endswith('@s.whatsapp.net') and not phone_number:
            phone_number = j.split('@')[0]
        elif j.endswith('@lid') and not cached_lid:
            cached_lid = j.split('@')[0]

    if not phone_number:
        send_jid, _ = resolve_send_target(query)
        if send_jid and send_jid.endswith('@s.whatsapp.net'):
            phone_number = send_jid.split('@')[0]
    if not phone_number and cached_lid:
        phone_number = _pn_for_lid(cached_lid)

    result: Dict[str, Any] = {
        "query": query,
        "name": display_name,
        "jid": primary_jid,
        "phone_number": phone_number,
        "cached_lid": cached_lid,
        "associated_jids": all_jids,
    }

    if phone_number:
        live = check_whatsapp(phone_number)
        result["on_whatsapp"] = live.get("on_whatsapp")
        result["current_jid"] = live.get("jid")
        result["current_lid"] = (live.get("jid") or "").split('@')[0] if live.get("jid") else None
        if live.get("error"):
            result["live_error"] = live["error"]
    else:
        result["on_whatsapp"] = None
        result["current_jid"] = None
        result["current_lid"] = None

    return result


def get_sender_name(sender_jid: str) -> str:
    """Gets human-readable sender name from phone contacts or chats."""
    # First check whatsmeow_contacts (phonebook)
    if os.path.exists(WHATSAPP_DB_PATH):
        try:
            conn_wa = sqlite3.connect(WHATSAPP_DB_PATH)
            c_wa = conn_wa.cursor()
            row = c_wa.execute(
                "SELECT COALESCE(NULLIF(full_name, ''), NULLIF(first_name, ''), push_name) FROM whatsmeow_contacts WHERE their_jid = ?",
                (sender_jid,)
            ).fetchone()
            if row and row[0]:
                conn_wa.close()
                return row[0]
            
            # The sender may be a LID, either as '...@lid' or as bare digits the
            # way messages.sender stores it. Map LID -> phone number -> contact.
            if '@lid' in sender_jid or '@' not in sender_jid:
                lid = sender_jid.split('@')[0]
                map_row = c_wa.execute("SELECT pn FROM whatsmeow_lid_map WHERE lid = ?", (lid,)).fetchone()
                if map_row and map_row[0]:
                    pn_jid = f"{map_row[0]}@s.whatsapp.net"
                    row = c_wa.execute(
                        "SELECT COALESCE(NULLIF(full_name, ''), NULLIF(first_name, ''), push_name) FROM whatsmeow_contacts WHERE their_jid = ?",
                        (pn_jid,)
                    ).fetchone()
                    if row and row[0]:
                        conn_wa.close()
                        return row[0]
            conn_wa.close()
        except Exception:
            pass

    # Next check chats table in messages.db
    if os.path.exists(MESSAGES_DB_PATH):
        try:
            conn_m = sqlite3.connect(MESSAGES_DB_PATH)
            c_m = conn_m.cursor()
            row = c_m.execute("SELECT name FROM chats WHERE jid = ? LIMIT 1", (sender_jid,)).fetchone()
            if row and row[0]:
                conn_m.close()
                return row[0]
            conn_m.close()
        except Exception:
            pass

    # Fallback to phone number part without domain
    if '@' in sender_jid:
        return sender_jid.split('@')[0]
    return sender_jid

def format_message(message: Message, show_chat_info: bool = True) -> str:
    """Formats a single message cleanly."""
    time_str = message.timestamp.strftime("%Y-%m-%d %H:%M:%S") if isinstance(message.timestamp, datetime) else str(message.timestamp)
    chat_info = f"Chat: {message.chat_name} " if (show_chat_info and message.chat_name) else ""
    sender_name = "Me" if message.is_from_me else get_sender_name(message.sender)
    media_info = f"[{message.media_type}] " if (message.media_type and message.media_type != 'none') else ""
    return f"[{time_str}] {chat_info}From {sender_name}: {media_info}{message.content}".strip()

def format_messages_list(messages: List[Message], show_chat_info: bool = True) -> str:
    """Formats a list of messages into readable text."""
    if not messages:
        return "No messages found."
    return "\n".join(format_message(m, show_chat_info) for m in messages)

def search_contacts(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search WhatsApp contacts by name or phone number across both the address book and chat history."""
    limit, _ = _clamp_limit_page(limit, 0, 50)
    pattern = f"%{query}%"
    contacts_map: Dict[str, Dict[str, Any]] = {}

    # Query whatsmeow_contacts (2,300+ phonebook contacts)
    if os.path.exists(WHATSAPP_DB_PATH):
        try:
            conn_wa = sqlite3.connect(WHATSAPP_DB_PATH)
            c_wa = conn_wa.cursor()
            rows = c_wa.execute("""
                SELECT their_jid, COALESCE(NULLIF(full_name, ''), NULLIF(first_name, ''), push_name, their_jid)
                FROM whatsmeow_contacts
                WHERE full_name LIKE ? OR first_name LIKE ? OR push_name LIKE ? OR their_jid LIKE ?
                LIMIT ?
            """, (pattern, pattern, pattern, pattern, limit * 2)).fetchall()
            
            for jid, name in rows:
                pn = jid.split('@')[0] if '@' in jid else jid
                lid_row = c_wa.execute("SELECT lid FROM whatsmeow_lid_map WHERE pn = ?", (pn,)).fetchone()
                lid = f"{lid_row[0]}@lid" if (lid_row and lid_row[0]) else None
                contacts_map[pn] = {
                    "name": name,
                    "phone_number": pn,
                    "jid": jid,
                    "lid": lid,
                    "target": lid if lid else jid
                }
            conn_wa.close()
        except Exception as e:
            print(f"Error querying whatsmeow_contacts: {e}")

    # Query chats table in messages.db
    if os.path.exists(MESSAGES_DB_PATH):
        try:
            conn_m = sqlite3.connect(MESSAGES_DB_PATH)
            c_m = conn_m.cursor()
            rows = c_m.execute("""
                SELECT jid, name
                FROM chats
                WHERE (name LIKE ? OR jid LIKE ?) AND jid NOT LIKE '%@g.us'
                LIMIT ?
            """, (pattern, pattern, limit * 2)).fetchall()
            
            for jid, name in rows:
                pn = jid.split('@')[0] if '@' in jid else jid
                if pn not in contacts_map and name:
                    contacts_map[pn] = {
                        "name": name,
                        "phone_number": pn,
                        "jid": jid,
                        "lid": None,
                        "target": jid
                    }
            conn_m.close()
        except Exception as e:
            print(f"Error querying chats for contacts: {e}")

    return list(contacts_map.values())[:limit]

def list_messages(
    chat_or_contact: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    after: Optional[str] = None,
    before: Optional[str] = None,
    sender_phone_number: Optional[str] = None,
    chat_jid: Optional[str] = None,
    include_context: bool = False,
    context_before: int = 1,
    context_after: int = 1
) -> List[Dict[str, Any]]:
    """Get WhatsApp messages matching specified criteria as clean, structured dictionaries.
    
    Args:
        chat_or_contact: Contact name ('Tysen'), phone number ('0817721286'), or JID to filter messages for.
        query: Optional text search term to filter message content.
        limit: Max messages to return (default 20).
        page: Page number for pagination.
        after: Optional ISO-8601 string for messages after date.
        before: Optional ISO-8601 string for messages before date.
        sender_phone_number: Filter by sender phone number.
        chat_jid: Specific chat JID.
    """
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        query_parts = [
            "SELECT m.timestamp, m.sender, c.name, m.content, m.is_from_me, m.chat_jid, m.id, m.media_type",
            "FROM messages m",
            "LEFT JOIN chats c ON m.chat_jid = c.jid"
        ]
        where_clauses = []
        params: List[Any] = []

        # Resolve chat_or_contact to all associated JIDs (both LID and Phone JID)
        target = chat_or_contact or chat_jid
        if target:
            _, _, all_jids = resolve_recipient(target)
            if all_jids:
                placeholders = ','.join(['?'] * len(all_jids))
                where_clauses.append(f"(m.chat_jid IN ({placeholders}) OR m.sender IN ({placeholders}))")
                params.extend(all_jids * 2)
            else:
                where_clauses.append("m.chat_jid = ?")
                params.append(target)

        if after:
            where_clauses.append("m.timestamp > ?")
            params.append(after)

        if before:
            where_clauses.append("m.timestamp < ?")
            params.append(before)

        if sender_phone_number:
            where_clauses.append("m.sender LIKE ? ESCAPE '\\'")
            params.append(_like(sender_phone_number))

        if query:
            where_clauses.append("LOWER(m.content) LIKE LOWER(?) ESCAPE '\\'")
            params.append(_like(query))

        if where_clauses:
            query_parts.append("WHERE " + " AND ".join(where_clauses))

        limit, page = _clamp_limit_page(limit, page)
        offset = page * limit
        query_parts.append("ORDER BY m.timestamp DESC")
        query_parts.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])

        cursor.execute(" ".join(query_parts), tuple(params))
        rows = cursor.fetchall()

        results = []
        for r in rows:
            ts = r[0]
            sender = r[1]
            chat_name = r[2]
            content = r[3]
            is_from_me = bool(r[4])
            c_jid = r[5]
            msg_id = r[6]
            media_type = r[7]

            sender_name = "Me" if is_from_me else get_sender_name(sender)
            results.append({
                "id": msg_id,
                "timestamp": str(ts),
                "sender": sender,
                "sender_name": sender_name,
                "content": content,
                "is_from_me": is_from_me,
                "chat_jid": c_jid,
                "chat_name": chat_name,
                "media_type": media_type
            })

        return results
    except Exception as e:
        print(f"Database error in list_messages: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()

def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active"
) -> List[Dict[str, Any]]:
    """Get WhatsApp chats matching specified criteria as clean dictionaries."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        query_parts = [
            "SELECT c.jid, c.name, c.last_message_time, m.content, m.sender, m.is_from_me",
            "FROM chats c",
            "LEFT JOIN messages m ON c.jid = m.chat_jid AND c.last_message_time = m.timestamp"
        ]
        params: List[Any] = []

        if query:
            query_parts.append("WHERE LOWER(c.name) LIKE LOWER(?) ESCAPE '\\' OR LOWER(c.jid) LIKE LOWER(?) ESCAPE '\\'")
            params.extend([_like(query), _like(query)])

        order_col = "c.name ASC" if sort_by == "name" else "c.last_message_time DESC"
        query_parts.append(f"ORDER BY {order_col}")

        limit, page = _clamp_limit_page(limit, page)
        offset = page * limit
        query_parts.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])

        cursor.execute(" ".join(query_parts), tuple(params))
        rows = cursor.fetchall()

        results = []
        for r in rows:
            jid = r[0]
            name = r[1]
            last_time = r[2]
            last_content = r[3]
            last_sender = r[4]
            last_is_from_me = bool(r[5]) if r[5] is not None else None

            sender_name = "Me" if last_is_from_me else (get_sender_name(last_sender) if last_sender else None)
            results.append({
                "jid": jid,
                "name": name or (get_sender_name(jid) if not jid.endswith('@g.us') else jid),
                "last_message_time": str(last_time) if last_time else None,
                "last_message": last_content or "",
                "last_sender": last_sender,
                "last_sender_name": sender_name,
                "last_is_from_me": last_is_from_me,
                "is_group": jid.endswith("@g.us")
            })

        return results
    except Exception as e:
        print(f"Database error in list_chats: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()

def get_last_interaction(contact: str) -> Optional[Dict[str, Any]]:
    """Get the most recent WhatsApp message involving a contact (accepts name, phone, or JID)."""
    target_jid, display_name, all_jids = resolve_recipient(contact)
    if not all_jids:
        all_jids = [target_jid] if target_jid else []

    if not all_jids:
        return None

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        placeholders = ','.join(['?'] * len(all_jids))

        cursor.execute(f"""
            SELECT m.timestamp, m.sender, c.name, m.content, m.is_from_me, m.chat_jid, m.id, m.media_type
            FROM messages m
            LEFT JOIN chats c ON m.chat_jid = c.jid
            WHERE m.chat_jid IN ({placeholders}) OR m.sender IN ({placeholders})
            ORDER BY m.timestamp DESC
            LIMIT 1
        """, tuple(all_jids * 2))

        r = cursor.fetchone()
        if not r:
            return None

        is_from_me = bool(r[4])
        sender_name = "Me" if is_from_me else (display_name or get_sender_name(r[1]))

        return {
            "id": r[6],
            "timestamp": str(r[0]),
            "sender": r[1],
            "sender_name": sender_name,
            "content": r[3],
            "is_from_me": is_from_me,
            "chat_jid": r[5],
            "chat_name": r[2] or display_name,
            "media_type": r[7],
            "contact_name": display_name or sender_name
        }
    except Exception as e:
        print(f"Database error in get_last_interaction: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()

def wait_for_reply(
    recipient: str,
    timeout_seconds: int = 30,
    after_timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """Wait for the next incoming message from a contact, up to timeout_seconds.

    If the contact already replied after your last message, this returns that
    reply immediately (it does not wait for a *newer* one). The blocking wait is
    capped at MAX_WAIT_SECONDS so it always returns before an MCP client's tool
    timeout; poll again to keep waiting.

    Args:
        recipient: Contact name ('Tysen'), phone number ('0817721286'), or JID.
        timeout_seconds: Max seconds to wait (default 30, capped at MAX_WAIT_SECONDS).
        after_timestamp: Only consider messages after this timestamp. Defaults to
            the time of your last message in the chat. Pass the returned
            ``next_after`` to fetch the reply *after* the current one.
    """
    try:
        timeout_seconds = max(0, min(int(timeout_seconds), MAX_WAIT_SECONDS))
    except (TypeError, ValueError):
        timeout_seconds = 30

    target_jid, display_name, all_jids = resolve_recipient(recipient)
    if not all_jids:
        all_jids = [target_jid] if target_jid else []

    if not all_jids:
        return {"status": "error", "message": f"Could not find or resolve recipient: '{recipient}'"}

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        c = conn.cursor()
        placeholders = ','.join(['?'] * len(all_jids))

        # Baseline: the newest message WE sent. Anything the contact sends after
        # that is a reply — including one that already arrived before this call.
        baseline = after_timestamp
        if not baseline:
            row = c.execute(
                f"""SELECT MAX(timestamp) FROM messages
                    WHERE (chat_jid IN ({placeholders}) OR sender IN ({placeholders}))
                      AND is_from_me = 1""",
                tuple(all_jids * 2)
            ).fetchone()
            baseline = row[0] if (row and row[0]) else "2000-01-01"

        deadline = time.time() + timeout_seconds
        while True:
            # Oldest incoming message (is_from_me = 0) newer than the baseline.
            r = c.execute(
                f"""
                SELECT m.timestamp, m.sender, c.name, m.content, m.chat_jid, m.id, m.media_type
                FROM messages m
                LEFT JOIN chats c ON m.chat_jid = c.jid
                WHERE (m.chat_jid IN ({placeholders}) OR m.sender IN ({placeholders}))
                  AND m.is_from_me = 0
                  AND m.timestamp > ?
                ORDER BY m.timestamp ASC
                LIMIT 1
                """,
                tuple(all_jids * 2 + [baseline])
            ).fetchone()

            if r:
                sender_name = display_name or get_sender_name(r[1])
                return {
                    "status": "received",
                    "sender": r[1],
                    "sender_name": sender_name,
                    "content": r[3],
                    "timestamp": str(r[0]),
                    "chat_jid": r[4],
                    "id": r[5],
                    "media_type": r[6],
                    "next_after": str(r[0]),
                }

            if time.time() >= deadline:
                return {
                    "status": "timeout",
                    "message": f"No reply from {display_name or recipient} within {timeout_seconds}s.",
                    "baseline_timestamp": baseline,
                }
            time.sleep(1.5)
    except Exception as e:
        return {"status": "error", "message": f"Error waiting for reply: {e}"}
    finally:
        if 'conn' in locals():
            conn.close()

def get_chat(chat_jid: str, include_last_message: bool = True) -> Optional[Dict[str, Any]]:
    """Get chat metadata by JID."""
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        query = """
            SELECT c.jid, c.name, c.last_message_time, m.content, m.sender, m.is_from_me
            FROM chats c
            LEFT JOIN messages m ON c.jid = m.chat_jid AND c.last_message_time = m.timestamp
            WHERE c.jid = ?
        """
        cursor.execute(query, (chat_jid,))
        r = cursor.fetchone()
        if not r:
            return None

        is_from_me = bool(r[5]) if r[5] is not None else None
        return {
            "jid": r[0],
            "name": r[1] or get_sender_name(r[0]),
            "last_message_time": str(r[2]) if r[2] else None,
            "last_message": r[3] or "",
            "last_sender": r[4],
            "last_is_from_me": is_from_me,
            "is_group": r[0].endswith("@g.us")
        }
    except Exception as e:
        print(f"Database error in get_chat: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()

def get_direct_chat_by_contact(sender_phone_number: str) -> Optional[Dict[str, Any]]:
    """Get chat metadata by phone number or contact name."""
    target_jid, _, _ = resolve_recipient(sender_phone_number)
    if not target_jid:
        return None
    return get_chat(target_jid)

def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Dict[str, Any]]:
    """Get all WhatsApp chats involving the contact."""
    _, _, all_jids = resolve_recipient(jid)
    if not all_jids:
        all_jids = [jid]

    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        placeholders = ','.join(['?'] * len(all_jids))

        cursor.execute(f"""
            SELECT DISTINCT c.jid, c.name, c.last_message_time
            FROM chats c
            JOIN messages m ON c.jid = m.chat_jid
            WHERE m.sender IN ({placeholders}) OR c.jid IN ({placeholders})
            ORDER BY c.last_message_time DESC
            LIMIT ? OFFSET ?
        """, tuple(all_jids * 2 + [limit, page * limit]))

        rows = cursor.fetchall()
        return [{
            "jid": r[0],
            "name": r[1] or get_sender_name(r[0]),
            "last_message_time": str(r[2]) if r[2] else None,
            "is_group": r[0].endswith("@g.us")
        } for r in rows]
    except Exception as e:
        print(f"Database error in get_contact_chats: {e}")
        return []
    finally:
        if 'conn' in locals():
            conn.close()

def get_message_context(message_id: str, before: int = 5, after: int = 5) -> Dict[str, Any]:
    """Get context around a specific message."""
    try:
        before = max(0, min(int(before), 50))
        after = max(0, min(int(after), 50))
    except (TypeError, ValueError):
        before, after = 5, 5
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT m.timestamp, m.sender, c.name, m.content, m.is_from_me, m.chat_jid, m.id, m.media_type
            FROM messages m
            LEFT JOIN chats c ON m.chat_jid = c.jid
            WHERE m.id = ?
        """, (message_id,))
        target_row = cursor.fetchone()
        if not target_row:
            return {"target": None, "before": [], "after": []}

        target_ts = target_row[0]
        chat_jid = target_row[5]

        # Messages before
        cursor.execute("""
            SELECT m.timestamp, m.sender, c.name, m.content, m.is_from_me, m.chat_jid, m.id, m.media_type
            FROM messages m
            LEFT JOIN chats c ON m.chat_jid = c.jid
            WHERE m.chat_jid = ? AND m.timestamp < ?
            ORDER BY m.timestamp DESC
            LIMIT ?
        """, (chat_jid, target_ts, before))
        before_rows = cursor.fetchall()

        # Messages after
        cursor.execute("""
            SELECT m.timestamp, m.sender, c.name, m.content, m.is_from_me, m.chat_jid, m.id, m.media_type
            FROM messages m
            LEFT JOIN chats c ON m.chat_jid = c.jid
            WHERE m.chat_jid = ? AND m.timestamp > ?
            ORDER BY m.timestamp ASC
            LIMIT ?
        """, (chat_jid, target_ts, after))
        after_rows = cursor.fetchall()

        def to_dict(r):
            is_me = bool(r[4])
            return {
                "id": r[6],
                "timestamp": str(r[0]),
                "sender": r[1],
                "sender_name": "Me" if is_me else get_sender_name(r[1]),
                "content": r[3],
                "is_from_me": is_me,
                "chat_jid": r[5],
                "chat_name": r[2],
                "media_type": r[7]
            }

        return {
            "target": to_dict(target_row),
            "before": [to_dict(r) for r in reversed(before_rows)],
            "after": [to_dict(r) for r in after_rows]
        }
    except Exception as e:
        print(f"Error in get_message_context: {e}")
        return {"target": None, "before": [], "after": []}
    finally:
        if 'conn' in locals():
            conn.close()

def send_message(recipient: str, message: str) -> Tuple[bool, str]:
    """Send a WhatsApp message. Resolves contact name, phone, JID, or LID automatically."""
    target_jid, display_name = resolve_send_target(recipient)
    if not target_jid:
        return False, f"Recipient could not be resolved: '{recipient}'"

    url = f"{WHATSAPP_API_BASE_URL}/send"
    payload = {
        "recipient": target_jid,
        "message": message,
    }

    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.status_code == 200:
            result = response.json()
            dest_label = f"{display_name} ({target_jid})" if display_name else target_jid
            return result.get("success", False), f"Message delivered to {dest_label}"
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"
    except requests.RequestException as e:
        return False, f"Request error connecting to WhatsApp bridge: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def send_file(recipient: str, media_path: str) -> Tuple[bool, str]:
    """Send a file (image, video, document) via WhatsApp with automatic recipient resolution."""
    target_jid, display_name = resolve_send_target(recipient)
    if not target_jid:
        return False, f"Recipient could not be resolved: '{recipient}'"

    if not media_path or not os.path.isfile(media_path):
        return False, f"Media file not found: {media_path}"

    url = f"{WHATSAPP_API_BASE_URL}/send"
    payload = {
        "recipient": target_jid,
        "media_path": media_path
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            result = response.json()
            dest_label = f"{display_name} ({target_jid})" if display_name else target_jid
            return result.get("success", False), f"File delivered to {dest_label}"
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"
    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def send_audio_message(recipient: str, media_path: str) -> Tuple[bool, str]:
    """Send an audio voice message via WhatsApp with automatic recipient resolution."""
    target_jid, display_name = resolve_send_target(recipient)
    if not target_jid:
        return False, f"Recipient could not be resolved: '{recipient}'"

    if not media_path or not os.path.isfile(media_path):
        return False, f"Audio file not found: {media_path}"

    converted_file = None
    if not media_path.endswith(".ogg"):
        try:
            converted_file = audio.convert_to_opus_ogg_temp(media_path)
            upload_path = converted_file
        except Exception as e:
            return False, f"Audio conversion error: {str(e)}"
    else:
        upload_path = media_path

    try:
        success, msg = send_file(target_jid, upload_path)
        return success, msg
    finally:
        if converted_file and os.path.exists(converted_file):
            try:
                os.unlink(converted_file)
            except Exception:
                pass

def download_media(message_id: str, chat_jid: str) -> Optional[str]:
    """Download media from a WhatsApp message."""
    try:
        url = f"{WHATSAPP_API_BASE_URL}/download"
        payload = {"message_id": message_id, "chat_jid": chat_jid}
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                return result.get("file_path")
        return None
    except Exception as e:
        print(f"Error downloading media: {e}")
        return None


def _ensure_handled_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS handled (chat_jid TEXT PRIMARY KEY, handled_at TEXT)")


def _latest_per_chat(conn: sqlite3.Connection) -> List[Any]:
    return conn.execute(
        """
        SELECT m.chat_jid, c.name, m.timestamp, m.content, m.is_from_me, m.sender
        FROM messages m
        LEFT JOIN chats c ON c.jid = m.chat_jid
        WHERE m.timestamp = (SELECT MAX(m2.timestamp) FROM messages m2 WHERE m2.chat_jid = m.chat_jid)
        ORDER BY m.timestamp DESC
        LIMIT ?
        """,
        (MAX_LIMIT,),
    ).fetchall()


def list_outbox(limit: int = 50) -> List[Dict[str, Any]]:
    """Chats that need a reply: the newest message in the chat is from the other
    person (not you) and the chat has not been marked handled.

    If you reply (a message is stored with is_from_me), the chat drops out on its
    own; mark_handled() hides one you are deliberately ignoring."""
    limit, _ = _clamp_limit_page(limit, 0, 50)
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        _ensure_handled_table(conn)
        rows = _latest_per_chat(conn)
        handled = {r[0] for r in conn.execute("SELECT chat_jid FROM handled").fetchall()}
        conn.close()
        out: List[Dict[str, Any]] = []
        for jid, name, ts, content, is_from_me, sender in rows:
            if is_from_me or jid in handled:
                continue
            out.append({
                "chat_jid": jid,
                "chat_name": name or get_sender_name(sender),
                "last_message": content,
                "last_message_time": str(ts),
                "needs_reply": True,
            })
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        print(f"Database error in list_outbox: {e}")
        return []


def list_inbox(limit: int = 50) -> List[Dict[str, Any]]:
    """Recent conversations and where each stands: who spoke last and whether it
    still needs a reply from you."""
    limit, _ = _clamp_limit_page(limit, 0, 50)
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        _ensure_handled_table(conn)
        rows = _latest_per_chat(conn)
        handled = {r[0] for r in conn.execute("SELECT chat_jid FROM handled").fetchall()}
        conn.close()
        out: List[Dict[str, Any]] = []
        for jid, name, ts, content, is_from_me, sender in rows:
            out.append({
                "chat_jid": jid,
                "chat_name": name or (None if is_from_me else get_sender_name(sender)),
                "last_message": content,
                "last_message_time": str(ts),
                "last_from_me": bool(is_from_me),
                "needs_reply": (not is_from_me) and (jid not in handled),
            })
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        print(f"Database error in list_inbox: {e}")
        return []


def mark_handled(chat: str, handled: bool = True) -> Dict[str, Any]:
    """Mark a chat as handled (or clear it) so it leaves/returns to the outbox."""
    target_jid, _, all_jids = resolve_recipient(chat)
    targets = all_jids or ([target_jid] if target_jid else [chat])
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH, timeout=5)
        conn.execute("PRAGMA busy_timeout=5000")
        _ensure_handled_table(conn)
        for t in targets:
            if handled:
                conn.execute("INSERT OR REPLACE INTO handled (chat_jid, handled_at) VALUES (?, datetime('now'))", (t,))
            else:
                conn.execute("DELETE FROM handled WHERE chat_jid = ?", (t,))
        conn.commit()
        conn.close()
        return {"chat": targets[0], "handled": handled}
    except Exception as e:
        return {"error": str(e)}


def get_thread(chat_or_contact: str, limit: int = 30) -> List[Dict[str, Any]]:
    """The recent message thread with a person or group, newest first."""
    return list_messages(chat_or_contact=chat_or_contact, limit=limit)


def request_reply_approval(contact: str, draft: str) -> Dict[str, Any]:
    """Ask you (the account owner, WA_OWNER_JID) to approve a draft reply before
    it is sent. Sends the draft to your own WhatsApp; reply YES/NO/edited."""
    owner = os.environ.get("WA_OWNER_JID", "").strip()
    if not owner:
        return {"sent": False, "error": "WA_OWNER_JID is not set for this account"}
    body = (
        f"[approval] Draft reply to {contact}:\n\n{draft}\n\n"
        "Reply YES to send it, NO to cancel, or send an edited version."
    )
    ok, msg = send_message(owner, body)
    return {"sent": ok, "message": msg, "awaiting": "your reply"}
