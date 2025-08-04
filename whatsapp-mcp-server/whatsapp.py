import sqlite3
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple
import os.path
import requests
import json
import audio
import subprocess
import time
import threading
import queue
import psutil
import signal

MESSAGES_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'messages.db')
WHATSAPP_API_BASE_URL = "http://localhost:8080/api"
BRIDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge')
BRIDGE_EXECUTABLE = "main.go"
BRIDGE_PROCESS = None
BRIDGE_OUTPUT_QUEUE = queue.Queue()
QR_CODE_DATA = None

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

@dataclass
class BridgeStatus:
    is_running: bool
    is_authenticated: bool
    api_responsive: bool
    qr_code: Optional[str] = None
    error_message: Optional[str] = None

def get_sender_name(sender_jid: str) -> str:
    try:
        conn = sqlite3.connect(MESSAGES_DB_PATH)
        cursor = conn.cursor()
        
        # First try matching by exact JID
        cursor.execute("""
            SELECT name
            FROM chats
            WHERE jid = ?
            LIMIT 1
        """, (sender_jid,))
        
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

# Bridge Management Functions

def is_bridge_process_running() -> bool:
    """Check if the bridge Go process is currently running."""
    global BRIDGE_PROCESS
    
    if BRIDGE_PROCESS and BRIDGE_PROCESS.poll() is None:
        return True
    
    # Check if any go process is running main.go in the bridge directory
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'] in ['go', 'main']:
                cmdline = proc.info['cmdline']
                if cmdline and any('main.go' in arg for arg in cmdline):
                    if any(BRIDGE_DIR in arg for arg in cmdline):
                        return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    return False

def check_api_health() -> bool:
    """Check if the bridge API is responsive."""
    try:
        response = requests.get(f"{WHATSAPP_API_BASE_URL.replace('/api', '')}/", timeout=5)
        return response.status_code in [200, 404]  # 404 is OK, means server is running
    except requests.RequestException:
        return False

def check_authentication_status() -> Tuple[bool, Optional[str]]:
    """Check if WhatsApp is authenticated by looking for session data."""
    whatsapp_db_path = os.path.join(BRIDGE_DIR, 'store', 'whatsapp.db')
    
    if not os.path.exists(whatsapp_db_path):
        return False, "No session database found"
    
    try:
        conn = sqlite3.connect(whatsapp_db_path)
        cursor = conn.cursor()
        
        # Check if device table exists and has data
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='whatsmeow_device';")
        if not cursor.fetchone():
            return False, "No device table found"
        
        cursor.execute("SELECT COUNT(*) FROM whatsmeow_device;")
        device_count = cursor.fetchone()[0]
        
        if device_count == 0:
            return False, "No device registered"
        
        return True, None
        
    except sqlite3.Error as e:
        return False, f"Database error: {e}"
    finally:
        if 'conn' in locals():
            conn.close()

def monitor_bridge_output(process):
    """Monitor bridge process output for QR codes and status updates."""
    global QR_CODE_DATA, BRIDGE_OUTPUT_QUEUE
    
    qr_lines = []
    capturing_qr = False
    
    for line in iter(process.stdout.readline, ''):
        line_str = line.strip()
        BRIDGE_OUTPUT_QUEUE.put(line_str)
        
        # Detect QR code start
        if "Scan this QR code with your WhatsApp app:" in line_str:
            capturing_qr = True
            qr_lines = []
            continue
        
        # Capture QR code lines (they contain █ and ▄ characters)
        if capturing_qr:
            if "Successfully connected and authenticated!" in line_str:
                capturing_qr = False
                if qr_lines:
                    QR_CODE_DATA = "\n".join(qr_lines)
            elif any(char in line_str for char in ['█', '▄', '▀', '▐', '▌']):
                qr_lines.append(line_str)

def start_bridge_process() -> Tuple[bool, str]:
    """Start the WhatsApp bridge Go process."""
    global BRIDGE_PROCESS
    
    if is_bridge_process_running():
        return True, "Bridge is already running"
    
    try:
        # Change to bridge directory and start the Go application
        bridge_path = os.path.abspath(BRIDGE_DIR)
        
        if not os.path.exists(bridge_path):
            return False, f"Bridge directory not found: {bridge_path}"
        
        go_file = os.path.join(bridge_path, BRIDGE_EXECUTABLE)
        if not os.path.exists(go_file):
            return False, f"Bridge executable not found: {go_file}"
        
        # Find Go executable
        go_cmd = None
        for go_path in ['/usr/local/go/bin/go', '/opt/homebrew/bin/go', 'go']:
            try:
                result = subprocess.run([go_path, 'version'], capture_output=True, timeout=5)
                if result.returncode == 0:
                    go_cmd = go_path
                    break
            except (subprocess.SubprocessError, FileNotFoundError):
                continue
        
        if not go_cmd:
            return False, "Go executable not found. Please ensure Go is installed and accessible."
        
        # Prepare environment with Go paths
        env = os.environ.copy()
        env['PATH'] = '/usr/local/go/bin:/opt/homebrew/bin:' + env.get('PATH', '')
        env['GOPATH'] = env.get('GOPATH', os.path.expanduser('~/go'))
        env['GOROOT'] = env.get('GOROOT', '/usr/local/go')
        
        # Start the process
        BRIDGE_PROCESS = subprocess.Popen(
            [go_cmd, 'run', 'main.go'],
            cwd=bridge_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        
        # Start output monitoring in a separate thread
        output_thread = threading.Thread(target=monitor_bridge_output, args=(BRIDGE_PROCESS,))
        output_thread.daemon = True
        output_thread.start()
        
        # Wait a moment for the process to start
        time.sleep(2)
        
        if BRIDGE_PROCESS.poll() is not None:
            return False, f"Bridge process failed to start. Exit code: {BRIDGE_PROCESS.returncode}"
        
        return True, "Bridge process started successfully"
        
    except Exception as e:
        return False, f"Failed to start bridge process: {str(e)}"

def stop_bridge_process() -> bool:
    """Stop the WhatsApp bridge process."""
    global BRIDGE_PROCESS
    
    if BRIDGE_PROCESS:
        try:
            BRIDGE_PROCESS.terminate()
            BRIDGE_PROCESS.wait(timeout=10)
        except subprocess.TimeoutExpired:
            BRIDGE_PROCESS.kill()
        except Exception:
            pass
        finally:
            BRIDGE_PROCESS = None
    
    return True

def wait_for_authentication(timeout: int = 120) -> Tuple[bool, Optional[str]]:
    """Wait for WhatsApp authentication to complete."""
    global QR_CODE_DATA, BRIDGE_OUTPUT_QUEUE
    
    start_time = time.time()
    qr_returned = False
    collected_output = []
    
    while time.time() - start_time < timeout:
        # Check authentication status first
        is_auth, _ = check_authentication_status()
        if is_auth:
            return True, None
        
        # Check for new output from bridge
        try:
            while True:
                line = BRIDGE_OUTPUT_QUEUE.get_nowait()
                collected_output.append(line)
                print(f"Bridge output: {line}")  # Debug output
        except queue.Empty:
            pass
        
        # Check if we have a QR code to display (only return it once)
        if QR_CODE_DATA and not qr_returned:
            qr_returned = True
            return False, QR_CODE_DATA
        
        # Look for QR code patterns in collected output
        output_text = '\n'.join(collected_output)
        if "Scan this QR code with your WhatsApp app:" in output_text and not qr_returned:
            # Extract QR code lines manually
            qr_lines = []
            in_qr = False
            for line in collected_output:
                if "Scan this QR code with your WhatsApp app:" in line:
                    in_qr = True
                    continue
                if in_qr:
                    if any(char in line for char in ['█', '▄', '▀', '▐', '▌']):
                        qr_lines.append(line)
                    elif "Successfully connected" in line or "Connected to WhatsApp" in line:
                        break
            
            if qr_lines:
                qr_code = '\n'.join(qr_lines)
                qr_returned = True
                return False, qr_code
        
        # Check if bridge process is still running
        if not is_bridge_process_running():
            return False, "Bridge process stopped unexpectedly"
        
        time.sleep(0.5)  # Check more frequently
    
    # Return collected output for debugging if timeout
    debug_info = f"Authentication timeout. Collected output:\n" + '\n'.join(collected_output[-20:])  # Last 20 lines
    return False, debug_info

def get_bridge_status() -> BridgeStatus:
    """Get comprehensive bridge status."""
    is_running = is_bridge_process_running()
    api_responsive = check_api_health() if is_running else False
    is_authenticated, auth_error = check_authentication_status()
    
    status = BridgeStatus(
        is_running=is_running,
        is_authenticated=is_authenticated,
        api_responsive=api_responsive,
        error_message=auth_error
    )
    
    return status

def get_qr_code_from_running_bridge() -> Optional[str]:
    """Try to get QR code from a running bridge by restarting it and capturing output."""
    global BRIDGE_PROCESS
    
    # Stop current bridge
    stop_bridge_process()
    time.sleep(1)
    
    try:
        # Start bridge and capture initial output
        bridge_path = os.path.abspath(BRIDGE_DIR)
        
        # Find Go executable
        go_cmd = None
        for go_path in ['/usr/local/go/bin/go', '/opt/homebrew/bin/go', 'go']:
            try:
                result = subprocess.run([go_path, 'version'], capture_output=True, timeout=5)
                if result.returncode == 0:
                    go_cmd = go_path
                    break
            except (subprocess.SubprocessError, FileNotFoundError):
                continue
        
        if not go_cmd:
            return None
        
        # Prepare environment
        env = os.environ.copy()
        env['PATH'] = '/usr/local/go/bin:/opt/homebrew/bin:' + env.get('PATH', '')
        env['GOPATH'] = env.get('GOPATH', os.path.expanduser('~/go'))
        env['GOROOT'] = env.get('GOROOT', '/usr/local/go')
        
        # Start process and capture output for a few seconds
        process = subprocess.Popen(
            [go_cmd, 'run', 'main.go'],
            cwd=bridge_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )
        
        output_lines = []
        start_time = time.time()
        
        # Capture output for up to 8 seconds
        while time.time() - start_time < 8:
            try:
                line = process.stdout.readline()
                if line:
                    output_lines.append(line.strip())
                    # Check if we found authentication success
                    if "Successfully connected and authenticated" in line:
                        break
                else:
                    time.sleep(0.1)
            except:
                break
        
        # Set the global process reference
        BRIDGE_PROCESS = process
        
        # Extract QR code from output
        qr_lines = []
        in_qr = False
        
        for line in output_lines:
            if "Scan this QR code with your WhatsApp app:" in line:
                in_qr = True
                continue
            if in_qr:
                if any(char in line for char in ['█', '▄', '▀', '▐', '▌']):
                    qr_lines.append(line)
                elif "Successfully connected" in line or "Connected to WhatsApp" in line:
                    break
                elif line.strip() == "":  # End of QR code
                    break
        
        if qr_lines:
            return '\n'.join(qr_lines)
        
        return None
        
    except Exception as e:
        print(f"Error getting QR code: {e}")
        return None

def ensure_bridge_ready() -> Tuple[bool, str, Optional[str]]:
    """Ensure bridge is running and authenticated. Returns (success, message, qr_url)."""
    
    status = get_bridge_status()
    
    # If everything is ready, return success
    if status.is_running and status.api_responsive and status.is_authenticated:
        return True, "Bridge is ready", None
    
    # If bridge is not running, start it
    if not status.is_running:
        success, message = start_bridge_process()
        if not success:
            return False, f"Failed to start bridge: {message}", None
        
        # Wait for API to become responsive
        for _ in range(30):  # Wait up to 30 seconds
            if check_api_health():
                break
            time.sleep(1)
        else:
            return False, "Bridge started but API is not responsive", None
    
    # Check authentication status again after ensuring bridge is running
    status = get_bridge_status()
    if status.is_authenticated:
        return True, "Bridge is ready and authenticated", None
    
    # Not authenticated - bridge should be serving QR code via web interface
    qr_url = "http://localhost:8080/qr"
    return False, "Bridge is running but not authenticated. Please scan the QR code via the web interface.", qr_url

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
        
        result = []
        for contact_data in contacts:
            contact = Contact(
                phone_number=contact_data[0].split('@')[0],
                name=contact_data[1],
                jid=contact_data[0]
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


def get_last_interaction(jid: str) -> str:
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
                m.id,
                m.media_type
            FROM messages m
            JOIN chats c ON m.chat_jid = c.jid
            WHERE m.sender = ? OR c.jid = ?
            ORDER BY m.timestamp DESC
            LIMIT 1
        """, (jid, jid))
        
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
