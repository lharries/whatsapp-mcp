package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSafeFileName(t *testing.T) {
	cases := map[string]string{
		"invoice.pdf":         "invoice.pdf",
		"../../.zshrc":        "file_",
		"..\\..\\evil.exe":    "evil.exe",
		"/etc/passwd":         "passwd",
		"sub/dir/report.docx": "report.docx",
		"":                    "file_",
		"..":                  "file_",
		".bashrc":             "file_",
	}
	for in, want := range cases {
		got := safeFileName(in)
		if strings.Contains(got, "/") || strings.Contains(got, "\\") || !strings.HasPrefix(got, want) {
			t.Errorf("safeFileName(%q) = %q, want prefix %q", in, got, want)
		}
	}
}

func TestSafeChatDirName(t *testing.T) {
	if got := safeChatDirName("123@s.whatsapp.net"); got != "123@s.whatsapp.net" {
		t.Errorf("got %q", got)
	}
	if got := safeChatDirName("../x:y/z"); strings.ContainsAny(got, "/:\\") {
		t.Errorf("unsafe chars survived: %q", got)
	}
}

func TestResolveOutgoingMediaPath(t *testing.T) {
	root := t.TempDir()
	allowed := filepath.Join(root, "media")
	if err := os.MkdirAll(allowed, 0700); err != nil {
		t.Fatal(err)
	}
	inside := filepath.Join(allowed, "a.png")
	outside := filepath.Join(root, "secret.txt")
	for _, p := range []string{inside, outside} {
		if err := os.WriteFile(p, []byte("x"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	link := filepath.Join(allowed, "link.png")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}

	t.Setenv("WHATSAPP_MEDIA_DIR", "")
	if _, err := resolveOutgoingMediaPath(outside); err != nil {
		t.Errorf("without allowlist any file should resolve: %v", err)
	}
	if _, err := resolveOutgoingMediaPath(filepath.Join(root, "missing")); err == nil {
		t.Errorf("missing file should fail")
	}

	t.Setenv("WHATSAPP_MEDIA_DIR", allowed)
	if _, err := resolveOutgoingMediaPath(inside); err != nil {
		t.Errorf("file inside allowlist rejected: %v", err)
	}
	if _, err := resolveOutgoingMediaPath(outside); err == nil {
		t.Errorf("file outside allowlist accepted")
	}
	if _, err := resolveOutgoingMediaPath(link); err == nil {
		t.Errorf("symlink escaping allowlist accepted")
	}
	if _, err := resolveOutgoingMediaPath(filepath.Join(allowed, "..", "secret.txt")); err == nil {
		t.Errorf("dot-dot escape accepted")
	}
}

func TestRequireAPIToken(t *testing.T) {
	ok := func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) }
	call := func(h http.HandlerFunc, auth string) int {
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/api/send", nil)
		if auth != "" {
			req.Header.Set("Authorization", auth)
		}
		h(rec, req)
		return rec.Code
	}

	t.Setenv("WHATSAPP_API_TOKEN", "")
	if code := call(requireAPIToken(ok), ""); code != http.StatusOK {
		t.Errorf("no token configured: got %d", code)
	}

	t.Setenv("WHATSAPP_API_TOKEN", "s3cret")
	h := requireAPIToken(ok)
	if code := call(h, ""); code != http.StatusUnauthorized {
		t.Errorf("missing header: got %d", code)
	}
	if code := call(h, "Bearer wrong"); code != http.StatusUnauthorized {
		t.Errorf("wrong token: got %d", code)
	}
	if code := call(h, "Bearer s3cret"); code != http.StatusOK {
		t.Errorf("right token: got %d", code)
	}
}

func TestBridgeBindAddr(t *testing.T) {
	t.Setenv("WHATSAPP_BRIDGE_BIND", "")
	if got := bridgeBindAddr(8080); got != "127.0.0.1:8080" {
		t.Errorf("default bind = %q", got)
	}
	t.Setenv("WHATSAPP_BRIDGE_BIND", "0.0.0.0")
	if got := bridgeBindAddr(8080); got != "0.0.0.0:8080" {
		t.Errorf("override bind = %q", got)
	}
}
