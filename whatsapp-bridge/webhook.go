package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"time"
)

// WebhookPayload is POSTed to cfg.WebhookURL for each incoming message, so an
// agent can react ("this person texted X, how should I reply?") without polling.
type WebhookPayload struct {
	Account    string `json:"account"`
	Event      string `json:"event"`
	ChatJID    string `json:"chat_jid"`
	ChatName   string `json:"chat_name,omitempty"`
	Sender     string `json:"sender"`
	SenderName string `json:"sender_name,omitempty"`
	MessageID  string `json:"message_id,omitempty"`
	Text       string `json:"text"`
	MediaType  string `json:"media_type,omitempty"`
	Timestamp  string `json:"timestamp"`
	IsGroup    bool   `json:"is_group"`
}

// emitWebhook posts the payload asynchronously with a couple of retries. It never
// blocks the message path and never fails the caller.
func (cfg Config) emitWebhook(p WebhookPayload) {
	if cfg.WebhookURL == "" {
		return
	}
	body, err := json.Marshal(p)
	if err != nil {
		return
	}
	var sig string
	if cfg.WebhookSecret != "" {
		mac := hmac.New(sha256.New, []byte(cfg.WebhookSecret))
		mac.Write(body)
		sig = "sha256=" + hex.EncodeToString(mac.Sum(nil))
	}
	go func() {
		client := &http.Client{Timeout: 10 * time.Second}
		for attempt := 0; attempt < 3; attempt++ {
			req, err := http.NewRequest(http.MethodPost, cfg.WebhookURL, bytes.NewReader(body))
			if err != nil {
				return
			}
			req.Header.Set("Content-Type", "application/json")
			if sig != "" {
				req.Header.Set("X-WA-Signature", sig)
			}
			resp, err := client.Do(req)
			if err == nil {
				resp.Body.Close()
				if resp.StatusCode < 300 {
					return
				}
			}
			time.Sleep(time.Duration(attempt+1) * time.Second)
		}
	}()
}
