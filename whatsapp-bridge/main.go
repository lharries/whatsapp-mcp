package main

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	mathrand "math/rand"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"github.com/mdp/qrterminal"
	qrcode "github.com/skip2/go-qrcode"

	"encoding/base64"

	"bytes"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
)

// processStartTime marks when the bridge process came up; surfaced by /health
// so the watchdog (and humans) can see real uptime, not just "port is bound".
var processStartTime = time.Now()

// Pairing state shared between the QR pairing loop and GET /api/qr, so the
// Cave app (or any local client) can render the current QR code in-app instead
// of the operator digging it out of stdout. Guarded by pairMu; cleared on
// pairing success so a paired bridge never serves a stale code.
var (
	pairMu     sync.Mutex
	pairQRCode string
	pairQRAt   time.Time
)

func setPairQR(code string) {
	pairMu.Lock()
	pairQRCode = code
	pairQRAt = time.Now()
	pairMu.Unlock()
}

func clearPairQR() {
	pairMu.Lock()
	pairQRCode = ""
	pairQRAt = time.Time{}
	pairMu.Unlock()
}

// Message represents a chat message for our client
type Message struct {
	Time      time.Time
	Sender    string
	Content   string
	IsFromMe  bool
	MediaType string
	Filename  string
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

	// Open SQLite database for messages
	db, err := sql.Open("sqlite3", "file:store/messages.db?_foreign_keys=on")
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

// Store a chat in the database
func (store *MessageStore) StoreChat(jid, name string, lastMessageTime time.Time) error {
	_, err := store.db.Exec(
		"INSERT OR REPLACE INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)",
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
	Success            bool                 `json:"success"`
	Message            string               `json:"message"`
	NeedsConfirmation  bool                 `json:"needs_confirmation,omitempty"`
	ConfirmToken       string               `json:"confirm_token,omitempty"`
	Resolved           *ResolvedCandidate   `json:"resolved,omitempty"`
	OtherCandidates    []ResolvedCandidate  `json:"other_candidates,omitempty"`
}

// SendMessageRequest represents the request body for the send message API
type SendMessageRequest struct {
	Recipient    string `json:"recipient"`
	Message      string `json:"message"`
	MediaPath    string `json:"media_path,omitempty"`
	ConfirmToken string `json:"confirm_token,omitempty"`
}

// RevokeMessageRequest represents the request body for revoking ("delete for everyone") a message
type RevokeMessageRequest struct {
	ChatJID   string `json:"chat_jid"`
	MessageID string `json:"message_id"`
	SenderJID string `json:"sender_jid,omitempty"` // empty = self
}

// ResolveRecipientRequest is the request body for /api/resolve-recipient
type ResolveRecipientRequest struct {
	Query string `json:"query"`
	Limit int    `json:"limit,omitempty"`
}

// ResolveRecipientResponse is the response body for /api/resolve-recipient
type ResolveRecipientResponse struct {
	Success    bool                 `json:"success"`
	Message    string               `json:"message"`
	Candidates []ResolvedCandidate  `json:"candidates"`
}

// ResolvedCandidate is a single ranked match for a name/phone query
type ResolvedCandidate struct {
	JID             string `json:"jid"`
	PushName        string `json:"push_name,omitempty"`
	FullName        string `json:"full_name,omitempty"`
	BusinessName    string `json:"business_name,omitempty"`
	Phone           string `json:"phone,omitempty"`
	IsLid           bool   `json:"is_lid"`
	IsGroup         bool   `json:"is_group"`
	InAddressBook   bool   `json:"in_address_book"`
	HasChatHistory  bool   `json:"has_chat_history"`
	LastMessageAt   string `json:"last_message_at,omitempty"`
	ChatDisplayName string `json:"chat_display_name,omitempty"`
	Confidence      int    `json:"confidence"` // 0..100; 100 = perfect addr-book + phone match
}

// pendingSend holds an unconfirmed send waiting for a confirm-token callback
type pendingSend struct {
	Recipient string
	Message   string
	MediaPath string
	Resolved  ResolvedCandidate
	ExpiresAt time.Time
}

var (
	pendingSendsMu sync.Mutex
	pendingSends   = map[string]*pendingSend{}
)

// generateConfirmToken returns a random 16-byte hex string suitable for one-shot confirmations
func generateConfirmToken() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

// storePendingSend records a pending send and returns its token; tokens expire in 60 seconds
func storePendingSend(p *pendingSend) (string, error) {
	token, err := generateConfirmToken()
	if err != nil {
		return "", err
	}
	p.ExpiresAt = time.Now().Add(60 * time.Second)
	pendingSendsMu.Lock()
	defer pendingSendsMu.Unlock()
	// Opportunistic cleanup of expired tokens (cheap when map is small)
	for k, v := range pendingSends {
		if time.Now().After(v.ExpiresAt) {
			delete(pendingSends, k)
		}
	}
	pendingSends[token] = p
	return token, nil
}

// popPendingSend retrieves AND removes a pending send by token. Returns nil if missing or expired.
func popPendingSend(token string) *pendingSend {
	pendingSendsMu.Lock()
	defer pendingSendsMu.Unlock()
	p, ok := pendingSends[token]
	if !ok {
		return nil
	}
	delete(pendingSends, token)
	if time.Now().After(p.ExpiresAt) {
		return nil
	}
	return p
}

// Function to send a WhatsApp message
func sendWhatsAppMessage(client *whatsmeow.Client, recipient string, message string, mediaPath string) (bool, string) {
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
	_, err = client.SendMessage(context.Background(), recipientJID, msg)

	if err != nil {
		return false, fmt.Sprintf("Error sending message: %v", err)
	}

	return true, fmt.Sprintf("Message sent to %s", recipient)
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
	// Save message to database
	chatJID := msg.Info.Chat.String()
	sender := msg.Info.Sender.User

	// Get appropriate chat name (pass nil for conversation since we don't have one for regular messages)
	name := GetChatName(client, messageStore, msg.Info.Chat, chatJID, nil, sender, logger)

	// Update chat in database with the message timestamp (keeps last message time updated)
	err := messageStore.StoreChat(chatJID, name, msg.Info.Timestamp)
	if err != nil {
		logger.Warnf("Failed to store chat: %v", err)
	}

	// Extract text content
	content := extractTextContent(msg.Message)

	// Extract media info
	mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := extractMediaInfo(msg.Message)

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
	}
}

// DownloadMediaRequest represents the request body for the download media API
type DownloadMediaRequest struct {
	MessageID string `json:"message_id"`
	ChatJID   string `json:"chat_jid"`
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

	// Generate a local path for the file
	localPath = fmt.Sprintf("%s/%s", chatDir, filename)

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

	// Remove query parameters
	pathPart = strings.SplitN(pathPart, "?", 2)[0]

	// Create proper direct path format
	return "/" + pathPart
}

// resolveRecipient ranks possible recipients for a free-text query (name, partial name, or phone).
// Pulls from whatsmeow's canonical contacts store first, then falls back to the local `chats` table.
// Confidence scoring favours: address-book matches > exact phone matches > active @s.whatsapp.net chats > stale @lid chats.
func resolveRecipient(client *whatsmeow.Client, messageStore *MessageStore, query string, limit int) []ResolvedCandidate {
	if limit <= 0 {
		limit = 20
	}
	q := strings.TrimSpace(query)
	if q == "" {
		return nil
	}
	qLower := strings.ToLower(q)
	// Strip non-digits for phone matching
	qDigits := strings.Map(func(r rune) rune {
		if r >= '0' && r <= '9' {
			return r
		}
		return -1
	}, q)

	seen := map[string]*ResolvedCandidate{}

	// --- Pass 1: whatsmeow's canonical address book ---
	if client != nil && client.Store != nil && client.Store.Contacts != nil {
		contacts, err := client.Store.Contacts.GetAllContacts(context.Background())
		if err == nil {
			for jid, info := range contacts {
				jidStr := jid.String()
				phone := jid.User
				isLid := jid.Server == "lid"
				// Skip groups in resolve-recipient (groups are usually addressed by JID directly)
				if jid.Server == "g.us" {
					continue
				}
				// Check if this contact matches the query
				nameMatches := false
				for _, n := range []string{info.FullName, info.PushName, info.BusinessName, info.FirstName} {
					if n != "" && strings.Contains(strings.ToLower(n), qLower) {
						nameMatches = true
						break
					}
				}
				phoneMatches := qDigits != "" && strings.Contains(phone, qDigits)
				if !nameMatches && !phoneMatches {
					continue
				}
				cand := &ResolvedCandidate{
					JID:           jidStr,
					PushName:      info.PushName,
					FullName:      info.FullName,
					BusinessName:  info.BusinessName,
					Phone:         phone,
					IsLid:         isLid,
					InAddressBook: true,
				}
				// Confidence scoring
				cand.Confidence = 60 // base for address-book hit
				if phoneMatches {
					cand.Confidence += 30
				}
				// Exact (case-insensitive) name match is strongest signal
				for _, n := range []string{info.FullName, info.PushName, info.BusinessName, info.FirstName} {
					if n != "" && strings.EqualFold(n, q) {
						cand.Confidence += 10
						break
					}
				}
				if isLid {
					cand.Confidence -= 25 // LIDs are suspicious; prefer real phone JIDs
				}
				if cand.Confidence > 100 {
					cand.Confidence = 100
				}
				seen[jidStr] = cand
			}
		}
	}

	// --- Pass 2: local chats table (fallback / enriches with chat metadata) ---
	if messageStore != nil && messageStore.db != nil {
		searchPattern := "%" + q + "%"
		rows, err := messageStore.db.Query(`
			SELECT jid, name, last_message_time
			FROM chats
			WHERE (LOWER(name) LIKE LOWER(?) OR LOWER(jid) LIKE LOWER(?))
			  AND jid NOT LIKE '%@g.us'
			ORDER BY last_message_time DESC
			LIMIT 200
		`, searchPattern, searchPattern)
		if err == nil {
			defer rows.Close()
			for rows.Next() {
				var jidStr, name string
				var lastTime sql.NullTime
				if err := rows.Scan(&jidStr, &name, &lastTime); err != nil {
					continue
				}
				phone := jidStr
				if at := strings.Index(jidStr, "@"); at >= 0 {
					phone = jidStr[:at]
				}
				isLid := strings.HasSuffix(jidStr, "@lid")
				if existing, ok := seen[jidStr]; ok {
					// Enrich existing address-book candidate with chat metadata
					existing.HasChatHistory = true
					existing.ChatDisplayName = name
					if lastTime.Valid {
						existing.LastMessageAt = lastTime.Time.Format(time.RFC3339)
					}
					continue
				}
				// New candidate — only from chats, NOT in address book = lower confidence
				cand := &ResolvedCandidate{
					JID:             jidStr,
					ChatDisplayName: name,
					Phone:           phone,
					IsLid:           isLid,
					InAddressBook:   false,
					HasChatHistory:  true,
					Confidence:      30, // base for chat-only hit
				}
				if lastTime.Valid {
					cand.LastMessageAt = lastTime.Time.Format(time.RFC3339)
				}
				if isLid {
					cand.Confidence -= 20 // chat-only @lid is the highest-risk class
				}
				seen[jidStr] = cand
			}
		}
	}

	// --- Pass 3: if query looks like a phone number with no hits, allow direct JID candidate ---
	if len(seen) == 0 && qDigits != "" && len(qDigits) >= 7 {
		jidStr := qDigits + "@s.whatsapp.net"
		seen[jidStr] = &ResolvedCandidate{
			JID:        jidStr,
			Phone:      qDigits,
			IsLid:      false,
			Confidence: 40, // raw phone, unverified
		}
	}

	// Collect + sort by confidence desc
	out := make([]ResolvedCandidate, 0, len(seen))
	for _, c := range seen {
		out = append(out, *c)
	}
	sort.SliceStable(out, func(i, j int) bool {
		return out[i].Confidence > out[j].Confidence
	})
	if len(out) > limit {
		out = out[:limit]
	}
	return out
}

// Start a REST API server to expose the WhatsApp client functionality
func startRESTServer(client *whatsmeow.Client, messageStore *MessageStore, port int) {
	// Handler for sending messages — two-phase with confirm-token gate.
	// Phase 1 (no confirm_token): resolves the recipient, stores a pending send, returns needs_confirmation + token.
	// Phase 2 (with confirm_token): retrieves the matching pending send, dispatches it, clears the token.
	http.HandleFunc("/api/send", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req SendMessageRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}

		w.Header().Set("Content-Type", "application/json")

		// --- Phase 2: confirmation callback ---
		if req.ConfirmToken != "" {
			pending := popPendingSend(req.ConfirmToken)
			if pending == nil {
				w.WriteHeader(http.StatusUnauthorized)
				json.NewEncoder(w).Encode(SendMessageResponse{
					Success: false,
					Message: "confirm_token invalid or expired (60s TTL). Call /api/send without a token to get a fresh one.",
				})
				return
			}
			// Reject mismatched payloads — token is one-shot AND payload-bound
			if pending.Recipient != req.Recipient || pending.Message != req.Message || pending.MediaPath != req.MediaPath {
				w.WriteHeader(http.StatusBadRequest)
				json.NewEncoder(w).Encode(SendMessageResponse{
					Success: false,
					Message: "confirm_token does not match supplied payload (recipient/message/media_path changed since token was issued)",
				})
				return
			}
			fmt.Println("Confirmed send to", pending.Resolved.JID, "msg:", pending.Message)
			success, message := sendWhatsAppMessage(client, pending.Recipient, pending.Message, pending.MediaPath)
			if !success {
				w.WriteHeader(http.StatusInternalServerError)
			}
			json.NewEncoder(w).Encode(SendMessageResponse{
				Success:  success,
				Message:  message,
				Resolved: &pending.Resolved,
			})
			return
		}

		// --- Phase 1: resolve recipient + issue token ---
		if req.Recipient == "" {
			http.Error(w, "Recipient is required", http.StatusBadRequest)
			return
		}
		if req.Message == "" && req.MediaPath == "" {
			http.Error(w, "Message or media path is required", http.StatusBadRequest)
			return
		}

		// Resolve. If caller passed a raw JID, treat it as a self-resolved candidate so we still token-gate.
		var resolved ResolvedCandidate
		var others []ResolvedCandidate
		if strings.Contains(req.Recipient, "@") {
			resolved = ResolvedCandidate{
				JID:           req.Recipient,
				IsLid:         strings.HasSuffix(req.Recipient, "@lid"),
				IsGroup:       strings.HasSuffix(req.Recipient, "@g.us"),
				InAddressBook: false,
				Confidence:    50, // explicit JID, no verification
			}
			if at := strings.Index(req.Recipient, "@"); at >= 0 {
				resolved.Phone = req.Recipient[:at]
			}
		} else {
			candidates := resolveRecipient(client, messageStore, req.Recipient, 5)
			if len(candidates) == 0 {
				w.WriteHeader(http.StatusNotFound)
				json.NewEncoder(w).Encode(SendMessageResponse{
					Success: false,
					Message: fmt.Sprintf("no recipient candidates found for query %q. Call /api/resolve-recipient first or pass an explicit JID.", req.Recipient),
				})
				return
			}
			resolved = candidates[0]
			if len(candidates) > 1 {
				others = candidates[1:]
			}
		}

		// Persist pending send keyed by resolved JID so confirmation hits the SAME jid we showed the caller
		pending := &pendingSend{
			Recipient: resolved.JID,
			Message:   req.Message,
			MediaPath: req.MediaPath,
			Resolved:  resolved,
		}
		token, err := storePendingSend(pending)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(SendMessageResponse{
				Success: false,
				Message: fmt.Sprintf("failed to issue confirm token: %v", err),
			})
			return
		}

		w.WriteHeader(http.StatusAccepted)
		json.NewEncoder(w).Encode(SendMessageResponse{
			Success:           false,
			Message:           "confirmation required — re-send the SAME recipient/message/media_path with confirm_token within 60s",
			NeedsConfirmation: true,
			ConfirmToken:      token,
			Resolved:          &resolved,
			OtherCandidates:   others,
		})
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

	// Handler for revoking ("delete for everyone") a message.
	// Uses whatsmeow's client.BuildRevoke + client.SendMessage. Also drops the row from the local messages.db
	// so list_messages reflects the revoke immediately.
	http.HandleFunc("/api/revoke", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req RevokeMessageRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		if req.ChatJID == "" || req.MessageID == "" {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(SendMessageResponse{
				Success: false,
				Message: "chat_jid and message_id are required",
			})
			return
		}
		if !client.IsConnected() {
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(SendMessageResponse{
				Success: false,
				Message: "Not connected to WhatsApp",
			})
			return
		}
		chatJID, err := types.ParseJID(req.ChatJID)
		if err != nil {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(SendMessageResponse{
				Success: false,
				Message: fmt.Sprintf("invalid chat_jid: %v", err),
			})
			return
		}
		var senderJID types.JID
		if req.SenderJID != "" {
			senderJID, err = types.ParseJID(req.SenderJID)
			if err != nil {
				w.WriteHeader(http.StatusBadRequest)
				json.NewEncoder(w).Encode(SendMessageResponse{
					Success: false,
					Message: fmt.Sprintf("invalid sender_jid: %v", err),
				})
				return
			}
		} else if client.Store.ID != nil {
			// Default to our own JID — revoking our own messages
			senderJID = *client.Store.ID
		}

		revoke := client.BuildRevoke(chatJID, senderJID, types.MessageID(req.MessageID))
		_, err = client.SendMessage(context.Background(), chatJID, revoke)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(SendMessageResponse{
				Success: false,
				Message: fmt.Sprintf("revoke send failed: %v", err),
			})
			return
		}

		// Drop from local DB so list_messages reflects the revoke
		if _, dbErr := messageStore.db.Exec(
			`DELETE FROM messages WHERE id = ? AND chat_jid = ?`,
			req.MessageID, req.ChatJID,
		); dbErr != nil {
			// Log but don't fail the request — remote revoke already succeeded
			fmt.Printf("warning: local DB delete after revoke failed: %v\n", dbErr)
		}

		json.NewEncoder(w).Encode(SendMessageResponse{
			Success: true,
			Message: fmt.Sprintf("Message %s revoked in chat %s", req.MessageID, req.ChatJID),
		})
	})

	// Handler for resolving a free-text query (name/phone) to ranked recipient candidates.
	// This is the safe alternative to the old LIKE-on-chats search_contacts.
	http.HandleFunc("/api/resolve-recipient", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req ResolveRecipientRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request format", http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		if strings.TrimSpace(req.Query) == "" {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(ResolveRecipientResponse{
				Success: false,
				Message: "query is required",
			})
			return
		}
		candidates := resolveRecipient(client, messageStore, req.Query, req.Limit)
		json.NewEncoder(w).Encode(ResolveRecipientResponse{
			Success:    true,
			Message:    fmt.Sprintf("%d candidate(s) for %q", len(candidates), req.Query),
			Candidates: candidates,
		})
	})

	// Health check endpoint. This PROVES the bridge is actually serving HTTP —
	// not merely holding the port. The watchdog launchd agent probes this; if it
	// stops returning 200 (the "port held but socket dead" wedge), the watchdog
	// force-restarts the process via `launchctl kickstart -k`.
	// GET /api/qr — current pairing state for in-app QR rendering (Cave app's
	// Link-conversation setup step). While unpaired the pairing loop keeps a
	// fresh code here; once logged in the code fields go empty and logged_in
	// flips true, which is the client's signal to proceed.
	http.HandleFunc("/api/qr", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		pairMu.Lock()
		code := pairQRCode
		at := pairQRAt
		pairMu.Unlock()

		loggedIn := client.IsLoggedIn()
		resp := map[string]interface{}{
			"logged_in": loggedIn,
			"connected": client.IsConnected(),
			"qr_code":   "",
			"qr_png":    "",
		}
		if !loggedIn && code != "" {
			resp["qr_code"] = code
			resp["qr_generated_at"] = at.Format(time.RFC3339)
			// PNG as a data URL so clients can <img src> it without their own
			// QR encoder. Failure to encode degrades to the raw code string.
			if png, err := qrcode.Encode(code, qrcode.Medium, 512); err == nil {
				resp["qr_png"] = "data:image/png;base64," + base64.StdEncoding.EncodeToString(png)
			}
		}
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(resp)
	})

	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":             "ok",
			"whatsapp_connected": client.IsConnected(),
			"logged_in":          client.IsLoggedIn(),
			"uptime_seconds":     int(time.Since(processStartTime).Seconds()),
			"time":               time.Now().Format(time.RFC3339),
		})
	})

	// Start the server with explicit timeouts so a single slow/stuck client or
	// handler can't silently wedge the accept loop while leaving the port bound
	// (the classic "process alive, port held, nothing answers" failure mode).
	// SO_REUSEADDR lets a fresh instance re-bind 8080 immediately after a forced
	// restart instead of tripping over a lingering TIME_WAIT socket.
	serverAddr := fmt.Sprintf(":%d", port)
	fmt.Printf("Starting REST API server on %s...\n", serverAddr)

	lc := net.ListenConfig{
		Control: func(network, address string, c syscall.RawConn) error {
			var sockErr error
			if ctrlErr := c.Control(func(fd uintptr) {
				sockErr = syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_REUSEADDR, 1)
			}); ctrlErr != nil {
				return ctrlErr
			}
			return sockErr
		},
	}

	srv := &http.Server{
		Addr:              serverAddr,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	// Run server in a goroutine so it doesn't block. If the listener can't bind
	// or Serve dies, exit non-zero rather than lingering as a half-dead zombie —
	// launchd (KeepAlive) then restarts us cleanly.
	go func() {
		ln, err := lc.Listen(context.Background(), "tcp", serverAddr)
		if err != nil {
			fmt.Printf("REST API server listen error: %v\n", err)
			os.Exit(1)
		}
		if err := srv.Serve(ln); err != nil && err != http.ErrServerClosed {
			fmt.Printf("REST API server error: %v\n", err)
			os.Exit(1)
		}
	}()
}

// runPairingLoop drives QR pairing until it succeeds, publishing each fresh
// code to the shared pair state (for /api/qr) AND printing it to stdout (the
// pre-existing terminal flow, kept for operators pairing over SSH). Returns
// true once paired, false only on unrecoverable client errors.
func runPairingLoop(client *whatsmeow.Client, logger waLog.Logger) bool {
	defer clearPairQR()
	for attempt := 1; ; attempt++ {
		qrChan, err := client.GetQRChannel(context.Background())
		if err != nil {
			// Store gained an ID between cycles (paired via another path).
			if client.Store.ID != nil {
				return client.IsConnected() || client.Connect() == nil
			}
			logger.Errorf("Failed to get QR channel (attempt %d): %v", attempt, err)
			time.Sleep(5 * time.Second)
			continue
		}
		if err := client.Connect(); err != nil {
			logger.Errorf("Failed to connect for pairing (attempt %d): %v", attempt, err)
			time.Sleep(5 * time.Second)
			continue
		}

		success := false
		for evt := range qrChan {
			switch evt.Event {
			case "code":
				setPairQR(evt.Code)
				fmt.Println("\nScan this QR code with your WhatsApp app:")
				qrterminal.GenerateHalfBlock(evt.Code, qrterminal.L, os.Stdout)
			case "success":
				success = true
			default:
				// "timeout" / transient errors — channel is about to close;
				// the outer loop starts a fresh cycle.
			}
		}
		clearPairQR()

		if success {
			fmt.Println("\nSuccessfully connected and authenticated!")
			return true
		}
		client.Disconnect()
		logger.Warnf("QR pairing cycle %d ended without a scan — starting a fresh cycle", attempt)
		time.Sleep(2 * time.Second)
	}
}

func main() {
	// Set up logger
	logger := waLog.Stdout("Client", "INFO", true)
	logger.Infof("Starting WhatsApp client...")

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

	// Setup event handling for messages and history sync
	client.AddEventHandler(func(evt interface{}) {
		switch v := evt.(type) {
		case *events.Message:
			// Process regular messages
			handleMessage(client, messageStore, v, logger)

		case *events.HistorySync:
			// Process history sync events
			handleHistorySync(client, messageStore, v, logger)

		case *events.Connected:
			logger.Infof("Connected to WhatsApp")

		case *events.LoggedOut:
			logger.Warnf("Device logged out, please scan QR code to log in again")
		}
	})

	// Start the REST API server BEFORE pairing so GET /api/qr (and /health) are
	// reachable while the bridge is still unpaired — that's what lets the Cave
	// app render the QR code in-app instead of the operator reading stdout.
	// Handlers degrade gracefully pre-login (sends error, /health reports
	// logged_in:false), so serving early is safe.
	port := 8080
	if raw := os.Getenv("WHATSAPP_BRIDGE_PORT"); raw != "" {
		if p, perr := strconv.Atoi(raw); perr == nil && p > 0 && p < 65536 {
			port = p
		} else {
			logger.Warnf("Ignoring invalid WHATSAPP_BRIDGE_PORT=%q, using %d", raw, port)
		}
	}
	startRESTServer(client, messageStore, port)

	// Connect to WhatsApp
	if client.Store.ID == nil {
		// No ID stored — pair with phone. Loop forever: each whatsmeow QR
		// cycle lasts ~3 minutes then closes its channel; instead of dying
		// (the old behavior), disconnect and start a fresh cycle so /api/qr
		// always has a scannable code however long the user takes.
		if !runPairingLoop(client, logger) {
			return
		}
	} else {
		// Already logged in, just connect
		err = client.Connect()
		if err != nil {
			logger.Errorf("Failed to connect: %v", err)
			return
		}
	}

	// Wait a moment for connection to stabilize
	time.Sleep(2 * time.Second)

	if !client.IsConnected() {
		logger.Errorf("Failed to establish stable connection")
		return
	}

	fmt.Println("\n✓ Connected to WhatsApp! Type 'help' for commands.")

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

// GetChatName determines the appropriate name for a chat based on JID and other info
func GetChatName(client *whatsmeow.Client, messageStore *MessageStore, jid types.JID, chatJID string, conversation interface{}, sender string, logger waLog.Logger) string {
	// First, check if chat already exists in database with a name
	var existingName string
	err := messageStore.db.QueryRow("SELECT name FROM chats WHERE jid = ?", chatJID).Scan(&existingName)
	if err == nil && existingName != "" {
		// Chat exists with a name, use that
		logger.Infof("Using existing chat name for %s: %s", chatJID, existingName)
		return existingName
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

		// Just use contact info (full name)
		contact, err := client.Store.Contacts.GetContact(context.Background(), jid)
		if err == nil && contact.FullName != "" {
			name = contact.FullName
		} else if sender != "" {
			// Fallback to sender
			name = sender
		} else {
			// Last fallback to JID
			name = jid.User
		}

		logger.Infof("Using contact name: %s", name)
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
						sender = *msg.Message.Key.Participant
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
	mathrand.Seed(int64(duration))

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
		val += (mathrand.Float64() - 0.5) * 15

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
