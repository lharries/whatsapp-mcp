package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestDjangoAPIClientConstruction(t *testing.T) {
	client := NewDjangoAPIClient("http://django:8000", "test-service-key")

	if client.baseURL != "http://django:8000" {
		t.Errorf("expected baseURL http://django:8000, got %s", client.baseURL)
	}
	if client.serviceKey != "test-service-key" {
		t.Errorf("expected serviceKey test-service-key, got %s", client.serviceKey)
	}
	if client.httpClient == nil {
		t.Error("expected httpClient to be initialized")
	}
	if client.httpClient.Timeout != 30*time.Second {
		t.Error("expected default timeout of 30 seconds")
	}
}

const defaultTimeout = 1e9

func TestNewRequestWithBody(t *testing.T) {
	client := NewDjangoAPIClient("http://django:8000", "test-key")

	req, err := client.newRequest(http.MethodPost, "/api/test/", map[string]string{"key": "value"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if req.Method != http.MethodPost {
		t.Errorf("expected POST method, got %s", req.Method)
	}

	if req.Header.Get("X-Service-Key") != "test-key" {
		t.Errorf("expected X-Service-Key header to be test-key, got %s", req.Header.Get("X-Service-Key"))
	}

	if req.Header.Get("Content-Type") != "application/json" {
		t.Errorf("expected Content-Type to be application/json, got %s", req.Header.Get("Content-Type"))
	}
}

func TestNewRequestWithoutBody(t *testing.T) {
	client := NewDjangoAPIClient("http://django:8000", "test-key")

	req, err := client.newRequest(http.MethodGet, "/api/test/", nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if req.Method != http.MethodGet {
		t.Errorf("expected GET method, got %s", req.Method)
	}

	if req.Header.Get("X-Service-Key") != "test-key" {
		t.Errorf("expected X-Service-Key header to be test-key, got %s", req.Header.Get("X-Service-Key"))
	}
}

func TestGetUsersEndpoint(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/users/" {
			t.Errorf("expected path /api/users/, got %s", r.URL.Path)
		}
		if r.Header.Get("X-Service-Key") != "test-key" {
			t.Errorf("expected X-Service-Key header test-key, got %s", r.Header.Get("X-Service-Key"))
		}
		w.Write([]byte(`{"results":[{"id":1,"username":"testuser","status":"pending_init_request"}]}`))
	}))
	defer server.Close()

	client := NewDjangoAPIClient(server.URL, "test-key")
	users, err := client.GetUsers(context.Background())

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(users) != 1 {
		t.Fatalf("expected 1 user, got %d", len(users))
	}

	if users[0].Username != "testuser" {
		t.Errorf("expected username testuser, got %s", users[0].Username)
	}
}

func TestGetUsersUnauthorized(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer server.Close()

	client := NewDjangoAPIClient(server.URL, "wrong-key")
	_, err := client.GetUsers(context.Background())

	if err == nil {
		t.Error("expected error for unauthorized request")
	}
}

func TestPushQRBuildsCorrectRequest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/users/1/qr/" {
			t.Errorf("expected path /api/users/1/qr/, got %s", r.URL.Path)
		}
		if r.Method != http.MethodPatch {
			t.Errorf("expected PATCH method, got %s", r.Method)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := NewDjangoAPIClient(server.URL, "test-key")
	err := client.PushQR(context.Background(), 1, "base64data", time.Now().Add(5*time.Minute))

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestUpdateUserStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/users/1/" {
			t.Errorf("expected path /api/users/1/, got %s", r.URL.Path)
		}
		if r.Method != http.MethodPatch {
			t.Errorf("expected PATCH method, got %s", r.Method)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := NewDjangoAPIClient(server.URL, "test-key")
	err := client.UpdateUserStatus(context.Background(), 1, "connected")

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}