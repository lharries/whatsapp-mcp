package main

import (
	"path/filepath"
	"testing"
	"time"
)

func TestNewBridgeConfig(t *testing.T) {
	config := &Config{
		DjangoURL:    "http://django:8000",
		JWTSecret:    "test-secret",
		ServiceKey:   "test-key",
		PollInterval: 60 * time.Second,
		MaxUsers:     5,
		LogLevel:     "INFO",
		Port:         8080,
		StorePath:    "store",
	}

	bridge := NewBridge(config, nil)

	if bridge.DjangoURL != config.DjangoURL {
		t.Errorf("expected DjangoURL %s, got %s", config.DjangoURL, bridge.DjangoURL)
	}
	if bridge.MaxUsers != config.MaxUsers {
		t.Errorf("expected MaxUsers %d, got %d", config.MaxUsers, bridge.MaxUsers)
	}
	if len(bridge.users) != 0 {
		t.Errorf("expected empty users map, got %d users", len(bridge.users))
	}
}

func TestBridgeUserCount(t *testing.T) {
	bridge := &Bridge{
		users: make(map[string]*UserClient),
	}

	if bridge.UserCount() != 0 {
		t.Errorf("expected 0 users, got %d", bridge.UserCount())
	}

	bridge.users["1"] = &UserClient{UserID: "1"}
	bridge.users["2"] = &UserClient{UserID: "2"}

	if bridge.UserCount() != 2 {
		t.Errorf("expected 2 users, got %d", bridge.UserCount())
	}
}

func TestBridgeHasCapacity(t *testing.T) {
	bridge := &Bridge{
		MaxUsers: 2,
		users:    make(map[string]*UserClient),
	}

	if !bridge.HasCapacity() {
		t.Error("expected HasCapacity to be true with 0 users")
	}

	bridge.users["1"] = &UserClient{UserID: "1"}

	if !bridge.HasCapacity() {
		t.Error("expected HasCapacity to be true with 1 user")
	}

	bridge.users["2"] = &UserClient{UserID: "2"}

	if bridge.HasCapacity() {
		t.Error("expected HasCapacity to be false with 2 users (max 2)")
	}
}

func TestBridgeRemoveUser(t *testing.T) {
	bridge := &Bridge{
		users: make(map[string]*UserClient),
	}

	uc := &UserClient{
		UserID: "1",
		StopChan: make(chan struct{}),
	}
	bridge.users["1"] = uc

	bridge.removeUser("1")

	if len(bridge.users) != 0 {
		t.Errorf("expected 0 users after remove, got %d", len(bridge.users))
	}
}

func TestUserMessageStorePath(t *testing.T) {
	basePath := "store"
	userID := "testuser"

	path := filepath.Join(basePath, userID, "messages.db")

	expected := "store" + string(filepath.Separator) + "testuser" + string(filepath.Separator) + "messages.db"
	if path != expected {
		t.Errorf("expected path %s, got %s", expected, path)
	}
}

func TestValidateUserIDInBridge(t *testing.T) {
	tests := []struct {
		userID string
		valid  bool
	}{
		{"1", true},
		{"123", true},
		{"abc", true},
		{"test-user", true},
		{"test_user", true},
	}

	for _, tc := range tests {
		err := ValidateUserID(tc.userID)
		if tc.valid && err != nil {
			t.Errorf("expected %s to be valid, got error: %v", tc.userID, err)
		}
		if !tc.valid && err == nil {
			t.Errorf("expected %s to be invalid", tc.userID)
		}
	}
}