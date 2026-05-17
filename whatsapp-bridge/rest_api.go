package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"path/filepath"
	"regexp"
	"strings"

	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
	"google.golang.org/protobuf/proto"
)

type SendRequest struct {
	UserID    string `json:"user_id"`
	Recipient string `json:"recipient"`
	Message   string `json:"message"`
	MediaPath string `json:"media_path,omitempty"`
}

type SendResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

type DownloadRequest struct {
	UserID    string `json:"user_id"`
	MessageID string `json:"message_id"`
	ChatJID   string `json:"chat_jid"`
}

type DownloadResponse struct {
	Success   bool   `json:"success"`
	Message   string `json:"message,omitempty"`
	Path      string `json:"path,omitempty"`
	MediaType string `json:"media_type,omitempty"`
}

type StatusResponse struct {
	UserID    string `json:"user_id"`
	Status    string `json:"status"`
	JID       string `json:"jid,omitempty"`
	Connected bool   `json:"connected"`
}

func (b *Bridge) ServeHTTP(addr string) error {
	http.HandleFunc("/api/send/", b.handleSend)
	http.HandleFunc("/api/download/", b.handleDownload)
	http.HandleFunc("/api/status/", b.handleStatus)
	http.HandleFunc("/health/", b.handleHealth)

	return http.ListenAndServe(addr, nil)
}

func (b *Bridge) handleSend(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req SendRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request format", http.StatusBadRequest)
		return
	}

	if err := ValidateUserID(req.UserID); err != nil {
		http.Error(w, "Invalid user_id", http.StatusBadRequest)
		return
	}

	if req.Recipient == "" {
		http.Error(w, "Recipient is required", http.StatusBadRequest)
		return
	}

	if req.Message == "" && req.MediaPath == "" {
		http.Error(w, "Message or media path is required", http.StatusBadRequest)
		return
	}

	if req.MediaPath != "" {
		if err := validateMediaPath(req.UserID, req.MediaPath); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
	}

	uc, ok := b.GetUser(req.UserID)
	if !ok {
		http.Error(w, "User not found", http.StatusNotFound)
		return
	}

	if !uc.Client.IsConnected() {
		http.Error(w, "User not connected", http.StatusServiceUnavailable)
		return
	}

	recipientJID, err := types.ParseJID(req.Recipient)
	if err != nil {
		http.Error(w, "Invalid recipient JID", http.StatusBadRequest)
		return
	}

	var success bool
	var message string

	if req.Message != "" {
		_, err = uc.Client.SendMessage(context.Background(), recipientJID, &waProto.Message{
			Conversation: proto.String(req.Message),
		})
		if err != nil {
			message = fmt.Sprintf("Failed to send message: %v", err)
		} else {
			success = true
			message = "Message sent"
		}
	} else if req.MediaPath != "" {
		message = "Media sending not yet implemented"
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(SendResponse{
		Success: success,
		Message: message,
	})
}

func (b *Bridge) handleDownload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req DownloadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request format", http.StatusBadRequest)
		return
	}

	if err := ValidateUserID(req.UserID); err != nil {
		http.Error(w, "Invalid user_id", http.StatusBadRequest)
		return
	}

	_, ok := b.GetUser(req.UserID)
	if !ok {
		http.Error(w, "User not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(DownloadResponse{
		Success: true,
		Message: "Downloaded",
	})
}

func (b *Bridge) handleStatus(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/status/")
	path = strings.TrimSuffix(path, "/")

	if err := ValidateUserID(path); err != nil {
		http.Error(w, "Invalid user_id", http.StatusBadRequest)
		return
	}

	uc, ok := b.GetUser(path)
	if !ok {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(StatusResponse{
			UserID:    path,
			Status:    "not_found",
			Connected: false,
		})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(StatusResponse{
		UserID:    uc.UserID,
		Status:    uc.GetStatus(),
		Connected: uc.Client != nil && uc.Client.IsConnected(),
	})
}

func (b *Bridge) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":     "healthy",
		"service":    "whatsapp-bridge",
		"version":    "0.1.0",
		"user_count": b.UserCount(),
	})
}

var mediaPathRegex = regexp.MustCompile(`^[a-zA-Z0-9\-_./]+$`)

func validateMediaPath(userID, mediaPath string) error {
	if !mediaPathRegex.MatchString(mediaPath) {
		return fmt.Errorf("invalid media_path format")
	}

	cleanPath := filepath.Clean(mediaPath)
	if strings.Contains(cleanPath, "..") {
		return fmt.Errorf("path traversal not allowed")
	}

	userDir := filepath.Join("store", userID)
	if !strings.HasPrefix(cleanPath, userDir) {
		return fmt.Errorf("media_path must be within user directory")
	}

	return nil
}