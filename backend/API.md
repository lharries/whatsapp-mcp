# WhatsApp MCP REST API Documentation

## Base URL

```
http://localhost:8080
```

## Common Response Format

All API responses follow this structure:

```typescript
{
  "success": boolean,
  "data"?: any,
  "error"?: {
    "code": string,
    "message": string,
    "details"?: object
  },
  "message"?: string,
  "timestamp": Date
}
```

## Authentication Endpoints

### GET /api/auth/status

Get current WhatsApp authentication status.

**Response:**
```json
{
  "success": true,
  "data": {
    "isAuthenticated": true,
    "isConnected": true,
    "qrCode": "data:image/png;base64,...",
    "connectionStatus": "ready",
    "lastConnected": "2025-10-23T12:00:00.000Z",
    "phoneNumber": "+1234567890"
  },
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### GET /api/auth/qr

Get QR code for authentication (if available).

**Response:**
```json
{
  "success": true,
  "data": {
    "qrCode": "data:image/png;base64,iVBORw0KGgo..."
  },
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### POST /api/auth/logout

Logout and disconnect from WhatsApp.

**Response:**
```json
{
  "success": true,
  "message": "Logged out successfully",
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

## Chat Endpoints

### GET /api/chats

List all chats with optional filtering.

**Query Parameters:**
- `query` (optional): Search term for chat names
- `limit` (optional): Maximum chats to return (default: 20)
- `page` (optional): Page number for pagination (default: 0)
- `sortBy` (optional): Sort field - `last_active` or `name` (default: `last_active`)

**Example:**
```
GET /api/chats?query=John&limit=10&sortBy=name
```

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "jid": "1234567890@s.whatsapp.net",
      "name": "John Doe",
      "lastMessageTime": "2025-10-23T11:30:00.000Z",
      "isGroup": false,
      "unreadCount": 3
    }
  ],
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### GET /api/chats/:chatJid

Get specific chat by JID.

**Parameters:**
- `chatJid`: WhatsApp JID (e.g., `1234567890@s.whatsapp.net` or `120363123456@g.us`)

**Example:**
```
GET /api/chats/1234567890@s.whatsapp.net
```

**Response:**
```json
{
  "success": true,
  "data": {
    "jid": "1234567890@s.whatsapp.net",
    "name": "John Doe",
    "lastMessageTime": "2025-10-23T11:30:00.000Z",
    "isGroup": false,
    "participantList": [],
    "unreadCount": 3
  },
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### GET /api/chats/contact/:phoneNumber

Get direct chat with a contact by phone number.

**Parameters:**
- `phoneNumber`: Phone number without + or special characters (e.g., `1234567890`)

**Example:**
```
GET /api/chats/contact/1234567890
```

### GET /api/chats/by-contact/:jid

Get all chats involving a specific contact.

**Parameters:**
- `jid`: Contact's WhatsApp JID

**Query Parameters:**
- `limit` (optional): Maximum chats (default: 20)
- `page` (optional): Page number (default: 0)

**Example:**
```
GET /api/chats/by-contact/1234567890@s.whatsapp.net?limit=10
```

## Message Endpoints

### GET /api/messages

List messages with optional filtering.

**Query Parameters:**
- `chatJid` (optional): Filter by specific chat
- `query` (optional): Search in message content
- `senderPhoneNumber` (optional): Filter by sender
- `after` (optional): ISO-8601 date - messages after this date
- `before` (optional): ISO-8601 date - messages before this date
- `limit` (optional): Maximum messages (default: 20)
- `page` (optional): Page number (default: 0)

**Example:**
```
GET /api/messages?chatJid=1234567890@s.whatsapp.net&limit=50&query=meeting
```

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": "3EB0123456789ABCDEF",
      "chatJid": "1234567890@s.whatsapp.net",
      "sender": "1234567890@s.whatsapp.net",
      "senderName": "John Doe",
      "content": "Let's have a meeting tomorrow",
      "timestamp": "2025-10-23T11:30:00.000Z",
      "isFromMe": false,
      "mediaType": null
    }
  ],
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### GET /api/messages/:chatJid/:messageId/context

Get context around a specific message (messages before and after).

**Parameters:**
- `chatJid`: Chat JID
- `messageId`: Message ID

**Query Parameters:**
- `before` (optional): Number of messages before (default: 5)
- `after` (optional): Number of messages after (default: 5)

**Example:**
```
GET /api/messages/1234567890@s.whatsapp.net/3EB0123456789ABCDEF/context?before=3&after=3
```

**Response:**
```json
{
  "success": true,
  "data": {
    "targetMessage": { /* message object */ },
    "messageListBefore": [ /* array of messages */ ],
    "messageListAfter": [ /* array of messages */ ],
    "chat": {
      "jid": "1234567890@s.whatsapp.net",
      "name": "John Doe"
    }
  },
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### POST /api/messages/send

Send a text message.

**Request Body:**
```json
{
  "recipient": "1234567890",
  "message": "Hello, this is a test message"
}
```

Or with JID:
```json
{
  "recipient": "1234567890@s.whatsapp.net",
  "message": "Hello, this is a test message"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Message sent to 1234567890",
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### POST /api/messages/send-file

Send a media file (image, video, document).

**Request Body:**
```json
{
  "recipient": "1234567890",
  "mediaPath": "/absolute/path/to/file.jpg",
  "caption": "Optional caption"
}
```

**Response:**
```json
{
  "success": true,
  "message": "File sent to 1234567890",
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### POST /api/messages/send-audio

Send an audio file as a voice message.

**Request Body:**
```json
{
  "recipient": "1234567890",
  "mediaPath": "/absolute/path/to/audio.mp3"
}
```

**Note**: If FFmpeg is installed, audio will be automatically converted to Opus format. Otherwise, send as file using `/send-file`.

**Response:**
```json
{
  "success": true,
  "message": "Voice message sent to 1234567890",
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### POST /api/messages/:chatJid/:messageId/download

Download media from a message.

**Parameters:**
- `chatJid`: Chat JID
- `messageId`: Message ID containing media

**Response:**
```json
{
  "success": true,
  "data": {
    "filePath": "/absolute/path/to/downloaded/media.jpg"
  },
  "message": "Media downloaded successfully",
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

## Contact Endpoints

### GET /api/contacts

List all contacts.

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "jid": "1234567890@s.whatsapp.net",
      "name": "John Doe",
      "phoneNumber": "1234567890",
      "pushName": "John",
      "isBlocked": false
    }
  ],
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

### GET /api/contacts/search

Search contacts by name or phone number.

**Query Parameters:**
- `query` (required): Search term

**Example:**
```
GET /api/contacts/search?query=John
```

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "jid": "1234567890@s.whatsapp.net",
      "name": "John Doe",
      "phoneNumber": "1234567890",
      "pushName": "John"
    }
  ],
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

## WebSocket Events

Connect to WebSocket at `ws://localhost:8080/ws`

### Client → Server Messages

**Ping:**
```json
{
  "type": "ping"
}
```

### Server → Client Messages

**Connection Update:**
```json
{
  "type": "connection_update",
  "data": {
    "status": "ready",
    "message": "Connected to WhatsApp",
    "timestamp": "2025-10-23T12:00:00.000Z"
  },
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

**New Message:**
```json
{
  "type": "message",
  "data": {
    "id": "3EB0123456789ABCDEF",
    "chatJid": "1234567890@s.whatsapp.net",
    "sender": "1234567890@s.whatsapp.net",
    "content": "New message received",
    "timestamp": "2025-10-23T12:00:00.000Z",
    "isFromMe": false
  },
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

**Chat Update:**
```json
{
  "type": "chat_update",
  "data": {
    "jid": "1234567890@s.whatsapp.net",
    "name": "John Doe",
    "lastMessageTime": "2025-10-23T12:00:00.000Z"
  },
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

**Heartbeat:**
```json
{
  "type": "ping",
  "data": {},
  "timestamp": "2025-10-23T12:00:00.000Z"
}
```

## Error Codes

| Code | Description |
|------|-------------|
| `VALIDATION_ERROR` | Request validation failed |
| `NOT_FOUND` | Resource not found |
| `UNAUTHORIZED` | Authentication required |
| `FORBIDDEN` | Access denied |
| `INTERNAL_ERROR` | Internal server error |
| `WHATSAPP_ERROR` | WhatsApp-specific error |
| `STORAGE_ERROR` | Data storage error |
| `MEDIA_ERROR` | Media processing error |

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | OK - Request successful |
| 201 | Created - Resource created |
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Authentication required |
| 403 | Forbidden - Access denied |
| 404 | Not Found - Resource doesn't exist |
| 500 | Internal Server Error |

## Examples

### Sending a Message (curl)

```bash
curl -X POST http://localhost:8080/api/messages/send \
  -H "Content-Type: application/json" \
  -d '{
    "recipient": "1234567890",
    "message": "Hello from REST API!"
  }'
```

### Getting Chat List (curl)

```bash
curl http://localhost:8080/api/chats?limit=10&sortBy=last_active
```

### WebSocket Connection (JavaScript)

```javascript
const ws = new WebSocket('ws://localhost:8080/ws');

ws.onopen = () => {
  console.log('Connected to WebSocket');
};

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Received:', message);

  if (message.type === 'message') {
    console.log('New WhatsApp message:', message.data);
  }
};

// Send ping
ws.send(JSON.stringify({ type: 'ping' }));
```

## Rate Limiting

Currently, there are no rate limits enforced. This may be added in future versions.

## CORS

CORS is enabled by default for development. Configure allowed origins in `.env`:

```
ENABLE_CORS=true
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```
