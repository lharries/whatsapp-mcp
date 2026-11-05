package main

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/appstate"
	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/proto"
)

type jidsRequest struct {
	JIDs []string `json:"jids"`
}

type businessInfo struct {
	JID          string   `json:"jid"`
	IsBusiness   bool     `json:"is_business"`
	VerifiedName string   `json:"verified_name,omitempty"`
	Categories   []string `json:"categories,omitempty"`
	Email        string   `json:"email,omitempty"`
	Address      string   `json:"address,omitempty"`
	Error        string   `json:"error,omitempty"`
}

type actionResult struct {
	JID   string `json:"jid"`
	OK    bool   `json:"ok"`
	Error string `json:"error,omitempty"`
}

func decodeJIDs(w http.ResponseWriter, r *http.Request) ([]string, bool) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return nil, false
	}
	var req jidsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || len(req.JIDs) == 0 {
		http.Error(w, "jids is required", http.StatusBadRequest)
		return nil, false
	}
	return req.JIDs, true
}

// registerAdminRoutes adds business lookup, block and delete-chat endpoints.
func registerAdminRoutes(client *whatsmeow.Client, messageStore *MessageStore) {
	http.HandleFunc("/api/business-check", func(w http.ResponseWriter, r *http.Request) {
		jids, ok := decodeJIDs(w, r)
		if !ok {
			return
		}
		ctx := context.Background()
		results := make([]businessInfo, 0, len(jids))
		for _, s := range jids {
			res := businessInfo{JID: s}
			jid, err := types.ParseJID(s)
			if err != nil {
				res.Error = err.Error()
				results = append(results, res)
				continue
			}
			if info, err := client.GetUserInfo(ctx, []types.JID{jid}); err == nil {
				if ui, ok := info[jid]; ok && ui.VerifiedName != nil && ui.VerifiedName.Details != nil {
					res.IsBusiness = true
					res.VerifiedName = ui.VerifiedName.Details.GetVerifiedName()
				}
			} else {
				res.Error = err.Error()
			}
			// Non-business accounts return an empty profile.
			if bp, err := client.GetBusinessProfile(ctx, jid); err == nil && bp != nil {
				for _, c := range bp.Categories {
					res.Categories = append(res.Categories, c.Name)
				}
				res.Email, res.Address = bp.Email, bp.Address
				if len(res.Categories) > 0 || res.Email != "" || res.Address != "" {
					res.IsBusiness = true
				}
			}
			results = append(results, res)
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(results)
	})

	http.HandleFunc("/api/block", func(w http.ResponseWriter, r *http.Request) {
		jids, ok := decodeJIDs(w, r)
		if !ok {
			return
		}
		results := make([]actionResult, 0, len(jids))
		for _, s := range jids {
			res := actionResult{JID: s}
			jid, err := types.ParseJID(s)
			if err == nil {
				_, err = client.UpdateBlocklist(context.Background(), jid, events.BlocklistChangeActionBlock, "")
			}
			if err != nil {
				res.Error = err.Error()
			} else {
				res.OK = true
			}
			results = append(results, res)
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(results)
	})

	http.HandleFunc("/api/delete-chat", func(w http.ResponseWriter, r *http.Request) {
		jids, ok := decodeJIDs(w, r)
		if !ok {
			return
		}
		results := make([]actionResult, 0, len(jids))
		for _, s := range jids {
			res := actionResult{JID: s}
			jid, err := types.ParseJID(s)
			if err == nil {
				// The delete range must reference the chat's latest message when we know it.
				var lastTS time.Time
				var lastKey *waCommon.MessageKey
				var id string
				var fromMe bool
				if messageStore.db.QueryRow("SELECT id, timestamp, is_from_me FROM messages WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT 1", s).Scan(&id, &lastTS, &fromMe) == nil {
					lastKey = &waCommon.MessageKey{RemoteJID: proto.String(s), FromMe: proto.Bool(fromMe), ID: proto.String(id)}
				} else {
					lastTS = time.Now()
				}
				err = client.SendAppState(context.Background(), appstate.BuildDeleteChat(jid, lastTS, lastKey, true))
			}
			if err == nil {
				messageStore.db.Exec("DELETE FROM messages WHERE chat_jid = ?", s)
				messageStore.db.Exec("DELETE FROM chats WHERE jid = ?", s)
				res.OK = true
			} else {
				res.Error = err.Error()
			}
			results = append(results, res)
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(results)
	})
}
