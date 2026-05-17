# WhatsApp Bridge Architecture

## Document Overview

This document describes the architecture of the WhatsApp Bridge service, documenting both the current state (single-user) and the target state (multi-tenant). It aligns with the IMPLEMENTATION_PLAN.md design and provides detailed migration steps.

---

## 1. Current Architecture (Before Multi-User Changes)

### 1.1 Component Overview

The current bridge is a **single-user WhatsApp client** that runs as a standalone service. It does not communicate with Django and has no concept of multi-tenancy.

```
┌─────────────────────────────────────────────────────────────┐
│                    whatsapp-bridge                          │
│                                                              │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐   │
│  │  WhatsApp   │     │   REST API  │     │   Message   │   │
│  │   Client    │◄────│   :8080     │     │    Store    │   │
│  │  (single)   │     │             │     │   SQLite    │   │
│  └──────┬──────┘     └─────────────┘     └─────────────┘   │
│         │                                                       │
│         ▼                                                       │
│  ┌─────────────┐                                               │
│  │    QR       │                                               │
│  │  Terminal   │  (stdout output)                              │
│  └─────────────┘                                               │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 File Structure

```
whatsapp-bridge/
├── go.mod
├── go.sum
├── main.go           # Single 1348-line file with all logic
└── store/
    ├── messages.db   # Message history SQLite DB
    └── whatsapp.db   # WhatsApp session SQLite DB (whatsmeow)
```

### 1.3 Key Components in main.go

#### 1.3.1 WhatsApp Client Initialization (lines 789-896)

```go
// Single client instance - no user isolation
client := whatsmeow.NewClient(deviceStore, logger)

// QR code generation via terminal (lines 860-887)
// - No API to retrieve QR code remotely
// - Only prints to stdout via qrterminal.GenerateHalfBlock
```

**Current Flow:**
1. Creates single WhatsApp client for one user
2. Checks if device exists in `store/whatsapp.db`
3. If no device: generates QR code, prints to stdout, waits 3 minutes for scan
4. If device exists: connects with stored session
5. No concept of user management

#### 1.3.2 MessageStore (lines 45-173)

```go
type MessageStore struct {
    db *sql.DB  // Single SQLite connection
}

// Storage path: store/messages.db (hardcoded, line 57)
// No user isolation - all messages in single database
```

**Current Schema:**
- `chats` table: jid, name, last_message_time
- `messages` table: id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length

**Limitations:**
- No user_id column - all messages co-mingled
- No path traversal protection
- Media stored in `store/{chat_jid}/` without user isolation

#### 1.3.3 REST API (lines 678-787)

```go
func startRESTServer(client *whatsmeow.Client, messageStore *MessageStore, port int)
```

**Current Endpoints:**

| Method | Endpoint | Handler | Auth |
|--------|----------|----------|------|
| POST | `/api/send` | sendWhatsAppMessage | None |
| POST | `/api/download` | downloadMedia | None |

**Current Security Issues:**
- No authentication on any endpoint
- No user_id validation
- No service key validation
- No path traversal protection on `media_path` parameter

**Request/Response:**

```go
// POST /api/send
type SendMessageRequest struct {
    Recipient string `json:"recipient"`
    Message   string `json:"message"`
    MediaPath string `json:"media_path,omitempty"`  // DANGEROUS: No validation
}

// POST /api/download
type DownloadMediaRequest struct {
    MessageID string `json:"message_id"`
    ChatJID   string `json:"chat_jid"`
}
```

#### 1.3.4 QR Code Generation

**Current Implementation (lines 860-887):**
```go
qrChan, _ := client.GetQRChannel(context.Background())
for evt := range qrChan {
    if evt.Event == "code" {
        qrterminal.GenerateHalfBlock(evt.Code, qrterminal.L, os.Stdout)
    }
}
```

**Limitations:**
- QR code only printed to stdout
- No API to retrieve QR code
- No push to Django
- No multi-user QR management

#### 1.3.5 Event Handlers (lines 838-854)

```go
client.AddEventHandler(func(evt interface{}) {
    switch v := evt.(type) {
    case *events.Message:
        handleMessage(client, messageStore, v, logger)
    case *events.HistorySync:
        handleHistorySync(client, messageStore, v, logger)
    case *events.Connected:
        logger.Infof("Connected to WhatsApp")
    case *events.LoggedOut:
        logger.Warnf("Device logged out...")
    }
})
```

**Limitations:**
- Single event handler for single user
- No per-user callback registration
- No user_id context passed to handlers

---

## 2. Target Architecture (After Multi-User Changes)

### 2.1 Component Overview

The target architecture supports multiple concurrent WhatsApp users with proper isolation, Django integration for user management, and MCP server connectivity.

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Docker Compose                                │
│                                                                      │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐           │
│  │  Django     │     │   Bridge    │     │    MCP      │           │
│  │  :18080     │◄────│   :18081    │     │   :18082    │           │
│  │             │     │             │     │             │           │
│  │  Admin UI   │     │  Per-user   │     │  Streamable │           │
│  │  REST API   │     │  GoRoutines │     │  HTTP MCP   │           │
│  │  QR Display │     │             │     │             │           │
│  └─────────────┘     └──────┬──────┘     └──────┬──────┘           │
│         │                   │                   │                  │
│         └───────────────────┼───────────────────┘                  │
│                             ▼                                        │
│                   ┌───────────────────┐                             │
│                   │  shared_storage/  │                             │
│                   │                   │                             │
│                   │  user_{id}/       │                             │
│                   │    ├─ messages.db│                             │
│                   │    └─ whatsapp.db│                             │
│                   └───────────────────┘                             │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 Target File Structure

```
whatsapp-bridge/
├── go.mod
├── go.sum
├── main.go              # Entry point, service initialization
├── bridge.go            # Main bridge logic, user polling
├── user_client.go       # Per-user WhatsApp client wrapper
├── message_store.go     # User-scoped message storage
├── api_client.go        # Django API client
└── store/               # Per-user storage (created dynamically)
    ├── user_{id}/
    │   ├── messages.db
    │   └── whatsapp.db
```

### 2.3 Core Data Structures

#### 2.3.1 UserClient (Per-User WhatsApp Client)

```go
type UserClient struct {
    UserID       string
    Username     string
    Client       *whatsmeow.Client
    MessageStore *MessageStore
    Status       string              // pending_init_request, pending_handshake, connected, sync_error
    StopChan     chan struct{}
    QRChan       chan *QRCodeEvent    // Channel for QR code events
}
```

#### 2.3.2 QRCodeEvent (QR Code Communication)

```go
type QRCodeEvent struct {
    UserID    string
    ImageData string               // Base64 encoded PNG
    ExpiresAt time.Time
}
```

#### 2.3.3 Bridge (Main Orchestrator)

```go
type Bridge struct {
    djangoURL    string
    jwtSecret    string
    serviceKey   string
    pollInterval time.Duration
    users        map[string]*UserClient
    mu           sync.RWMutex
    httpClient   *http.Client
}
```

### 2.4 REST API Endpoints (Target)

All endpoints require `X-Service-Key` header for Bridge-Django auth.

| Method | Endpoint | Request | Response | Description |
|--------|----------|---------|----------|-------------|
| POST | `/api/send/` | `{user_id, recipient, message, media_path}` | `{success, message}` | Send message |
| POST | `/api/download/` | `{user_id, message_id, chat_jid}` | `{success, path, media_type}` | Download media |
| GET | `/api/status/{user_id}/` | - | `{status, jid, connected}` | Get connection status |
| GET | `/health/` | - | `{healthy}` | Health check |

**Security Requirements:**
- `user_id` must match pattern `^[a-zA-Z0-9\-_]{1,64}$`
- All filesystem paths validated against path traversal
- JWT validation chain: MCP → Bridge validates user_id

---

## 3. Architecture Comparison

### 3.1 Current vs Target

| Aspect | Current | Target |
|--------|---------|--------|
| Users | Single hardcoded | Multi-tenant via Django |
| WhatsApp Clients | One client instance | Per-user Client instances |
| QR Code | stdout only | Push to Django via API |
| REST API Auth | None | Service Key + JWT |
| Message Storage | Single DB | Per-user DBs |
| Django Integration | None | Polling + API |
| Path Traversal Protection | None | Validated |
| User ID Validation | N/A | Required |
| Logging | fmt.Println | Structured logging |

### 3.2 Port Configuration

| Service | Current Port | Target Port | Purpose |
|---------|--------------|-------------|---------|
| Bridge REST | 8080 | 8080 | MCP → Bridge communication |
| Bridge Internal | N/A | 18081 | Django ↔ Bridge communication |

**Note:** Bridge port 8080 is for MCP communication. External exposure is through MCP on 18082. Bridge on 18081 is internal only.

---

## 4. User Flows

### 4.1 User Creation & QR Onboarding (Target)

```
Django Admin
    │
    ▼
Create User → status: 'pending_init_request'
    │
    ▼
Bridge poll (every 60s)
    │
    ├── Detect new user
    ├── Create store/{user_id}/
    ├── Initialize SQLite tables
    └── Start HandleUser goroutine
    │
    ▼
HandleUser sees 'pending_init_request'
    │
    ├── Generate QR code via whatsmeow
    ├── PATCH /api/users/{id}/qr/  (push QR to Django)
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
```

### 4.2 MCP Request Flow (Target)

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
    └── Validate not expired
    │
    ▼
MCP receives tool call
    │
    ├── Route to Bridge API (user_id from JWT)
    │   POST /api/send/ with {user_id, recipient, message}
    │
    └── Return response
```

---

## 5. Migration Steps (Preserving Single-User Behavior)

### Phase 1: Foundation (No Behavior Change)

**Step 1.1: Create Module Structure**
```
main.go → Split into modules:
- bridge.go: Bridge struct, polling loop
- user_client.go: UserClient struct
- message_store.go: MessageStore (user-scoped)
- api_client.go: Django API client
```

**Step 1.2: Add Configuration**
```go
type Config struct {
    DjangoURL    string
    JWT Secret   string
    ServiceKey   string
    PollInterval time.Duration
}
```

**Step 1.3: Initialize with Default User**
- On startup, create a default user if none exists
- Maintain backward compatibility with current single-user behavior
- This phase: no multi-user yet, just code reorganization

### Phase 2: Django Integration (Bridge → Django)

**Step 2.1: Implement API Client**
- Add `api_client.go` with methods:
  - `GetUsers() ([]User, error)`
  - `UpdateUserStatus(userID, status string) error`
  - `PushQRCode(userID, imageData string) error`

**Step 2.2: Add Service Key Authentication**
```go
func (c *APIClient) addServiceKey(req *http.Request) {
    req.Header.Set("X-Service-Key", c.serviceKey)
}
```

**Step 2.3: Implement User Polling Loop**
```go
func (b *Bridge) PollUsers(ctx context.Context) {
    users, err := b.api.GetUsers()
    // Diff with local users map
    // Start/stop goroutines accordingly
}
```

**Step 2.4: Add Per-User Goroutine**
```go
func (b *Bridge) HandleUser(ctx context.Context, user *UserClient) {
    for {
        select {
        case <-user.StopChan:
            return
        case qr := <-user.QRChan:
            b.api.PushQRCode(user.UserID, qr.ImageData)
        }
    }
}
```

### Phase 3: Multi-User Support (Bridge Internal)

**Step 3.1: User-Scoped Storage**
```go
func NewUserMessageStore(userID string) (*MessageStore, error) {
    // Create store/{userID}/ directory
    // Initialize user-specific SQLite
}
```

**Step 3.2: Per-User WhatsApp Client**
```go
func NewUserClient(userID string, store *sqlstore.Container) *UserClient {
    // Each user gets own whatsmeow.Client
    // Own event handlers
    // Own session storage
}
```

**Step 3.3: QR Code API Push**
```go
func (uc *UserClient) handleQRCode(code string) {
    qr := &QRCodeEvent{
        UserID:    uc.UserID,
        ImageData: base64PNG(code),
        ExpiresAt: time.Now().Add(60 * time.Second),
    }
    select {
    case uc.QRChan <- qr:
    default:
    }
}
```

### Phase 4: REST API Security

**Step 4.1: Add User ID Validation**
```go
func validateUserID(userID string) error {
    matched, _ := regexp.MatchString(`^[a-zA-Z0-9\-_]{1,64}$`, userID)
    if !matched {
        return fmt.Errorf("invalid user_id format")
    }
    return nil
}
```

**Step 4.2: Add Service Key Validation**
```go
func validateServiceKey(r *http.Request, expectedKey string) bool {
    key := r.Header.Get("X-Service-Key")
    return secrets.compare_digest(key, expectedKey)
}
```

**Step 4.3: Path Traversal Prevention**
```go
func safePath(userID, filename string) (string, error) {
    // Validate userID format
    // Join with base path
    // Verify result is within base directory
}
```

---

## 6. Failure Points and Mitigations

### 6.1 WhatsApp Connection Failures

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| QR scan timeout | Status stays `pending_handshake` > 5 min | Bridge auto-regenerates QR, pushes new to Django |
| Disconnection | `events.Disconnected` | Auto-reconnect with exponential backoff |
| Device logged out | `events.LoggedOut` | Signal Django status → `sync_error`, admin notified |
| Rate limited | WhatsApp returns error | Back off 60s, retry with jitter |

### 6.2 Bridge → Django Communication Failures

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Django unreachable | HTTP timeout/error | Log error, continue polling, retry next interval |
| QR push fails | API returns error | Log error, retry on next QR generation cycle |
| JWT invalid | 401 from Django | Log warning, skip user update, check service key |

### 6.3 Multi-User Isolation Failures

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| User accesses another user's data | user_id mismatch | Return 403, log security event |
| Path traversal attempt | Invalid characters in path | Return 400, log security event |
| User deleted mid-operation | JWT validation fails | Clean up goroutine, return 401 |

### 6.4 Storage Failures

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Disk full | os.MkdirAll fails | Log critical, signal user status → `sync_error` |
| SQLite corruption | db.Exec returns error | Delete and recreate DB, request history re-sync |
| Permission denied | File creation fails | Log critical, exit gracefully |

---

## 7. Logging Requirements

### 7.1 Required Log Events

**User Lifecycle:**
```
user_polling_cycle_start{user_count=N}
user_added{user_id, username}
user_removed{user_id}
user_status_changed{user_id, old_status, new_status}
```

**WhatsApp Connection:**
```
whatsapp_client_connect{user_id}
whatsapp_client_disconnect{user_id}
whatsapp_client_reconnect{user_id, attempt}
qr_code_generated{user_id}
qr_code_scan_success{user_id}
```

**Message Sync:**
```
message_sync_start{user_id, chat_count}
message_received{user_id, chat_jid, message_id}
message_sent{user_id, recipient, success}
```

**API Calls:**
```
api_request{user_id, endpoint, method, status}
api_error{user_id, endpoint, error}
```

**Security:**
```
security_user_id_mismatch{user_id, requested_user_id}
security_path_traversal_attempt{user_id, path}
security_invalid_service_key{ip}
```

### 7.2 Log Format

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

---

## 8. Testing Considerations

### 8.1 Unit Test Coverage

| Component | Test Cases |
|-----------|------------|
| UserClient | Init, QR handling, status transitions |
| Bridge | Polling, user diffing, goroutine management |
| MessageStore | Store/retrieve messages, chats |
| API Client | Service key auth, retry logic |
| Validation | user_id format, path traversal |

### 8.2 Integration Test Scenarios

1. **Single user flow**: Admin creates user → Bridge detects → QR generated → User scans → Connected
2. **Multi-user isolation**: Two users, verify data cannot cross
3. **Graceful degradation**: Django down, Bridge continues with cached state
4. **Reconnection**: WhatsApp disconnects, verify auto-reconnect
5. **Cleanup**: User deleted, verify all resources cleaned

---

## 9. Backward Compatibility

### 9.1 Preserving Single-User Mode

During migration, a `DEFAULT_USER_ID` environment variable allows running in single-user mode:

```go
if defaultUserID := os.Getenv("DEFAULT_USER_ID"); defaultUserID != "" {
    // Operate in single-user mode for backward compatibility
    // Use defaultUserID for all operations
}
```

### 9.2 Migration Path

1. **Phase 1-2**: Add code but don't change behavior (single user still works)
2. **Phase 3**: Multi-user internally, single user via `DEFAULT_USER_ID`
3. **Phase 4**: Full multi-user with Django

---

## 10. Environment Variables

| Variable | Current | Target | Description |
|----------|---------|--------|-------------|
| `PORT` | 8080 | 8080 | REST API port |
| `DJANGO_API_URL` | - | Required | Django API base URL |
| `SERVICE_KEY` | - | Required | Service-to-service auth |
| `JWT_SECRET` | - | Required | JWT validation |
| `POLL_INTERVAL` | - | 60 | User polling interval (seconds) |
| `MAX_CONCURRENT_USERS` | - | 5 | Maximum concurrent WhatsApp connections |
| `DEFAULT_USER_ID` | - | Optional | Backward compat mode |
| `LOG_LEVEL` | - | INFO | Logging level |

---

## 11. Dependencies

### Current Dependencies (go.mod)

```go
require (
    github.com/mattn/go-sqlite3 v1.14.42
    github.com/mdp/qrterminal v1.0.1
    go.mau.fi/whatsmeow v0.0.0-20260511155711-eb05d94dea7d
    google.golang.org/protobuf v1.36.11
)
```

### Additional Dependencies (Target)

```go
// For HTTP client with retry
github.com/hashicorp/go-retryablehttp

// For logging
github.com/rs/zerolog

// For timing-safe comparison
// (standard library: crypto/subtle.ConstantTimeCompare)
```

---

*Document Version: 1.0*
*Aligned with: IMPLEMENTATION_PLAN.md*
