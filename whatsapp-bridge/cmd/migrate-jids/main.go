// migrate-jids backfills chat_pn / chat_lid / sender_pn / sender_lid on an
// existing whatsapp-bridge messages.db using the whatsmeow_lid_map table from
// the companion whatsapp.db.
//
// Safe to run multiple times. Use -dry-run to preview before writing.
//
// Usage from the whatsapp-bridge directory:
//
//	go run ./cmd/migrate-jids -dry-run
//	go run ./cmd/migrate-jids            # actually writes
//	go run ./cmd/migrate-jids -store /path/to/store
package main

import (
	"database/sql"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"

	_ "github.com/mattn/go-sqlite3"
)

func main() {
	storeDir := flag.String("store", "store", "Path to the bridge store directory (contains messages.db and whatsapp.db)")
	dryRun := flag.Bool("dry-run", false, "Report what would change without writing")
	flag.Parse()

	messagesPath := filepath.Join(*storeDir, "messages.db")
	whatsappPath := filepath.Join(*storeDir, "whatsapp.db")

	for _, p := range []string{messagesPath, whatsappPath} {
		if _, err := os.Stat(p); err != nil {
			log.Fatalf("cannot stat %s: %v", p, err)
		}
	}

	db, err := sql.Open("sqlite3", messagesPath+"?_journal_mode=WAL&_foreign_keys=on")
	if err != nil {
		log.Fatalf("open messages.db: %v", err)
	}
	defer db.Close()

	// Attach whatsapp.db read-only so we can read whatsmeow_lid_map.
	if _, err := db.Exec(fmt.Sprintf("ATTACH DATABASE 'file:%s?mode=ro' AS wm", whatsappPath)); err != nil {
		log.Fatalf("attach whatsapp.db: %v", err)
	}

	if err := ensureColumns(db); err != nil {
		log.Fatalf("ensure columns: %v", err)
	}

	if err := report(db, "BEFORE"); err != nil {
		log.Fatalf("report: %v", err)
	}

	tx, err := db.Begin()
	if err != nil {
		log.Fatalf("begin: %v", err)
	}
	defer tx.Rollback()

	chatsUpdated, err := backfillChats(tx)
	if err != nil {
		log.Fatalf("chats: %v", err)
	}

	messagesUpdated, err := backfillMessages(tx)
	if err != nil {
		log.Fatalf("messages: %v", err)
	}

	fmt.Printf("\nRows that would change:\n")
	fmt.Printf("  chats:    %d\n", chatsUpdated)
	fmt.Printf("  messages: %d\n", messagesUpdated)

	if *dryRun {
		fmt.Println("\n-dry-run set: rolling back, no changes written.")
		return
	}

	if err := tx.Commit(); err != nil {
		log.Fatalf("commit: %v", err)
	}
	fmt.Println("\nCommitted.")

	if err := report(db, "AFTER"); err != nil {
		log.Fatalf("report: %v", err)
	}
}

// ensureColumns adds chat_pn / chat_lid on chats and sender_pn / sender_lid on
// messages when they do not already exist. Idempotent.
func ensureColumns(db *sql.DB) error {
	need := map[string]map[string]string{
		"chats": {
			"chat_pn":  "TEXT",
			"chat_lid": "TEXT",
		},
		"messages": {
			"sender_pn":  "TEXT",
			"sender_lid": "TEXT",
		},
	}
	for table, cols := range need {
		for name, typ := range cols {
			var count int
			err := db.QueryRow(
				`SELECT COUNT(*) FROM pragma_table_info(?) WHERE name = ?`,
				table, name,
			).Scan(&count)
			if err != nil {
				return fmt.Errorf("pragma_table_info(%s): %w", table, err)
			}
			if count == 0 {
				stmt := fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", table, name, typ)
				if _, err := db.Exec(stmt); err != nil {
					return fmt.Errorf("%s: %w", stmt, err)
				}
				fmt.Printf("Added column %s.%s\n", table, name)
			}
		}
	}
	return nil
}

func report(db *sql.DB, label string) error {
	rows, err := db.Query(`
		SELECT 'chats.chat_pn_filled'    AS k, COUNT(*) FROM chats    WHERE chat_pn    IS NOT NULL UNION ALL
		SELECT 'chats.chat_lid_filled',          COUNT(*) FROM chats    WHERE chat_lid   IS NOT NULL UNION ALL
		SELECT 'messages.sender_pn_filled',      COUNT(*) FROM messages WHERE sender_pn  IS NOT NULL UNION ALL
		SELECT 'messages.sender_lid_filled',     COUNT(*) FROM messages WHERE sender_lid IS NOT NULL
	`)
	if err != nil {
		return err
	}
	defer rows.Close()
	fmt.Printf("\n%s:\n", label)
	for rows.Next() {
		var k string
		var n int
		if err := rows.Scan(&k, &n); err != nil {
			return err
		}
		fmt.Printf("  %-32s %d\n", k, n)
	}
	return rows.Err()
}

// backfillChats derives chat_pn and chat_lid from the chat jid. For
// @s.whatsapp.net chats the user part IS the phone number; for @lid chats the
// user part IS the LID. The other side is resolved via whatsmeow_lid_map.
// Groups (@g.us) and broadcasts keep both columns NULL.
func backfillChats(tx *sql.Tx) (int64, error) {
	const q = `
		UPDATE chats
		SET chat_pn = CASE
				WHEN chat_pn IS NOT NULL AND chat_pn <> '' THEN chat_pn
				WHEN jid LIKE '%@s.whatsapp.net' THEN substr(jid, 1, instr(jid, '@') - 1)
				WHEN jid LIKE '%@lid' THEN (
					SELECT pn FROM wm.whatsmeow_lid_map
					WHERE lid = substr(jid, 1, instr(jid, '@') - 1)
				)
				ELSE NULL
			END,
			chat_lid = CASE
				WHEN chat_lid IS NOT NULL AND chat_lid <> '' THEN chat_lid
				WHEN jid LIKE '%@lid' THEN substr(jid, 1, instr(jid, '@') - 1)
				WHEN jid LIKE '%@s.whatsapp.net' THEN (
					SELECT lid FROM wm.whatsmeow_lid_map
					WHERE pn = substr(jid, 1, instr(jid, '@') - 1)
				)
				ELSE NULL
			END
		WHERE (chat_pn IS NULL OR chat_pn = '')
		   OR (chat_lid IS NULL OR chat_lid = '')
	`
	res, err := tx.Exec(q)
	if err != nil {
		return 0, err
	}
	return res.RowsAffected()
}

// backfillMessages poblates sender_pn / sender_lid from the existing `sender`
// column by looking it up in whatsmeow_lid_map. `sender` stores only the User
// part (no server) so we decide which side it belongs to by checking both
// columns of the map. If the sender is not in the map, both PN and LID stay
// NULL.
func backfillMessages(tx *sql.Tx) (int64, error) {
	const q = `
		UPDATE messages
		SET sender_pn = COALESCE(
				sender_pn,
				CASE
					WHEN sender IS NULL OR sender = '' THEN NULL
					WHEN EXISTS (SELECT 1 FROM wm.whatsmeow_lid_map WHERE pn  = messages.sender) THEN messages.sender
					ELSE (SELECT pn  FROM wm.whatsmeow_lid_map WHERE lid = messages.sender)
				END
			),
			sender_lid = COALESCE(
				sender_lid,
				CASE
					WHEN sender IS NULL OR sender = '' THEN NULL
					WHEN EXISTS (SELECT 1 FROM wm.whatsmeow_lid_map WHERE lid = messages.sender) THEN messages.sender
					ELSE (SELECT lid FROM wm.whatsmeow_lid_map WHERE pn  = messages.sender)
				END
			)
		WHERE (sender_pn  IS NULL OR sender_pn  = '')
		   OR (sender_lid IS NULL OR sender_lid = '')
	`
	res, err := tx.Exec(q)
	if err != nil {
		return 0, err
	}
	return res.RowsAffected()
}
