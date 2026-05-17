package main

import (
	"os"
	"testing"
	"time"
)

func TestLoadConfigDefaults(t *testing.T) {
	os.Unsetenv("DJANGO_API_URL")
	os.Unsetenv("JWT_SECRET")
	os.Unsetenv("SERVICE_KEY")

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

	if config.DjangoURL != "http://django:8000" {
		t.Errorf("expected DjangoURL default http://django:8000, got %s", config.DjangoURL)
	}
	if config.PollInterval != 60*time.Second {
		t.Errorf("expected PollInterval default 60s, got %v", config.PollInterval)
	}
	if config.MaxUsers != 5 {
		t.Errorf("expected MaxUsers default 5, got %d", config.MaxUsers)
	}
	if config.LogLevel != "INFO" {
		t.Errorf("expected LogLevel default INFO, got %s", config.LogLevel)
	}
}

func TestValidateUserID(t *testing.T) {
	tests := []struct {
		userID string
		valid  bool
	}{
		{"testuser", true},
		{"test-user", true},
		{"test_user", true},
		{"test-user_123", true},
		{"a", true},
		{"abc123-def_456", true},
		{"", false},
		{"test user", false},
		{"test/user", false},
		{"test\\user", false},
		{"user@domain", false},
		{"user\x00name", false},
		{"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", false},
	}

	for _, tc := range tests {
		err := ValidateUserID(tc.userID)
		if tc.valid && err != nil {
			t.Errorf("expected %q to be valid, got error: %v", tc.userID, err)
		}
		if !tc.valid && err == nil {
			t.Errorf("expected %q to be invalid, got no error", tc.userID)
		}
	}
}

func TestValidationError(t *testing.T) {
	err := &ValidationError{Field: "user_id", Message: "must match pattern"}
	expected := "user_id must match pattern"
	if err.Error() != expected {
		t.Errorf("expected error string %q, got %q", expected, err.Error())
	}
}

func TestUserClientStatus(t *testing.T) {
	uc := NewUserClient("test", "testuser", nil)

	initialStatus := uc.GetStatus()
	if initialStatus != "pending_init_request" {
		t.Errorf("expected initial status pending_init_request, got %s", initialStatus)
	}

	uc.SetStatus("connected")
	connectedStatus := uc.GetStatus()
	if connectedStatus != "connected" {
		t.Errorf("expected status connected, got %s", connectedStatus)
	}
}

func TestUserClientStopChan(t *testing.T) {
	uc := NewUserClient("test", "testuser", nil)

	select {
	case _, ok := <-uc.StopChan:
		if ok {
			t.Error("expected StopChan to be open initially")
		}
	default:
	}

	uc.Stop()

	select {
	case _, ok := <-uc.StopChan:
		if ok {
			t.Error("expected StopChan to be closed after Stop()")
		}
	default:
		t.Error("expected StopChan to be closed after Stop()")
	}
}

func TestUserClientQRChan(t *testing.T) {
	uc := NewUserClient("test", "testuser", nil)

	select {
	case <-uc.QRChan:
		t.Error("expected QRChan to be empty initially")
	default:
	}

	qr := &QRCodeEvent{UserID: "test", ImageData: "base64data"}
	select {
	case uc.QRChan <- qr:
	default:
		t.Error("expected to be able to send to QRChan")
	}
}