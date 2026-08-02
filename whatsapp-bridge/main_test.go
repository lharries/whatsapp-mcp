package main

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
)

// fakeWAClient implements whatsAppSender for tests, without needing a real
// WhatsApp connection.
type fakeWAClient struct {
	connected bool

	uploadResp whatsmeow.UploadResponse
	uploadErr  error

	sendErr error

	downloadData []byte
	downloadErr  error
}

func (f *fakeWAClient) IsConnected() bool { return f.connected }

func (f *fakeWAClient) Upload(_ context.Context, _ []byte, _ whatsmeow.MediaType) (whatsmeow.UploadResponse, error) {
	return f.uploadResp, f.uploadErr
}

func (f *fakeWAClient) SendMessage(_ context.Context, _ types.JID, _ *waProto.Message, _ ...whatsmeow.SendRequestExtra) (whatsmeow.SendResponse, error) {
	return whatsmeow.SendResponse{}, f.sendErr
}

func (f *fakeWAClient) Download(_ context.Context, _ whatsmeow.DownloadableMessage) ([]byte, error) {
	return f.downloadData, f.downloadErr
}

// ---------------------------------------------------------------------
// F-02: media_path traversal / arbitrary file read
// ---------------------------------------------------------------------

func TestResolveMediaPath_RejectsUnsafePaths(t *testing.T) {
	root := t.TempDir()

	// File used as the target of a symlink that lives inside root but
	// points outside of it.
	outsideDir := t.TempDir()
	outsideFile := filepath.Join(outsideDir, "secret.txt")
	if err := os.WriteFile(outsideFile, []byte("secret"), 0o600); err != nil {
		t.Fatalf("failed to prepare outside file: %v", err)
	}

	symlinkPath := filepath.Join(root, "link-out")
	symlinkSupported := true
	if err := os.Symlink(outsideFile, symlinkPath); err != nil {
		symlinkSupported = false
	}

	oversizedPath := filepath.Join(root, "oversized.bin")
	f, err := os.Create(oversizedPath)
	if err != nil {
		t.Fatalf("failed to create oversized file: %v", err)
	}
	if err := f.Truncate(maxMediaFileSize + 1); err != nil {
		f.Close()
		t.Fatalf("failed to truncate oversized file: %v", err)
	}
	f.Close()

	cases := []struct {
		name string
		path string
	}{
		{"absolute path outside root", "/etc/hostname"},
		{"parent directory traversal", "../../etc/passwd"},
		{"device file outside root", "/dev/zero"},
		{"file above size cap", "oversized.bin"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := resolveMediaPath(root, tc.path); err == nil {
				t.Fatalf("expected resolveMediaPath(%q) to be rejected, got nil error", tc.path)
			}
		})
	}

	t.Run("symlink escaping root", func(t *testing.T) {
		if !symlinkSupported {
			t.Skip("symlinks not supported in this environment")
		}
		if _, err := resolveMediaPath(root, "link-out"); err == nil {
			t.Fatalf("expected symlink to be rejected")
		}
	})
}

func TestResolveMediaPath_RejectsNonRegularFile(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("unix sockets behave differently on windows")
	}

	root := t.TempDir()
	sockPath := filepath.Join(root, "sock")
	ln, err := net.Listen("unix", sockPath)
	if err != nil {
		t.Skipf("unix sockets not supported in this environment: %v", err)
	}
	defer ln.Close()

	if _, err := resolveMediaPath(root, "sock"); err == nil {
		t.Fatalf("expected non-regular file to be rejected")
	}
}

func TestResolveMediaPath_AcceptsLegitimateFileInsideRoot(t *testing.T) {
	root := t.TempDir()
	filePath := filepath.Join(root, "photo.jpg")
	if err := os.WriteFile(filePath, []byte("fake-image-bytes"), 0o600); err != nil {
		t.Fatalf("failed to create test file: %v", err)
	}

	got, err := resolveMediaPath(root, "photo.jpg")
	if err != nil {
		t.Fatalf("expected legitimate path to be accepted, got error: %v", err)
	}

	wantAbs, err := filepath.Abs(filePath)
	if err != nil {
		t.Fatalf("failed to compute expected path: %v", err)
	}
	if got != filepath.Clean(wantAbs) {
		t.Fatalf("got %q, want %q", got, wantAbs)
	}
}

func TestSendWhatsAppMessage_RejectsMediaPathOutsideRoot(t *testing.T) {
	root := t.TempDir()
	orig := allowedMediaRoot
	allowedMediaRoot = root
	defer func() { allowedMediaRoot = orig }()

	fake := &fakeWAClient{connected: true}
	success, message := sendWhatsAppMessage(fake, "123@s.whatsapp.net", "hi", "/etc/hostname")
	if success {
		t.Fatalf("expected failure for malicious media path")
	}
	if strings.Contains(message, "/etc/hostname") || strings.Contains(message, "no such file") {
		t.Fatalf("response message leaks path details: %q", message)
	}
}

// ---------------------------------------------------------------------
// F-01: authentication
// ---------------------------------------------------------------------

func TestRequireAuth(t *testing.T) {
	const token = "s3cr3t"
	handler := requireAuth(token, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	tests := []struct {
		name       string
		header     string
		wantStatus int
	}{
		{"missing header", "", http.StatusUnauthorized},
		{"wrong token", "Bearer wrong-token", http.StatusUnauthorized},
		{"correct token", "Bearer " + token, http.StatusOK},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/api/send", nil)
			if tc.header != "" {
				req.Header.Set("Authorization", tc.header)
			}
			rec := httptest.NewRecorder()
			handler(rec, req)
			if rec.Code != tc.wantStatus {
				t.Fatalf("got status %d, want %d", rec.Code, tc.wantStatus)
			}
		})
	}
}

func TestStartRESTServer_RequiresToken(t *testing.T) {
	store, err := NewMessageStoreAt(t.TempDir())
	if err != nil {
		t.Fatalf("failed to create message store: %v", err)
	}
	defer store.Close()

	fake := &fakeWAClient{connected: true}
	if err := startRESTServer(fake, store, "127.0.0.1:0", ""); err == nil {
		t.Fatal("expected startRESTServer to refuse to start without WHATSAPP_BRIDGE_TOKEN")
	}
}

// ---------------------------------------------------------------------
// F-03 / F-01 / F-07: handler-level behavior (auth, body size, sanitized errors)
// ---------------------------------------------------------------------

func TestSendHandler_AuthAndBodyLimit(t *testing.T) {
	store, err := NewMessageStoreAt(t.TempDir())
	if err != nil {
		t.Fatalf("failed to create message store: %v", err)
	}
	defer store.Close()

	fake := &fakeWAClient{connected: true}
	const token = "test-token"
	mux := buildRESTMux(fake, store, token)

	t.Run("missing auth header rejected", func(t *testing.T) {
		body := strings.NewReader(`{"recipient":"123","message":"hi"}`)
		req := httptest.NewRequest(http.MethodPost, "/api/send", body)
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("got %d, want 401", rec.Code)
		}
	})

	t.Run("wrong token rejected", func(t *testing.T) {
		body := strings.NewReader(`{"recipient":"123","message":"hi"}`)
		req := httptest.NewRequest(http.MethodPost, "/api/send", body)
		req.Header.Set("Authorization", "Bearer nope")
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("got %d, want 401", rec.Code)
		}
	})

	t.Run("correct token accepted", func(t *testing.T) {
		body := strings.NewReader(`{"recipient":"123","message":"hi"}`)
		req := httptest.NewRequest(http.MethodPost, "/api/send", body)
		req.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("got %d, want 200, body=%s", rec.Code, rec.Body.String())
		}
		var resp SendMessageResponse
		if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
			t.Fatalf("failed to decode response: %v", err)
		}
		if !resp.Success {
			t.Fatalf("expected success, got message=%q", resp.Message)
		}
	})

	t.Run("body over 1MB rejected", func(t *testing.T) {
		oversized := `{"recipient":"123","message":"` + strings.Repeat("a", 2*1024*1024) + `"}`
		req := httptest.NewRequest(http.MethodPost, "/api/send", strings.NewReader(oversized))
		req.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("got %d, want 400 for oversized body", rec.Code)
		}
	})
}

func TestErrorMessagesAreSanitized(t *testing.T) {
	store, err := NewMessageStoreAt(t.TempDir())
	if err != nil {
		t.Fatalf("failed to create message store: %v", err)
	}
	defer store.Close()

	fake := &fakeWAClient{connected: true}
	const token = "test-token"
	mux := buildRESTMux(fake, store, token)

	t.Run("download of unknown message does not leak sql details", func(t *testing.T) {
		body := `{"message_id":"does-not-exist","chat_jid":"1@s.whatsapp.net"}`
		req := httptest.NewRequest(http.MethodPost, "/api/download", strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)

		respBody := rec.Body.String()
		if strings.Contains(respBody, "sql:") {
			t.Fatalf("response leaks sql error detail: %s", respBody)
		}
	})

	t.Run("send with malicious media_path does not leak filesystem details", func(t *testing.T) {
		body := `{"recipient":"123","message":"hi","media_path":"/etc/hostname"}`
		req := httptest.NewRequest(http.MethodPost, "/api/send", strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)

		respBody := rec.Body.String()
		if strings.Contains(respBody, "/etc/hostname") || strings.Contains(respBody, "sql:") {
			t.Fatalf("response leaks path/sql detail: %s", respBody)
		}
	})
}

// ---------------------------------------------------------------------
// Data layer: WAL mode, indices, connection pool
// ---------------------------------------------------------------------

func TestMessageStoreSchema_CreatesExpectedIndicesAndPragmas(t *testing.T) {
	store, err := NewMessageStoreAt(t.TempDir())
	if err != nil {
		t.Fatalf("failed to create message store: %v", err)
	}
	defer store.Close()

	wantIndices := []string{"idx_messages_chat_time", "idx_chats_last_message_time"}
	for _, name := range wantIndices {
		var found string
		err := store.db.QueryRow("SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?", name).Scan(&found)
		if err != nil {
			t.Fatalf("expected index %q to exist: %v", name, err)
		}
	}

	var journalMode string
	if err := store.db.QueryRow("PRAGMA journal_mode;").Scan(&journalMode); err != nil {
		t.Fatalf("failed to read journal_mode: %v", err)
	}
	if !strings.EqualFold(journalMode, "wal") {
		t.Fatalf("got journal_mode=%q, want wal", journalMode)
	}

	stats := store.db.Stats()
	if stats.MaxOpenConnections != 4 {
		t.Fatalf("got MaxOpenConnections=%d, want 4", stats.MaxOpenConnections)
	}
}
