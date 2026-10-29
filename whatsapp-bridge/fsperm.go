package main

import "os"

// ensurePrivateDir creates dir (and its parents) if needed and restricts it to the owner.
// The store directory holds the WhatsApp session keys and the message history.
func ensurePrivateDir(dir string) error {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	// MkdirAll keeps the mode of an existing directory, so tighten it explicitly
	return os.Chmod(dir, 0700)
}

// ensurePrivateFile creates path if needed and restricts it to the owner, keeping its content.
// Creating SQLite databases this way before opening them also gives their -wal/-shm/-journal
// files the same mode, as SQLite copies the database file permissions.
func ensurePrivateFile(path string) error {
	f, err := os.OpenFile(path, os.O_RDONLY|os.O_CREATE, 0600)
	if err != nil {
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Chmod(path, 0600)
}
