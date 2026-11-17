package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSafePathComponentStripsTraversal(t *testing.T) {
	cases := map[string]string{
		"../../../.zshrc":      "zshrc",
		"..\\..\\evil.exe":     "evil.exe",
		"/etc/passwd":          "passwd",
		"..":                   "fallback",
		"":                     "fallback",
		"report.pdf":           "report.pdf",
		"123@s.whatsapp.net":   "123@s.whatsapp.net",
		"123:4@s.whatsapp.net": "123_4@s.whatsapp.net",
		"a\x00b":               "a_b",
	}
	for in, want := range cases {
		if got := safePathComponent(in, "fallback"); got != want {
			t.Errorf("safePathComponent(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestIsWithinDir(t *testing.T) {
	if !isWithinDir("/a/b", "/a/b/c.txt") {
		t.Error("expected /a/b/c.txt to be inside /a/b")
	}
	if isWithinDir("/a/b", "/a/bc/d.txt") {
		t.Error("sibling dir with shared prefix must not count as inside")
	}
	if isWithinDir("/a/b", "/a/x.txt") {
		t.Error("parent dir file must not count as inside")
	}
}

func TestResolveSendMediaPath(t *testing.T) {
	root := t.TempDir()
	outbox := filepath.Join(root, "outbox")
	if err := os.Mkdir(outbox, 0700); err != nil {
		t.Fatal(err)
	}
	inside := filepath.Join(outbox, "photo.jpg")
	outside := filepath.Join(root, "secret.txt")
	for _, p := range []string{inside, outside} {
		if err := os.WriteFile(p, []byte("x"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Symlink(outside, filepath.Join(outbox, "link.txt")); err != nil {
		t.Fatal(err)
	}
	t.Setenv(envSendMediaDir, outbox)

	if _, err := resolveSendMediaPath(inside); err != nil {
		t.Errorf("file inside outbox rejected: %v", err)
	}
	if _, err := resolveSendMediaPath("photo.jpg"); err != nil {
		t.Errorf("relative file inside outbox rejected: %v", err)
	}
	rejected := []string{
		outside,
		filepath.Join(outbox, "..", "secret.txt"),
		"../secret.txt",
		filepath.Join(outbox, "link.txt"), // symlink pointing outside
		outbox,                            // directory, not a file
		filepath.Join(outbox, "missing.jpg"),
	}
	for _, p := range rejected {
		if _, err := resolveSendMediaPath(p); err == nil {
			t.Errorf("expected %q to be rejected", p)
		}
	}
}

func TestRequireToken(t *testing.T) {
	handler := requireToken("s3cret", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	cases := map[string]int{
		"":              http.StatusUnauthorized,
		"Bearer wrong":  http.StatusUnauthorized,
		"s3cret":        http.StatusUnauthorized,
		"Bearer s3cret": http.StatusOK,
	}
	for header, want := range cases {
		req := httptest.NewRequest(http.MethodPost, "/api/send", strings.NewReader("{}"))
		if header != "" {
			req.Header.Set("Authorization", header)
		}
		rec := httptest.NewRecorder()
		handler(rec, req)
		if rec.Code != want {
			t.Errorf("Authorization %q: got %d, want %d", header, rec.Code, want)
		}
	}
}

func TestAPIBindAddrDefaultsToLoopback(t *testing.T) {
	t.Setenv(envBindHost, "")
	if got := apiBindAddr(8080); got != "127.0.0.1:8080" {
		t.Errorf("default bind = %q, want 127.0.0.1:8080", got)
	}
	t.Setenv(envBindHost, "0.0.0.0")
	if got := apiBindAddr(8080); got != "0.0.0.0:8080" {
		t.Errorf("override bind = %q, want 0.0.0.0:8080", got)
	}
}

func TestLoadOrCreateAPITokenPersistsPrivately(t *testing.T) {
	t.Chdir(t.TempDir())
	t.Setenv(envAPIToken, "")
	if err := ensurePrivateStore(); err != nil {
		t.Fatal(err)
	}
	first, err := loadOrCreateAPIToken()
	if err != nil || len(first) != tokenBytes*2 {
		t.Fatalf("token = %q, err = %v", first, err)
	}
	second, err := loadOrCreateAPIToken()
	if err != nil || second != first {
		t.Errorf("token not reused: %q vs %q (err %v)", second, first, err)
	}
	info, err := os.Stat(apiTokenFile)
	if err != nil || info.Mode().Perm() != privateFilePerm {
		t.Errorf("token file mode = %v, want %v (err %v)", info.Mode().Perm(), privateFilePerm, err)
	}
}
