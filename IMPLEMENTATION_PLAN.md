# Multi-Tenant WhatsApp MCP Server - Implementation Plan

## Overview

This document describes the implementation of a multi-tenant WhatsApp MCP server that allows multiple users to connect their personal WhatsApp accounts via QR code, and exposes MCP tools for AI agents (Claude, Cursor, etc.) to interact with WhatsApp.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Docker Compose                                │
│                                                                   │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│  │  Django     │     │   Bridge    │     │    MCP      │       │
│  │  :18080     │◄────│   :18081    │     │   :18082    │       │
│  │             │     │             │     │             │       │
│  │  Admin UI   │     │  Per-user   │     │  Streamable │       │
│  │  REST API   │     │  GoRoutines │     │  HTTP MCP   │       │
│  │  QR Display │     │             │     │             │       │
│  └─────────────┘     └──────┬──────┘     └──────┬──────┘       │
│         │                   │                   │              │
│         └───────────────────┼───────────────────┘              │
│                             ▼                                   │
│                   ┌───────────────────┐                         │
│                   │  shared_storage/  │                         │
│                   │                   │                         │
│                   │  user_{id}/       │                         │
│                   │    ├─ messages.db│                         │
│                   │    └─ whatsapp.db│                         │
│                   └───────────────────┘                         │
└──────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Port | Purpose |
|-----------|------|---------|
| Django | 18080 | User management, Admin UI, QR code display, REST API |
| Bridge | 18081 | WhatsApp connection management, message storage, user polling |
| MCP | 18082 | MCP protocol over HTTP, JWT authentication, tool execution |

### Data Flow

1. **Admin creates user** → Django stores user with `pending_init_request` status
2. **Bridge polls Django** → Detects new user, creates storage, generates QR
3. **Bridge pushes QR to Django** → User status changes to `pending_handshake`
4. **User scans QR** → WhatsApp handshake completes, status changes to `connected`
5. **AI agent connects via MCP** → Validates JWT, accesses user's WhatsApp data

---

## 1. Shared Configuration

**File: `.env`**

```env
# JWT - shared across all services
JWT_SECRET=your-256-bit-secret-key-here-change-in-production

# Service Keys - for internal service-to-service auth
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SERVICE_KEY=sha256-hash-of-bridge-service-key

# Django
DJANGO_SECRET_KEY=your-django-secret-key-change-in-production
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,django,bridge,mcp

# Bridge
BRIDGE_POLL_INTERVAL=60
DJANGO_API_URL=http://django:8000
MAX_CONCURRENT_USERS=5

# MCP
DJANGO_API_URL=http://django:8000
```

**Service Key Flow**:
1. `SERVICE_KEY` is shared secret stored in all services' environment
2. Bridge and MCP include `X-Service-Key: <SERVICE_KEY>` in requests to Django
3. Django validates using `secrets.compare_digest()` (timing-safe comparison)

---

## 2. Django Server (`django-server/`)

### 2.1 Project Structure

```
django-server/
├── Dockerfile
├── manage.py
├── requirements.txt
├── whatsapp_mgr/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── users/
    ├── __init__.py
    ├── models.py
    ├── admin.py
    ├── views.py
    ├── serializers.py
    ├── urls.py
    └── tests.py
```

### 2.2 Models (`users/models.py`)

```python
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    """Extended user model for WhatsApp multi-tenant setup."""

    STATUS_CHOICES = [
        ('pending_init_request', 'Pending Init Request'),
        ('pending_handshake', 'Pending Handshake'),
        ('connected', 'Connected'),
        ('sync_error', 'Sync Error'),
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending_init_request'
    )
    whatsapp_jid = models.CharField(max_length=100, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class QRCode(models.Model):
    """QR code storage for WhatsApp authentication."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='qrcodes'
    )
    image_data = models.TextField(help_text="Base64 encoded PNG")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    verified = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'QR Codes'

    def __str__(self):
        return f"QR for {self.user.username} - {'verified' if self.verified else 'pending'}"
```

### 2.3 REST API Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/users/` | List all users | Service Key |
| `POST` | `/api/users/` | Create new user | Admin |
| `GET` | `/api/users/{id}/` | Get user details | Service Key |
| `PATCH` | `/api/users/{id}/` | Update user (status, whatsapp_jid) | Service Key |
| `DELETE` | `/api/users/{id}/` | Delete user | Admin |
| `GET` | `/api/users/{id}/qr/` | Get latest QR code | Service Key |
| `PATCH` | `/api/users/{id}/qr/` | Update QR code (Bridge → Django) | Service Key |
| `POST` | `/api/auth/token/` | Get JWT tokens | Public |
| `POST` | `/api/auth/token/refresh/` | Refresh JWT token | Public |

**Service Key Authentication**: All internal service-to-service calls require `X-Service-Key` header.

### 2.4 Admin Interface

Django Admin with:
- **User List**: Columns for Username, Status (sync_status), Created date
- **Filters**: Status filter (all states), date range
- **User Change Form**: Editable status field (admin can manually force state changes)
- **Admin Actions**:
  - `Show WhatsApp QR`: Display QR code in modal/popup for admin to scan
  - `Generate API Key`: Generate JWT and display in popup for admin to copy

**Note**: All status changes can be done directly via the edit form. No separate reset/force actions needed.

### 2.5 QR Display (Admin Action)

**Admin Action**: `Show WhatsApp QR` on User change form

1. Admin selects user → clicks "Show WhatsApp QR" action
2. Modal/popup displays current QR code from QRCode record
3. Shows connection status: pending_handshake, connected, etc.
4. Admin scans the QR with their phone WhatsApp app
5. On stale QR, admin presses F5 or reopens modal to get updated QR

**No polling** - QR refresh is manual (F5 or close/reopen modal). Bridge updates QR in Django on each new QR generation cycle.

**Note**: User status is displayed as a column in the user list and in the change form. Admin can manually edit the status field to force state changes.

---

## 3. WhatsApp Bridge (`whatsapp-bridge/`)

### 3.1 Project Structure

```
whatsapp-bridge/
├── Dockerfile
├── go.mod
├── go.sum
├── main.go
├── go/
│   ├── bridge.go        # Main bridge logic, user polling
│   ├── user_client.go   # Per-user WhatsApp client
│   ├── message_store.go # Message storage operations
│   └── api_client.go   # Django API client
└── store/
    └── .gitkeep
```

### 3.2 Core Components

#### UserClient
```go
type UserClient struct {
    UserID    string
    Username  string
    Client    *whatsmeow.Client
    MessageStore *MessageStore
    Status    string
    StopChan  chan struct{}
}
```

#### Bridge
```go
type Bridge struct {
    djangoURL    string
    jwtSecret    string
    pollInterval time.Duration
    users        map[string]*UserClient
    mu           sync.RWMutex
}
```

### 3.3 User Polling Loop

Runs every `BRIDGE_POLL_INTERVAL` (default 60 seconds):

1. `GET /api/users/` → Fetch all users from Django
2. Check if `MAX_CONCURRENT_USERS` limit reached (default: 5)
3. Diff with local `users` map
4. **New user** (if under limit):
   - Create `store/{user_id}/` directory
   - Initialize SQLite tables
   - Start `HandleUser()` goroutine
5. **New user** (if limit reached):
   - Log warning, skip user creation
   - User remains in Django with current status
6. **Deleted user**:
   - Signal `StopChan` to stop goroutine
   - Clean up WhatsApp client
   - Delete `store/{user_id}/`
7. **Status change**:
   - Update local state
   - If `pending_init_request` → generate QR

**User Limit**: Maximum 5 concurrent WhatsApp connections (configurable via `MAX_CONCURRENT_USERS`).

### 3.4 Per-User GoRoutine

```go
func (b *Bridge) HandleUser(ctx context.Context, user *UserClient) {
    for {
        select {
        case <-user.StopChan:
            return
        default:
            // Check if needs QR generation
            if user.Status == "pending_init_request" {
                qr := generateQR(user)
                pushQRToDjango(user.UserID, qr)
                user.Status = "pending_handshake"
            }

            // Maintain connection, sync messages
            // Report status to Django periodically
        }
    }
}
```

### 3.5 REST API (for MCP server)

All endpoints require `X-Service-Key` header for Bridge → Django auth.
MCP calls must include JWT-validated user_id; Bridge independently validates.

| Method | Endpoint | Request | Response |
|--------|----------|---------|----------|
| `POST` | `/api/send/` | `{user_id, recipient, message, media_path}` | `{success, message}` |
| `POST` | `/api/download/` | `{user_id, message_id, chat_jid}` | `{success, path, media_type}` |
| `GET` | `/api/status/{user_id}/` | - | `{status, jid, connected}` |

**Security**:
- Bridge validates `user_id` matches the JWT's user_id before processing
- `user_id` must match pattern `^[a-zA-Z0-9\-_]{1,64}$` (alphanumeric, dash, underscore, max 64 chars)
- All filesystem paths are validated against path traversal attacks

---

## 4. MCP Server (`whatsapp-mcp-server/`)

### 4.1 Project Structure

```
whatsapp-mcp-server/
├── Dockerfile
├── pyproject.toml
├── requirements.txt
├── server.py          # Main MCP HTTP server
├── auth.py            # JWT validation
├── whatsapp.py        # User-scoped DB queries
└── audio.py           # Audio conversion (unchanged)
```

### 4.2 Authentication

**JWT Bearer token** validation on all `/mcp/` endpoints.

**User validation**: MCP must validate that requested `user_id` in tool calls matches the JWT's subject.

```python
# auth.py
import jwt
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def validate_jwt(token: str) -> Optional[str]:
    """Validate JWT and return user_id."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id") or payload.get("sub")
        logger.info(f"JWT validated for user_id: {user_id}")
        return user_id
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT validation failed: {e}")
        return None

def validate_user_for_request(jwt_user_id: str, requested_user_id: str) -> str:
    """Validate that the request targets the correct user."""
    if jwt_user_id != requested_user_id:
        logger.error(f"User ID mismatch: JWT={jwt_user_id}, Requested={requested_user_id}")
        raise PermissionError("User ID mismatch")
    return jwt_user_id
```

**Service Key** validation for Bridge ↔ MCP internal calls:

```python
def validate_service_key(request) -> bool:
    """Validate X-Service-Key header."""
    key = request.headers.get('X-Service-Key')
    if not key or not secrets.compare_digest(key, settings.SERVICE_KEY):
        logger.warning("Invalid or missing service key")
        return False
    return True
```

### 4.3 MCP Tools

All tools receive `user_id` from JWT context:

| Tool | Description | Data Source |
|------|-------------|--------------|
| `search_contacts` | Search contacts by name/number | `store/{user_id}/messages.db` |
| `list_messages` | Get messages with filters | `store/{user_id}/messages.db` |
| `list_chats` | List all chats | `store/{user_id}/messages.db` |
| `get_chat` | Get chat metadata | `store/{user_id}/messages.db` |
| `get_direct_chat_by_contact` | Find direct chat | `store/{user_id}/messages.db` |
| `get_contact_chats` | Chats with contact | `store/{user_id}/messages.db` |
| `get_last_interaction` | Latest message | `store/{user_id}/messages.db` |
| `get_message_context` | Message with context | `store/{user_id}/messages.db` |
| `send_message` | Send WhatsApp message | Bridge API |
| `send_file` | Send file | Bridge API |
| `send_audio_message` | Send voice message | Bridge API |
| `download_media` | Download media | Bridge API |

### 4.4 HTTP Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/mcp/` | MCP HTTP connection (streamable-http or WebSocket fallback) |
| `POST` | `/mcp/` | MCP message handler |
| `GET` | `/health/` | Health check (no auth) |

**Transport Selection**: Use streamable-http if available in MCP SDK. If not available, fall back to WebSocket transport which is also well-supported.

---

## 5. Docker Compose

```yaml
version: '3.8'

services:
  django:
    build: ./django-server
    ports:
      - "18080:8000"
    volumes:
      - shared_storage:/app/store
    environment:
      - DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
      - JWT_SECRET=${JWT_SECRET}
      - SERVICE_KEY=${SERVICE_KEY}
      - DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,django,bridge,mcp
      - DJANGO_DEBUG=false
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health/"]
      interval: 30s
      timeout: 10s
      retries: 3

  bridge:
    build: ./whatsapp-bridge
    ports:
      - "18081:8080"
    volumes:
      - shared_storage:/app/store
    environment:
      - DJANGO_API_URL=http://django:8000
      - JWT_SECRET=${JWT_SECRET}
      - SERVICE_KEY=${SERVICE_KEY}
      - POLL_INTERVAL=60
    depends_on:
      - django
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health/"]
      interval: 30s
      timeout: 10s
      retries: 3

  mcp:
    build: ./whatsapp-mcp-server
    ports:
      - "18082:8001"
    volumes:
      - shared_storage:/app/store
    environment:
      - DJANGO_API_URL=http://django:8000
      - JWT_SECRET=${JWT_SECRET}
      - SERVICE_KEY=${SERVICE_KEY}
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8001
    depends_on:
      - django
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health/"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  shared_storage:
```

**Note**: Only Django (18080) and MCP (18082) need external port exposure. Bridge (18081) is internal only.

---

## 6. User Flows

### 6.1 User Creation & QR Onboarding

```
Admin (Django Admin)
    │
    ▼
Create User → status: 'pending_init_request'
    │
    ▼
Bridge poll (every 60s)
    │
    ├── Detect new user
    ├── Create store/{user_id}/
    ├── Initialize SQLite
    └── Start HandleUser goroutine
    │
    ▼
HandleUser sees 'pending_init_request'
    │
    ├── Generate QR code
    ├── PATCH /api/users/{id}/qr/
    └── Update status → 'pending_handshake'
    │
    ▼
Admin triggers "Show WhatsApp QR" action
    │
    ├── Scans QR with their phone
    └── WhatsApp handshake completes
    │
    ▼
Bridge detects connected
    │
    ├── Update status → 'connected'
    ├── Store whatsapp.db session
    └── Begin message sync
    │
    ▼
Admin triggers "Generate API Key" action
    │
    ├── JWT token generated and displayed
    └── Admin copies to LLM client config
```

### 6.2 MCP Request Flow

```
AI Agent (Claude, Cursor)
    │
    ▼
GET /mcp/ with Authorization: Bearer <JWT>
    │
    ▼
MCP validates JWT
    │
    ├── Extract user_id
    ├── Validate not expired
    └── Check user status == 'connected'
    │
    ▼
MCP receives tool call
    │
    ├── Route to user's store/{user_id}/messages.db
    └── Return response
```

### 6.3 User Deletion

```
Admin (Django Admin)
    │
    ▼
Delete User → DELETE /api/users/{id}/
    │
    ▼
Bridge poll detects deletion
    │
    ▼
For user being deleted:
    │
    ├── Signal StopChan
    ├── Disconnect WhatsApp client
    ├── Remove store/{user_id}/
    └── Remove from users map
    │
    ▼
MCP
    │
    └── JWT validation fails for deleted user
```

---

## 7. Error Handling

### 7.1 Bridge → Django Communication

| Scenario | Handling |
|----------|----------|
| Django unreachable | Log error, continue polling, retry next interval |
| JWT invalid | Log warning, skip user update |
| QR push fails | Log error, retry on next status change |

### 7.2 WhatsApp Connection

| Scenario | Handling |
|----------|----------|
| QR scan timeout | Status → 'sync_error', allow retry |
| Disconnected | Auto-reconnect with backoff, update Django status |
| Rate limited | Log and back off |

### 7.3 MCP Server

| Scenario | Handling |
|----------|----------|
| Invalid JWT | 401 Unauthorized |
| User not connected | 403 Forbidden with status info |
| Database error | 500 with error message |

---

## 8. Implementation Order

### Phase 1: Django Server

**Step 1.1: Project Setup**
1. Scaffold Django project with `django-admin startproject`
2. Create `users` app
3. Configure settings (JWT_SECRET, SERVICE_KEY, ALLOWED_HOSTS)
4. Write unit tests for: project setup, settings configuration

**Step 1.2: Models**
1. Create `User` model extending AbstractUser with status and whatsapp_jid
2. Create `QRCode` model with user FK, image_data, expires_at, verified
3. Write unit tests for: model validation, status choices, QRCode relationships

**Step 1.3: REST API**
1. Configure DRF with ViewSets, Serializers
2. Implement `/api/users/` CRUD endpoints with service key auth
3. Implement `/api/users/{id}/qr/` GET/PATCH endpoints
4. Implement `/api/auth/token/` endpoint for JWT generation
5. Write unit tests for: serializers, view permissions, service key validation

**Step 1.4: Django Admin**
1. Configure User admin with list view (username, status, created)
2. Add status filter in list view
3. Add `Show WhatsApp QR` action (displays QR in popup)
4. Add `Generate API Key` action (generates and displays JWT)
5. Make status field editable in user change form
6. Write unit tests for: admin actions, QR display, API key generation

**Step 1.5: Logging**
1. Configure structured logging for all operations
2. Log all admin actions, API calls, status changes
3. Write unit tests for: log format, log events

**Verification**: Each step must pass all unit tests before proceeding to next step.

### Phase 2: WhatsApp Bridge

**Step 2.1: Module Structure (Unit Tests Required)**
1. Create `go/` directory structure
2. Extract `UserClient`, `Bridge`, `MessageStore` types
3. Add configuration loading from environment variables
4. Write unit tests for: config validation, struct initialization

**Step 2.2: Django API Client (Unit Tests Required)**
1. Implement `DjangoAPIClient` with service key auth
2. Add methods: `GetUsers()`, `UpdateUser()`, `PushQR()`
3. Write unit tests for: service key validation, HTTP request/response handling, error handling

**Step 2.3: User Polling Loop (Unit Tests Required)**
1. Implement polling goroutine with diff logic
2. Add user add/remove/update operations
3. Write unit tests for: user diffing, concurrent map access, polling interval

**Step 2.4: Per-User GoRoutine (Unit Tests Required)**
1. Implement `HandleUser()` with status machine
2. Add QR channel handling and push to Django
3. Write unit tests for: status transitions, QR event handling, goroutine lifecycle

**Step 2.5: REST API for MCP (Unit Tests Required)**
1. Add `POST /api/send/` with user_id validation
2. Add `POST /api/download/` with path traversal prevention
3. Add `GET /api/status/{user_id}/`
4. Write unit tests for: user_id regex validation, path traversal prevention, request routing

**Step 2.6: Message Store (Unit Tests Required)**
1. Implement per-user SQLite operations
2. Add message/chats CRUD
3. Write unit tests for: user isolation, message storage, query correctness

**Verification**: Each step must pass all unit tests before proceeding to next step.

### Phase 3: MCP Server

**Step 3.1: Project Setup (Unit Tests Required)**
1. Set up FastMCP project structure
2. Determine available transport (streamable-http vs WebSocket)
3. Configure environment variables (JWT_SECRET, SERVICE_KEY, DJANGO_API_URL)
4. Write unit tests for: config loading, transport detection

**Step 3.2: JWT Authentication (Unit Tests Required)**
1. Implement JWT validation function
2. Create middleware for extracting user_id from Bearer token
3. Implement service key validation for Bridge calls
4. Write unit tests for: JWT decode, user_id extraction, token validation edge cases

**Step 3.3: User-Scoped Database (Unit Tests Required)**
1. Modify whatsapp.py to accept user_id parameter
2. Implement path construction `store/{user_id}/messages.db`
3. Add path traversal prevention
4. Write unit tests for: path construction, user isolation, query correctness

**Step 3.4: MCP Tools (Unit Tests Required)**
1. Update all tools to accept and validate user_id from JWT context
2. Implement user_id mismatch prevention
3. Add proper error responses for unauthorized access
4. Write unit tests for: user context propagation, authorization checks

**Step 3.5: Bridge API Integration (Unit Tests Required)**
1. Implement calls to Bridge `/api/send/`, `/api/download/`
2. Add service key header to Bridge requests
3. Handle error responses appropriately
4. Write unit tests for: API client, error handling, response parsing

**Step 3.6: Health Endpoint**
1. Add `GET /health/` endpoint (no auth required)
2. Return service status and version
3. Write unit tests for: health check response

**Verification**: Each step must pass all unit tests before proceeding to next step.

### Phase 4: Integration
1. Create Dockerfiles for each service
2. Write docker-compose.yml
3. Test end-to-end user flow
4. Verify JWT validation chain
5. Test error scenarios

---

## 9. Testing Strategy

### Unit Tests
- Django: Model validation, API serializers, view logic
- Bridge: User polling, QR generation, message storage
- MCP: JWT validation, user-scoped queries

### Integration Tests
- Full user creation → QR scan → connected flow
- MCP tool execution with real database
- User deletion cleanup

---

## 10. Logging Requirements

All services must implement structured logging for troubleshooting.

### 10.1 Log Levels

| Level | Usage |
|-------|-------|
| `DEBUG` | Detailed troubleshooting (connection attempts, DB queries) |
| `INFO` | Normal operations (user actions, successful operations) |
| `WARNING` | Recoverable issues (retry, timeout, degraded state) |
| `ERROR` | Failed operations (connection failed, invalid input) |
| `CRITICAL` | System failure (crash, security event) |

### 10.2 Required Log Events

**Django Server**:
- User created/deleted/status changed
- JWT token generated
- Service key validation success/failure
- QR code generated/pushed/verified/expired
- Admin actions (all CRUD on users)

**Bridge**:
- User polling cycle start/complete (with user count)
- User added/removed/updated
- WhatsApp client connect/disconnect/reconnect
- QR code generation success/failure
- Message sync start/complete (with message count)
- API call from MCP (user_id, action, success/failure)
- All errors with stack traces

**MCP Server**:
- JWT validation success/failure (with user_id if available)
- MCP connection opened/closed
- Tool call received (tool name, user_id)
- Tool execution start/complete (with duration)
- Database query errors
- Bridge API call success/failure

### 10.3 Log Format

```json
{
  "timestamp": "2025-01-15T10:30:00Z",
  "level": "INFO",
  "service": "bridge",
  "event": "user_status_changed",
  "user_id": "user123",
  "old_status": "pending_handshake",
  "new_status": "connected",
  "details": "WhatsApp connection established"
}
```

### 10.4 Implementation

```python
# Python - use structlog or standard logging with JSON formatter
import logging
import structlog

logger = structlog.get_logger()

# Go - use zerolog or slog
import "log/slog"
```

---

## 11. API Key Generation

### 11.1 Flow

1. Admin creates user in Django Admin
2. Admin triggers `Show WhatsApp QR` action → scans with phone
3. Admin triggers `Generate API Key` action → JWT displayed
4. Admin copies token to LLM client configuration

### 11.2 JWT Generation (Django)

```python
import jwt
from datetime import datetime

def generate_api_key(user_id: str) -> str:
    """Generate a JWT token for user_id. No expiry."""
    payload = {
        "user_id": user_id,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
```

### 11.3 Validation (MCP Server)

```python
def validate_jwt(token: str) -> Optional[str]:
    """Validate JWT and return user_id. No expiry check."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        return payload.get("user_id")
    except jwt.InvalidTokenError:
        return None
```

### 11.4 Revocation

No explicit revocation mechanism. If admin needs to revoke access:
1. Delete the user in Django Admin
2. Create new user with new credentials

---

## 12. Security Considerations

### 12.1 P0 Security Fixes (Implemented)

1. **Service-to-Service Authentication**:
   - All internal calls require `X-Service-Key` header
   - Django validates using timing-safe comparison (`secrets.compare_digest`)
   - Service key is shared secret in environment variables

2. **MCP → Bridge User ID Validation**:
   - Bridge validates that `user_id` in request matches JWT's subject
   - MCP validates user_id mismatch before making Bridge call
   - Prevents sending messages as another user

3. **Path Traversal Prevention**:
   - `user_id` must match pattern `^[a-zA-Z0-9\-_]{1,64}$`
   - All filesystem paths validated before use
   - User data isolated to `store/{user_id}/`

4. **Rate Limiting** (Accepted - Not Implemented):
   - Per user or IP rate limiting on public endpoints
   - External network only, not critical for internal services

### 12.2 Accepted Risks

| Risk | Acceptance Rationale |
|------|---------------------|
| No TLS between services | Docker internal network only; external ports not exposed |
| WhatsApp session unencrypted | Acceptable for single-tenant deployment; volume-level encryption not needed |
| No mTLS between services | Internal network isolation sufficient |
| No JWT expiration | Simplifies operations; revocation via user deletion |

---

## 13. File Structure Summary

```
whatsapp-mcp/
├── IMPLEMENTATION_PLAN.md
├── docker-compose.yml
├── .env.example
│
├── django-server/
│   ├── Dockerfile
│   ├── manage.py
│   ├── requirements.txt
│   ├── whatsapp_mgr/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   └── users/
│       ├── __init__.py
│       ├── models.py
│       ├── admin.py
│       ├── views.py
│       ├── serializers.py
│       ├── urls.py
│       └── tests.py
│
├── whatsapp-bridge/
│   ├── Dockerfile
│   ├── go.mod
│   ├── go.sum
│   ├── main.go
│   └── go/
│       ├── bridge.go
│       ├── user_client.go
│       ├── message_store.go
│       └── api_client.go
│
└── whatsapp-mcp-server/
    ├── Dockerfile
    ├── pyproject.toml
    ├── requirements.txt
    ├── server.py
    ├── auth.py
    ├── whatsapp.py
    └── audio.py
```

---

## 14. Ports Summary

| Service | Port | Purpose |
|---------|------|---------|
| Django | 18080 | Admin UI, REST API, QR display |
| Bridge | 18081 | WhatsApp connections, message storage (internal only) |
| MCP | 18082 | MCP protocol endpoint for AI agents |