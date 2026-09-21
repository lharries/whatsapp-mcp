package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/reflect/protoreflect"
)

// On-demand history backfill: asks the primary phone for messages older than the
// oldest one we already have, chat by chat, until the phone has nothing older.

const (
	backfillBatchDefault = 50
	backfillWaitTimeout  = 60 * time.Second
	backfillPause        = 2 * time.Second
	backfillMaxTimeouts  = 3
)

type backfillStatus struct {
	Running        bool     `json:"running"`
	StopRequested  bool     `json:"stop_requested"`
	CurrentChat    string   `json:"current_chat"`
	ChatsDone      int      `json:"chats_done"`
	ChatsTotal     int      `json:"chats_total"`
	Requests       int      `json:"requests"`
	MessagesBefore int      `json:"messages_before"`
	MessagesNow    int      `json:"messages_now"`
	Timeouts       int      `json:"timeouts"`
	LastError      string   `json:"last_error,omitempty"`
	StartedAt      string   `json:"started_at,omitempty"`
	FinishedAt     string   `json:"finished_at,omitempty"`
	Recent         []string `json:"recent"`
}

var (
	backfillMu    sync.Mutex
	backfillState backfillStatus
	// handleHistorySync pushes a summary of every ON_DEMAND response here.
	onDemandSyncCh = make(chan onDemandResult, 32)
)

// anchor identifies a message the phone can page back from.
type anchor struct {
	ID        string
	Sender    string // full JID string for group participants, bare user otherwise
	Timestamp time.Time
	IsFromMe  bool
}

type onDemandResult struct {
	Raw    int     // messages in the response, stored or not
	Oldest *anchor // oldest message in the response
}

// summarizeOnDemand extracts the raw count and the oldest message key of an ON_DEMAND sync.
func summarizeOnDemand(hs *events.HistorySync) onDemandResult {
	var res onDemandResult
	for _, c := range hs.Data.Conversations {
		for _, m := range c.Messages {
			if m == nil || m.Message == nil || m.Message.Key == nil || m.Message.Key.ID == nil {
				continue
			}
			res.Raw++
			ts := time.Unix(int64(m.Message.GetMessageTimestamp()), 0)
			if res.Oldest == nil || ts.Before(res.Oldest.Timestamp) {
				res.Oldest = &anchor{
					ID:        *m.Message.Key.ID,
					Sender:    m.Message.Key.GetParticipant(),
					Timestamp: ts,
					IsFromMe:  m.Message.Key.GetFromMe(),
				}
			}
		}
	}
	return res
}

// messageKind names the populated message type (stickerMessage -> "sticker") for messages
// that carry neither text nor downloadable media.
func messageKind(msg *waE2E.Message) string {
	if msg == nil {
		return "unknown"
	}
	kind := "unknown"
	msg.ProtoReflect().Range(func(fd protoreflect.FieldDescriptor, _ protoreflect.Value) bool {
		name := string(fd.Name())
		if strings.HasSuffix(name, "Message") {
			kind = strings.TrimSuffix(name, "Message")
			return false
		}
		return true
	})
	return kind
}

func backfillLog(format string, args ...interface{}) {
	line := time.Now().Format("15:04:05") + " " + fmt.Sprintf(format, args...)
	fmt.Println("[backfill] " + line)
	backfillMu.Lock()
	backfillState.Recent = append(backfillState.Recent, line)
	if len(backfillState.Recent) > 30 {
		backfillState.Recent = backfillState.Recent[len(backfillState.Recent)-30:]
	}
	backfillMu.Unlock()
}

type oldestMessage = anchor

func (store *MessageStore) GetOldestMessage(chatJID string) (*oldestMessage, error) {
	row := store.db.QueryRow(
		"SELECT id, sender, timestamp, is_from_me FROM messages WHERE chat_jid = ? AND id != '' ORDER BY timestamp ASC LIMIT 1",
		chatJID)
	var m oldestMessage
	if err := row.Scan(&m.ID, &m.Sender, &m.Timestamp, &m.IsFromMe); err != nil {
		return nil, err
	}
	return &m, nil
}

func (store *MessageStore) CountMessages(chatJID string) (int, error) {
	var n int
	q, args := "SELECT COUNT(*) FROM messages", []interface{}{}
	if chatJID != "" {
		q, args = q+" WHERE chat_jid = ?", []interface{}{chatJID}
	}
	err := store.db.QueryRow(q, args...).Scan(&n)
	return n, err
}

func (store *MessageStore) ListChatJIDs() ([]string, error) {
	rows, err := store.db.Query("SELECT jid FROM chats ORDER BY last_message_time DESC")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var jid string
		if err := rows.Scan(&jid); err != nil {
			return nil, err
		}
		out = append(out, jid)
	}
	return out, rows.Err()
}

// senderJID rebuilds a types.JID from the sender column (full JID for groups, bare user otherwise).
func senderJID(client *whatsmeow.Client, chat types.JID, m *oldestMessage) types.JID {
	if m.IsFromMe && client.Store.ID != nil {
		return client.Store.ID.ToNonAD()
	}
	if strings.Contains(m.Sender, "@") {
		if j, err := types.ParseJID(m.Sender); err == nil {
			return j
		}
	}
	if chat.Server == types.GroupServer || chat.Server == types.NewsletterServer {
		return types.NewJID(m.Sender, types.DefaultUserServer)
	}
	return chat
}

// backfillChat keeps requesting older messages for one chat. Returns new messages fetched.
// requestAs, when non-empty, is the chat JID written into the request (e.g. the contact's
// @lid) while the anchor message still comes from chatJID's stored history.
func backfillChat(ctx context.Context, client *whatsmeow.Client, store *MessageStore, chatJID, requestAs string, batch int) (int, error) {
	chat, err := types.ParseJID(chatJID)
	if err != nil {
		return 0, err
	}
	reqChat := chat
	if requestAs != "" {
		if reqChat, err = types.ParseJID(requestAs); err != nil {
			return 0, err
		}
	}
	if chat.Server == types.BroadcastServer || chat.Server == types.NewsletterServer {
		return 0, nil // status@broadcast and channels have no on-demand history
	}
	total := 0
	oldest, err := store.GetOldestMessage(chatJID)
	if err != nil {
		return 0, nil // no anchor message stored -> nothing to page back from
	}
	for {
		if ctx.Err() != nil {
			return total, ctx.Err()
		}
		before, _ := store.CountMessages("")

		info := &types.MessageInfo{
			MessageSource: types.MessageSource{Chat: reqChat, Sender: senderJID(client, reqChat, oldest), IsFromMe: oldest.IsFromMe, IsGroup: reqChat.Server == types.GroupServer},
			ID:            oldest.ID,
			Timestamp:     oldest.Timestamp,
		}
		req := client.BuildHistorySyncRequest(info, batch)
		if req == nil {
			return total, fmt.Errorf("could not build history request")
		}
		// Drain stale signals so we only wait on our own response.
		for len(onDemandSyncCh) > 0 {
			<-onDemandSyncCh
		}
		if _, err := client.SendPeerMessage(ctx, req); err != nil {
			return total, fmt.Errorf("send request: %w", err)
		}
		backfillMu.Lock()
		backfillState.Requests++
		backfillMu.Unlock()

		var res onDemandResult
		select {
		case res = <-onDemandSyncCh:
		case <-time.After(backfillWaitTimeout):
			return total, errTimeout
		case <-ctx.Done():
			return total, ctx.Err()
		}
		after, _ := store.CountMessages("")
		gained := after - before
		total += gained
		backfillMu.Lock()
		backfillState.MessagesNow += gained
		backfillState.Timeouts = 0
		backfillMu.Unlock()

		if res.Raw == 0 || res.Oldest == nil || res.Oldest.ID == oldest.ID {
			return total, nil // reached the beginning of what the phone has
		}
		// Prefer the DB anchor (has the resolved sender); fall back to the response key.
		if dbOldest, err := store.GetOldestMessage(chatJID); err == nil && dbOldest.ID == res.Oldest.ID {
			oldest = dbOldest
		} else {
			oldest = res.Oldest
		}
		time.Sleep(backfillPause)
	}
}

var errTimeout = fmt.Errorf("timeout waiting for phone (is it online with WhatsApp open?)")

func runBackfill(client *whatsmeow.Client, store *MessageStore, chats []string, requestAs string, batch int) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { // stop watcher
		for {
			time.Sleep(time.Second)
			backfillMu.Lock()
			stop := backfillState.StopRequested || !backfillState.Running
			backfillMu.Unlock()
			if stop {
				cancel()
				return
			}
		}
	}()
	defer func() {
		backfillMu.Lock()
		backfillState.Running = false
		backfillState.CurrentChat = ""
		backfillState.FinishedAt = time.Now().Format(time.RFC3339)
		backfillMu.Unlock()
		backfillLog("finished")
	}()

	consecutiveTimeouts := 0
	for i, jid := range chats {
		if ctx.Err() != nil {
			backfillLog("stopped by request")
			return
		}
		backfillMu.Lock()
		backfillState.CurrentChat = jid
		backfillMu.Unlock()

		got, err := backfillChat(ctx, client, store, jid, requestAs, batch)
		backfillMu.Lock()
		backfillState.ChatsDone = i + 1
		if err != nil {
			backfillState.LastError = fmt.Sprintf("%s: %v", jid, err)
		}
		backfillMu.Unlock()

		if err == errTimeout {
			consecutiveTimeouts++
			backfillMu.Lock()
			backfillState.Timeouts = consecutiveTimeouts
			backfillMu.Unlock()
			backfillLog("%s: +%d then timeout (%d/%d)", jid, got, consecutiveTimeouts, backfillMaxTimeouts)
			if consecutiveTimeouts >= backfillMaxTimeouts {
				backfillLog("phone not responding, aborting run")
				return
			}
			continue
		}
		consecutiveTimeouts = 0
		if err != nil && ctx.Err() == nil {
			backfillLog("%s: +%d, error: %v", jid, got, err)
		} else if got > 0 {
			backfillLog("%s: +%d older messages", jid, got)
		}
	}
}

func registerBackfillRoutes(client *whatsmeow.Client, store *MessageStore) {
	writeJSON := func(w http.ResponseWriter, code int, v interface{}) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(code)
		_ = json.NewEncoder(w).Encode(v)
	}

	http.HandleFunc("/api/backfill", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST only"})
			return
		}
		var req struct {
			ChatJID   string `json:"chat_jid"`
			RequestAs string `json:"request_as"` // optional alternate JID (e.g. @lid) to put in the request
			Batch     int    `json:"batch"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		if req.Batch <= 0 || req.Batch > 200 {
			req.Batch = backfillBatchDefault
		}
		if !client.IsConnected() || client.Store.ID == nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "not connected"})
			return
		}
		var chats []string
		if req.ChatJID != "" {
			chats = []string{req.ChatJID}
		} else {
			req.RequestAs = ""
			all, err := store.ListChatJIDs()
			if err != nil {
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
				return
			}
			chats = all
		}
		backfillMu.Lock()
		if backfillState.Running {
			backfillMu.Unlock()
			writeJSON(w, http.StatusConflict, map[string]string{"error": "backfill already running"})
			return
		}
		total, _ := store.CountMessages("")
		backfillState = backfillStatus{Running: true, ChatsTotal: len(chats), MessagesBefore: total, MessagesNow: total, StartedAt: time.Now().Format(time.RFC3339)}
		backfillMu.Unlock()
		backfillLog("starting: %d chats, batch %d", len(chats), req.Batch)
		go runBackfill(client, store, chats, req.RequestAs, req.Batch)
		writeJSON(w, http.StatusAccepted, map[string]interface{}{"started": true, "chats": len(chats)})
	})

	http.HandleFunc("/api/backfill/status", func(w http.ResponseWriter, r *http.Request) {
		backfillMu.Lock()
		s := backfillState
		backfillMu.Unlock()
		writeJSON(w, http.StatusOK, s)
	})

	http.HandleFunc("/api/backfill/stop", func(w http.ResponseWriter, r *http.Request) {
		backfillMu.Lock()
		backfillState.StopRequested = true
		backfillMu.Unlock()
		writeJSON(w, http.StatusOK, map[string]bool{"stopping": true})
	})
}
