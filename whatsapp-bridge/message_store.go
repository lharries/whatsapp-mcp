package main

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type UserMessageStore struct {
	db     *sql.DB
	userID string
	mu     sync.RWMutex
}

func NewUserMessageStore(basePath, userID string) *UserMessageStore {
	storeDir := filepath.Join(basePath, userID)
	if err := os.MkdirAll(storeDir, 0755); err != nil {
		return nil
	}

	dbPath := filepath.Join(storeDir, "messages.db")
	db, err := sql.Open("sqlite3", "file:"+dbPath)
	if err != nil {
		return nil
	}

	ms := &UserMessageStore{
		db:     db,
		userID: userID,
	}

	if err := ms.initTables(); err != nil {
		db.Close()
		return nil
	}

	return ms
}

func (ms *UserMessageStore) initTables() error {
	_, err := ms.db.Exec(`
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
	return err
}

func (ms *UserMessageStore) Close() error {
	if ms == nil || ms.db == nil {
		return nil
	}
	return ms.db.Close()
}

func (ms *UserMessageStore) GetChats() ([]UserChat, error) {
	ms.mu.RLock()
	defer ms.mu.RUnlock()

	rows, err := ms.db.Query("SELECT jid, name, last_message_time FROM chats ORDER BY last_message_time DESC")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var chats []UserChat
	for rows.Next() {
		var c UserChat
		if err := rows.Scan(&c.JID, &c.Name, &c.LastMessageTime); err != nil {
			return nil, err
		}
		chats = append(chats, c)
	}
	return chats, nil
}

func (ms *UserMessageStore) GetMessages(chatJID string, limit int) ([]UserMessage, error) {
	ms.mu.RLock()
	defer ms.mu.RUnlock()

	if limit <= 0 {
		limit = 50
	}

	query := `
		SELECT id, chat_jid, sender, content, timestamp, is_from_me,
		       media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length
		FROM messages
		WHERE chat_jid = ?
		ORDER BY timestamp DESC
		LIMIT ?
	`

	rows, err := ms.db.Query(query, chatJID, limit)
	if err != nil {
		return nil, fmt.Errorf("failed to query messages: %w", err)
	}
	defer rows.Close()

	var messages []UserMessage
	for rows.Next() {
		var m UserMessage
		if err := rows.Scan(
			&m.ID, &m.ChatJID, &m.Sender, &m.Content, &m.Timestamp, &m.IsFromMe,
			&m.MediaType, &m.Filename, &m.URL, &m.MediaKey, &m.FileSHA256, &m.FileEncSHA2, &m.FileLength,
		); err != nil {
			return nil, fmt.Errorf("failed to scan message: %w", err)
		}
		messages = append(messages, m)
	}
	return messages, nil
}

func (ms *UserMessageStore) SaveMessage(m *UserMessage) error {
	ms.mu.Lock()
	defer ms.mu.Unlock()

	_, err := ms.db.Exec(`
		INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(id, chat_jid) DO UPDATE SET
			content = excluded.content,
			timestamp = excluded.timestamp
	`, m.ID, m.ChatJID, m.Sender, m.Content, m.Timestamp, m.IsFromMe, m.MediaType, m.Filename, m.URL, m.MediaKey, m.FileSHA256, m.FileEncSHA2, m.FileLength)

	return err
}

func (ms *UserMessageStore) SaveChat(c *UserChat) error {
	ms.mu.Lock()
	defer ms.mu.Unlock()

	_, err := ms.db.Exec(`
		INSERT INTO chats (jid, name, last_message_time)
		VALUES (?, ?, ?)
		ON CONFLICT(jid) DO UPDATE SET
			name = excluded.name,
			last_message_time = excluded.last_message_time
	`, c.JID, c.Name, c.LastMessageTime)

	return err
}

type UserChat struct {
	JID             string
	Name            string
	LastMessageTime time.Time
}

type UserMessage struct {
	ID          string
	ChatJID     string
	Sender      string
	Content     string
	Timestamp   time.Time
	IsFromMe    bool
	MediaType   string
	Filename    string
	URL         string
	MediaKey    []byte
	FileSHA256  []byte
	FileEncSHA2 []byte
	FileLength  int64
}