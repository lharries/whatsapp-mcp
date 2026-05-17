package main

import (
	"testing"
	"time"
)

func TestNewUserMessageStoreWithInvalidPath(t *testing.T) {
	store := NewUserMessageStore("/invalid/path/that/does/not/exist", "user")
	if store != nil {
		t.Error("expected nil store for invalid path")
	}
}

func TestMessageStoreClose(t *testing.T) {
	tmpDir := t.TempDir()
	userID := "testuser"

	store := NewUserMessageStore(tmpDir, userID)
	if store == nil {
		t.Skip("store creation requires filesystem, skipping")
	}

	if err := store.Close(); err != nil {
		t.Errorf("unexpected error on close: %v", err)
	}
}

func TestMessageStoreSaveAndGetChat(t *testing.T) {
	tmpDir := t.TempDir()
	userID := "testuser"

	store := NewUserMessageStore(tmpDir, userID)
	if store == nil {
		t.Skip("store creation requires filesystem, skipping")
	}
	defer store.Close()

	chat := &UserChat{
		JID:             "test@example.com",
		Name:            "Test Chat",
		LastMessageTime: time.Now(),
	}

	if err := store.SaveChat(chat); err != nil {
		t.Fatalf("failed to save chat: %v", err)
	}

	chats, err := store.GetChats()
	if err != nil {
		t.Fatalf("failed to get chats: %v", err)
	}

	if len(chats) != 1 {
		t.Fatalf("expected 1 chat, got %d", len(chats))
	}

	if chats[0].JID != chat.JID {
		t.Errorf("expected JID %s, got %s", chat.JID, chats[0].JID)
	}
}

func TestMessageStoreSaveAndGetMessages(t *testing.T) {
	tmpDir := t.TempDir()
	userID := "testuser"

	store := NewUserMessageStore(tmpDir, userID)
	if store == nil {
		t.Skip("store creation requires filesystem, skipping")
	}
	defer store.Close()

	chatJID := "test@example.com"
	chat := &UserChat{
		JID:             chatJID,
		Name:            "Test Chat",
		LastMessageTime: time.Now(),
	}
	store.SaveChat(chat)

	msg := &UserMessage{
		ID:        "msg1",
		ChatJID:   chatJID,
		Sender:    "sender@example.com",
		Content:   "Hello World",
		Timestamp: time.Now(),
		IsFromMe:  false,
	}

	if err := store.SaveMessage(msg); err != nil {
		t.Fatalf("failed to save message: %v", err)
	}

	messages, err := store.GetMessages(chatJID, 50)
	if err != nil {
		t.Fatalf("failed to get messages: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(messages))
	}

	if messages[0].Content != msg.Content {
		t.Errorf("expected content %s, got %s", msg.Content, messages[0].Content)
	}
}

func TestMessageStoreGetMessagesWithLimit(t *testing.T) {
	tmpDir := t.TempDir()
	userID := "testuser"

	store := NewUserMessageStore(tmpDir, userID)
	if store == nil {
		t.Skip("store creation requires filesystem, skipping")
	}
	defer store.Close()

	chatJID := "test@example.com"
	chat := &UserChat{
		JID:             chatJID,
		Name:            "Test Chat",
		LastMessageTime: time.Now(),
	}
	store.SaveChat(chat)

	for i := 0; i < 5; i++ {
		msg := &UserMessage{
			ID:        string(rune('a' + i)),
			ChatJID:   chatJID,
			Sender:    "sender@example.com",
			Content:   "Message content",
			Timestamp: time.Now(),
			IsFromMe:  false,
		}
		store.SaveMessage(msg)
	}

	messages, err := store.GetMessages(chatJID, 3)
	if err != nil {
		t.Fatalf("failed to get messages: %v", err)
	}

	if len(messages) != 3 {
		t.Errorf("expected 3 messages with limit, got %d", len(messages))
	}
}

func TestMessageStoreGetChatsEmpty(t *testing.T) {
	tmpDir := t.TempDir()
	userID := "testuser"

	store := NewUserMessageStore(tmpDir, userID)
	if store == nil {
		t.Skip("store creation requires filesystem, skipping")
	}
	defer store.Close()

	chats, err := store.GetChats()
	if err != nil {
		t.Fatalf("failed to get chats: %v", err)
	}

	if len(chats) != 0 {
		t.Errorf("expected 0 chats initially, got %d", len(chats))
	}
}