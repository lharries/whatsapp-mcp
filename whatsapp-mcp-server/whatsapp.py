import json
import logging
import os
import os.path
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

import requests

import audio  # type: ignore[import-not-found]  # local sibling module

logger = logging.getLogger(__name__)

MESSAGES_DB_PATH = os.environ.get(
    "MESSAGES_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "whatsapp-bridge",
        "store",
        "messages.db",
    ),
)
WHATSAPP_API_BASE_URL = os.environ.get(
    "WHATSAPP_API_BASE_URL", "http://localhost:8080/api"
)
# whatsmeow's own session db, always next to messages.db. Holds whatsmeow_lid_map.
SESSION_DB_PATH = os.path.join(os.path.dirname(MESSAGES_DB_PATH), "whatsapp.db")

# Dual-source routing (Phase E shim)
WA_BRIDGE_SOURCE = os.environ.get("WA_BRIDGE_SOURCE", "local")
SSH_HOST = os.environ.get("WA_BRIDGE_SSH_HOST", "")
VPS_DB_PATH = os.environ.get("WA_BRIDGE_VPS_DB", "/opt/wa-bridge/bridge.db")


@dataclass
class Message:
    timestamp: datetime
    sender: str
    content: str
    is_from_me: bool
    chat_jid: str
    id: str
    chat_name: str | None = None
    media_type: str | None = None


@dataclass
class Chat:
    jid: str
    name: str | None
    last_message_time: datetime | None
    last_message: str | None = None
    last_sender: str | None = None
    last_is_from_me: bool | None = None

    @property
    def is_group(self) -> bool:
        """Determine if chat is a group based on JID pattern."""
        return self.jid.endswith("@g.us")


@dataclass
class Contact:
    phone_number: str
    name: str | None
    jid: str


@dataclass
class MessageContext:
    message: Message
    before: list[Message]
    after: list[Message]


def _sql_literal(v: object) -> str:
    """Safely quote a value for inline SQL substitution (used for ssh+sqlite3 path)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("'", "''")
    return f"'{s}'"


def _ssh_query(sql: str, params: list | None = None) -> list[tuple]:
    """Execute SQL on the VPS via ssh+sqlite3.

    Returns rows as tuples (tab-separated parse). Uses positional ``?``
    substitution like sqlite3.execute, but interpolates values into the SQL
    string after escaping single quotes — safe for our internal use because
    callers control the SQL template and only values flow through ``params``.
    """
    if params:
        parts = sql.split("?")
        if len(parts) != len(params) + 1:
            raise ValueError(
                f"param count mismatch: {len(params)} for {len(parts) - 1} placeholders"
            )
        sql_filled = parts[0]
        for i, p in enumerate(params):
            sql_filled += _sql_literal(p) + parts[i + 1]
    else:
        sql_filled = sql
    # ssh re-evaluates the remote command string through the login shell, so
    # we must shell-escape every token (including the SQL with its parens,
    # spaces, and quotes) before sending it across. We use sqlite3 JSON mode
    # because the default tab/newline output cannot represent embedded
    # newlines in text columns (each \n becomes a fake row), corrupting
    # column counts on rows with multi-line message text.
    remote_cmd = " ".join(
        shlex.quote(t)
        for t in ("sqlite3", "-json", VPS_DB_PATH, sql_filled)
    )
    result = subprocess.run(  # noqa: S603
        ["ssh", SSH_HOST, remote_cmd],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ssh sqlite3 failed: {result.stderr}")
    out = result.stdout.strip()
    if not out:
        return []
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ssh sqlite3 JSON parse failed: {e}") from e
    # sqlite3 -json returns a list of dicts; preserve column order from SQL
    # by reading the first dict's keys (sqlite3 emits them in SELECT order).
    if not parsed:
        return []
    keys = list(parsed[0].keys())
    return [tuple(row.get(k) for k in keys) for row in parsed]


def _vps_jid(phone: str, is_group: int | str) -> str:
    """Convert VPS phone+is_group to a JID-like string."""
    is_g = int(is_group) if str(is_group) else 0
    return f"{phone}@g.us" if is_g else f"{phone}@s.whatsapp.net"


def _vps_iso(ts: int | str) -> str:
    """Convert VPS unix ts to ISO-8601 string (UTC)."""
    return datetime.utcfromtimestamp(int(ts)).isoformat()


def get_sender_name(sender_jid: str) -> str:
    if WA_BRIDGE_SOURCE == "ssh":
        # VPS msgs has no chats table — use name from msgs by phone match.
        phone_part = sender_jid.split("@")[0] if "@" in sender_jid else sender_jid
        try:
            rows = _ssh_query(
                "SELECT name FROM msgs WHERE phone = ? AND name != '' ORDER BY ts DESC LIMIT 1",
                [phone_part],
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("ssh sender lookup failed: %s", e)
            return sender_jid
        if rows and rows[0] and rows[0][0]:
            return rows[0][0]
        return sender_jid

    try:
        with sqlite3.connect(MESSAGES_DB_PATH) as conn:
            cursor = conn.cursor()

            # First try matching by exact JID
            cursor.execute(
                """
                SELECT name
                FROM chats
                WHERE jid = ?
                LIMIT 1
            """,
                (sender_jid,),
            )

            result = cursor.fetchone()

            # If no result, try looking for the number within JIDs
            if not result:
                # Extract the phone number part if it's a JID
                if "@" in sender_jid:
                    phone_part = sender_jid.split("@")[0]
                else:
                    phone_part = sender_jid

                cursor.execute(
                    """
                    SELECT name
                    FROM chats
                    WHERE jid LIKE ?
                    LIMIT 1
                """,
                    (f"%{phone_part}%",),
                )

                result = cursor.fetchone()

            if result and result[0]:
                return result[0]
            return sender_jid
    except sqlite3.Error as e:
        logger.warning("Database error while getting sender name: %s", e)
        return sender_jid


def format_message(message: Message, show_chat_info: bool = True) -> str:
    """Format a single message as a string."""
    output = ""

    if show_chat_info and message.chat_name:
        output += (
            f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] Chat: {message.chat_name} "
        )
    else:
        output += f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] "

    content_prefix = ""
    if hasattr(message, "media_type") and message.media_type:
        content_prefix = (
            f"[{message.media_type} - Message ID: {message.id}"
            f" - Chat JID: {message.chat_jid}] "
        )

    try:
        sender_name = (
            get_sender_name(message.sender) if not message.is_from_me else "Me"
        )
        output += f"From: {sender_name}: {content_prefix}{message.content}\n"
    except Exception as e:  # noqa: BLE001
        logger.warning("Error formatting message: %s", e)
    return output


def format_messages_list(
    messages: list[Message], show_chat_info: bool = True
) -> str:
    output = ""
    if not messages:
        output += "No messages to display."
        return output

    for message in messages:
        output += format_message(message, show_chat_info)
    return output


def _ssh_list_messages(
    after: str | None,
    before: str | None,
    sender_phone_number: str | None,
    chat_jid: str | None,
    query: str | None,
    limit: int,
    page: int,
) -> list[Message]:
    """SSH-path implementation of list_messages (returns Message list)."""
    where: list[str] = []
    params: list = []

    if after:
        try:
            after_dt = datetime.fromisoformat(after)
        except ValueError as e:
            raise ValueError(
                f"Invalid date format for 'after': {after}. Please use ISO-8601 format."
            ) from e
        where.append("ts > ?")
        params.append(int(after_dt.timestamp()))

    if before:
        try:
            before_dt = datetime.fromisoformat(before)
        except ValueError as e:
            raise ValueError(
                f"Invalid date format for 'before': {before}. Please use ISO-8601 format."
            ) from e
        where.append("ts < ?")
        params.append(int(before_dt.timestamp()))

    if sender_phone_number:
        phone_part = (
            sender_phone_number.split("@")[0]
            if "@" in sender_phone_number
            else sender_phone_number
        )
        where.append("phone = ?")
        params.append(phone_part)

    if chat_jid:
        phone_part = chat_jid.split("@")[0] if "@" in chat_jid else chat_jid
        where.append("phone = ?")
        params.append(phone_part)

    if query:
        where.append("LOWER(text) LIKE LOWER(?)")
        params.append(f"%{query}%")

    # ponytail: live msgs table has no is_group column — emit literal 0 so downstream unpacking still gets the key. Ceiling: all VPS chats treated as 1:1 (no group detection); add real column if bridge ever stores groups.
    sql = "SELECT ts, dir, phone, name, text, msg_id, 0 AS is_group FROM msgs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
    params.extend([limit, page * limit])

    rows = _ssh_query(sql, params)
    out: list[Message] = []
    for r in rows:
        ts, direction, phone, name, text, msg_id, is_group = r
        jid = _vps_jid(phone, is_group)
        out.append(
            Message(
                timestamp=datetime.utcfromtimestamp(int(ts)),
                sender=phone,
                chat_name=name or None,
                content=text or "",
                is_from_me=(direction == "out"),
                chat_jid=jid,
                id=msg_id or "",
                media_type=None,
            )
        )
    return out


def list_messages(
    after: str | None = None,
    before: str | None = None,
    sender_phone_number: str | None = None,
    chat_jid: str | None = None,
    query: str | None = None,
    limit: int = 20,
    page: int = 0,
    include_context: bool = True,
    context_before: int = 1,
    context_after: int = 1,
) -> str:
    """Get messages matching the specified criteria with optional context."""
    if WA_BRIDGE_SOURCE == "ssh":
        try:
            result = _ssh_list_messages(
                after, before, sender_phone_number, chat_jid, query, limit, page
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("ssh list_messages failed: %s", e)
            return ""
        if include_context and result:
            messages_with_context: list[Message] = []
            for msg in result:
                ctx = get_message_context(msg.id, context_before, context_after)
                messages_with_context.extend(ctx.before)
                messages_with_context.append(ctx.message)
                messages_with_context.extend(ctx.after)
            return format_messages_list(messages_with_context, show_chat_info=True)
        return format_messages_list(result, show_chat_info=True)

    try:
        with sqlite3.connect(MESSAGES_DB_PATH) as conn:
            cursor = conn.cursor()

            # Build base query
            query_parts = [
                "SELECT messages.timestamp, messages.sender, chats.name, messages.content,"
                " messages.is_from_me, chats.jid, messages.id, messages.media_type FROM messages"
            ]
            query_parts.append("JOIN chats ON messages.chat_jid = chats.jid")
            where_clauses: list[str] = []
            params: list = []

            # Add filters
            if after:
                try:
                    after_dt = datetime.fromisoformat(after)
                except ValueError as e:
                    raise ValueError(
                        f"Invalid date format for 'after': {after}."
                        " Please use ISO-8601 format."
                    ) from e

                where_clauses.append("messages.timestamp > ?")
                params.append(after_dt)

            if before:
                try:
                    before_dt = datetime.fromisoformat(before)
                except ValueError as e:
                    raise ValueError(
                        f"Invalid date format for 'before': {before}."
                        " Please use ISO-8601 format."
                    ) from e

                where_clauses.append("messages.timestamp < ?")
                params.append(before_dt)

            if sender_phone_number:
                where_clauses.append("messages.sender = ?")
                params.append(sender_phone_number)

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
                    id=msg[6],
                    media_type=msg[7],
                )
                result.append(message)

            if include_context and result:
                # Add context for each message
                messages_with_context = []
                for msg in result:
                    context = get_message_context(
                        msg.id, context_before, context_after
                    )
                    messages_with_context.extend(context.before)
                    messages_with_context.append(context.message)
                    messages_with_context.extend(context.after)

                return format_messages_list(
                    messages_with_context, show_chat_info=True
                )

            # Format and display messages without context
            return format_messages_list(result, show_chat_info=True)
    except sqlite3.Error as e:
        logger.warning("Database error: %s", e)
        return ""


def get_message_context(
    message_id: str,
    before: int = 5,
    after: int = 5,
) -> MessageContext:
    """Get context around a specific message."""
    if WA_BRIDGE_SOURCE == "ssh":
        rows = _ssh_query(
            # ponytail: no is_group column on live table — literal 0 keeps unpack shape.
            "SELECT ts, dir, phone, name, text, msg_id, 0 AS is_group"
            " FROM msgs WHERE msg_id = ? LIMIT 1",
            [message_id],
        )
        if not rows:
            raise ValueError(f"Message with ID {message_id} not found")
        ts, direction, phone, name, text, msg_id, is_group = rows[0]
        jid = _vps_jid(phone, is_group)
        target_message = Message(
            timestamp=datetime.utcfromtimestamp(int(ts)),
            sender=phone,
            chat_name=name or None,
            content=text or "",
            is_from_me=(direction == "out"),
            chat_jid=jid,
            id=msg_id or "",
            media_type=None,
        )
        before_rows = _ssh_query(
            # ponytail: no is_group column on live table — literal 0 keeps unpack shape.
            "SELECT ts, dir, phone, name, text, msg_id, 0 AS is_group"
            " FROM msgs WHERE phone = ? AND ts < ? ORDER BY ts DESC LIMIT ?",
            [phone, int(ts), before],
        )
        before_messages = [
            Message(
                timestamp=datetime.utcfromtimestamp(int(r[0])),
                sender=r[2],
                chat_name=r[3] or None,
                content=r[4] or "",
                is_from_me=(r[1] == "out"),
                chat_jid=_vps_jid(r[2], r[6]),
                id=r[5] or "",
                media_type=None,
            )
            for r in before_rows
        ]
        after_rows = _ssh_query(
            # ponytail: no is_group column on live table — literal 0 keeps unpack shape.
            "SELECT ts, dir, phone, name, text, msg_id, 0 AS is_group"
            " FROM msgs WHERE phone = ? AND ts > ? ORDER BY ts ASC LIMIT ?",
            [phone, int(ts), after],
        )
        after_messages = [
            Message(
                timestamp=datetime.utcfromtimestamp(int(r[0])),
                sender=r[2],
                chat_name=r[3] or None,
                content=r[4] or "",
                is_from_me=(r[1] == "out"),
                chat_jid=_vps_jid(r[2], r[6]),
                id=r[5] or "",
                media_type=None,
            )
            for r in after_rows
        ]
        return MessageContext(
            message=target_message, before=before_messages, after=after_messages
        )

    try:
        with sqlite3.connect(MESSAGES_DB_PATH) as conn:
            cursor = conn.cursor()

            # Get the target message first
            cursor.execute(
                """
                SELECT messages.timestamp, messages.sender, chats.name, messages.content,
                       messages.is_from_me, chats.jid, messages.id, messages.chat_jid,
                       messages.media_type
                FROM messages
                JOIN chats ON messages.chat_jid = chats.jid
                WHERE messages.id = ?
            """,
                (message_id,),
            )
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
                media_type=msg_data[8],
            )

            # Get messages before
            cursor.execute(
                """
                SELECT messages.timestamp, messages.sender, chats.name, messages.content,
                       messages.is_from_me, chats.jid, messages.id, messages.media_type
                FROM messages
                JOIN chats ON messages.chat_jid = chats.jid
                WHERE messages.chat_jid = ? AND messages.timestamp < ?
                ORDER BY messages.timestamp DESC
                LIMIT ?
            """,
                (msg_data[7], msg_data[0], before),
            )

            before_messages = []
            for msg in cursor.fetchall():
                before_messages.append(
                    Message(
                        timestamp=datetime.fromisoformat(msg[0]),
                        sender=msg[1],
                        chat_name=msg[2],
                        content=msg[3],
                        is_from_me=msg[4],
                        chat_jid=msg[5],
                        id=msg[6],
                        media_type=msg[7],
                    )
                )

            # Get messages after
            cursor.execute(
                """
                SELECT messages.timestamp, messages.sender, chats.name, messages.content,
                       messages.is_from_me, chats.jid, messages.id, messages.media_type
                FROM messages
                JOIN chats ON messages.chat_jid = chats.jid
                WHERE messages.chat_jid = ? AND messages.timestamp > ?
                ORDER BY messages.timestamp ASC
                LIMIT ?
            """,
                (msg_data[7], msg_data[0], after),
            )

            after_messages = []
            for msg in cursor.fetchall():
                after_messages.append(
                    Message(
                        timestamp=datetime.fromisoformat(msg[0]),
                        sender=msg[1],
                        chat_name=msg[2],
                        content=msg[3],
                        is_from_me=msg[4],
                        chat_jid=msg[5],
                        id=msg[6],
                        media_type=msg[7],
                    )
                )

            return MessageContext(
                message=target_message,
                before=before_messages,
                after=after_messages,
            )
    except sqlite3.Error as e:
        logger.warning("Database error: %s", e)
        raise


def list_chats(
    query: str | None = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active",
) -> list[Chat]:
    """Get chats matching the specified criteria."""
    if WA_BRIDGE_SOURCE == "ssh":
        # Derive "chats" from msgs aggregation. Each (phone, is_group) → one chat.
        where = []
        params: list = []
        if query:
            where.append("(LOWER(name) LIKE LOWER(?) OR phone LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
        sql = (
            "SELECT phone, MAX(name) AS name, MAX(ts) AS last_ts,"
            " (SELECT text FROM msgs m2 WHERE m2.phone = msgs.phone"
            " ORDER BY ts DESC LIMIT 1) AS last_text,"
            " (SELECT dir FROM msgs m2 WHERE m2.phone = msgs.phone"
            " ORDER BY ts DESC LIMIT 1) AS last_dir,"
            # ponytail: no is_group column on live table — literal 0 + group by phone only.
            " 0 AS is_group"
            " FROM msgs"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY phone"
        order_by = "last_ts DESC" if sort_by == "last_active" else "name"
        sql += f" ORDER BY {order_by} LIMIT ? OFFSET ?"
        params.extend([limit, page * limit])
        try:
            rows = _ssh_query(sql, params)
        except (RuntimeError, ValueError) as e:
            logger.warning("ssh list_chats failed: %s", e)
            return []
        out: list[Chat] = []
        for r in rows:
            phone, name, last_ts, last_text, last_dir, is_group = r
            jid = _vps_jid(phone, is_group)
            last_dt = datetime.utcfromtimestamp(int(last_ts)) if last_ts else None
            out.append(
                Chat(
                    jid=jid,
                    name=name or None,
                    last_message_time=last_dt,
                    last_message=last_text or None,
                    last_sender=phone,
                    last_is_from_me=(last_dir == "out") if last_dir else None,
                )
            )
        return out

    try:
        with sqlite3.connect(MESSAGES_DB_PATH) as conn:
            cursor = conn.cursor()

            # Build base query
            query_parts = [
                """
                SELECT
                    chats.jid,
                    chats.name,
                    chats.last_message_time,
                    messages.content as last_message,
                    messages.sender as last_sender,
                    messages.is_from_me as last_is_from_me
                FROM chats
            """
            ]

            if include_last_message:
                query_parts.append(
                    """
                    LEFT JOIN messages ON chats.jid = messages.chat_jid
                    AND chats.last_message_time = messages.timestamp
                """
                )

            where_clauses: list[str] = []
            params = []

            if query:
                where_clauses.append(
                    "(LOWER(chats.name) LIKE LOWER(?) OR chats.jid LIKE ?)"
                )
                params.extend([f"%{query}%", f"%{query}%"])

            if where_clauses:
                query_parts.append("WHERE " + " AND ".join(where_clauses))

            # Add sorting
            order_by = (
                "chats.last_message_time DESC"
                if sort_by == "last_active"
                else "chats.name"
            )
            query_parts.append(f"ORDER BY {order_by}")

            # Add pagination
            offset = (page) * limit
            query_parts.append("LIMIT ? OFFSET ?")
            params.extend([limit, offset])

            cursor.execute(" ".join(query_parts), tuple(params))
            chats = cursor.fetchall()

            result: list[Chat] = []
            for chat_data in chats:
                chat = Chat(
                    jid=chat_data[0],
                    name=chat_data[1],
                    last_message_time=datetime.fromisoformat(chat_data[2])
                    if chat_data[2]
                    else None,
                    last_message=chat_data[3],
                    last_sender=chat_data[4],
                    last_is_from_me=chat_data[5],
                )
                result.append(chat)
            return result
    except sqlite3.Error as e:
        logger.warning("Database error: %s", e)
        return []


def search_contacts(query: str) -> list[Contact]:
    """Search contacts by name or phone number."""
    if WA_BRIDGE_SOURCE == "ssh":
        search_pattern = "%" + query + "%"
        try:
            rows = _ssh_query(
                # ponytail: dropped `AND is_group = 0` — column doesn't exist on live table; all rows are 1:1 anyway.
                "SELECT DISTINCT phone, MAX(name) AS name FROM msgs"
                " WHERE (LOWER(name) LIKE LOWER(?) OR phone LIKE ?)"
                " GROUP BY phone ORDER BY name, phone LIMIT 50",
                [search_pattern, search_pattern],
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("ssh search_contacts failed: %s", e)
            return []
        return [
            Contact(phone_number=r[0], name=r[1] or None, jid=_vps_jid(r[0], 0))
            for r in rows
        ]

    try:
        with sqlite3.connect(MESSAGES_DB_PATH) as conn:
            cursor = conn.cursor()

            # Split query into characters to support partial matching
            search_pattern = "%" + query + "%"

            cursor.execute(
                """
                SELECT DISTINCT
                    jid,
                    name
                FROM chats
                WHERE
                    (LOWER(name) LIKE LOWER(?) OR LOWER(jid) LIKE LOWER(?))
                    AND jid NOT LIKE '%@g.us'
                ORDER BY name, jid
                LIMIT 50
            """,
                (search_pattern, search_pattern),
            )

            contacts = cursor.fetchall()

            result: list[Contact] = []
            for contact_data in contacts:
                contact = Contact(
                    phone_number=contact_data[0].split("@")[0],
                    name=contact_data[1],
                    jid=contact_data[0],
                )
                result.append(contact)
            return result
    except sqlite3.Error as e:
        logger.warning("Database error: %s", e)
        return []


def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> list[Chat]:
    """Get all chats involving the contact.

    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    if WA_BRIDGE_SOURCE == "ssh":
        phone_part = jid.split("@")[0] if "@" in jid else jid
        try:
            rows = _ssh_query(
                "SELECT phone, MAX(name) AS name, MAX(ts) AS last_ts,"
                " (SELECT text FROM msgs m2 WHERE m2.phone = msgs.phone"
                " ORDER BY ts DESC LIMIT 1) AS last_text,"
                " (SELECT dir FROM msgs m2 WHERE m2.phone = msgs.phone"
                " ORDER BY ts DESC LIMIT 1) AS last_dir,"
                # ponytail: no is_group column on live table — literal 0 + group by phone only.
                " 0 AS is_group"
                " FROM msgs WHERE phone = ?"
                " GROUP BY phone"
                " ORDER BY last_ts DESC LIMIT ? OFFSET ?",
                [phone_part, limit, page * limit],
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("ssh get_contact_chats failed: %s", e)
            return []
        out: list[Chat] = []
        for r in rows:
            phone, name, last_ts, last_text, last_dir, is_group = r
            jid2 = _vps_jid(phone, is_group)
            last_dt = datetime.utcfromtimestamp(int(last_ts)) if last_ts else None
            out.append(
                Chat(
                    jid=jid2,
                    name=name or None,
                    last_message_time=last_dt,
                    last_message=last_text or None,
                    last_sender=phone,
                    last_is_from_me=(last_dir == "out") if last_dir else None,
                )
            )
        return out

    try:
        with sqlite3.connect(MESSAGES_DB_PATH) as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
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
            """,
                (jid, jid, limit, page * limit),
            )

            chats = cursor.fetchall()

            result: list[Chat] = []
            for chat_data in chats:
                chat = Chat(
                    jid=chat_data[0],
                    name=chat_data[1],
                    last_message_time=datetime.fromisoformat(chat_data[2])
                    if chat_data[2]
                    else None,
                    last_message=chat_data[3],
                    last_sender=chat_data[4],
                    last_is_from_me=chat_data[5],
                )
                result.append(chat)
            return result
    except sqlite3.Error as e:
        logger.warning("Database error: %s", e)
        return []


def get_last_interaction(jid: str) -> str | None:
    """Get most recent message involving the contact."""
    if WA_BRIDGE_SOURCE == "ssh":
        phone_part = jid.split("@")[0] if "@" in jid else jid
        try:
            rows = _ssh_query(
                # ponytail: no is_group column on live table — literal 0 keeps unpack shape.
                "SELECT ts, dir, phone, name, text, msg_id, 0 AS is_group FROM msgs"
                " WHERE phone = ? ORDER BY ts DESC LIMIT 1",
                [phone_part],
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("ssh get_last_interaction failed: %s", e)
            return None
        if not rows:
            return None
        ts, direction, phone, name, text, msg_id, is_group = rows[0]
        message = Message(
            timestamp=datetime.utcfromtimestamp(int(ts)),
            sender=phone,
            chat_name=name or None,
            content=text or "",
            is_from_me=(direction == "out"),
            chat_jid=_vps_jid(phone, is_group),
            id=msg_id or "",
            media_type=None,
        )
        return format_message(message)

    try:
        with sqlite3.connect(MESSAGES_DB_PATH) as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
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
                WHERE m.sender = ? OR c.jid = ?
                ORDER BY m.timestamp DESC
                LIMIT 1
            """,
                (jid, jid),
            )

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
                media_type=msg_data[7],
            )
            return format_message(message)
    except sqlite3.Error as e:
        logger.warning("Database error: %s", e)
        return None


def get_chat(chat_jid: str, include_last_message: bool = True) -> Chat | None:
    """Get chat metadata by JID."""
    if WA_BRIDGE_SOURCE == "ssh":
        phone_part = chat_jid.split("@")[0] if "@" in chat_jid else chat_jid
        try:
            rows = _ssh_query(
                "SELECT phone, MAX(name) AS name, MAX(ts) AS last_ts,"
                " (SELECT text FROM msgs m2 WHERE m2.phone = msgs.phone"
                " ORDER BY ts DESC LIMIT 1) AS last_text,"
                " (SELECT dir FROM msgs m2 WHERE m2.phone = msgs.phone"
                " ORDER BY ts DESC LIMIT 1) AS last_dir,"
                # ponytail: no is_group column on live table — literal 0 + group by phone only.
                " 0 AS is_group"
                " FROM msgs WHERE phone = ? GROUP BY phone LIMIT 1",
                [phone_part],
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("ssh get_chat failed: %s", e)
            return None
        if not rows:
            return None
        phone, name, last_ts, last_text, last_dir, is_group = rows[0]
        last_dt = datetime.utcfromtimestamp(int(last_ts)) if last_ts else None
        return Chat(
            jid=_vps_jid(phone, is_group),
            name=name or None,
            last_message_time=last_dt,
            last_message=last_text or None,
            last_sender=phone,
            last_is_from_me=(last_dir == "out") if last_dir else None,
        )

    try:
        with sqlite3.connect(MESSAGES_DB_PATH) as conn:
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
                last_message_time=datetime.fromisoformat(chat_data[2])
                if chat_data[2]
                else None,
                last_message=chat_data[3],
                last_sender=chat_data[4],
                last_is_from_me=chat_data[5],
            )
    except sqlite3.Error as e:
        logger.warning("Database error: %s", e)
        return None


def get_direct_chat_by_contact(sender_phone_number: str) -> Chat | None:
    """Get chat metadata by sender phone number."""
    if WA_BRIDGE_SOURCE == "ssh":
        phone_part = (
            sender_phone_number.split("@")[0]
            if "@" in sender_phone_number
            else sender_phone_number
        )
        try:
            rows = _ssh_query(
                # ponytail: dropped `AND is_group = 0` — column doesn't exist on live table; all rows are 1:1 anyway.
                "SELECT phone, MAX(name) AS name, MAX(ts) AS last_ts,"
                " (SELECT text FROM msgs m2 WHERE m2.phone = msgs.phone"
                " ORDER BY ts DESC LIMIT 1) AS last_text,"
                " (SELECT dir FROM msgs m2 WHERE m2.phone = msgs.phone"
                " ORDER BY ts DESC LIMIT 1) AS last_dir"
                " FROM msgs WHERE phone LIKE ?"
                " GROUP BY phone LIMIT 1",
                [f"%{phone_part}%"],
            )
        except (RuntimeError, ValueError) as e:
            logger.warning("ssh get_direct_chat_by_contact failed: %s", e)
            return None
        if not rows:
            return None
        phone, name, last_ts, last_text, last_dir = rows[0]
        last_dt = datetime.utcfromtimestamp(int(last_ts)) if last_ts else None
        return Chat(
            jid=_vps_jid(phone, 0),
            name=name or None,
            last_message_time=last_dt,
            last_message=last_text or None,
            last_sender=phone,
            last_is_from_me=(last_dir == "out") if last_dir else None,
        )

    try:
        with sqlite3.connect(MESSAGES_DB_PATH) as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
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
            """,
                (f"%{sender_phone_number}%",),
            )

            chat_data = cursor.fetchone()

            if not chat_data:
                return None

            return Chat(
                jid=chat_data[0],
                name=chat_data[1],
                last_message_time=datetime.fromisoformat(chat_data[2])
                if chat_data[2]
                else None,
                last_message=chat_data[3],
                last_sender=chat_data[4],
                last_is_from_me=chat_data[5],
            )
    except sqlite3.Error as e:
        logger.warning("Database error: %s", e)
        return None


@lru_cache(maxsize=1)
def _sending_line() -> str:
    """Which WhatsApp line a send actually goes out on.

    ponytail: nothing in the config reaches the code — BRIDGE_URL is read by
    nobody, so an MCP server configured for one account can silently send from
    another. The code can't know which server it is, but it can always say
    which line it just used, which makes the mix-up impossible to miss.
    Cached: the bridge can't switch accounts without a restart.
    """
    if WA_BRIDGE_SOURCE == "ssh":
        return f"ssh bridge {SSH_HOST}"
    try:
        with sqlite3.connect(f"file:{SESSION_DB_PATH}?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT jid FROM whatsmeow_device LIMIT 1").fetchone()
    except sqlite3.Error:
        return "unknown line"
    return row[0].split(":")[0].split("@")[0] if row else "no line paired"


def _resolve_recipient(recipient: str) -> tuple[str, str | None]:
    """Translate a @lid recipient to its real phone. Returns (recipient, error).

    ponytail: @lid is an internal WhatsApp id, not a phone number. The bridge
    hands it to whatsmeow as-is, the server acks a stanza encrypted for zero
    devices, and the outgoing path never writes a db row — so a non-delivery
    looks exactly like a success. whatsmeow already stores the lid→phone
    mapping it learns from the server, so translate instead of refusing, and
    fail loud only when the mapping is genuinely absent.
    """
    if "@lid" not in recipient.lower():
        return recipient, None
    lid = recipient.split("@")[0]
    try:
        with sqlite3.connect(f"file:{SESSION_DB_PATH}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT pn FROM whatsmeow_lid_map WHERE lid = ?", (lid,)
            ).fetchone()
    except sqlite3.Error as e:
        return "", f"Cannot resolve LID {recipient!r} (session db unreadable): {e}"
    if not row:
        return "", (
            f"Recipient {recipient!r} is a LID (hidden WhatsApp id) with no known "
            "phone number in the local mapping — refusing to send, since a LID "
            "send is acked by the server but delivered to nobody. Ask the contact "
            "for their phone number, or message them once from the phone first."
        )
    return f"{row[0]}@s.whatsapp.net", None


def _ssh_send_text(recipient: str, message: str) -> tuple[bool, str]:
    """Send a text message via the VPS bridge over SSH.

    Mirrors what /opt/wa-bridge itself does: POST to the local wuzapi endpoint
    with the WUZAPI_TOKEN read from the VPS .env. The token is grepped remotely
    and never leaves the VPS / never touches the Mac or the logs. Phone is
    digits-only (no +) to match how bridge.db stores it.
    """
    recipient, resolve_error = _resolve_recipient(recipient)
    if resolve_error:
        return False, resolve_error
    # ponytail: digits-only to match bridge.db phone format. Ceiling: assumes E.164-ish input; no country-code inference.
    phone = "".join(ch for ch in recipient.split("@")[0] if ch.isdigit())
    if not phone:
        return False, f"Invalid recipient (no digits): {recipient!r}"
    body = json.dumps({"Phone": phone, "Body": message})
    remote_cmd = (
        'curl -s -o /dev/null -w "%{http_code}" '
        '-H "token: $(grep -E ^WUZAPI_TOKEN= /opt/wa-bridge/.env | cut -d= -f2-)" '
        '-H "Content-Type: application/json" '
        "-d @- http://127.0.0.1:8080/chat/send/text"
    )
    result = subprocess.run(  # noqa: S603
        ["ssh", SSH_HOST, remote_cmd],  # noqa: S607
        input=body,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return False, f"ssh send failed: {result.stderr.strip()}"
    status = result.stdout.strip()
    if status.startswith("2"):
        return True, f"Sent (HTTP {status}) [line: {_sending_line()}]"
    return False, f"Send failed: HTTP {status}"


def send_message(recipient: str, message: str) -> tuple[bool, str]:
    response = None
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        recipient, resolve_error = _resolve_recipient(recipient)
        if resolve_error:
            return False, resolve_error

        # ponytail: SSH mode sends via VPS bridge (localhost:8080/api is dead on the Mac). Ceiling: text only; media still uses the old HTTP path.
        if WA_BRIDGE_SOURCE == "ssh":
            return _ssh_send_text(recipient, message)

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "message": message,
        }

        response = requests.post(url, json=payload, timeout=30)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), (
                f"{result.get('message', 'Unknown response')} "
                f"[line: {_sending_line()}]"
            )
        return False, f"Error: HTTP {response.status_code} - {response.text}"
    except requests.RequestException as e:
        return False, f"Request error: {e}"
    except json.JSONDecodeError:
        body = response.text if response is not None else "<no response>"
        return False, f"Error parsing response: {body}"
    except Exception as e:  # noqa: BLE001
        return False, f"Unexpected error: {e}"


def send_file(recipient: str, media_path: str) -> tuple[bool, str]:
    response = None
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        recipient, resolve_error = _resolve_recipient(recipient)
        if resolve_error:
            return False, resolve_error

        if not media_path:
            return False, "Media path must be provided"

        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {"recipient": recipient, "media_path": media_path}

        response = requests.post(url, json=payload, timeout=60)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), (
                f"{result.get('message', 'Unknown response')} "
                f"[line: {_sending_line()}]"
            )
        return False, f"Error: HTTP {response.status_code} - {response.text}"
    except requests.RequestException as e:
        return False, f"Request error: {e}"
    except json.JSONDecodeError:
        body = response.text if response is not None else "<no response>"
        return False, f"Error parsing response: {body}"
    except Exception as e:  # noqa: BLE001
        return False, f"Unexpected error: {e}"


def send_audio_message(recipient: str, media_path: str) -> tuple[bool, str]:
    response = None
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"

        recipient, resolve_error = _resolve_recipient(recipient)
        if resolve_error:
            return False, resolve_error

        if not media_path:
            return False, "Media path must be provided"

        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"

        if not media_path.endswith(".ogg"):
            try:
                media_path = audio.convert_to_opus_ogg_temp(media_path)
            except Exception as e:  # noqa: BLE001
                return (
                    False,
                    "Error converting file to opus ogg."
                    f" You likely need to install ffmpeg: {e}",
                )

        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {"recipient": recipient, "media_path": media_path}

        response = requests.post(url, json=payload, timeout=60)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), (
                f"{result.get('message', 'Unknown response')} "
                f"[line: {_sending_line()}]"
            )
        return False, f"Error: HTTP {response.status_code} - {response.text}"
    except requests.RequestException as e:
        return False, f"Request error: {e}"
    except json.JSONDecodeError:
        body = response.text if response is not None else "<no response>"
        return False, f"Error parsing response: {body}"
    except Exception as e:  # noqa: BLE001
        return False, f"Unexpected error: {e}"


def download_media(message_id: str, chat_jid: str) -> str | None:
    """Download media from a message and return the local file path.

    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message

    Returns:
        The local file path if download was successful, None otherwise
    """
    response = None
    try:
        url = f"{WHATSAPP_API_BASE_URL}/download"
        payload = {"message_id": message_id, "chat_jid": chat_jid}

        response = requests.post(url, json=payload, timeout=60)

        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                path = result.get("path")
                logger.info("Media downloaded successfully: %s", path)
                return path
            logger.warning(
                "Download failed: %s", result.get("message", "Unknown error")
            )
            return None
        logger.warning(
            "Error: HTTP %s - %s", response.status_code, response.text
        )
        return None
    except requests.RequestException as e:
        logger.warning("Request error: %s", e)
        return None
    except json.JSONDecodeError:
        body = response.text if response is not None else "<no response>"
        logger.warning("Error parsing response: %s", body)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("Unexpected error: %s", e)
        return None
