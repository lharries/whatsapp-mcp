package main

import (
	"crypto/subtle"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Config is the bridge's runtime configuration, read from the environment so the
// same binary runs on macOS (launchd) and on a Linux server (systemd), and so
// multiple accounts are just multiple processes with their own store dir + port.
type Config struct {
	// Account is a label for this process (e.g. "main", "second"). It is only
	// used in logs and in the webhook payload; each process owns one account.
	Account string
	// Port is the REST port. Each account process uses a different one.
	Port int
	// DBDir holds the SQLite stores. Defaults to ./store for local dev,
	// /var/lib/whatsapp-mcp on a server.
	DBDir string
	// Token, when set, must be presented as `Authorization: Bearer <token>` (or
	// `?token=`) on every /api/* and /pair request.
	Token string
	// WebhookURL, when set, receives a POST for every incoming message.
	WebhookURL string
	// WebhookSecret signs webhook bodies (HMAC-SHA256, header X-WA-Signature).
	WebhookSecret string
	// OwnerJID is your own WhatsApp JID for this account, used by the reply
	// approval loop (e.g. 2648xxxxxxx@s.whatsapp.net).
	OwnerJID string
}

// storeRoot is where media and the "store" fallback live. Set from Config.DBDir
// in main so tests and non-default dirs work.
var storeRoot = "store"

// appCfg is the process-wide config, used by handlers that don't take it.
var appCfg Config

func env(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

// LoadConfig reads the environment. Nothing is required; defaults match local
// development (./store, port 8080, no auth) so `go run main.go` still works.
func LoadConfig() Config {
	port := 8080
	if v := os.Getenv("WA_PORT"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 && n < 65536 {
			port = n
		}
	}
	return Config{
		Account:       env("WA_ACCOUNT", "main"),
		Port:          port,
		DBDir:         env("WA_DB_DIR", "store"),
		Token:         os.Getenv("WA_TOKEN"),
		WebhookURL:    os.Getenv("WEBHOOK_URL"),
		WebhookSecret: os.Getenv("WEBHOOK_SECRET"),
		OwnerJID:      env("WA_OWNER_JID", os.Getenv("OWNER_JID")),
	}
}

// StoreDir returns the absolute store directory, creating it if needed.
func (c Config) StoreDir() (string, error) {
	if err := os.MkdirAll(c.DBDir, 0755); err != nil {
		return "", fmt.Errorf("create store dir %q: %w", c.DBDir, err)
	}
	abs, err := filepath.Abs(c.DBDir)
	if err != nil {
		return "", err
	}
	return abs, nil
}

func (c Config) whatsmeowDBPath() string {
	return filepath.Join(c.DBDir, "whatsapp.db")
}

func (c Config) messagesDBPath() string {
	return filepath.Join(c.DBDir, "messages.db")
}

// authOK reports whether a request may proceed. With no token configured the
// API trusts any caller (it is bound to loopback); with a token set, every
// request must present it.
func (c Config) authOK(r *http.Request) bool {
	if c.Token == "" {
		return true
	}
	got := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if got == "" {
		got = r.URL.Query().Get("token")
	}
	return subtle.ConstantTimeCompare([]byte(got), []byte(c.Token)) == 1
}

// withAuth wraps a handler with the token check (except /healthz, which is left
// open for liveness probes).
func withAuth(h http.Handler, cfg Config) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" || cfg.authOK(r) {
			h.ServeHTTP(w, r)
			return
		}
		http.Error(w, "unauthorized", http.StatusUnauthorized)
	})
}
