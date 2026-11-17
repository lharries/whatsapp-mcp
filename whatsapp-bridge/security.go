package main

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

const (
	storeDir = "store"

	// File holding the API token, shared with the MCP server.
	apiTokenFile = "store/api_token"

	// Default directory that /api/send may read media files from.
	defaultSendMediaDir = "store/outbox"

	envBindHost     = "WHATSAPP_BRIDGE_HOST"
	envAPIToken     = "WHATSAPP_BRIDGE_TOKEN"
	envSendMediaDir = "WHATSAPP_SEND_MEDIA_DIR"

	defaultBindHost = "127.0.0.1"
	tokenBytes      = 32

	// Owner-only permissions: the store holds the session keys and all message history.
	privateDirPerm  os.FileMode = 0700
	privateFilePerm os.FileMode = 0600
)

// ensurePrivateStore creates the store directory with owner-only permissions and
// tightens it if an older version created it world-readable.
func ensurePrivateStore() error {
	if err := os.MkdirAll(storeDir, privateDirPerm); err != nil {
		return fmt.Errorf("failed to create store directory: %v", err)
	}
	if err := os.Chmod(storeDir, privateDirPerm); err != nil {
		return fmt.Errorf("failed to restrict store directory permissions: %v", err)
	}
	return nil
}

// apiBindAddr returns the address for the REST API. It binds to loopback only,
// unless WHATSAPP_BRIDGE_HOST is set explicitly.
func apiBindAddr(port int) string {
	host := strings.TrimSpace(os.Getenv(envBindHost))
	if host == "" {
		host = defaultBindHost
	}
	return fmt.Sprintf("%s:%d", host, port)
}

// loadOrCreateAPIToken returns the token required on every REST API request.
// Order: WHATSAPP_BRIDGE_TOKEN env var, then store/api_token, else a new random
// token is generated and written to store/api_token (mode 0600).
func loadOrCreateAPIToken() (string, error) {
	if token := strings.TrimSpace(os.Getenv(envAPIToken)); token != "" {
		return token, nil
	}

	data, err := os.ReadFile(apiTokenFile)
	if err == nil {
		if token := strings.TrimSpace(string(data)); token != "" {
			return token, nil
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", fmt.Errorf("failed to read API token file: %v", err)
	}

	buf := make([]byte, tokenBytes)
	if _, err := rand.Read(buf); err != nil {
		return "", fmt.Errorf("failed to generate API token: %v", err)
	}
	token := hex.EncodeToString(buf)
	if err := os.WriteFile(apiTokenFile, []byte(token+"\n"), privateFilePerm); err != nil {
		return "", fmt.Errorf("failed to write API token file: %v", err)
	}
	return token, nil
}

// requireToken rejects requests without a matching "Authorization: Bearer <token>" header.
// A custom header also means browsers cannot send these requests cross-origin without a
// CORS preflight, which this server never approves.
func requireToken(token string, next http.HandlerFunc) http.HandlerFunc {
	expected := []byte("Bearer " + token)
	return func(w http.ResponseWriter, r *http.Request) {
		got := []byte(r.Header.Get("Authorization"))
		if subtle.ConstantTimeCompare(got, expected) != 1 {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		next(w, r)
	}
}

// sendMediaDir returns the absolute, symlink-resolved directory that /api/send may read from.
func sendMediaDir() (string, error) {
	dir := strings.TrimSpace(os.Getenv(envSendMediaDir))
	if dir == "" {
		dir = defaultSendMediaDir
		if err := os.MkdirAll(dir, privateDirPerm); err != nil {
			return "", fmt.Errorf("failed to create media outbox directory: %v", err)
		}
	}
	abs, err := filepath.Abs(dir)
	if err != nil {
		return "", fmt.Errorf("invalid media directory: %v", err)
	}
	resolved, err := filepath.EvalSymlinks(abs)
	if err != nil {
		return "", fmt.Errorf("media directory is not accessible: %v", err)
	}
	return resolved, nil
}

// resolveSendMediaPath checks that mediaPath is a regular file inside the allowed
// media directory (after resolving symlinks) and returns its resolved path.
func resolveSendMediaPath(mediaPath string) (string, error) {
	baseDir, err := sendMediaDir()
	if err != nil {
		return "", err
	}

	candidate := mediaPath
	if !filepath.IsAbs(candidate) {
		candidate = filepath.Join(baseDir, candidate)
	}
	resolved, err := filepath.EvalSymlinks(candidate)
	if err != nil {
		return "", fmt.Errorf("media file is not accessible")
	}
	if !isWithinDir(baseDir, resolved) {
		return "", fmt.Errorf("media_path must be inside %s (set %s to change it)", baseDir, envSendMediaDir)
	}

	info, err := os.Stat(resolved)
	if err != nil || !info.Mode().IsRegular() {
		return "", fmt.Errorf("media_path must be a regular file")
	}
	return resolved, nil
}

// isWithinDir reports whether path is dir itself or a descendant of it.
func isWithinDir(dir, path string) bool {
	rel, err := filepath.Rel(dir, path)
	if err != nil {
		return false
	}
	return rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && !filepath.IsAbs(rel)
}

// safePathComponent turns an untrusted name (a sender-chosen filename, a chat JID)
// into a single path component that cannot escape its parent directory.
func safePathComponent(name, fallback string) string {
	name = strings.ReplaceAll(name, "\\", "/")
	name = filepath.Base(name)
	name = strings.Map(func(r rune) rune {
		if r == 0 || r == ':' || r < 0x20 {
			return '_'
		}
		return r
	}, name)
	name = strings.TrimLeft(name, ".")
	if name == "" || name == "/" {
		return fallback
	}
	return name
}
