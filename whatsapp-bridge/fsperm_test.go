package main

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"
)

func skipOnWindows(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX permission bits do not apply on Windows")
	}
}

func assertMode(t *testing.T, path string, want os.FileMode) {
	t.Helper()
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if got := info.Mode().Perm(); got != want {
		t.Errorf("%s: mode %o, want %o", filepath.Base(path), got, want)
	}
}

func TestEnsurePrivateDir(t *testing.T) {
	skipOnWindows(t)
	base := t.TempDir()

	created := filepath.Join(base, "store", "chat")
	if err := ensurePrivateDir(created); err != nil {
		t.Fatal(err)
	}
	assertMode(t, created, 0700)

	existing := filepath.Join(base, "legacy")
	if err := os.Mkdir(existing, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(existing, 0755); err != nil {
		t.Fatal(err)
	}
	if err := ensurePrivateDir(existing); err != nil {
		t.Fatal(err)
	}
	assertMode(t, existing, 0700)
}

func TestEnsurePrivateFile(t *testing.T) {
	skipOnWindows(t)
	base := t.TempDir()

	created := filepath.Join(base, "new.db")
	if err := ensurePrivateFile(created); err != nil {
		t.Fatal(err)
	}
	assertMode(t, created, 0600)

	existing := filepath.Join(base, "old.db")
	if err := os.WriteFile(existing, []byte("keep me"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(existing, 0644); err != nil {
		t.Fatal(err)
	}
	if err := ensurePrivateFile(existing); err != nil {
		t.Fatal(err)
	}
	assertMode(t, existing, 0600)
	if data, _ := os.ReadFile(existing); string(data) != "keep me" {
		t.Fatalf("content changed: %q", data)
	}
}

// The real message store: store/ must be 0700 and the database (and its WAL files) 0600,
// even with the usual 022 umask and an existing world-readable store directory.
func TestEnsurePrivateMessageStore(t *testing.T) {
	skipOnWindows(t)
	t.Chdir(t.TempDir())
	if err := os.Mkdir("store", 0755); err != nil {
		t.Fatal(err)
	}

	store, err := NewMessageStore()
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	if _, err := store.db.Exec("PRAGMA journal_mode=WAL"); err != nil {
		t.Fatal(err)
	}
	if err := store.StoreChat("123@s.whatsapp.net", "Test", time.Now()); err != nil {
		t.Fatal(err)
	}

	assertMode(t, "store", 0700)
	for _, f := range []string{"store/messages.db", "store/messages.db-wal", "store/messages.db-shm"} {
		assertMode(t, f, 0600)
	}
}
