package main

import (
	"context"
	"database/sql"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"math/rand"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"syscall"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"github.com/mdp/qrterminal"

	"bytes"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/proto/waCompanionReg"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/proto/waWa6"
	wastore "go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

// Message represents a chat message for our client
type Message struct {
	Time      time.Time
	Sender    string
	Content   string
	IsFromMe  bool
	MediaType string
	Filename  string
}

// SSE pub/sub: connected clients and broadcast
var (
	sseClients = make(map[chan []byte]struct{})
	sseMu      sync.Mutex
)

func broadcastEvent(eventType string, data map[string]interface{}) {
	payload, _ := json.Marshal(data)
	event := fmt.Sprintf("event: %s\ndata: %s\n\n", eventType, payload)
	sseMu.Lock()
	defer sseMu.Unlock()
	for ch := range sseClients {
		select {
		case ch <- []byte(event):
		default:
			// Client too slow, skip (non-blocking)
		}
	}
}

// --- LID <-> phone canonicalization ----------------------------------------
//
// WhatsApp addresses inbound 1:1 messages by the sender's LID (user@lid) rather
// than their phone number (user@s.whatsapp.net). Storing the raw @lid splits a
// contact's thread from their phone-keyed chat (where outbound history and the
// user's subscription live). We collapse LID -> phone so every path keys on one
// canonical JID. whatsmeow already keeps the mapping (it auto-populates
// whatsmeow_lid_map from SenderAlt in handleEncryptedMessage), so this is a thin
// resolver over client.Store.LIDs — no hand-built alias table.
//
// Groups (@g.us), broadcast and already-phone JIDs pass through UNCHANGED — only a
// 1:1 @lid chat key is rewritten (group carve-out). Contacts with no phone mapping
// (username-only) are tolerated as their raw @lid.

// lidPnNegCache remembers @lid users we've already failed to resolve, so we only
// hit the network (GetUserInfo) once per unmapped contact per process.
var (
	lidPnNegCache   = make(map[string]struct{})
	lidPnNegCacheMu sync.Mutex
)

// canonicalChatJID maps a 1:1 @lid chat JID to its phone JID when the mapping is
// known; groups/broadcast/phone JIDs and orphan LIDs are returned unchanged.
// altHint is SenderAlt (inbound) — the server-supplied phone of the chat party.
func canonicalChatJID(client *whatsmeow.Client, chat types.JID, altHint types.JID) types.JID {
	if chat.Server != types.HiddenUserServer {
		return chat // phone / group / broadcast — never rewrite
	}
	// 1. Trust the server-provided alt (already persisted by whatsmeow).
	if !altHint.IsEmpty() && altHint.Server == types.DefaultUserServer {
		return altHint.ToNonAD()
	}
	lid := chat.ToNonAD()
	// 2. Persistent LID->PN map.
	if pn, err := client.Store.LIDs.GetPNForLID(context.Background(), lid); err == nil && !pn.IsEmpty() {
		return pn.ToNonAD()
	}
	// 3. One-shot live backfill, negative-cached.
	lidPnNegCacheMu.Lock()
	_, tried := lidPnNegCache[lid.User]
	lidPnNegCacheMu.Unlock()
	if !tried {
		_, _ = client.GetUserInfo(context.Background(), []types.JID{lid})
		if pn, err := client.Store.LIDs.GetPNForLID(context.Background(), lid); err == nil && !pn.IsEmpty() {
			return pn.ToNonAD()
		}
		lidPnNegCacheMu.Lock()
		lidPnNegCache[lid.User] = struct{}{}
		lidPnNegCacheMu.Unlock()
	}
	// 4. Orphan / username-only contact — keep the raw @lid.
	return chat
}

// canonicalSenderUser resolves a message/receipt sender to its canonical phone
// user-part when the sender is a @lid and a mapping exists. Runs in 1:1 AND groups
// (so a group participant collapses to one identity). Returns the raw user-part for
// phone senders and orphan LIDs. User-part only (no server) to match the existing
// messages.sender column and get_sender_name's phone-substring lookup.
func canonicalSenderUser(client *whatsmeow.Client, sender types.JID, senderAlt types.JID) string {
	if sender.Server != types.HiddenUserServer {
		return sender.User
	}
	if !senderAlt.IsEmpty() && senderAlt.Server == types.DefaultUserServer {
		return senderAlt.User
	}
	if pn, err := client.Store.LIDs.GetPNForLID(context.Background(), sender.ToNonAD()); err == nil && !pn.IsEmpty() {
		return pn.User
	}
	return sender.User
}

// isOwnUser reports whether a bare user-part is one of our own identities (phone or
// LID) — used to filter self-receipts that may be addressed by either.
func isOwnUser(client *whatsmeow.Client, user string) bool {
	if user == "" {
		return false
	}
	if client.Store.ID != nil && user == client.Store.ID.User {
		return true
	}
	if !client.Store.LID.IsEmpty() && user == client.Store.LID.User {
		return true
	}
	return false
}

// resolveChatKey returns the canonical chat JID for an event's chat. It is the
// single insertion point for canonicalization (and, in the merge phase, lazy
// thread consolidation via maybeLazyMerge). store is threaded through for that
// merge trigger.
func resolveChatKey(client *whatsmeow.Client, store *MessageStore, chat types.JID, altHint types.JID) types.JID {
	canon := canonicalChatJID(client, chat, altHint)
	if chat.Server == types.HiddenUserServer && canon.Server == types.DefaultUserServer {
		maybeLazyMerge(client, store, chat.ToNonAD(), canon)
	}
	return canon
}

// --- Lazy per-contact thread consolidation ---------------------------------
//
// When a @lid chat first resolves to a phone JID, any history already stored under
// the raw @lid is merged onto the phone thread — once per contact per process. This
// is the whole of "backfill": no big-bang migration, only N small idempotent
// per-contact transactions triggered as contacts are seen. Take a DB backup before
// first deploy; every merge is logged so it's reconstructable from the LID<->PN map.
var (
	mergedContacts   = make(map[string]struct{})
	mergedContactsMu sync.Mutex
)

// maybeLazyMerge merges a contact's split @lid thread onto its phone thread at most
// once per process. Safe to call on every resolved event.
func maybeLazyMerge(client *whatsmeow.Client, store *MessageStore, lid, pn types.JID) {
	if store == nil {
		return
	}
	mergedContactsMu.Lock()
	if _, done := mergedContacts[lid.User]; done {
		mergedContactsMu.Unlock()
		return
	}
	mergedContacts[lid.User] = struct{}{}
	mergedContactsMu.Unlock()

	if err := mergeOneContact(store, lid, pn); err != nil {
		fmt.Printf("Warning: lazy LID merge %s -> %s failed: %v\n", lid.String(), pn.String(), err)
	}
}

// pickRealName prefers a human name (non-empty, containing a non-digit) over a raw
// number, preferring the first (phone-side) argument on ties.
func pickRealName(a, b string) string {
	real := func(s string) bool {
		if s == "" {
			return false
		}
		for _, c := range s {
			if c < '0' || c > '9' {
				return true
			}
		}
		return false
	}
	switch {
	case real(a):
		return a
	case real(b):
		return b
	case a != "":
		return a
	default:
		return b
	}
}

// mergeOneContact re-keys a single contact's @lid chat/messages/events/media onto
// its phone JID in one transaction. Idempotent: after success the @lid chat is gone,
// so re-running is a no-op. FK-safe ordering: create the phone chat parent before
// moving children; delete @lid children before the @lid chat row.
func mergeOneContact(store *MessageStore, lid, pn types.JID) error {
	lidStr, pnStr := lid.String(), pn.String()
	lidUser, pnUser := lid.User, pn.User

	// Cheap skip if there's nothing under the @lid key (already merged / never split).
	var lidRows int
	store.db.QueryRow(
		"SELECT (SELECT COUNT(*) FROM chats WHERE jid=?) + (SELECT COUNT(*) FROM messages WHERE chat_jid=?) + (SELECT COUNT(*) FROM events WHERE chat_jid=?)",
		lidStr, lidStr, lidStr,
	).Scan(&lidRows)
	if lidRows == 0 {
		return nil
	}

	// Read both chat rows to merge name + last_message_time.
	var lidName, pnName string
	var lidTime, pnTime time.Time
	store.db.QueryRow("SELECT name, last_message_time FROM chats WHERE jid=?", lidStr).Scan(&lidName, &lidTime)
	store.db.QueryRow("SELECT name, last_message_time FROM chats WHERE jid=?", pnStr).Scan(&pnName, &pnTime)
	mergedName := pickRealName(pnName, lidName)
	mergedTime := pnTime
	if lidTime.After(mergedTime) {
		mergedTime = lidTime
	}

	tx, err := store.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	// (A) Ensure the phone chats row exists (parent for the moved messages).
	if _, err := tx.Exec(
		`INSERT INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)
		 ON CONFLICT(jid) DO UPDATE SET name=excluded.name, last_message_time=excluded.last_message_time`,
		pnStr, mergedName, mergedTime,
	); err != nil {
		return err
	}

	// (B) Move @lid messages onto the phone key, rewriting the sender and keeping the
	// richer row on an (id, chat_jid) collision.
	if _, err := tx.Exec(
		`INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length)
		 SELECT id, ?, CASE WHEN sender=? THEN ? ELSE sender END, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length
		 FROM messages WHERE chat_jid=?
		 ON CONFLICT(id, chat_jid) DO UPDATE SET
		   content = CASE WHEN length(excluded.content) > length(messages.content) THEN excluded.content ELSE messages.content END,
		   media_type = COALESCE(NULLIF(messages.media_type,''), NULLIF(excluded.media_type,''), messages.media_type),
		   media_key = COALESCE(messages.media_key, excluded.media_key),
		   filename = COALESCE(NULLIF(messages.filename,''), excluded.filename),
		   url = COALESCE(NULLIF(messages.url,''), excluded.url),
		   file_sha256 = COALESCE(messages.file_sha256, excluded.file_sha256),
		   file_enc_sha256 = COALESCE(messages.file_enc_sha256, excluded.file_enc_sha256),
		   file_length = CASE WHEN messages.file_length>0 THEN messages.file_length ELSE excluded.file_length END`,
		pnStr, lidUser, pnUser, lidStr,
	); err != nil {
		return err
	}

	// (C) Normalize this contact's sender everywhere (incl. group-participant rows).
	if _, err := tx.Exec("UPDATE messages SET sender=? WHERE sender=?", pnUser, lidUser); err != nil {
		return err
	}

	// (D) Drop the old @lid messages (before the @lid chat row, FK-safe).
	if _, err := tx.Exec("DELETE FROM messages WHERE chat_jid=?", lidStr); err != nil {
		return err
	}

	// (E) Re-point events + normalize their sender (events has no FK/PK on chat_jid).
	if _, err := tx.Exec("UPDATE events SET chat_jid=? WHERE chat_jid=?", pnStr, lidStr); err != nil {
		return err
	}
	if _, err := tx.Exec("UPDATE events SET sender=? WHERE sender=?", pnUser, lidUser); err != nil {
		return err
	}

	// Finally drop the now-childless @lid chat row.
	if _, err := tx.Exec("DELETE FROM chats WHERE jid=?", lidStr); err != nil {
		return err
	}

	if err := tx.Commit(); err != nil {
		return err
	}

	// Move already-downloaded media from the @lid dir onto the phone dir (idempotent,
	// no-clobber). downloadMedia also falls back to the @lid dir, so this is best-effort.
	moveMediaDir(lidStr, pnStr)

	fmt.Printf("LID MERGE: consolidated %s -> %s\n", lidStr, pnStr)
	return nil
}

// moveMediaDir moves already-downloaded media from the @lid chat dir onto the phone
// chat dir without clobbering (keeps any existing file, e.g. a view-once original).
func moveMediaDir(lidStr, pnStr string) {
	src := "store/" + strings.ReplaceAll(lidStr, ":", "_")
	dst := "store/" + strings.ReplaceAll(pnStr, ":", "_")
	entries, err := os.ReadDir(src)
	if err != nil {
		return
	}
	os.MkdirAll(dst, 0755)
	for _, e := range entries {
		d := filepath.Join(dst, e.Name())
		if _, err := os.Stat(d); err == nil {
			continue
		}
		os.Rename(filepath.Join(src, e.Name()), d)
	}
	if remaining, _ := os.ReadDir(src); len(remaining) == 0 {
		os.Remove(src)
	}
}

// Database handler for storing message history
type MessageStore struct {
	db *sql.DB
}

// Initialize message store
func NewMessageStore() (*MessageStore, error) {
	// Create directory for database if it doesn't exist
	if err := os.MkdirAll("store", 0755); err != nil {
		return nil, fmt.Errorf("failed to create store directory: %v", err)
	}

	// Open SQLite database for messages. busy_timeout lets concurrent writers wait for
	// a lock (e.g. while a per-contact merge transaction runs) instead of erroring with
	// SQLITE_BUSY.
	db, err := sql.Open("sqlite3", "file:store/messages.db?_foreign_keys=on&_busy_timeout=5000")
	if err != nil {
		return nil, fmt.Errorf("failed to open message database: %v", err)
	}

	// Create tables if they don't exist
	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS chats (
			jid TEXT PRIMARY KEY,
			name TEXT,
			last_message_time TIMESTAMP
		);
		
		CREATE TABLE IF NOT EXISTS messages (
			id TEXT,
			chat_jid TEXT,
			sender TEXT,
			content TEXT,
			timestamp TIMESTAMP,
			is_from_me BOOLEAN,
			media_type TEXT,
			filename TEXT,
			url TEXT,
			media_key BLOB,
			file_sha256 BLOB,
			file_enc_sha256 BLOB,
			file_length INTEGER,
			PRIMARY KEY (id, chat_jid),
			FOREIGN KEY (chat_jid) REFERENCES chats(jid)
		);

		CREATE TABLE IF NOT EXISTS events (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			chat_jid TEXT NOT NULL,
			event_type TEXT NOT NULL,
			sender TEXT,
			timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			data TEXT
		);

		-- Poll option names keyed by the poll's message ID. whatsmeow stores the
		-- message secret on send (so votes decrypt), but a vote only carries SHA256
		-- hashes of the chosen options; we keep the names here to reverse them.
		CREATE TABLE IF NOT EXISTS poll_options (
			poll_id TEXT PRIMARY KEY,
			chat_jid TEXT,
			options TEXT
		);
	`)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to create tables: %v", err)
	}

	return &MessageStore{db: db}, nil
}

// Close the database connection
func (store *MessageStore) Close() error {
	return store.db.Close()
}

// Store a chat in the database. Upsert (not INSERT OR REPLACE) so a call with an
// empty name — e.g. the write-back after an outbound send — never wipes an existing
// real name.
func (store *MessageStore) StoreChat(jid, name string, lastMessageTime time.Time) error {
	_, err := store.db.Exec(
		`INSERT INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)
		 ON CONFLICT(jid) DO UPDATE SET
		   last_message_time=excluded.last_message_time,
		   name=CASE WHEN excluded.name != '' THEN excluded.name ELSE chats.name END`,
		jid, name, lastMessageTime,
	)
	return err
}

// Store a message in the database
func (store *MessageStore) StoreMessage(id, chatJID, sender, content string, timestamp time.Time, isFromMe bool,
	mediaType, filename, url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64) error {
	// Only store if there's actual content or media
	if content == "" && mediaType == "" {
		return nil
	}

	_, err := store.db.Exec(
		`INSERT OR REPLACE INTO messages 
		(id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length) 
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		id, chatJID, sender, content, timestamp, isFromMe, mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength,
	)
	return err
}

// Get messages from a chat
func (store *MessageStore) GetMessages(chatJID string, limit int) ([]Message, error) {
	rows, err := store.db.Query(
		"SELECT sender, content, timestamp, is_from_me, media_type, filename FROM messages WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT ?",
		chatJID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var messages []Message
	for rows.Next() {
		var msg Message
		var timestamp time.Time
		err := rows.Scan(&msg.Sender, &msg.Content, &timestamp, &msg.IsFromMe, &msg.MediaType, &msg.Filename)
		if err != nil {
			return nil, err
		}
		msg.Time = timestamp
		messages = append(messages, msg)
	}

	return messages, nil
}

// Get all chats
func (store *MessageStore) GetChats() (map[string]time.Time, error) {
	rows, err := store.db.Query("SELECT jid, last_message_time FROM chats ORDER BY last_message_time DESC")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	chats := make(map[string]time.Time)
	for rows.Next() {
		var jid string
		var lastMessageTime time.Time
		err := rows.Scan(&jid, &lastMessageTime)
		if err != nil {
			return nil, err
		}
		chats[jid] = lastMessageTime
	}

	return chats, nil
}

// Extract text content from a message
func extractTextContent(msg *waProto.Message) string {
	if msg == nil {
		return ""
	}

	// Try to get text content
	if text := msg.GetConversation(); text != "" {
		return text
	} else if extendedText := msg.GetExtendedTextMessage(); extendedText != nil {
		return extendedText.GetText()
	}

	// For now, we're ignoring non-text messages
	return ""
}

// SendMessageResponse represents the response for the send message API
type SendMessageResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

// SendMessageRequest represents the request body for the send message API
type SendMessageRequest struct {
	Recipient string `json:"recipient"`
	Message   string `json:"message"`
	MediaPath string `json:"media_path,omitempty"`
}

// PollRequest is the request body for the /api/poll endpoint.
type PollRequest struct {
	Recipient       string   `json:"recipient"`
	Name            string   `json:"name"`    // the poll question
	Options         []string `json:"options"` // 2–12 answer options
	SelectableCount int      `json:"selectable_count,omitempty"`
}

// Function to send a WhatsApp message
func sendWhatsAppMessage(client *whatsmeow.Client, messageStore *MessageStore, recipient string, message string, mediaPath string) (bool, string) {
	if !client.IsConnected() {
		return false, "Not connected to WhatsApp"
	}

	// Create JID for recipient
	var recipientJID types.JID
	var err error

	// Check if recipient is a JID
	isJID := strings.Contains(recipient, "@")

	if isJID {
		// Parse the JID string
		recipientJID, err = types.ParseJID(recipient)
		if err != nil {
			return false, fmt.Sprintf("Error parsing JID: %v", err)
		}
	} else {
		// Create JID from phone number
		recipientJID = types.JID{
			User:   recipient,
			Server: "s.whatsapp.net", // For personal chats
		}
	}

	msg := &waProto.Message{}

	// Check if we have media to send
	if mediaPath != "" {
		// Read media file
		mediaData, err := os.ReadFile(mediaPath)
		if err != nil {
			return false, fmt.Sprintf("Error reading media file: %v", err)
		}

		// Determine media type and mime type based on file extension
		fileExt := strings.ToLower(mediaPath[strings.LastIndex(mediaPath, ".")+1:])
		var mediaType whatsmeow.MediaType
		var mimeType string

		// Handle different media types
		switch fileExt {
		// Image types
		case "jpg", "jpeg":
			mediaType = whatsmeow.MediaImage
			mimeType = "image/jpeg"
		case "png":
			mediaType = whatsmeow.MediaImage
			mimeType = "image/png"
		case "gif":
			mediaType = whatsmeow.MediaImage
			mimeType = "image/gif"
		case "webp":
			mediaType = whatsmeow.MediaImage
			mimeType = "image/webp"

		// Audio types
		case "ogg":
			mediaType = whatsmeow.MediaAudio
			mimeType = "audio/ogg; codecs=opus"

		// Video types
		case "mp4":
			mediaType = whatsmeow.MediaVideo
			mimeType = "video/mp4"
		case "avi":
			mediaType = whatsmeow.MediaVideo
			mimeType = "video/avi"
		case "mov":
			mediaType = whatsmeow.MediaVideo
			mimeType = "video/quicktime"

		// Document types (for any other file type)
		default:
			mediaType = whatsmeow.MediaDocument
			mimeType = "application/octet-stream"
		}

		// Upload media to WhatsApp servers
		resp, err := client.Upload(context.Background(), mediaData, mediaType)
		if err != nil {
			return false, fmt.Sprintf("Error uploading media: %v", err)
		}

		fmt.Println("Media uploaded", resp)

		// Create the appropriate message type based on media type
		switch mediaType {
		case whatsmeow.MediaImage:
			msg.ImageMessage = &waProto.ImageMessage{
				Caption:       proto.String(message),
				Mimetype:      proto.String(mimeType),
				URL:           &resp.URL,
				DirectPath:    &resp.DirectPath,
				MediaKey:      resp.MediaKey,
				FileEncSHA256: resp.FileEncSHA256,
				FileSHA256:    resp.FileSHA256,
				FileLength:    &resp.FileLength,
			}
		case whatsmeow.MediaAudio:
			// Handle ogg audio files
			var seconds uint32 = 30 // Default fallback
			var waveform []byte = nil

			// Try to analyze the ogg file
			if strings.Contains(mimeType, "ogg") {
				analyzedSeconds, analyzedWaveform, err := analyzeOggOpus(mediaData)
				if err == nil {
					seconds = analyzedSeconds
					waveform = analyzedWaveform
				} else {
					return false, fmt.Sprintf("Failed to analyze Ogg Opus file: %v", err)
				}
			} else {
				fmt.Printf("Not an Ogg Opus file: %s\n", mimeType)
			}

			msg.AudioMessage = &waProto.AudioMessage{
				Mimetype:      proto.String(mimeType),
				URL:           &resp.URL,
				DirectPath:    &resp.DirectPath,
				MediaKey:      resp.MediaKey,
				FileEncSHA256: resp.FileEncSHA256,
				FileSHA256:    resp.FileSHA256,
				FileLength:    &resp.FileLength,
				Seconds:       proto.Uint32(seconds),
				PTT:           proto.Bool(true),
				Waveform:      waveform,
			}
		case whatsmeow.MediaVideo:
			msg.VideoMessage = &waProto.VideoMessage{
				Caption:       proto.String(message),
				Mimetype:      proto.String(mimeType),
				URL:           &resp.URL,
				DirectPath:    &resp.DirectPath,
				MediaKey:      resp.MediaKey,
				FileEncSHA256: resp.FileEncSHA256,
				FileSHA256:    resp.FileSHA256,
				FileLength:    &resp.FileLength,
			}
		case whatsmeow.MediaDocument:
			msg.DocumentMessage = &waProto.DocumentMessage{
				Title:         proto.String(mediaPath[strings.LastIndex(mediaPath, "/")+1:]),
				Caption:       proto.String(message),
				Mimetype:      proto.String(mimeType),
				URL:           &resp.URL,
				DirectPath:    &resp.DirectPath,
				MediaKey:      resp.MediaKey,
				FileEncSHA256: resp.FileEncSHA256,
				FileSHA256:    resp.FileSHA256,
				FileLength:    &resp.FileLength,
			}
		}
	} else {
		msg.Conversation = proto.String(message)
	}

	// Send message
	resp, err := client.SendMessage(context.Background(), recipientJID, msg)

	if err != nil {
		return false, fmt.Sprintf("Error sending message: %v", err)
	}

	// Store sent message in DB immediately (echo from WhatsApp is unreliable).
	// Canonicalize the recipient so outbound history keys on the same thread inbound
	// replies land on (we still SendMessage to the original recipientJID above).
	if messageStore != nil {
		chatJID := resolveChatKey(client, messageStore, recipientJID, types.EmptyJID).String()
		sender := ""
		if client.Store.ID != nil {
			sender = client.Store.ID.User
		}

		mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := extractMediaInfo(msg)

		storeErr := messageStore.StoreMessage(
			resp.ID,
			chatJID,
			sender,
			message,
			resp.Timestamp,
			true, // is_from_me
			mediaType,
			filename,
			url,
			mediaKey,
			fileSHA256,
			fileEncSHA256,
			fileLength,
		)
		if storeErr != nil {
			fmt.Printf("Warning: failed to store sent message: %v\n", storeErr)
		}

		// Update chat's last message time
		messageStore.StoreChat(chatJID, "", resp.Timestamp)
	}

	return true, fmt.Sprintf("Message sent to %s", recipient)
}

// parseRecipientJID converts a recipient string (JID/LID or bare phone) to a JID.
func parseRecipientJID(recipient string) (types.JID, error) {
	if strings.Contains(recipient, "@") {
		return types.ParseJID(recipient)
	}
	return types.JID{User: recipient, Server: "s.whatsapp.net"}, nil
}

// revokeMessage unsends (deletes for everyone) one of our own messages.
func revokeMessage(client *whatsmeow.Client, store *MessageStore, recipient, messageID string) (bool, string) {
	if !client.IsConnected() {
		return false, "Not connected to WhatsApp"
	}
	if client.Store.ID == nil {
		return false, "Not logged in"
	}
	chatJID, err := parseRecipientJID(recipient)
	if err != nil {
		return false, fmt.Sprintf("Error parsing JID: %v", err)
	}
	// Empty sender = revoke our own message.
	revoke := client.BuildRevoke(chatJID, types.EmptyJID, types.MessageID(messageID))
	if _, err := client.SendMessage(context.Background(), chatJID, revoke); err != nil {
		return false, fmt.Sprintf("Error unsending message: %v", err)
	}
	if store != nil {
		store.db.Exec("DELETE FROM messages WHERE id = ? AND chat_jid = ?", messageID, chatJID.String())
	}
	return true, "Message unsent"
}

// editMessage edits the text of one of our own messages.
func editMessage(client *whatsmeow.Client, store *MessageStore, recipient, messageID, newText string) (bool, string) {
	if !client.IsConnected() {
		return false, "Not connected to WhatsApp"
	}
	chatJID, err := parseRecipientJID(recipient)
	if err != nil {
		return false, fmt.Sprintf("Error parsing JID: %v", err)
	}
	edited := client.BuildEdit(chatJID, types.MessageID(messageID), &waProto.Message{
		Conversation: proto.String(newText),
	})
	if _, err := client.SendMessage(context.Background(), chatJID, edited); err != nil {
		return false, fmt.Sprintf("Error editing message: %v", err)
	}
	if store != nil {
		store.db.Exec("UPDATE messages SET content = ? WHERE id = ? AND chat_jid = ?", newText, messageID, chatJID.String())
	}
	return true, "Message edited"
}

// reactToMessage sends an emoji reaction to a message (empty reaction removes it).
func reactToMessage(client *whatsmeow.Client, store *MessageStore, recipient, messageID, reaction string) (bool, string) {
	if !client.IsConnected() {
		return false, "Not connected to WhatsApp"
	}
	chatJID, err := parseRecipientJID(recipient)
	if err != nil {
		return false, fmt.Sprintf("Error parsing JID: %v", err)
	}
	// Target message sender: us for our own messages; otherwise the other party,
	// which in a direct chat is the chat JID itself.
	senderJID := chatJID
	if store != nil {
		var isFromMe bool
		if err := store.db.QueryRow(
			"SELECT is_from_me FROM messages WHERE id = ? AND chat_jid = ?", messageID, chatJID.String(),
		).Scan(&isFromMe); err == nil && isFromMe && client.Store.ID != nil {
			senderJID = *client.Store.ID
		}
	}
	react := client.BuildReaction(chatJID, senderJID, types.MessageID(messageID), reaction)
	if _, err := client.SendMessage(context.Background(), chatJID, react); err != nil {
		return false, fmt.Sprintf("Error reacting: %v", err)
	}
	return true, "Reaction sent"
}

// Extract media info from a message
func extractMediaInfo(msg *waProto.Message) (mediaType string, filename string, url string, mediaKey []byte, fileSHA256 []byte, fileEncSHA256 []byte, fileLength uint64) {
	if msg == nil {
		return "", "", "", nil, nil, nil, 0
	}

	// Check for image message
	if img := msg.GetImageMessage(); img != nil {
		return "image", "image_" + time.Now().Format("20060102_150405") + ".jpg",
			img.GetURL(), img.GetMediaKey(), img.GetFileSHA256(), img.GetFileEncSHA256(), img.GetFileLength()
	}

	// Check for video message
	if vid := msg.GetVideoMessage(); vid != nil {
		return "video", "video_" + time.Now().Format("20060102_150405") + ".mp4",
			vid.GetURL(), vid.GetMediaKey(), vid.GetFileSHA256(), vid.GetFileEncSHA256(), vid.GetFileLength()
	}

	// Check for audio message
	if aud := msg.GetAudioMessage(); aud != nil {
		return "audio", "audio_" + time.Now().Format("20060102_150405") + ".ogg",
			aud.GetURL(), aud.GetMediaKey(), aud.GetFileSHA256(), aud.GetFileEncSHA256(), aud.GetFileLength()
	}

	// Check for document message
	if doc := msg.GetDocumentMessage(); doc != nil {
		filename := doc.GetFileName()
		if filename == "" {
			filename = "document_" + time.Now().Format("20060102_150405")
		}
		return "document", filename,
			doc.GetURL(), doc.GetMediaKey(), doc.GetFileSHA256(), doc.GetFileEncSHA256(), doc.GetFileLength()
	}

	return "", "", "", nil, nil, nil, 0
}

// Handle regular incoming messages with media support
func handleMessage(client *whatsmeow.Client, messageStore *MessageStore, msg *events.Message, logger waLog.Logger) {
	// Save message to database. Canonicalize a LID-addressed 1:1 chat to its phone JID
	// (and lazily merge any pre-existing @lid thread) so inbound lands on the same
	// thread as outbound history and phone-keyed subscriptions.
	canonChat := resolveChatKey(client, messageStore, msg.Info.Chat, msg.Info.SenderAlt)
	chatJID := canonChat.String()
	sender := canonicalSenderUser(client, msg.Info.Sender, msg.Info.SenderAlt)

	// Get appropriate chat name (pass nil for conversation since we don't have one for regular messages)
	name := GetChatName(client, messageStore, canonChat, chatJID, nil, sender, logger)

	// Update chat in database with the message timestamp (keeps last message time updated)
	err := messageStore.StoreChat(chatJID, name, msg.Info.Timestamp)
	if err != nil {
		logger.Warnf("Failed to store chat: %v", err)
	}

	// Extract text content
	content := extractTextContent(msg.Message)

	// Extract media info
	mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := extractMediaInfo(msg.Message)

	// Surface incoming reactions as a distinct event (they carry no text/media).
	if react := msg.Message.GetReactionMessage(); react != nil {
		broadcastEvent("reaction", map[string]interface{}{
			"chat_jid":          chatJID,
			"sender":            sender,
			"sender_name":       name,
			"reaction":          react.GetText(),
			"target_message_id": react.GetKey().GetID(),
			"timestamp":         msg.Info.Timestamp.Format(time.RFC3339),
			"is_from_me":        msg.Info.IsFromMe,
		})
		return
	}

	// Surface poll votes as their own event (they carry no text/media, only
	// encrypted option hashes). Store options on creation so votes resolve to names.
	if create := msg.Message.GetPollCreationMessage(); create != nil {
		names := make([]string, len(create.GetOptions()))
		for i, opt := range create.GetOptions() {
			names[i] = opt.GetOptionName()
		}
		if err := messageStore.StorePollOptions(msg.Info.ID, chatJID, names); err != nil {
			logger.Warnf("Failed to store poll options for %s: %v", msg.Info.ID, err)
		}
		return
	}
	if handlePollVote(client, messageStore, msg, chatJID, sender, name, logger) {
		return
	}

	// Skip if there's no content and no media
	if content == "" && mediaType == "" {
		return
	}

	// Store message in database
	err = messageStore.StoreMessage(
		msg.Info.ID,
		chatJID,
		sender,
		content,
		msg.Info.Timestamp,
		msg.Info.IsFromMe,
		mediaType,
		filename,
		url,
		mediaKey,
		fileSHA256,
		fileEncSHA256,
		fileLength,
	)

	if err != nil {
		logger.Warnf("Failed to store message: %v", err)
	} else {
		// Log message reception
		timestamp := msg.Info.Timestamp.Format("2006-01-02 15:04:05")
		direction := "←"
		if msg.Info.IsFromMe {
			direction = "→"
		}

		// Log based on message type
		if mediaType != "" {
			fmt.Printf("[%s] %s %s: [%s: %s] %s\n", timestamp, direction, sender, mediaType, filename, content)
		} else if content != "" {
			fmt.Printf("[%s] %s %s: %s\n", timestamp, direction, sender, content)
		}

		// Broadcast to SSE subscribers. whatsmeow auto-unwraps view-once into
		// msg.Message and sets IsViewOnce, so the media above is already captured;
		// we just flag it so the channel/persona knows it was a disappearing message.
		broadcastEvent("message", map[string]interface{}{
			"chat_jid":    chatJID,
			"sender":      sender,
			"sender_name": name,
			"content":     content,
			"message_id":  msg.Info.ID,
			"timestamp":   msg.Info.Timestamp.Format(time.RFC3339),
			"is_from_me":  msg.Info.IsFromMe,
			"media_type":  mediaType,
			"filename":    filename,
			"view_once":   msg.IsViewOnce,
			// StanzaID of a quoted message when this is a quote-reply (else ""),
			// so the operator-ask flow can route a quoted "answer:" to its question.
			"quoted_message_id": msg.Message.GetExtendedTextMessage().GetContextInfo().GetStanzaID(),
		})
	}
}

// handleUndecryptable surfaces a message that arrived encrypted-but-undecryptable
// (commonly a view-once whose Signal session wasn't ready, or a socket drop). We
// can't read its content yet, but whatsmeow is re-requesting it from the phone; if
// it redelivers it flows through handleMessage as the real media. Meanwhile we emit
// a "pending" placeholder so the persona knows a (view-once) photo just arrived and
// can react instead of going silent. We do NOT store it (no real content) — only
// broadcast.
func handleUndecryptable(client *whatsmeow.Client, messageStore *MessageStore, v *events.UndecryptableMessage, logger waLog.Logger) {
	canonChat := resolveChatKey(client, messageStore, v.Info.Chat, v.Info.SenderAlt)
	chatJID := canonChat.String()
	if chatJID == "status@broadcast" {
		return
	}
	sender := canonicalSenderUser(client, v.Info.Sender, v.Info.SenderAlt)
	name := GetChatName(client, messageStore, canonChat, chatJID, nil, sender, logger)
	isViewOnce := string(v.UnavailableType) == "view_once"

	broadcastEvent("message", map[string]interface{}{
		"chat_jid":      chatJID,
		"sender":        sender,
		"sender_name":   name,
		"content":       "",
		"message_id":    v.Info.ID,
		"timestamp":     v.Info.Timestamp.Format(time.RFC3339),
		"is_from_me":    v.Info.IsFromMe,
		"media_type":    "", // unknown until decrypted
		"filename":      "",
		"view_once":     isViewOnce,
		"undecryptable": true,
	})
}

// DownloadMediaRequest represents the request body for the download media API
type DownloadMediaRequest struct {
	MessageID string `json:"message_id"`
	ChatJID   string `json:"chat_jid"`
}

// RerequestRequest asks our primary phone to re-deliver a message that reached
// this companion without an <enc> payload (e.g. a view-once fanout placeholder).
// The phone still holds the plaintext for as long as the message is unopened
// there, so this is the only route to content the server withheld from us.
type RerequestRequest struct {
	ChatJID   string `json:"chat_jid"`
	SenderJID string `json:"sender_jid,omitempty"`
	MessageID string `json:"message_id"`
	Mode      string `json:"mode,omitempty"`
	Count     int    `json:"count,omitempty"`
	Timestamp int64  `json:"timestamp,omitempty"`
}

// RevokeRequest unsends (deletes for everyone) one of our own messages.
type RevokeRequest struct {
	ChatJID   string `json:"chat_jid"`
	MessageID string `json:"message_id"`
}

// EditRequest edits the text of one of our own messages.
type EditRequest struct {
	ChatJID   string `json:"chat_jid"`
	MessageID string `json:"message_id"`
	Message   string `json:"message"`
}

// ReactRequest reacts to a message (empty reaction removes it).
type ReactRequest struct {
	ChatJID   string `json:"chat_jid"`
	MessageID string `json:"message_id"`
	Reaction  string `json:"reaction"`
}

// MessageIDsRequest lists our OWN recent messages (id + text) so the caller can
// pick a message_id for unsend/edit. Optional substring filter to pin one.
type MessageIDsRequest struct {
	ChatJID string `json:"chat_jid"`
	Filter  string `json:"filter,omitempty"`
	Limit   int    `json:"limit,omitempty"`
}

// DownloadMediaResponse represents the response for the download media API
type DownloadMediaResponse struct {
	Success  bool   `json:"success"`
	Message  string `json:"message"`
	Filename string `json:"filename,omitempty"`
	Path     string `json:"path,omitempty"`
}

// Store additional media info in the database
func (store *MessageStore) StoreMediaInfo(id, chatJID, url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64) error {
	_, err := store.db.Exec(
		"UPDATE messages SET url = ?, media_key = ?, file_sha256 = ?, file_enc_sha256 = ?, file_length = ? WHERE id = ? AND chat_jid = ?",
		url, mediaKey, fileSHA256, fileEncSHA256, fileLength, id, chatJID,
	)
	return err
}

// Get media info from the database
func (store *MessageStore) GetMediaInfo(id, chatJID string) (string, string, string, []byte, []byte, []byte, uint64, error) {
	var mediaType, filename, url string
	var mediaKey, fileSHA256, fileEncSHA256 []byte
	var fileLength uint64

	err := store.db.QueryRow(
		"SELECT media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length FROM messages WHERE id = ? AND chat_jid = ?",
		id, chatJID,
	).Scan(&mediaType, &filename, &url, &mediaKey, &fileSHA256, &fileEncSHA256, &fileLength)

	return mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength, err
}

// MediaDownloader implements the whatsmeow.DownloadableMessage interface
type MediaDownloader struct {
	URL           string
	DirectPath    string
	MediaKey      []byte
	FileLength    uint64
	FileSHA256    []byte
	FileEncSHA256 []byte
	MediaType     whatsmeow.MediaType
}

// GetDirectPath implements the DownloadableMessage interface
func (d *MediaDownloader) GetDirectPath() string {
	return d.DirectPath
}

// GetURL implements the DownloadableMessage interface
func (d *MediaDownloader) GetURL() string {
	return d.URL
}

// GetMediaKey implements the DownloadableMessage interface
func (d *MediaDownloader) GetMediaKey() []byte {
	return d.MediaKey
}

// GetFileLength implements the DownloadableMessage interface
func (d *MediaDownloader) GetFileLength() uint64 {
	return d.FileLength
}

// GetFileSHA256 implements the DownloadableMessage interface
func (d *MediaDownloader) GetFileSHA256() []byte {
	return d.FileSHA256
}

// GetFileEncSHA256 implements the DownloadableMessage interface
func (d *MediaDownloader) GetFileEncSHA256() []byte {
	return d.FileEncSHA256
}

// GetMediaType implements the DownloadableMessage interface
func (d *MediaDownloader) GetMediaType() whatsmeow.MediaType {
	return d.MediaType
}

// Function to download media from a message
func downloadMedia(client *whatsmeow.Client, messageStore *MessageStore, messageID, chatJID string) (bool, string, string, string, error) {
	// Query the database for the message
	var mediaType, filename, url string
	var mediaKey, fileSHA256, fileEncSHA256 []byte
	var fileLength uint64
	var err error

	// First, check if we already have this file
	chatDir := fmt.Sprintf("store/%s", strings.ReplaceAll(chatJID, ":", "_"))
	localPath := ""

	// Get media info from the database
	mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength, err = messageStore.GetMediaInfo(messageID, chatJID)

	if err != nil {
		// Try to get basic info if extended info isn't available
		err = messageStore.db.QueryRow(
			"SELECT media_type, filename FROM messages WHERE id = ? AND chat_jid = ?",
			messageID, chatJID,
		).Scan(&mediaType, &filename)

		if err != nil {
			return false, "", "", "", fmt.Errorf("failed to find message: %v", err)
		}
	}

	// Check if this is a media message
	if mediaType == "" {
		return false, "", "", "", fmt.Errorf("not a media message")
	}

	// Create directory for the chat if it doesn't exist
	if err := os.MkdirAll(chatDir, 0755); err != nil {
		return false, "", "", "", fmt.Errorf("failed to create chat directory: %v", err)
	}

	// Generate a local path for the file, using messageID to ensure uniqueness
	// (multiple audio messages synced in the same second get the same filename)
	localPath = fmt.Sprintf("%s/%s_%s", chatDir, messageID, filename)

	// Get absolute path
	absPath, err := filepath.Abs(localPath)
	if err != nil {
		return false, "", "", "", fmt.Errorf("failed to get absolute path: %v", err)
	}

	// Check if file already exists
	if _, err := os.Stat(localPath); err == nil {
		// File exists, return it
		return true, mediaType, filename, absPath, nil
	}

	// Fall back to the pre-consolidation @lid media dir: media downloaded before the
	// LID->phone merge lives under store/<lid>@lid/. Trying it avoids a re-download with
	// now-expired keys (and irreplaceable view-once media). Makes the merge's dir-move
	// non-load-bearing.
	if pnJID, perr := types.ParseJID(chatJID); perr == nil && pnJID.Server == types.DefaultUserServer {
		if lidJID, lerr := client.Store.LIDs.GetLIDForPN(context.Background(), pnJID); lerr == nil && !lidJID.IsEmpty() {
			altDir := fmt.Sprintf("store/%s", strings.ReplaceAll(lidJID.ToNonAD().String(), ":", "_"))
			altPath := fmt.Sprintf("%s/%s_%s", altDir, messageID, filename)
			if _, err := os.Stat(altPath); err == nil {
				if absAlt, aerr := filepath.Abs(altPath); aerr == nil {
					return true, mediaType, filename, absAlt, nil
				}
			}
		}
	}

	// If we don't have all the media info we need, we can't download
	if url == "" || len(mediaKey) == 0 || len(fileSHA256) == 0 || len(fileEncSHA256) == 0 || fileLength == 0 {
		return false, "", "", "", fmt.Errorf("incomplete media information for download")
	}

	fmt.Printf("Attempting to download media for message %s in chat %s...\n", messageID, chatJID)

	// Extract direct path from URL
	directPath := extractDirectPathFromURL(url)

	// Create a downloader that implements DownloadableMessage
	var waMediaType whatsmeow.MediaType
	switch mediaType {
	case "image":
		waMediaType = whatsmeow.MediaImage
	case "video":
		waMediaType = whatsmeow.MediaVideo
	case "audio":
		waMediaType = whatsmeow.MediaAudio
	case "document":
		waMediaType = whatsmeow.MediaDocument
	default:
		return false, "", "", "", fmt.Errorf("unsupported media type: %s", mediaType)
	}

	downloader := &MediaDownloader{
		URL:           url,
		DirectPath:    directPath,
		MediaKey:      mediaKey,
		FileLength:    fileLength,
		FileSHA256:    fileSHA256,
		FileEncSHA256: fileEncSHA256,
		MediaType:     waMediaType,
	}

	// Download the media using whatsmeow client
	mediaData, err := client.Download(context.Background(), downloader)
	if err != nil {
		return false, "", "", "", fmt.Errorf("failed to download media: %v", err)
	}

	// Save the downloaded media to file
	if err := os.WriteFile(localPath, mediaData, 0644); err != nil {
		return false, "", "", "", fmt.Errorf("failed to save media file: %v", err)
	}

	fmt.Printf("Successfully downloaded %s media to %s (%d bytes)\n", mediaType, absPath, len(mediaData))
	return true, mediaType, filename, absPath, nil
}

// Extract direct path from a WhatsApp media URL
func extractDirectPathFromURL(url string) string {
	// The direct path is typically in the URL, we need to extract it
	// Example URL: https://mmg.whatsapp.net/v/t62.7118-24/13812002_698058036224062_3424455886509161511_n.enc?ccb=11-4&oh=...

	// Find the path part after the domain
	parts := strings.SplitN(url, ".net/", 2)
	if len(parts) < 2 {
		return url // Return original URL if parsing fails
	}

	pathPart := parts[1]

	// Keep the query string. whatsmeow's DownloadMediaWithPath appends "&hash=...&mms-type=..."
	// directly onto this path, so it must arrive already carrying its "?ccb=&oh=&oe=" signature.
	// Stripping it produced an unsigned URL and the CDN answered 403 for every download.

	// Create proper direct path format
	return "/" + pathPart
}

// Start a REST API server to expose the WhatsApp client functionality
func digitsOnly(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r >= '0' && r <= '9' {
			b.WriteRune(r)
		}
	}
	return b.String()
}

// recipientAllowed enforces an OPT-IN send allowlist (defense in depth). When
// WHATSAPP_ALLOWED_RECIPIENTS is empty (the default), every recipient is allowed —
// raw JIDs/LIDs/phone numbers all work exactly as before. When set, the recipient's
// digits must match a listed entry (entries may be JIDs or phone numbers).
func recipientAllowed(recipient string) bool {
	allow := strings.TrimSpace(os.Getenv("WHATSAPP_ALLOWED_RECIPIENTS"))
	if allow == "" {
		return true
	}
	want := digitsOnly(recipient)
	for _, entry := range strings.Split(allow, ",") {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		if entry == recipient || (want != "" && digitsOnly(entry) == want) {
			return true
		}
	}
	return false
}

func startRESTServer(client *whatsmeow.Client, messageStore *MessageStore, port int) {
	// Handler for sending messages
	http.HandleFunc("/api/send", func(w http.ResponseWriter, r *http.Request) {
		// Only allow POST requests
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		// Parse the request body
		var req SendMessageRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}

		// Validate request
		if req.Recipient == "" {
			http.Error(w, "Recipient is required", http.StatusBadRequest)
			return
		}

		if req.Message == "" && req.MediaPath == "" {
			http.Error(w, "Message or media path is required", http.StatusBadRequest)
			return
		}

		// Opt-in send allowlist (no-op unless WHATSAPP_ALLOWED_RECIPIENTS is set).
		if !recipientAllowed(req.Recipient) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(SendMessageResponse{
				Success: false,
				Message: "recipient not in WHATSAPP_ALLOWED_RECIPIENTS",
			})
			return
		}

		fmt.Println("Received request to send message", req.Message, req.MediaPath)

		// Send the message
		success, message := sendWhatsAppMessage(client, messageStore, req.Recipient, req.Message, req.MediaPath)
		fmt.Println("Message sent", success, message)
		// Set response headers
		w.Header().Set("Content-Type", "application/json")

		// Set appropriate status code
		if !success {
			w.WriteHeader(http.StatusInternalServerError)
		}

		// Send response
		json.NewEncoder(w).Encode(SendMessageResponse{
			Success: success,
			Message: message,
		})
	})

	// Handler for sending a poll (a question with tappable options)
	http.HandleFunc("/api/poll", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req PollRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}
		if req.Recipient == "" || req.Name == "" || len(req.Options) < 2 {
			http.Error(w, "recipient, name and at least 2 options are required", http.StatusBadRequest)
			return
		}
		if len(req.Options) > 12 {
			http.Error(w, "WhatsApp allows at most 12 poll options", http.StatusBadRequest)
			return
		}
		selectable := req.SelectableCount
		if selectable <= 0 {
			selectable = 1 // single-choice by default
		}
		success, message := sendPoll(client, messageStore, req.Recipient, req.Name, req.Options, selectable)
		w.Header().Set("Content-Type", "application/json")
		if !success {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(SendMessageResponse{Success: false, Message: message})
			return
		}
		json.NewEncoder(w).Encode(map[string]interface{}{"success": true, "message_id": message})
	})

	// Handler for unsending (revoking) one of our own messages
	http.HandleFunc("/api/revoke", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req RevokeRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}
		if req.ChatJID == "" || req.MessageID == "" {
			http.Error(w, "chat_jid and message_id are required", http.StatusBadRequest)
			return
		}
		success, message := revokeMessage(client, messageStore, req.ChatJID, req.MessageID)
		w.Header().Set("Content-Type", "application/json")
		if !success {
			w.WriteHeader(http.StatusInternalServerError)
		}
		json.NewEncoder(w).Encode(SendMessageResponse{Success: success, Message: message})
	})

	// Handler for asking our phone to re-deliver an undecryptable message.
	// mode="placeholder" sends a PLACEHOLDER_MESSAGE_RESEND peer request (the same
	// thing AutomaticMessageRerequestFromPhone fires once, automatically, at receipt
	// time); mode="history" asks for an on-demand history chunk ending at the given
	// message. Both answer asynchronously - the redelivered message arrives through
	// the normal events.Message path, so watch the stream or the store for it.
	http.HandleFunc("/api/rerequest", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req RerequestRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}
		if req.ChatJID == "" || req.MessageID == "" {
			http.Error(w, "chat_jid and message_id are required", http.StatusBadRequest)
			return
		}
		chat, err := types.ParseJID(req.ChatJID)
		if err != nil {
			http.Error(w, "Invalid chat_jid", http.StatusBadRequest)
			return
		}
		// For a 1:1 chat the sender is the chat itself unless caller overrides it
		// (the LID and phone-number JIDs address the same person, and which one the
		// phone indexed the message under is exactly what we may need to probe).
		sender := chat
		if req.SenderJID != "" {
			sender, err = types.ParseJID(req.SenderJID)
			if err != nil {
				http.Error(w, "Invalid sender_jid", http.StatusBadRequest)
				return
			}
		}

		mode := req.Mode
		if mode == "" {
			mode = "placeholder"
		}
		var peerMsg *waE2E.Message
		switch mode {
		case "placeholder":
			peerMsg = client.BuildUnavailableMessageRequest(chat, sender, req.MessageID)
		case "history":
			count := req.Count
			if count <= 0 {
				count = 50
			}
			ts := time.Now()
			if req.Timestamp > 0 {
				ts = time.Unix(req.Timestamp, 0)
			}
			peerMsg = client.BuildHistorySyncRequest(&types.MessageInfo{
				MessageSource: types.MessageSource{Chat: chat, Sender: sender},
				ID:            req.MessageID,
				Timestamp:     ts,
			}, count)
		default:
			http.Error(w, "mode must be \"placeholder\" or \"history\"", http.StatusBadRequest)
			return
		}

		resp, err := client.SendPeerMessage(context.Background(), peerMsg)
		w.Header().Set("Content-Type", "application/json")
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(SendMessageResponse{Success: false, Message: fmt.Sprintf("peer request failed: %v", err)})
			return
		}
		fmt.Printf("Sent %s re-request for %s in %s (stanza %s)\n", mode, req.MessageID, chat, resp.ID)
		json.NewEncoder(w).Encode(SendMessageResponse{
			Success: true,
			Message: fmt.Sprintf("%s re-request sent for %s (stanza %s); redelivery arrives asynchronously", mode, req.MessageID, resp.ID),
		})
	})

	// Handler for editing one of our own messages
	http.HandleFunc("/api/edit", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req EditRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}
		if req.ChatJID == "" || req.MessageID == "" || req.Message == "" {
			http.Error(w, "chat_jid, message_id and message are required", http.StatusBadRequest)
			return
		}
		success, message := editMessage(client, messageStore, req.ChatJID, req.MessageID, req.Message)
		w.Header().Set("Content-Type", "application/json")
		if !success {
			w.WriteHeader(http.StatusInternalServerError)
		}
		json.NewEncoder(w).Encode(SendMessageResponse{Success: success, Message: message})
	})

	// Handler for reacting to a message (empty reaction removes it)
	http.HandleFunc("/api/react", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req ReactRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}
		if req.ChatJID == "" || req.MessageID == "" {
			http.Error(w, "chat_jid and message_id are required", http.StatusBadRequest)
			return
		}
		success, message := reactToMessage(client, messageStore, req.ChatJID, req.MessageID, req.Reaction)
		w.Header().Set("Content-Type", "application/json")
		if !success {
			w.WriteHeader(http.StatusInternalServerError)
		}
		json.NewEncoder(w).Encode(SendMessageResponse{Success: success, Message: message})
	})

	// Handler for listing our OWN recent message IDs (for unsend/edit)
	http.HandleFunc("/api/messages", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req MessageIDsRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}
		if req.ChatJID == "" {
			http.Error(w, "chat_jid is required", http.StatusBadRequest)
			return
		}
		limit := req.Limit
		if limit <= 0 || limit > 50 {
			limit = 10
		}
		// Always our own messages; newest first.
		q := "SELECT id, timestamp, content FROM messages WHERE chat_jid = ? AND is_from_me = 1"
		args := []interface{}{req.ChatJID}
		if req.Filter != "" {
			q += " AND content LIKE ?"
			args = append(args, "%"+req.Filter+"%")
		}
		q += " ORDER BY timestamp DESC LIMIT ?"
		args = append(args, limit)

		w.Header().Set("Content-Type", "application/json")
		rows, err := messageStore.db.Query(q, args...)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": err.Error()})
			return
		}
		defer rows.Close()
		msgs := []map[string]interface{}{}
		for rows.Next() {
			var id, content string
			var ts time.Time
			if err := rows.Scan(&id, &ts, &content); err != nil {
				continue
			}
			msgs = append(msgs, map[string]interface{}{
				"id":        id,
				"timestamp": ts.Format(time.RFC3339),
				"content":   content,
			})
		}
		json.NewEncoder(w).Encode(map[string]interface{}{"success": true, "messages": msgs})
	})

	// Handler for downloading media
	http.HandleFunc("/api/download", func(w http.ResponseWriter, r *http.Request) {
		// Only allow POST requests
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		// Parse the request body
		var req DownloadMediaRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}

		// Validate request
		if req.MessageID == "" || req.ChatJID == "" {
			http.Error(w, "Message ID and Chat JID are required", http.StatusBadRequest)
			return
		}

		// Download the media
		success, mediaType, filename, path, err := downloadMedia(client, messageStore, req.MessageID, req.ChatJID)

		// Set response headers
		w.Header().Set("Content-Type", "application/json")

		// Handle download result
		if !success || err != nil {
			errMsg := "Unknown error"
			if err != nil {
				errMsg = err.Error()
			}

			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(DownloadMediaResponse{
				Success: false,
				Message: fmt.Sprintf("Failed to download media: %s", errMsg),
			})
			return
		}

		// Send successful response
		json.NewEncoder(w).Encode(DownloadMediaResponse{
			Success:  true,
			Message:  fmt.Sprintf("Successfully downloaded %s media", mediaType),
			Filename: filename,
			Path:     path,
		})
	})

	// Handler for sending read receipts (blue ticks) — MANUAL ONLY
	http.HandleFunc("/api/mark-read", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req MarkReadRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}

		if req.ChatJID == "" || len(req.MessageIDs) == 0 {
			http.Error(w, "chat_jid and message_ids required", http.StatusBadRequest)
			return
		}

		chatJID, err := types.ParseJID(req.ChatJID)
		if err != nil {
			http.Error(w, fmt.Sprintf("Invalid JID: %v", err), http.StatusBadRequest)
			return
		}

		// Convert string IDs to MessageID type
		msgIDs := make([]types.MessageID, len(req.MessageIDs))
		for i, id := range req.MessageIDs {
			msgIDs[i] = types.MessageID(id)
		}

		err = client.MarkRead(context.Background(), msgIDs, time.Now(), chatJID, types.EmptyJID, "")
		w.Header().Set("Content-Type", "application/json")
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": err.Error()})
			return
		}

		json.NewEncoder(w).Encode(map[string]interface{}{"success": true, "message": "Read receipt sent (blue ticks visible to them now)"})
	})

	// Handler for typing indicators — fake typing on demand
	http.HandleFunc("/api/typing", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req TypingRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}

		if req.ChatJID == "" {
			http.Error(w, "chat_jid required", http.StatusBadRequest)
			return
		}

		chatJID, err := types.ParseJID(req.ChatJID)
		if err != nil {
			http.Error(w, fmt.Sprintf("Invalid JID: %v", err), http.StatusBadRequest)
			return
		}

		state := types.ChatPresencePaused
		if req.Composing {
			state = types.ChatPresenceComposing
		}

		media := types.ChatPresenceMediaText
		if req.Media == "audio" {
			media = types.ChatPresenceMediaAudio
		}

		err = client.SendChatPresence(context.Background(), chatJID, state, media)
		w.Header().Set("Content-Type", "application/json")
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": err.Error()})
			return
		}

		action := "stopped typing"
		if req.Composing {
			action = "typing"
		}
		json.NewEncoder(w).Encode(map[string]interface{}{"success": true, "message": fmt.Sprintf("Now showing as %s", action)})
	})

	// Handler for online/offline presence
	http.HandleFunc("/api/presence", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req PresenceRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}

		presence := types.PresenceUnavailable
		if req.Available {
			presence = types.PresenceAvailable
		}

		err := client.SendPresence(context.Background(), presence)
		w.Header().Set("Content-Type", "application/json")
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": err.Error()})
			return
		}

		status := "offline"
		if req.Available {
			status = "online"
		}
		json.NewEncoder(w).Encode(map[string]interface{}{"success": true, "message": fmt.Sprintf("Now appearing %s", status)})
	})

	// Handler for requesting on-demand history sync for a specific chat
	http.HandleFunc("/api/resync", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		w.Header().Set("Content-Type", "application/json")

		if client == nil || !client.IsConnected() || client.Store == nil || client.Store.ID == nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": "Not connected to WhatsApp"})
			return
		}

		// Parse optional chat_jid from request body
		var req struct {
			ChatJID string `json:"chat_jid"`
			Count   int    `json:"count"`
		}
		json.NewDecoder(r.Body).Decode(&req)

		if req.ChatJID == "" {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": "chat_jid is required. On-demand sync only works per-chat."})
			return
		}

		// On-demand sync for specific chat: find oldest message and request more
		if req.Count == 0 {
			req.Count = 100
		}

		chatJID, err := types.ParseJID(req.ChatJID)
		if err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": fmt.Sprintf("Invalid JID: %v", err)})
			return
		}

		// Get oldest message in this chat from our DB
		var msgID string
		var isFromMe bool
		var timestamp int64
		err = messageStore.db.QueryRow(
			"SELECT id, is_from_me, strftime('%s', timestamp) FROM messages WHERE chat_jid = ? ORDER BY timestamp ASC LIMIT 1",
			req.ChatJID,
		).Scan(&msgID, &isFromMe, &timestamp)

		if err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": "No messages found for this chat to sync from"})
			return
		}

		msgInfo := &types.MessageInfo{
			MessageSource: types.MessageSource{
				Chat:     chatJID,
				IsFromMe: isFromMe,
			},
			ID:        msgID,
			Timestamp: time.Unix(timestamp, 0),
		}

		historyMsg := client.BuildHistorySyncRequest(msgInfo, req.Count)

		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_, err = client.SendPeerMessage(ctx, historyMsg)

		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": fmt.Sprintf("Failed: %v", err)})
			return
		}

		json.NewEncoder(w).Encode(map[string]interface{}{"success": true, "message": fmt.Sprintf("Requested %d older messages for %s. They'll arrive in the background.", req.Count, req.ChatJID)})
	})

	// Bulk-resolve all unresolved contact names (LIDs with numeric-only names)
	http.HandleFunc("/api/resolve-contacts", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		if client == nil || !client.IsConnected() {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": "Not connected"})
			return
		}

		logger := waLog.Stdout("Resolve", "INFO", true)

		// Find chats with numeric-only names that have recent messages (last 30 days)
		rows, err := messageStore.db.Query(`
			SELECT DISTINCT c.jid, c.name FROM chats c
			INNER JOIN messages m ON m.chat_jid = c.jid
			WHERE c.name IS NOT NULL
			AND m.timestamp > datetime('now', '-30 days')
		`)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": err.Error()})
			return
		}

		// Collect unresolved JIDs first, then close cursor before writing
		type unresolvedChat struct{ jid, name string }
		var toResolve []unresolvedChat
		for rows.Next() {
			var jidStr, name string
			rows.Scan(&jidStr, &name)
			isRaw := true
			for _, c := range name {
				if c < '0' || c > '9' {
					isRaw = false
					break
				}
			}
			if !isRaw || name == "" {
				continue
			}
			toResolve = append(toResolve, unresolvedChat{jidStr, name})
		}
		rows.Close()

		// Now resolve with no open cursor blocking writes
		resolved := 0
		total := len(toResolve)
		for _, chat := range toResolve {
			jid, err := types.ParseJID(chat.jid)
			if err != nil {
				continue
			}
			newName := GetChatName(client, messageStore, jid, chat.jid, nil, "", logger)
			if newName != chat.name && newName != "" {
				resolved++
			}
		}

		json.NewEncoder(w).Encode(map[string]interface{}{
			"success":    true,
			"resolved":   resolved,
			"unresolved": total - resolved,
			"total":      total,
		})
	})

	// Resolve any identifier (JID / @lid / bare phone) to its canonical chat JID.
	// The channel calls this before storing a subscription so a phone-keyed sub and a
	// LID-addressed event collapse to one key. Authoritative because canonicalChatJID
	// can do a live GetUserInfo backfill on a cache miss.
	http.HandleFunc("/api/resolve-jid", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		var req struct {
			JID string `json:"jid"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.JID == "" {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": "jid is required"})
			return
		}
		jid, err := parseRecipientJID(req.JID)
		if err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "message": fmt.Sprintf("invalid jid: %v", err)})
			return
		}
		canonical := canonicalChatJID(client, jid, types.EmptyJID)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": true,
			"jid":     canonical.String(),
		})
	})

	// SSE event stream — subscribers receive all WhatsApp events in real-time
	http.HandleFunc("/api/stream", func(w http.ResponseWriter, r *http.Request) {
		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "SSE not supported", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")
		w.Header().Set("Access-Control-Allow-Origin", "*")

		ch := make(chan []byte, 64)
		sseMu.Lock()
		sseClients[ch] = struct{}{}
		clientCount := len(sseClients)
		sseMu.Unlock()

		fmt.Printf("SSE client connected (%d total)\n", clientCount)

		defer func() {
			sseMu.Lock()
			delete(sseClients, ch)
			remaining := len(sseClients)
			sseMu.Unlock()
			fmt.Printf("SSE client disconnected (%d remaining)\n", remaining)
		}()

		// Send keepalive comment so client knows connection is live
		fmt.Fprintf(w, ": connected\n\n")
		flusher.Flush()

		// Heartbeat. Without it the stream is silent between messages, and a
		// client whose HTTP layer has an idle timeout tears the connection
		// down and reconnects -- which produced a TimeoutError every few
		// minutes in the channel server and a reconnect storm in the log.
		heartbeat := time.NewTicker(20 * time.Second)
		defer heartbeat.Stop()

		for {
			select {
			case data := <-ch:
				w.Write(data)
				flusher.Flush()
			case <-heartbeat.C:
				fmt.Fprintf(w, ": keepalive\n\n")
				flusher.Flush()
			case <-r.Context().Done():
				return
			}
		}
	})

	// Start the server
	serverAddr := fmt.Sprintf(":%d", port)
	fmt.Printf("Starting REST API server on %s...\n", serverAddr)

	// Run server in a goroutine so it doesn't block
	go func() {
		if err := http.ListenAndServe(serverAddr, nil); err != nil {
			fmt.Printf("REST API server error: %v\n", err)
		}
	}()
}

// Store an event in the database
func (store *MessageStore) StoreEvent(chatJID, eventType, sender, data string) error {
	_, err := store.db.Exec(
		"INSERT INTO events (chat_jid, event_type, sender, timestamp, data) VALUES (?, ?, ?, ?, ?)",
		chatJID, eventType, sender, time.Now().Format(time.RFC3339), data,
	)
	return err
}

// StorePollOptions remembers a poll's option names so incoming votes (which carry
// only SHA256 hashes of the chosen options) can be mapped back to names.
func (store *MessageStore) StorePollOptions(pollID, chatJID string, options []string) error {
	blob, err := json.Marshal(options)
	if err != nil {
		return err
	}
	_, err = store.db.Exec(
		"INSERT OR REPLACE INTO poll_options (poll_id, chat_jid, options) VALUES (?, ?, ?)",
		pollID, chatJID, string(blob),
	)
	return err
}

// GetPollOptions returns the stored option names for a poll, or nil if unknown.
func (store *MessageStore) GetPollOptions(pollID string) []string {
	var blob string
	if err := store.db.QueryRow("SELECT options FROM poll_options WHERE poll_id = ?", pollID).Scan(&blob); err != nil {
		return nil
	}
	var options []string
	if json.Unmarshal([]byte(blob), &options) != nil {
		return nil
	}
	return options
}

// resolvePollVote maps a decrypted vote's option hashes back to their names, using
// the stored option list for the poll. Unknown hashes are dropped.
func resolvePollVote(options []string, selected [][]byte) []string {
	hashes := whatsmeow.HashPollOptions(options)
	var chosen []string
	for _, sel := range selected {
		for i, h := range hashes {
			if bytes.Equal(sel, h) {
				chosen = append(chosen, options[i])
			}
		}
	}
	return chosen
}

// handlePollVote decrypts a poll vote and broadcasts it as a "poll_vote" SSE event.
// Returns true if the message was a poll vote (handled).
func handlePollVote(client *whatsmeow.Client, store *MessageStore, msg *events.Message, chatJID, sender, name string, logger waLog.Logger) bool {
	update := msg.Message.GetPollUpdateMessage()
	if update == nil {
		return false
	}
	pollID := update.GetPollCreationMessageKey().GetID()
	vote, err := client.DecryptPollVote(context.Background(), msg)
	if err != nil {
		logger.Warnf("Failed to decrypt poll vote for poll %s: %v", pollID, err)
		broadcastEvent("poll_vote", map[string]interface{}{
			"chat_jid":        chatJID,
			"sender":          sender,
			"sender_name":     name,
			"poll_message_id": pollID,
			"message_id":      msg.Info.ID,
			"error":           "decrypt_failed",
			"timestamp":       msg.Info.Timestamp.Format(time.RFC3339),
			"is_from_me":      msg.Info.IsFromMe,
		})
		return true
	}
	options := store.GetPollOptions(pollID)
	selected := resolvePollVote(options, vote.GetSelectedOptions())
	logger.Infof("Poll vote from %s on poll %s: %v", sender, pollID, selected)
	broadcastEvent("poll_vote", map[string]interface{}{
		"chat_jid":         chatJID,
		"sender":           sender,
		"sender_name":      name,
		"poll_message_id":  pollID,
		"message_id":       msg.Info.ID,
		"selected_options": selected,
		"selected_count":   len(vote.GetSelectedOptions()),
		"timestamp":        msg.Info.Timestamp.Format(time.RFC3339),
		"is_from_me":       msg.Info.IsFromMe,
	})
	return true
}

// sendPoll sends a poll message and stores its options for vote resolution.
func sendPoll(client *whatsmeow.Client, store *MessageStore, recipient, name string, options []string, selectableCount int) (bool, string) {
	if !client.IsConnected() {
		return false, "Not connected to WhatsApp"
	}
	if !recipientAllowed(recipient) {
		return false, "recipient not in WHATSAPP_ALLOWED_RECIPIENTS"
	}
	recipientJID, err := parseRecipientJID(recipient)
	if err != nil {
		return false, fmt.Sprintf("Error parsing JID: %v", err)
	}
	poll := client.BuildPollCreation(name, options, selectableCount)
	resp, err := client.SendMessage(context.Background(), recipientJID, poll)
	if err != nil {
		return false, fmt.Sprintf("Error sending poll: %v", err)
	}
	if err := store.StorePollOptions(resp.ID, recipientJID.String(), options); err != nil {
		fmt.Printf("Warning: poll %s sent but options not stored: %v\n", resp.ID, err)
	}
	return true, resp.ID
}

// Handle receipt events (read, delivered, played)
func handleReceipt(client *whatsmeow.Client, messageStore *MessageStore, receipt *events.Receipt, logger waLog.Logger) {
	canonChat := resolveChatKey(client, messageStore, receipt.Chat, receipt.SenderAlt)
	chatJID := canonChat.String()
	sender := canonicalSenderUser(client, receipt.Sender, receipt.SenderAlt)

	// Filter out self-receipts (our own devices reading/playing messages). The receipt
	// may be addressed by our phone OR our LID, so check both the canonical sender and
	// the raw one against both of our identities.
	if isOwnUser(client, sender) || isOwnUser(client, receipt.Sender.User) {
		logger.Infof("SELF RECEIPT (ignored): %s in %s (type: %s)", sender, chatJID, receipt.Type)
		return
	}

	var eventType string
	switch receipt.Type {
	case types.ReceiptTypeRead:
		eventType = "read"
		logger.Infof("READ RECEIPT: %s read messages in %s", sender, chatJID)
	case types.ReceiptTypeDelivered:
		eventType = "delivered"
		logger.Infof("DELIVERY RECEIPT: messages delivered to %s in %s", sender, chatJID)
	case types.ReceiptTypePlayed:
		eventType = "played"
		logger.Infof("PLAYED RECEIPT: %s played voice message in %s", sender, chatJID)
	case types.ReceiptTypeReadSelf:
		return // Always ignore self-reads
	case types.ReceiptTypePlayedSelf:
		return // Always ignore self-plays
	default:
		return
	}

	// Store message IDs as JSON
	msgIDs, _ := json.Marshal(receipt.MessageIDs)
	err := messageStore.StoreEvent(chatJID, eventType, sender, string(msgIDs))
	if err != nil {
		logger.Warnf("Failed to store receipt event: %v", err)
	}

	// Broadcast to SSE subscribers
	broadcastEvent("receipt", map[string]interface{}{
		"chat_jid":    chatJID,
		"sender":      sender,
		"event_type":  eventType,
		"message_ids": receipt.MessageIDs,
		"timestamp":   time.Now().Format(time.RFC3339),
	})
}

// Handle typing indicator events
func handleChatPresence(client *whatsmeow.Client, messageStore *MessageStore, presence *events.ChatPresence, logger waLog.Logger) {
	canonChat := resolveChatKey(client, messageStore, presence.Chat, presence.SenderAlt)
	chatJID := canonChat.String()
	sender := canonicalSenderUser(client, presence.Sender, presence.SenderAlt)

	var eventType string
	switch presence.State {
	case types.ChatPresenceComposing:
		eventType = "typing"
		logger.Infof("TYPING: %s is typing in %s", sender, chatJID)
	case types.ChatPresencePaused:
		eventType = "typing_stopped"
		logger.Infof("TYPING STOPPED: %s stopped typing in %s", sender, chatJID)
	default:
		return
	}

	mediaType := "text"
	if presence.Media == types.ChatPresenceMediaAudio {
		mediaType = "audio"
	}

	err := messageStore.StoreEvent(chatJID, eventType, sender, mediaType)
	if err != nil {
		logger.Warnf("Failed to store typing event: %v", err)
	}

	// Broadcast to SSE subscribers
	broadcastEvent("presence", map[string]interface{}{
		"chat_jid":   chatJID,
		"sender":     sender,
		"event_type": eventType,
		"media":      mediaType,
		"timestamp":  time.Now().Format(time.RFC3339),
	})
}

// MarkReadRequest for the mark-read API
type MarkReadRequest struct {
	ChatJID    string   `json:"chat_jid"`
	MessageIDs []string `json:"message_ids"`
}

// TypingRequest for the typing API
type TypingRequest struct {
	ChatJID   string `json:"chat_jid"`
	Composing bool   `json:"composing"`
	Media     string `json:"media"` // "text" or "audio"
}

// PresenceRequest for the presence API
type PresenceRequest struct {
	Available bool `json:"available"`
}

func main() {
	// Set up logger
	// Log level is env-driven so a wire-level trace (WA_LOG_LEVEL=DEBUG) can be
	// captured without a rebuild. DEBUG dumps every received node via the Recv
	// sub-logger, which is how view-once fanout stanzas become visible.
	logLevel := os.Getenv("WA_LOG_LEVEL")
	if logLevel == "" {
		logLevel = "INFO"
	}
	logger := waLog.Stdout("Client", logLevel, true)
	logger.Infof("Starting WhatsApp client...")

	// DeviceProps is sent ONLY in the registration node, i.e. at pairing time. A
	// device registered as whatsmeow/UNKNOWN cannot be re-labelled by reconnecting,
	// so this has no effect on an existing session - it only changes how a NEW
	// pairing identifies itself. Baileys' Browsers.windows("Desktop") yields
	// Os="Windows" + PlatformType=DESKTOP, and a Baileys maintainer reports
	// companions receiving view-once media; whatsmeow's whatsmeow/UNKNOWN default
	// is the last remaining difference between the two.
	if os.Getenv("WA_DEVICE_IDENTITY") == "DESKTOP" {
		wastore.DeviceProps.Os = proto.String("Windows")
		wastore.DeviceProps.PlatformType = waCompanionReg.DeviceProps_DESKTOP.Enum()
		logger.Infof("Device identity set to Windows/DESKTOP (takes effect only on a NEW pairing)")
	}

	// WhatsApp gates some companion-device features on the advertised web
	// sub-platform, which travels in ClientPayload.WebInfo - a per-connection
	// field, so this applies on reconnect and needs no re-pairing. whatsmeow
	// defaults to WEB_BROWSER; WIN_HYBRID (5) is the identity of the modern
	// native Windows Desktop app, which unlike this bridge CAN open view-once
	// media. Baileys hit the same wall for full history sync (their #2741).
	// Unset = unchanged upstream behaviour, so reverting is a restart.
	if sp := os.Getenv("WA_WEB_SUBPLATFORM"); sp != "" {
		subPlatforms := map[string]waWa6.ClientPayload_WebInfo_WebSubPlatform{
			"WEB_BROWSER": waWa6.ClientPayload_WebInfo_WEB_BROWSER,
			"APP_STORE":   waWa6.ClientPayload_WebInfo_APP_STORE,
			"WIN_STORE":   waWa6.ClientPayload_WebInfo_WIN_STORE,
			"DARWIN":      waWa6.ClientPayload_WebInfo_DARWIN,
			"WIN32":       waWa6.ClientPayload_WebInfo_WIN32,
			"WIN_HYBRID":  waWa6.ClientPayload_WebInfo_WIN_HYBRID,
		}
		v, ok := subPlatforms[strings.ToUpper(sp)]
		if !ok {
			logger.Errorf("Unknown WA_WEB_SUBPLATFORM %q - refusing to start rather than "+
				"connecting with an identity you did not choose", sp)
			return
		}
		wastore.BaseClientPayload.WebInfo.WebSubPlatform = v.Enum()
		logger.Infof("Advertising web sub-platform %s", strings.ToUpper(sp))
	}

	// Create database connection for storing session data
	dbLog := waLog.Stdout("Database", "INFO", true)

	// Create directory for database if it doesn't exist
	if err := os.MkdirAll("store", 0755); err != nil {
		logger.Errorf("Failed to create store directory: %v", err)
		return
	}

	container, err := sqlstore.New(context.Background(), "sqlite3", "file:store/whatsapp.db?_foreign_keys=on", dbLog)
	if err != nil {
		logger.Errorf("Failed to connect to database: %v", err)
		return
	}

	// Get device store - This contains session information
	deviceStore, err := container.GetFirstDevice(context.Background())
	if err != nil {
		if err == sql.ErrNoRows {
			// No device exists, create one
			deviceStore = container.NewDevice()
			logger.Infof("Created new device")
		} else {
			logger.Errorf("Failed to get device: %v", err)
			return
		}
	}

	// Create client instance
	client := whatsmeow.NewClient(deviceStore, logger)
	if client == nil {
		logger.Errorf("Failed to create WhatsApp client")
		return
	}

	// Initialize message store
	messageStore, err := NewMessageStore()
	if err != nil {
		logger.Errorf("Failed to initialize message store: %v", err)
		return
	}
	defer messageStore.Close()

	// STEALTH MODE: Don't auto-send active delivery receipts
	// This means their messages won't show double grey ticks immediately
	client.SetForceActiveDeliveryReceipts(false)

	// If a message arrives "unavailable" (e.g. a view-once that we missed because the
	// socket dropped mid-delivery), automatically ask our primary phone to resend it.
	// It then redelivers as a normal events.Message and goes through handleMessage —
	// so a transient disconnect no longer loses a view-once.
	client.AutomaticMessageRerequestFromPhone = true

	// Setup event handling for messages, receipts, typing, and history sync
	client.AddEventHandler(func(evt interface{}) {
		switch v := evt.(type) {
		case *events.Message:
			// Process regular messages (do NOT auto-send read receipts)
			handleMessage(client, messageStore, v, logger)

		case *events.UndecryptableMessage:
			// e.g. a view-once that arrived while the socket was dropping. With
			// AutomaticMessageRerequestFromPhone enabled, whatsmeow asks the phone to
			// resend it; it then comes back through the *events.Message path above.
			// But the resend can be slow or (for view-once) never arrive decryptable,
			// so we ALSO surface a placeholder now — otherwise the persona is blind to
			// a photo it may have just asked for.
			logger.Warnf("Undecryptable message %s from %s (unavailable=%v, type=%q) — re-requesting from phone",
				v.Info.ID, v.Info.SourceString(), v.IsUnavailable, v.UnavailableType)
			handleUndecryptable(client, messageStore, v, logger)

		case *events.HistorySync:
			// Process history sync events
			handleHistorySync(client, messageStore, v, logger)

		case *events.Receipt:
			// Store receipt events (read, delivered, played) — filters out self-receipts
			handleReceipt(client, messageStore, v, logger)

		case *events.ChatPresence:
			// Store typing indicators
			handleChatPresence(client, messageStore, v, logger)

		case *events.Connected:
			logger.Infof("Connected to WhatsApp")
			// STEALTH: Do NOT auto-send PresenceAvailable
			// This keeps delivery receipts as "inactive" (no grey double ticks for them)
			// Use /api/presence to go online manually when you want typing indicators

		case *events.LoggedOut:
			logger.Warnf("Device logged out, please scan QR code to log in again")
		}
	})

	// Create channel to track connection success
	connected := make(chan bool, 1)

	// Connect to WhatsApp
	if client.Store.ID == nil {
		// No ID stored, this is a new client, need to pair with phone
		qrChan, _ := client.GetQRChannel(context.Background())
		err = client.Connect()
		if err != nil {
			logger.Errorf("Failed to connect: %v", err)
			return
		}

		// Print QR code for pairing with phone
		for evt := range qrChan {
			if evt.Event == "code" {
				fmt.Println("\nScan this QR code with your WhatsApp app:")
				qrterminal.GenerateHalfBlock(evt.Code, qrterminal.L, os.Stdout)
			} else if evt.Event == "success" {
				connected <- true
				break
			}
		}

		// Wait for connection
		select {
		case <-connected:
			fmt.Println("\nSuccessfully connected and authenticated!")
		case <-time.After(3 * time.Minute):
			logger.Errorf("Timeout waiting for QR code scan")
			return
		}
	} else {
		// Already logged in, just connect
		err = client.Connect()
		if err != nil {
			logger.Errorf("Failed to connect: %v", err)
			return
		}
		connected <- true
	}

	// Wait a moment for connection to stabilize
	time.Sleep(2 * time.Second)

	if !client.IsConnected() {
		logger.Errorf("Failed to establish stable connection")
		return
	}

	fmt.Println("\n✓ Connected to WhatsApp! Type 'help' for commands.")

	// Start REST API server
	startRESTServer(client, messageStore, 8080)

	// Create a channel to keep the main goroutine alive
	exitChan := make(chan os.Signal, 1)
	signal.Notify(exitChan, syscall.SIGINT, syscall.SIGTERM)

	fmt.Println("REST server is running. Press Ctrl+C to disconnect and exit.")

	// Wait for termination signal
	<-exitChan

	fmt.Println("Disconnecting...")
	// Disconnect client
	client.Disconnect()
}

// contactName returns the best available stored name for a contact JID (FullName >
// PushName > BusinessName), or "" if none.
func contactName(client *whatsmeow.Client, jid types.JID) string {
	contact, err := client.Store.Contacts.GetContact(context.Background(), jid)
	if err != nil {
		return ""
	}
	if contact.FullName != "" {
		return contact.FullName
	}
	if contact.PushName != "" {
		return contact.PushName
	}
	if contact.BusinessName != "" {
		return contact.BusinessName
	}
	return ""
}

// GetChatName determines the appropriate name for a chat based on JID and other info
func GetChatName(client *whatsmeow.Client, messageStore *MessageStore, jid types.JID, chatJID string, conversation interface{}, sender string, logger waLog.Logger) string {
	// First, check if chat already exists in database with a name
	var existingName string
	err := messageStore.db.QueryRow("SELECT name FROM chats WHERE jid = ?", chatJID).Scan(&existingName)
	if err == nil && existingName != "" {
		// Check if the stored name is a real name or just a raw number/LID
		// If it's all digits, it's probably an unresolved LID — try to resolve again
		isRawNumber := true
		for _, c := range existingName {
			if c < '0' || c > '9' {
				isRawNumber = false
				break
			}
		}
		if !isRawNumber {
			logger.Infof("Using existing chat name for %s: %s", chatJID, existingName)
			return existingName
		}
		logger.Infof("Stored name for %s looks like raw ID (%s), trying to resolve...", chatJID, existingName)
	}

	// Need to determine chat name
	var name string

	if jid.Server == "g.us" {
		// This is a group chat
		logger.Infof("Getting name for group: %s", chatJID)

		// Use conversation data if provided (from history sync)
		if conversation != nil {
			// Extract name from conversation if available
			// This uses type assertions to handle different possible types
			var displayName, convName *string
			// Try to extract the fields we care about regardless of the exact type
			v := reflect.ValueOf(conversation)
			if v.Kind() == reflect.Ptr && !v.IsNil() {
				v = v.Elem()

				// Try to find DisplayName field
				if displayNameField := v.FieldByName("DisplayName"); displayNameField.IsValid() && displayNameField.Kind() == reflect.Ptr && !displayNameField.IsNil() {
					dn := displayNameField.Elem().String()
					displayName = &dn
				}

				// Try to find Name field
				if nameField := v.FieldByName("Name"); nameField.IsValid() && nameField.Kind() == reflect.Ptr && !nameField.IsNil() {
					n := nameField.Elem().String()
					convName = &n
				}
			}

			// Use the name we found
			if displayName != nil && *displayName != "" {
				name = *displayName
			} else if convName != nil && *convName != "" {
				name = *convName
			}
		}

		// If we didn't get a name, try group info
		if name == "" {
			groupInfo, err := client.GetGroupInfo(context.Background(), jid)
			if err == nil && groupInfo.Name != "" {
				name = groupInfo.Name
			} else {
				// Fallback name for groups
				name = fmt.Sprintf("Group %s", jid.User)
			}
		}

		logger.Infof("Using group name: %s", name)
	} else {
		// This is an individual contact
		logger.Infof("Getting name for contact: %s", chatJID)

		// Try all available name sources: FullName > PushName > BusinessName > sender > JID.
		// whatsmeow keys the push/full name under whichever identity WhatsApp used — often
		// the @lid, not the phone — so if the direct lookup is empty, try the alt identity.
		name = contactName(client, jid)
		if name == "" {
			if alt, aerr := client.Store.GetAltJID(context.Background(), jid); aerr == nil && !alt.IsEmpty() {
				name = contactName(client, alt)
			}
		}
		if name == "" {
			if sender != "" {
				name = sender // fallback to sender
			} else {
				name = jid.User // last fallback to JID
			}
		}

		logger.Infof("Using contact name: %s", name)
	}

	// If we resolved a better name than what's in the DB, update it
	if name != "" && name != existingName {
		messageStore.db.Exec("UPDATE chats SET name = ? WHERE jid = ?", name, chatJID)
		logger.Infof("Updated chat name for %s: %s → %s", chatJID, existingName, name)
	}

	return name
}

// Handle history sync events
func handleHistorySync(client *whatsmeow.Client, messageStore *MessageStore, historySync *events.HistorySync, logger waLog.Logger) {
	fmt.Printf("Received history sync event with %d conversations\n", len(historySync.Data.Conversations))

	syncedCount := 0
	for _, conversation := range historySync.Data.Conversations {
		// Parse JID from the conversation
		if conversation.ID == nil {
			continue
		}

		chatJID := *conversation.ID

		// Try to parse the JID
		jid, err := types.ParseJID(chatJID)
		if err != nil {
			logger.Warnf("Failed to parse JID %s: %v", chatJID, err)
			continue
		}

		// Canonicalize a LID-addressed 1:1 conversation to its phone JID (history sync
		// carries no alt hint — relies on the LID<->PN map / lazy merge).
		jid = resolveChatKey(client, messageStore, jid, types.EmptyJID)
		chatJID = jid.String()

		// Get appropriate chat name by passing the history sync conversation directly
		name := GetChatName(client, messageStore, jid, chatJID, conversation, "", logger)

		// Process messages
		messages := conversation.Messages
		if len(messages) > 0 {
			// Update chat with latest message timestamp
			latestMsg := messages[0]
			if latestMsg == nil || latestMsg.Message == nil {
				continue
			}

			// Get timestamp from message info
			timestamp := time.Time{}
			if ts := latestMsg.Message.GetMessageTimestamp(); ts != 0 {
				timestamp = time.Unix(int64(ts), 0)
			} else {
				continue
			}

			messageStore.StoreChat(chatJID, name, timestamp)

			// Store messages
			for _, msg := range messages {
				if msg == nil || msg.Message == nil {
					continue
				}

				// Extract text content
				var content string
				if msg.Message.Message != nil {
					if conv := msg.Message.Message.GetConversation(); conv != "" {
						content = conv
					} else if ext := msg.Message.Message.GetExtendedTextMessage(); ext != nil {
						content = ext.GetText()
					}
				}

				// Extract media info
				var mediaType, filename, url string
				var mediaKey, fileSHA256, fileEncSHA256 []byte
				var fileLength uint64

				if msg.Message.Message != nil {
					mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength = extractMediaInfo(msg.Message.Message)
				}

				// Log the message content for debugging
				logger.Infof("Message content: %v, Media Type: %v", content, mediaType)

				// Skip messages with no content and no media
				if content == "" && mediaType == "" {
					continue
				}

				// Determine sender
				var sender string
				isFromMe := false
				if msg.Message.Key != nil {
					if msg.Message.Key.FromMe != nil {
						isFromMe = *msg.Message.Key.FromMe
					}
					if !isFromMe && msg.Message.Key.Participant != nil && *msg.Message.Key.Participant != "" {
						// Participant may be a raw @lid — canonicalize to the phone user-part.
						if pjid, perr := types.ParseJID(*msg.Message.Key.Participant); perr == nil {
							sender = canonicalSenderUser(client, pjid, types.EmptyJID)
						} else {
							sender = *msg.Message.Key.Participant
						}
					} else if isFromMe {
						sender = client.Store.ID.User
					} else {
						sender = jid.User
					}
				} else {
					sender = jid.User
				}

				// Store message
				msgID := ""
				if msg.Message.Key != nil && msg.Message.Key.ID != nil {
					msgID = *msg.Message.Key.ID
				}

				// Get message timestamp
				timestamp := time.Time{}
				if ts := msg.Message.GetMessageTimestamp(); ts != 0 {
					timestamp = time.Unix(int64(ts), 0)
				} else {
					continue
				}

				err = messageStore.StoreMessage(
					msgID,
					chatJID,
					sender,
					content,
					timestamp,
					isFromMe,
					mediaType,
					filename,
					url,
					mediaKey,
					fileSHA256,
					fileEncSHA256,
					fileLength,
				)
				if err != nil {
					logger.Warnf("Failed to store history message: %v", err)
				} else {
					syncedCount++
					// Log successful message storage
					if mediaType != "" {
						logger.Infof("Stored message: [%s] %s -> %s: [%s: %s] %s",
							timestamp.Format("2006-01-02 15:04:05"), sender, chatJID, mediaType, filename, content)
					} else {
						logger.Infof("Stored message: [%s] %s -> %s: %s",
							timestamp.Format("2006-01-02 15:04:05"), sender, chatJID, content)
					}
				}
			}
		}
	}

	fmt.Printf("History sync complete. Stored %d messages.\n", syncedCount)
}

// Request history sync from the server
func requestHistorySync(client *whatsmeow.Client) {
	if client == nil {
		fmt.Println("Client is not initialized. Cannot request history sync.")
		return
	}

	if !client.IsConnected() {
		fmt.Println("Client is not connected. Please ensure you are connected to WhatsApp first.")
		return
	}

	if client.Store.ID == nil {
		fmt.Println("Client is not logged in. Please scan the QR code first.")
		return
	}

	// Build and send a history sync request
	historyMsg := client.BuildHistorySyncRequest(nil, 100)
	if historyMsg == nil {
		fmt.Println("Failed to build history sync request.")
		return
	}

	_, err := client.SendMessage(context.Background(), types.JID{
		Server: "s.whatsapp.net",
		User:   "status",
	}, historyMsg)

	if err != nil {
		fmt.Printf("Failed to request history sync: %v\n", err)
	} else {
		fmt.Println("History sync requested. Waiting for server response...")
	}
}

// analyzeOggOpus tries to extract duration and generate a simple waveform from an Ogg Opus file
func analyzeOggOpus(data []byte) (duration uint32, waveform []byte, err error) {
	// Try to detect if this is a valid Ogg file by checking for the "OggS" signature
	// at the beginning of the file
	if len(data) < 4 || string(data[0:4]) != "OggS" {
		return 0, nil, fmt.Errorf("not a valid Ogg file (missing OggS signature)")
	}

	// Parse Ogg pages to find the last page with a valid granule position
	var lastGranule uint64
	var sampleRate uint32 = 48000 // Default Opus sample rate
	var preSkip uint16 = 0
	var foundOpusHead bool

	// Scan through the file looking for Ogg pages
	for i := 0; i < len(data); {
		// Check if we have enough data to read Ogg page header
		if i+27 >= len(data) {
			break
		}

		// Verify Ogg page signature
		if string(data[i:i+4]) != "OggS" {
			// Skip until next potential page
			i++
			continue
		}

		// Extract header fields
		granulePos := binary.LittleEndian.Uint64(data[i+6 : i+14])
		pageSeqNum := binary.LittleEndian.Uint32(data[i+18 : i+22])
		numSegments := int(data[i+26])

		// Extract segment table
		if i+27+numSegments >= len(data) {
			break
		}
		segmentTable := data[i+27 : i+27+numSegments]

		// Calculate page size
		pageSize := 27 + numSegments
		for _, segLen := range segmentTable {
			pageSize += int(segLen)
		}

		// Check if we're looking at an OpusHead packet (should be in first few pages)
		if !foundOpusHead && pageSeqNum <= 1 {
			// Look for "OpusHead" marker in this page
			pageData := data[i : i+pageSize]
			headPos := bytes.Index(pageData, []byte("OpusHead"))
			if headPos >= 0 && headPos+12 < len(pageData) {
				// Found OpusHead, extract sample rate and pre-skip
				// OpusHead format: Magic(8) + Version(1) + Channels(1) + PreSkip(2) + SampleRate(4) + ...
				headPos += 8 // Skip "OpusHead" marker
				// PreSkip is 2 bytes at offset 10
				if headPos+12 <= len(pageData) {
					preSkip = binary.LittleEndian.Uint16(pageData[headPos+10 : headPos+12])
					sampleRate = binary.LittleEndian.Uint32(pageData[headPos+12 : headPos+16])
					foundOpusHead = true
					fmt.Printf("Found OpusHead: sampleRate=%d, preSkip=%d\n", sampleRate, preSkip)
				}
			}
		}

		// Keep track of last valid granule position
		if granulePos != 0 {
			lastGranule = granulePos
		}

		// Move to next page
		i += pageSize
	}

	if !foundOpusHead {
		fmt.Println("Warning: OpusHead not found, using default values")
	}

	// Calculate duration based on granule position
	if lastGranule > 0 {
		// Formula for duration: (lastGranule - preSkip) / sampleRate
		durationSeconds := float64(lastGranule-uint64(preSkip)) / float64(sampleRate)
		duration = uint32(math.Ceil(durationSeconds))
		fmt.Printf("Calculated Opus duration from granule: %f seconds (lastGranule=%d)\n",
			durationSeconds, lastGranule)
	} else {
		// Fallback to rough estimation if granule position not found
		fmt.Println("Warning: No valid granule position found, using estimation")
		durationEstimate := float64(len(data)) / 2000.0 // Very rough approximation
		duration = uint32(durationEstimate)
	}

	// Make sure we have a reasonable duration (at least 1 second, at most 300 seconds)
	if duration < 1 {
		duration = 1
	} else if duration > 300 {
		duration = 300
	}

	// Generate waveform
	waveform = placeholderWaveform(duration)

	fmt.Printf("Ogg Opus analysis: size=%d bytes, calculated duration=%d sec, waveform=%d bytes\n",
		len(data), duration, len(waveform))

	return duration, waveform, nil
}

// min returns the smaller of x or y
func min(x, y int) int {
	if x < y {
		return x
	}
	return y
}

// placeholderWaveform generates a synthetic waveform for WhatsApp voice messages
// that appears natural with some variability based on the duration
func placeholderWaveform(duration uint32) []byte {
	// WhatsApp expects a 64-byte waveform for voice messages
	const waveformLength = 64
	waveform := make([]byte, waveformLength)

	// Seed the random number generator for consistent results with the same duration
	rand.Seed(int64(duration))

	// Create a more natural looking waveform with some patterns and variability
	// rather than completely random values

	// Base amplitude and frequency - longer messages get faster frequency
	baseAmplitude := 35.0
	frequencyFactor := float64(min(int(duration), 120)) / 30.0

	for i := range waveform {
		// Position in the waveform (normalized 0-1)
		pos := float64(i) / float64(waveformLength)

		// Create a wave pattern with some randomness
		// Use multiple sine waves of different frequencies for more natural look
		val := baseAmplitude * math.Sin(pos*math.Pi*frequencyFactor*8)
		val += (baseAmplitude / 2) * math.Sin(pos*math.Pi*frequencyFactor*16)

		// Add some randomness to make it look more natural
		val += (rand.Float64() - 0.5) * 15

		// Add some fade-in and fade-out effects
		fadeInOut := math.Sin(pos * math.Pi)
		val = val * (0.7 + 0.3*fadeInOut)

		// Center around 50 (typical voice baseline)
		val = val + 50

		// Ensure values stay within WhatsApp's expected range (0-100)
		if val < 0 {
			val = 0
		} else if val > 100 {
			val = 100
		}

		waveform[i] = byte(val)
	}

	return waveform
}
