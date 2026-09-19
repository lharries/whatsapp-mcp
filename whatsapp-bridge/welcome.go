package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// Per-group welcome settings
type WelcomeGroup struct {
	Message         string `json:"message"`
	CooldownMinutes int    `json:"cooldown_minutes"`
}

// welcome.json - controls the join-triggered welcome message
type WelcomeConfig struct {
	Enabled         bool                    `json:"enabled"`
	DebounceSeconds int                     `json:"debounce_seconds"`
	OnlyInviteJoins bool                    `json:"only_invite_joins"`
	Groups          map[string]WelcomeGroup `json:"groups"`
}

// Joins that arrived within the debounce window, waiting to be sent as one message
type pendingJoins struct {
	users []types.JID
	timer *time.Timer
}

type welcomeState struct {
	mu       sync.Mutex
	config   WelcomeConfig
	pending  map[string]*pendingJoins
	lastSent map[string]time.Time
	client   *whatsmeow.Client
	store    *MessageStore
	logger   waLog.Logger
}

var welcome *welcomeState

const welcomeConfigPath = "welcome.json"
const recapPath = "store/recap.txt"

// Records joins and leaves so retention can actually be measured
func (store *MessageStore) initGroupEvents() error {
	_, err := store.db.Exec(`
		CREATE TABLE IF NOT EXISTS group_events (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			group_jid TEXT,
			user_jid TEXT,
			event_type TEXT,
			reason TEXT,
			timestamp TIMESTAMP
		);
		CREATE INDEX IF NOT EXISTS idx_group_events_time ON group_events(timestamp);
	`)
	return err
}

func (store *MessageStore) storeGroupEvent(groupJID, userJID, eventType, reason string, ts time.Time) error {
	_, err := store.db.Exec(
		"INSERT INTO group_events (group_jid, user_jid, event_type, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
		groupJID, userJID, eventType, reason, ts,
	)
	return err
}

func loadWelcomeConfig(logger waLog.Logger) WelcomeConfig {
	cfg := WelcomeConfig{Enabled: false, DebounceSeconds: 120, Groups: map[string]WelcomeGroup{}}

	data, err := os.ReadFile(welcomeConfigPath)
	if err != nil {
		if !os.IsNotExist(err) {
			logger.Warnf("Could not read %s: %v", welcomeConfigPath, err)
		}
		return cfg
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		logger.Errorf("Invalid %s, welcome disabled: %v", welcomeConfigPath, err)
		return WelcomeConfig{Enabled: false, DebounceSeconds: 120, Groups: map[string]WelcomeGroup{}}
	}
	if cfg.DebounceSeconds <= 0 {
		cfg.DebounceSeconds = 120
	}
	if cfg.Groups == nil {
		cfg.Groups = map[string]WelcomeGroup{}
	}
	return cfg
}

func initWelcome(client *whatsmeow.Client, store *MessageStore, logger waLog.Logger) {
	if err := store.initGroupEvents(); err != nil {
		logger.Errorf("Failed to create group_events table: %v", err)
	}

	welcome = &welcomeState{
		config:   loadWelcomeConfig(logger),
		pending:  make(map[string]*pendingJoins),
		lastSent: make(map[string]time.Time),
		client:   client,
		store:    store,
		logger:   logger,
	}

	if welcome.config.Enabled {
		logger.Infof("Welcome messages enabled for %d group(s)", len(welcome.config.Groups))
	} else {
		logger.Infof("Welcome messages disabled (edit %s to enable)", welcomeConfigPath)
	}

	registerGroupEventEndpoints(store)
	registerGroupsEndpoint(client)
	registerSetDescriptionEndpoint(client)
	registerSetPhotoEndpoint(client)
	registerPictureEndpoint(client)
	registerSetNameEndpoint(client)
}

// POST /api/set_name {"jid": "...", "name": "..."}
// Community and announcement group names are independent, like their descriptions.
func registerSetNameEndpoint(client *whatsmeow.Client) {
	http.HandleFunc("/api/set_name", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			JID  string `json:"jid"`
			Name string `json:"name"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request body", http.StatusBadRequest)
			return
		}

		jid, err := types.ParseJID(req.JID)
		if err != nil {
			http.Error(w, fmt.Sprintf("Invalid JID: %v", err), http.StatusBadRequest)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		if err := client.SetGroupName(r.Context(), jid, req.Name); err != nil {
			json.NewEncoder(w).Encode(map[string]any{"success": false, "message": err.Error()})
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"success": true, "message": "Name updated"})
	})
}

// GET /api/picture?jid=... - which picture a group currently shows, so an
// inherited icon can be told apart from one that was never set.
func registerPictureEndpoint(client *whatsmeow.Client) {
	http.HandleFunc("/api/picture", func(w http.ResponseWriter, r *http.Request) {
		jid, err := types.ParseJID(r.URL.Query().Get("jid"))
		if err != nil {
			http.Error(w, fmt.Sprintf("Invalid JID: %v", err), http.StatusBadRequest)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		info, err := client.GetProfilePictureInfo(r.Context(), jid, nil)
		if err != nil {
			json.NewEncoder(w).Encode(map[string]any{"success": false, "message": err.Error()})
			return
		}
		if info == nil {
			json.NewEncoder(w).Encode(map[string]any{"success": true, "picture_id": nil})
			return
		}
		json.NewEncoder(w).Encode(map[string]any{
			"success": true, "picture_id": info.ID, "url": info.URL, "type": info.Type,
		})
	})
}

// POST /api/set_photo {"jid": "...", "path": "C:\\...\\icon.jpg"}
// WhatsApp only accepts JPEG here. Omitting "path" removes the current photo.
func registerSetPhotoEndpoint(client *whatsmeow.Client) {
	http.HandleFunc("/api/set_photo", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			JID  string `json:"jid"`
			Path string `json:"path"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request body", http.StatusBadRequest)
			return
		}

		jid, err := types.ParseJID(req.JID)
		if err != nil {
			http.Error(w, fmt.Sprintf("Invalid JID: %v", err), http.StatusBadRequest)
			return
		}

		w.Header().Set("Content-Type", "application/json")

		var avatar []byte
		if req.Path != "" {
			avatar, err = os.ReadFile(req.Path)
			if err != nil {
				json.NewEncoder(w).Encode(map[string]any{"success": false, "message": err.Error()})
				return
			}
		}

		pictureID, err := client.SetGroupPhoto(r.Context(), jid, avatar)
		if err != nil {
			json.NewEncoder(w).Encode(map[string]any{"success": false, "message": err.Error()})
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"success": true, "picture_id": pictureID})
	})
}

// POST /api/set_description {"jid": "...", "description": "..."}
// Works for regular groups and for a community's parent group. Requires admin
// rights, and WhatsApp posts a system message in the group on success.
func registerSetDescriptionEndpoint(client *whatsmeow.Client) {
	http.HandleFunc("/api/set_description", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			JID         string `json:"jid"`
			Description string `json:"description"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request body", http.StatusBadRequest)
			return
		}

		jid, err := types.ParseJID(req.JID)
		if err != nil {
			http.Error(w, fmt.Sprintf("Invalid JID: %v", err), http.StatusBadRequest)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		if err := client.SetGroupTopic(r.Context(), jid, "", "", req.Description); err != nil {
			json.NewEncoder(w).Encode(map[string]any{"success": false, "message": err.Error()})
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"success": true, "message": "Description updated"})
	})
}

// GET /api/groups - group metadata, so the community announcement group can be
// identified for certain instead of guessed from its name
func registerGroupsEndpoint(client *whatsmeow.Client) {
	http.HandleFunc("/api/groups", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		groups, err := client.GetJoinedGroups(r.Context())
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		type groupOut struct {
			JID               string `json:"jid"`
			Name              string `json:"name"`
			Topic             string `json:"topic"`
			Participants      int    `json:"participants"`
			IsAnnounce        bool   `json:"is_announce"`
			IsParent          bool   `json:"is_community"`
			IsDefaultSubGroup bool   `json:"is_default_subgroup"`
			LinkedParentJID   string `json:"linked_parent_jid"`
		}

		out := []groupOut{}
		for _, g := range groups {
			parent := ""
			if !g.LinkedParentJID.IsEmpty() {
				parent = g.LinkedParentJID.String()
			}
			count := g.ParticipantCount
			if count == 0 {
				count = len(g.Participants)
			}
			out = append(out, groupOut{
				JID:               g.JID.String(),
				Name:              g.Name,
				Topic:             g.Topic,
				Participants:      count,
				IsAnnounce:        g.IsAnnounce,
				IsParent:          g.IsParent,
				IsDefaultSubGroup: g.IsDefaultSubGroup,
				LinkedParentJID:   parent,
			})
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(out)
	})
}

// Records the event, then queues a welcome if this group is configured for one
func handleGroupInfo(evt *events.GroupInfo, store *MessageStore, logger waLog.Logger) {
	groupJID := evt.JID.String()

	for _, u := range evt.Leave {
		if err := store.storeGroupEvent(groupJID, u.String(), "leave", evt.JoinReason, evt.Timestamp); err != nil {
			logger.Warnf("Failed to store leave event: %v", err)
		}
		logger.Infof("Member left %s: %s", groupJID, u.String())
	}

	if len(evt.Join) == 0 {
		return
	}

	for _, u := range evt.Join {
		if err := store.storeGroupEvent(groupJID, u.String(), "join", evt.JoinReason, evt.Timestamp); err != nil {
			logger.Warnf("Failed to store join event: %v", err)
		}
		logger.Infof("Member joined %s: %s (reason: %q)", groupJID, u.String(), evt.JoinReason)
	}

	if welcome == nil || !welcome.config.Enabled {
		return
	}
	if welcome.config.OnlyInviteJoins && evt.JoinReason != "invite" {
		return
	}
	if _, ok := welcome.config.Groups[groupJID]; !ok {
		return
	}

	welcome.queueJoins(groupJID, evt.Join)
}

// Batches joins arriving close together so ten arrivals produce one message, not ten
func (w *welcomeState) queueJoins(groupJID string, users []types.JID) {
	w.mu.Lock()
	defer w.mu.Unlock()

	p, ok := w.pending[groupJID]
	if !ok {
		p = &pendingJoins{}
		w.pending[groupJID] = p
	}
	p.users = append(p.users, users...)

	if p.timer != nil {
		p.timer.Stop()
	}
	delay := time.Duration(w.config.DebounceSeconds) * time.Second
	p.timer = time.AfterFunc(delay, func() { w.flush(groupJID) })
}

func (w *welcomeState) flush(groupJID string) {
	w.mu.Lock()
	p, ok := w.pending[groupJID]
	if !ok || len(p.users) == 0 {
		w.mu.Unlock()
		return
	}
	users := p.users
	delete(w.pending, groupJID)

	group := w.config.Groups[groupJID]
	cooldown := time.Duration(group.CooldownMinutes) * time.Minute
	if last, seen := w.lastSent[groupJID]; seen && cooldown > 0 && time.Since(last) < cooldown {
		w.mu.Unlock()
		w.logger.Infof("Skipping welcome in %s: cooldown active (%d min)", groupJID, group.CooldownMinutes)
		return
	}
	w.lastSent[groupJID] = time.Now()
	client := w.client
	w.mu.Unlock()

	text := renderWelcome(group.Message, users)
	if strings.TrimSpace(text) == "" {
		w.logger.Warnf("Empty welcome template for %s, nothing sent", groupJID)
		return
	}

	ok, errMsg := sendWhatsAppMessage(client, groupJID, text, "")
	if !ok {
		w.logger.Errorf("Failed to send welcome to %s: %s", groupJID, errMsg)
		return
	}
	w.logger.Infof("Sent welcome to %s for %d new member(s)", groupJID, len(users))
}

// Placeholders: {count}, {names}, {recap}
func renderWelcome(template string, users []types.JID) string {
	names := make([]string, 0, len(users))
	for _, u := range users {
		names = append(names, "+"+u.User)
	}

	recap := ""
	if data, err := os.ReadFile(recapPath); err == nil {
		recap = strings.TrimSpace(string(data))
	}

	out := template
	out = strings.ReplaceAll(out, "{count}", fmt.Sprintf("%d", len(users)))
	out = strings.ReplaceAll(out, "{names}", strings.Join(names, ", "))
	out = strings.ReplaceAll(out, "{recap}", recap)
	return out
}

func registerGroupEventEndpoints(store *MessageStore) {
	// GET /api/group_events?group=<jid>&days=30 - joins and leaves, for retention tracking
	http.HandleFunc("/api/group_events", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		days := 30
		if d := r.URL.Query().Get("days"); d != "" {
			fmt.Sscanf(d, "%d", &days)
		}
		since := time.Now().AddDate(0, 0, -days)

		var rows *sql.Rows
		var err error
		if g := r.URL.Query().Get("group"); g != "" {
			rows, err = store.db.Query(
				"SELECT group_jid, user_jid, event_type, reason, timestamp FROM group_events WHERE timestamp > ? AND group_jid = ? ORDER BY timestamp DESC",
				since, g)
		} else {
			rows, err = store.db.Query(
				"SELECT group_jid, user_jid, event_type, reason, timestamp FROM group_events WHERE timestamp > ? ORDER BY timestamp DESC",
				since)
		}
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		defer rows.Close()

		type ev struct {
			GroupJID  string    `json:"group_jid"`
			UserJID   string    `json:"user_jid"`
			EventType string    `json:"event_type"`
			Reason    string    `json:"reason"`
			Timestamp time.Time `json:"timestamp"`
		}
		out := []ev{}
		for rows.Next() {
			var e ev
			if err := rows.Scan(&e.GroupJID, &e.UserJID, &e.EventType, &e.Reason, &e.Timestamp); err != nil {
				continue
			}
			out = append(out, e)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(out)
	})
}
