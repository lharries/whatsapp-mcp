package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"testing"
	"time"
)

const testToken = "0123456789abcdef0123456789abcdef"
const testHost = "127.0.0.1:18765"

func testAPI(t *testing.T, actions apiActions) http.Handler {
	t.Helper()
	h, err := newAPIHandler(testToken, testHost, actions)
	if err != nil {
		t.Fatal(err)
	}
	return h
}

func testRequest(method, path, body string) *http.Request {
	r := httptest.NewRequest(method, "http://"+testHost+path, strings.NewReader(body))
	r.Header.Set("Authorization", "Bearer "+testToken)
	r.Header.Set("Content-Type", "application/json")
	return r
}

func countingActions(calls *int) apiActions {
	return apiActions{
		send: func(string, string, string) (bool, string) {
			*calls++
			return true, "sent"
		},
		download: func(string, string) (bool, string, string, string, error) {
			*calls++
			return true, "document", "report.pdf", "safe/report.pdf", nil
		},
		status: func() any {
			*calls++
			return map[string]any{"connected": true, "paired": true}
		},
	}
}

func TestAPIAuthenticationProtectsEveryRoute(t *testing.T) {
	routes := []struct{ method, path, body string }{
		{http.MethodPost, "/api/send", `{"recipient":"123","message":"hello"}`},
		{http.MethodPost, "/api/download", `{"message_id":"id","chat_jid":"chat"}`},
		{http.MethodGet, "/api/status", ""},
	}
	for _, route := range routes {
		for _, auth := range []string{"missing", "wrong", "duplicate", "comma-combined"} {
			t.Run(route.path+"/"+auth, func(t *testing.T) {
				calls := 0
				h := testAPI(t, countingActions(&calls))
				r := testRequest(route.method, route.path, route.body)
				switch auth {
				case "missing":
					r.Header.Del("Authorization")
				case "wrong":
					r.Header.Set("Authorization", "Bearer "+strings.Repeat("x", 32))
				case "duplicate":
					r.Header.Add("Authorization", "Bearer "+testToken)
				case "comma-combined":
					r.Header.Set("Authorization", "Bearer "+testToken+", Bearer "+testToken)
				}
				w := httptest.NewRecorder()
				h.ServeHTTP(w, r)
				if w.Code != http.StatusUnauthorized || calls != 0 {
					t.Fatalf("status=%d calls=%d body=%q", w.Code, calls, w.Body.String())
				}
				if w.Header().Get("Cache-Control") != "no-store" {
					t.Fatal("response permits caching")
				}
			})
		}
	}
}

func TestAPIValidRequestsPreserveArgumentsAndResponses(t *testing.T) {
	calls := [3]int{}
	h := testAPI(t, apiActions{
		send: func(recipient, message, path string) (bool, string) {
			calls[0]++
			if recipient != "123@g.us" || message != "Hello 世界" || path != `C:\approved\report.pdf` {
				t.Errorf("changed send arguments: %q %q %q", recipient, message, path)
			}
			return true, "Message sent"
		},
		download: func(id, chat string) (bool, string, string, string, error) {
			calls[1]++
			if id != "message-1" || chat != "123@g.us" {
				t.Errorf("changed download arguments: %q %q", id, chat)
			}
			return true, "document", "Résumé.pdf", `C:\safe\cached.pdf`, nil
		},
		status: func() any {
			calls[2]++
			return map[string]any{"connected": true, "paired": false, "qr_code": "test-pairing-data"}
		},
	})
	for _, tc := range []struct {
		method, path, body string
		want               map[string]any
	}{
		{http.MethodPost, "/api/send", `{"recipient":"123@g.us","message":"Hello 世界","media_path":"C:\\approved\\report.pdf"}`, map[string]any{"success": true, "message": "Message sent"}},
		{http.MethodPost, "/api/download", `{"message_id":"message-1","chat_jid":"123@g.us"}`, map[string]any{"success": true, "filename": "Résumé.pdf", "path": `C:\safe\cached.pdf`}},
		{http.MethodGet, "/api/status", "", map[string]any{"connected": true, "paired": false, "qr_code": "test-pairing-data"}},
	} {
		t.Run(tc.path, func(t *testing.T) {
			w := httptest.NewRecorder()
			h.ServeHTTP(w, testRequest(tc.method, tc.path, tc.body))
			if w.Code != http.StatusOK {
				t.Fatalf("status=%d body=%q", w.Code, w.Body.String())
			}
			var got map[string]any
			if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
				t.Fatal(err)
			}
			for key, want := range tc.want {
				if got[key] != want {
					t.Errorf("%s=%v, want %v", key, got[key], want)
				}
			}
			if w.Header().Get("Cache-Control") != "no-store" {
				t.Fatal("response permits caching")
			}
		})
	}
	if calls != [3]int{1, 1, 1} {
		t.Fatalf("unexpected action counts: %v", calls)
	}
}

func TestAPIRejectsHostOriginContentTypeAndMethod(t *testing.T) {
	for _, path := range []string{"/api/send", "/api/download", "/api/status"} {
		for _, tc := range []struct {
			name string
			edit func(*http.Request)
			want int
		}{
			{"foreign-host", func(r *http.Request) { r.Host = "attacker.example:18765" }, 403},
			{"localhost-alias", func(r *http.Request) { r.Host = "localhost:18765" }, 403},
			{"foreign-origin", func(r *http.Request) { r.Header.Set("Origin", "https://attacker.example") }, 403},
			{"null-origin", func(r *http.Request) { r.Header.Set("Origin", "null") }, 403},
			{"empty-origin", func(r *http.Request) { r.Header["Origin"] = []string{""} }, 403},
		} {
			t.Run(path+"/"+tc.name, func(t *testing.T) {
				calls := 0
				h := testAPI(t, countingActions(&calls))
				r := testRequest(http.MethodPost, path, `{}`)
				tc.edit(r)
				w := httptest.NewRecorder()
				h.ServeHTTP(w, r)
				if w.Code != tc.want || calls != 0 {
					t.Fatalf("status=%d calls=%d", w.Code, calls)
				}
			})
		}
	}
	for _, path := range []string{"/api/send", "/api/download"} {
		for _, contentType := range []string{"", "text/plain", "application/x-www-form-urlencoded", "application/json;broken"} {
			t.Run(path+"/content-type/"+contentType, func(t *testing.T) {
				calls := 0
				r := testRequest(http.MethodPost, path, `{}`)
				r.Header.Set("Content-Type", contentType)
				w := httptest.NewRecorder()
				testAPI(t, countingActions(&calls)).ServeHTTP(w, r)
				if w.Code != http.StatusUnsupportedMediaType || calls != 0 {
					t.Fatalf("status=%d calls=%d", w.Code, calls)
				}
			})
		}
		calls := 0
		w := httptest.NewRecorder()
		testAPI(t, countingActions(&calls)).ServeHTTP(w, testRequest(http.MethodGet, path, ""))
		if w.Code != http.StatusMethodNotAllowed || calls != 0 {
			t.Fatalf("GET %s: status=%d calls=%d", path, w.Code, calls)
		}
	}
	calls := 0
	w := httptest.NewRecorder()
	testAPI(t, countingActions(&calls)).ServeHTTP(w, testRequest(http.MethodPost, "/api/status", `{}`))
	if w.Code != http.StatusMethodNotAllowed || calls != 0 {
		t.Fatalf("POST status: status=%d calls=%d", w.Code, calls)
	}
}

func TestAPIRejectsMissingOrShortConfiguredToken(t *testing.T) {
	for _, token := range []string{"", "short", strings.Repeat("x", 31)} {
		if handler, err := newAPIHandler(token, testHost, apiActions{}); err == nil || handler != nil {
			t.Fatalf("accepted token length %d", len(token))
		}
	}
}

func TestAPIRejectsMalformedOversizedAndUnexpectedJSON(t *testing.T) {
	for _, path := range []string{"/api/send", "/api/download"} {
		for _, body := range []string{
			``, `{`, `[]`, `null`, `{}`, `{"unexpected":true}`,
			`{"recipient":"123","message":"ok"} {}`,
			`{"message_id":"id","chat_jid":"chat"} trailing`,
			`{"recipient":"123","message":"` + strings.Repeat("x", (1<<20)+1) + `"}`,
			`{"message_id":"id","chat_jid":"` + strings.Repeat("x", (1<<20)+1) + `"}`,
		} {
			t.Run(fmt.Sprintf("%s/body-length-%d", path, len(body)), func(t *testing.T) {
				calls := 0
				w := httptest.NewRecorder()
				testAPI(t, countingActions(&calls)).ServeHTTP(w, testRequest(http.MethodPost, path, body))
				if w.Code != http.StatusBadRequest || calls != 0 {
					t.Fatalf("status=%d calls=%d", w.Code, calls)
				}
			})
		}
	}
}

func TestMediaStorageConfinesUntrustedNamesAndCachesContent(t *testing.T) {
	root := filepath.Join(t.TempDir(), "media")
	safeName := regexp.MustCompile(`^[0-9a-f]{64}\.(bin|pdf|txt|jpg|mp4|ogg)$`)
	for i, tc := range []struct{ chat, id, kind, display, ext string }{
		{"../../outside", "../message", "document", "../../secret.txt", ".txt"},
		{`..\..\outside`, `C:\message`, "document", `C:\Windows\secret.txt`, ".txt"},
		{`\\server\share`, "id", "document", `..\..\malware.exe`, ".bin"},
		{"chat\x00../escape", "id", "document", "../name.txt:stream", ".bin"},
		{"123@g.us", "unicode-id", "document", "Résumé 世界 📄.PDF", ".pdf"},
		{"chat", "picture", "image", "../../bad.exe", ".jpg"},
		{"chat", "video", "video", "../../bad.exe", ".mp4"},
		{"chat", "audio", "audio", "../../bad.exe", ".ogg"},
	} {
		t.Run(fmt.Sprintf("case-%d", i), func(t *testing.T) {
			name := mediaStorageName(tc.chat, tc.id, tc.kind, tc.display)
			if !safeName.MatchString(name) || filepath.Ext(name) != tc.ext {
				t.Fatalf("unsafe or incorrect storage name: %q", name)
			}
			payload := []byte(fmt.Sprintf("media content %d", i))
			calls := 0
			loader := func() ([]byte, error) { calls++; return payload, nil }
			path, err := cachedOrDownloadMedia(root, tc.chat, tc.id, tc.kind, tc.display, loader)
			if err != nil {
				t.Fatal(err)
			}
			if !filepath.IsAbs(path) || filepath.Dir(path) != root || filepath.Base(path) != name {
				t.Fatalf("media escaped root: %q (root %q)", path, root)
			}
			data, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(data, payload) {
				t.Fatalf("content=%q error=%v", data, err)
			}
			again, err := cachedOrDownloadMedia(root, tc.chat, tc.id, tc.kind, tc.display, loader)
			if err != nil || again != path || calls != 1 {
				t.Fatalf("cache path=%q calls=%d error=%v", again, calls, err)
			}
		})
	}
}

func TestMediaStorageRejectsDirectoryAndSymlinkCacheEntries(t *testing.T) {
	for _, kind := range []string{"directory", "file-symlink", "directory-symlink"} {
		t.Run(kind, func(t *testing.T) {
			base := t.TempDir()
			root := filepath.Join(base, "media")
			if err := os.Mkdir(root, 0700); err != nil {
				t.Fatal(err)
			}
			name := mediaStorageName("chat", "message", "document", "file.txt")
			entry := filepath.Join(root, name)
			outside := filepath.Join(base, "outside")
			if kind == "directory" {
				if err := os.Mkdir(entry, 0700); err != nil {
					t.Fatal(err)
				}
			} else {
				var err error
				if kind == "directory-symlink" {
					err = os.Mkdir(outside, 0700)
				} else {
					err = os.WriteFile(outside, []byte("private outside data"), 0600)
				}
				if err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(outside, entry); err != nil {
					if runtime.GOOS == "windows" {
						t.Skipf("Windows symlink creation unavailable: %v", err)
					}
					t.Fatal(err)
				}
			}
			called := false
			path, err := cachedOrDownloadMedia(root, "chat", "message", "document", "file.txt", func() ([]byte, error) {
				called = true
				return []byte("new data"), nil
			})
			if err == nil || path != "" || called {
				t.Fatalf("accepted nonregular entry: path=%q called=%v err=%v", path, called, err)
			}
			if kind == "file-symlink" {
				data, err := os.ReadFile(outside)
				if err != nil || string(data) != "private outside data" {
					t.Fatalf("outside file changed: %q, %v", data, err)
				}
			}
		})
	}
}

func TestMediaDownloadFailureDoesNotCreateCache(t *testing.T) {
	root := filepath.Join(t.TempDir(), "media")
	wantErr := errors.New("download failed")
	path, err := cachedOrDownloadMedia(root, "chat", "id", "document", "report.pdf", func() ([]byte, error) {
		return nil, wantErr
	})
	if path != "" || !errors.Is(err, wantErr) {
		t.Fatalf("path=%q err=%v", path, err)
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 0 {
		t.Fatalf("failed download created cache: %v, %v", entries, err)
	}
}

func TestDownloadMediaDoesNotReturnLegacyTraversalFile(t *testing.T) {
	base := t.TempDir()
	t.Chdir(base)
	store, err := NewMessageStore()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	chat, id, display := "123@g.us", "malicious-message", "../../outside.txt"
	if err := os.MkdirAll(filepath.Join("store", chat), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile("outside.txt", []byte("private outside data"), 0600); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	if err := store.StoreChat(chat, "Test chat", now); err != nil {
		t.Fatal(err)
	}
	if err := store.StoreMessage(id, chat, "sender", "", now, false, "document", display, "", nil, nil, nil, 0); err != nil {
		t.Fatal(err)
	}
	// Missing download metadata ensures a nil client can never contact WhatsApp.
	ok, _, _, path, err := downloadMedia(nil, store, id, chat)
	if ok || path != "" || err == nil {
		t.Fatalf("returned legacy traversal target: ok=%v path=%q err=%v", ok, path, err)
	}
	data, err := os.ReadFile("outside.txt")
	if err != nil || string(data) != "private outside data" {
		t.Fatalf("outside file changed: %q, %v", data, err)
	}
}

func TestDownloadMediaReadsGeneratedCache(t *testing.T) {
	t.Chdir(t.TempDir())
	store, err := NewMessageStore()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	chat, id, display := "123@g.us", "cached-message", "Résumé 世界.pdf"
	now := time.Now()
	if err := store.StoreChat(chat, "Test chat", now); err != nil {
		t.Fatal(err)
	}
	if err := store.StoreMessage(id, chat, "sender", "", now, false, "document", display, "", nil, nil, nil, 0); err != nil {
		t.Fatal(err)
	}
	// A generated regular cache file remains readable with the original display name.
	safePath, err := cachedOrDownloadMedia("store/media", chat, id, "document", display, func() ([]byte, error) {
		return []byte("actual cached media"), nil
	})
	if err != nil {
		t.Fatal(err)
	}
	ok, kind, filename, path, err := downloadMedia(nil, store, id, chat)
	if err != nil || !ok || kind != "document" || filename != display || path != safePath {
		t.Fatalf("safe cache failed: ok=%v kind=%q filename=%q path=%q err=%v", ok, kind, filename, path, err)
	}
}

func opusTestPage(payload []byte, granule uint64) []byte {
	page := make([]byte, 28+len(payload))
	copy(page, "OggS")
	binary.LittleEndian.PutUint64(page[6:14], granule)
	page[26], page[27] = 1, byte(len(payload))
	copy(page[28:], payload)
	return page
}

func TestAnalyzeOggOpusTruncatedInputsDoNotPanic(t *testing.T) {
	header := make([]byte, 19)
	copy(header, "OpusHead")
	header[8], header[9] = 1, 1
	binary.LittleEndian.PutUint16(header[10:12], 312)
	binary.LittleEndian.PutUint32(header[12:16], 48000)
	valid := opusTestPage(header, 48312)
	for length := 0; length < len(valid); length++ {
		t.Run(fmt.Sprintf("prefix-%d", length), func(t *testing.T) {
			// Any unexpected panic is a test failure; incomplete headers may use fallback.
			analyzeOggOpus(valid[:length])
		})
	}
	for length := 8; length < 19; length++ {
		t.Run(fmt.Sprintf("complete-page-short-opus-header-%d", length), func(t *testing.T) {
			analyzeOggOpus(opusTestPage(header[:length], 0))
		})
	}
	truncated := append([]byte(nil), valid...)
	truncated[27] = 255
	if _, _, err := analyzeOggOpus(truncated); err == nil {
		t.Fatal("accepted page whose declared payload exceeds available data")
	}
}

func TestAnalyzeOggOpusBasicHeader(t *testing.T) {
	header := make([]byte, 19)
	copy(header, "OpusHead")
	header[8], header[9] = 1, 1
	binary.LittleEndian.PutUint16(header[10:12], 312)
	// Input sample-rate metadata can differ; Opus granules still use 48 kHz.
	binary.LittleEndian.PutUint32(header[12:16], 24000)
	duration, waveform, err := analyzeOggOpus(opusTestPage(header, 48312))
	if err != nil || duration != 1 || len(waveform) != 64 {
		t.Fatalf("duration=%d waveform=%d err=%v", duration, len(waveform), err)
	}
}
