package main

import (
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
)

type QRCodeEvent struct {
	UserID    string
	ImageData string
	ExpiresAt time.Time
}

type UserClient struct {
	UserID       string
	Username     string
	Client       *whatsmeow.Client
	MessageStore *UserMessageStore
	Status       string
	StopChan     chan struct{}
	QRChan       chan *QRCodeEvent
	mu           sync.RWMutex
}

func NewUserClient(userID, username string, store *UserMessageStore) *UserClient {
	return &UserClient{
		UserID:       userID,
		Username:     username,
		MessageStore: store,
		Status:       "pending_init_request",
		StopChan:     make(chan struct{}),
		QRChan:       make(chan *QRCodeEvent, 1),
	}
}

func (uc *UserClient) SetStatus(status string) {
	uc.mu.Lock()
	defer uc.mu.Unlock()
	uc.Status = status
}

func (uc *UserClient) GetStatus() string {
	uc.mu.RLock()
	defer uc.mu.RUnlock()
	return uc.Status
}

func (uc *UserClient) Stop() {
	close(uc.StopChan)
}

type UserInfo struct {
	ID          int    `json:"id"`
	Username    string `json:"username"`
	Status      string `json:"status"`
	WhatsAppJID string `json:"whatsapp_jid"`
	CreatedAt   string `json:"created_at"`
	UpdatedAt   string `json:"updated_at"`
}