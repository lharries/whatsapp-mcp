package main

import (
	"context"
	"fmt"
	"sync"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"
)

type Bridge struct {
	DjangoURL    string
	JWTSecret    string
	ServiceKey   string
	PollInterval time.Duration
	MaxUsers     int
	users        map[string]*UserClient
	mu           sync.RWMutex
	api          *DjangoAPIClient
	stopChan     chan struct{}
	logger       waLog.Logger
}

func NewBridge(config *Config, logger waLog.Logger) *Bridge {
	return &Bridge{
		DjangoURL:    config.DjangoURL,
		JWTSecret:    config.JWTSecret,
		ServiceKey:   config.ServiceKey,
		PollInterval: config.PollInterval,
		MaxUsers:     config.MaxUsers,
		users:        make(map[string]*UserClient),
		api:          NewDjangoAPIClient(config.DjangoURL, config.ServiceKey),
		stopChan:     make(chan struct{}),
		logger:       logger,
	}
}

func (b *Bridge) Start(ctx context.Context) error {
	ticker := time.NewTicker(b.PollInterval)
	defer ticker.Stop()

	b.pollUsers(ctx)

	for {
		select {
		case <-b.stopChan:
			return nil
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			b.pollUsers(ctx)
		}
	}
}

func (b *Bridge) Stop() {
	close(b.stopChan)
}

func (b *Bridge) pollUsers(ctx context.Context) {
	users, err := b.api.GetUsers(ctx)
	if err != nil {
		return
	}

	b.mu.Lock()
	defer b.mu.Unlock()

	currentUsers := make(map[string]bool)
	for _, user := range users {
		userID := fmt.Sprintf("%d", user.ID)
		currentUsers[userID] = true

		if _, exists := b.users[userID]; !exists {
			if len(b.users) >= b.MaxUsers {
				continue
			}
			b.addUser(user)
		} else {
			b.updateUser(user)
		}
	}

	for userID := range b.users {
		if !currentUsers[userID] {
			b.removeUser(userID)
		}
	}
}

func (b *Bridge) addUser(user UserInfo) {
	userID := fmt.Sprintf("%d", user.ID)
	store := NewUserMessageStore("store", userID)
	uc := NewUserClient(userID, user.Username, store)
	uc.SetStatus(user.Status)

	if err := b.initUserClient(uc); err != nil {
		b.logger.Errorf("Failed to init user client for %s: %v", userID, err)
		return
	}

	b.users[userID] = uc

	ctx := context.Background()
	go b.StartUserHandler(ctx, uc)

	b.logger.Infof("Added user: %s (username: %s)", userID, user.Username)
}

func (b *Bridge) updateUser(user UserInfo) {
	userID := fmt.Sprintf("%d", user.ID)
	if uc, ok := b.users[userID]; ok {
		uc.SetStatus(user.Status)
	}
}

func (b *Bridge) removeUser(userID string) {
	if uc, ok := b.users[userID]; ok {
		uc.Stop()
		if uc.MessageStore != nil {
			uc.MessageStore.Close()
		}
		delete(b.users, userID)
	}
}

func (b *Bridge) GetUser(userID string) (*UserClient, bool) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	uc, ok := b.users[userID]
	return uc, ok
}

func (b *Bridge) UserCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.users)
}

func (b *Bridge) HasCapacity() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.users) < b.MaxUsers
}