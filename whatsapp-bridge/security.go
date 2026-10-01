package main

import (
	"crypto/sha256"
	"crypto/subtle"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"go.mau.fi/whatsmeow"
)

const defaultAPIPort = 18765

type pairingInfo struct {
	sync.RWMutex
	QR     string
	Paired bool
	Error  string
}

var pairing pairingInfo

type apiActions struct {
	send     func(string, string, string) (bool, string)
	download func(string, string) (bool, string, string, string, error)
	status   func() any
}

// Every route shares the same caller boundary, including status and pairing.
func newAPIHandler(token, host string, actions apiActions) (http.Handler, error) {
	if len(token) < 32 {
		return nil, errors.New("a bridge token of at least 32 characters is required")
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "Method not allowed", 405)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(actions.status())
	})
	mux.HandleFunc("/api/send", func(w http.ResponseWriter, r *http.Request) {
		var req SendMessageRequest
		if !decodeRequest(w, r, &req) {
			return
		}
		if req.Recipient == "" || (req.Message == "" && req.MediaPath == "") {
			http.Error(w, "Recipient and message or media path required", 400)
			return
		}
		ok, message := actions.send(req.Recipient, req.Message, req.MediaPath)
		w.Header().Set("Content-Type", "application/json")
		if !ok {
			w.WriteHeader(500)
		}
		json.NewEncoder(w).Encode(SendMessageResponse{Success: ok, Message: message})
	})
	mux.HandleFunc("/api/download", func(w http.ResponseWriter, r *http.Request) {
		var req DownloadMediaRequest
		if !decodeRequest(w, r, &req) {
			return
		}
		if req.MessageID == "" || req.ChatJID == "" {
			http.Error(w, "Message ID and chat JID required", 400)
			return
		}
		ok, mediaType, filename, path, err := actions.download(req.MessageID, req.ChatJID)
		w.Header().Set("Content-Type", "application/json")
		if !ok || err != nil {
			w.WriteHeader(500)
			json.NewEncoder(w).Encode(DownloadMediaResponse{Message: "Media download failed"})
			return
		}
		json.NewEncoder(w).Encode(DownloadMediaResponse{Success: true, Message: "Downloaded " + mediaType, Filename: filename, Path: path})
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		if r.Host != host || len(r.Header.Values("Origin")) != 0 {
			http.Error(w, "Forbidden", 403)
			return
		}
		values := r.Header.Values("Authorization")
		if len(values) != 1 || subtle.ConstantTimeCompare([]byte(values[0]), []byte("Bearer "+token)) != 1 {
			http.Error(w, "Unauthorized", 401)
			return
		}
		mux.ServeHTTP(w, r)
	}), nil
}

func decodeRequest(w http.ResponseWriter, r *http.Request, dest any) bool {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", 405)
		return false
	}
	contentType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || contentType != "application/json" {
		http.Error(w, "JSON required", 415)
		return false
	}
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(dest); err != nil {
		http.Error(w, "Invalid request", 400)
		return false
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		http.Error(w, "Invalid request", 400)
		return false
	}
	return true
}

func startRESTServer(client *whatsmeow.Client, store *MessageStore, port int, token string) (*http.Server, error) {
	host := net.JoinHostPort("127.0.0.1", strconv.Itoa(port))
	handler, err := newAPIHandler(token, host, apiActions{
		send: func(recipient, message, path string) (bool, string) {
			return sendWhatsAppMessage(client, recipient, message, path)
		},
		download: func(id, chat string) (bool, string, string, string, error) {
			return downloadMedia(client, store, id, chat)
		},
		status: func() any {
			pairing.RLock()
			defer pairing.RUnlock()
			return map[string]any{"connected": client.IsConnected(), "paired": pairing.Paired, "qr_code": pairing.QR, "pairing_error": pairing.Error}
		},
	})
	if err != nil {
		return nil, err
	}
	certificate, err := tls.LoadX509KeyPair(os.Getenv("WHATSAPP_TLS_CERT"), os.Getenv("WHATSAPP_TLS_KEY"))
	if err != nil {
		return nil, fmt.Errorf("private TLS identity unavailable: %w", err)
	}
	listener, err := net.Listen("tcp", host)
	if err != nil {
		return nil, err
	}
	server := &http.Server{Handler: handler, TLSConfig: &tls.Config{MinVersion: tls.VersionTLS12, Certificates: []tls.Certificate{certificate}}, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 2 * time.Minute, IdleTimeout: 30 * time.Second}
	go func() {
		if err := server.ServeTLS(listener, "", ""); err != nil && err != http.ErrServerClosed {
			fmt.Println("Bridge HTTP server stopped")
		}
	}()
	return server, nil
}

var mediaMutex sync.Mutex

// No remote filename or chat identifier is ever interpreted as a filesystem path.
func mediaStorageName(chatID, messageID, mediaType, displayName string) string {
	digest := sha256.Sum256([]byte(chatID + "\x00" + messageID))
	ext := map[string]string{"image": ".jpg", "video": ".mp4", "audio": ".ogg"}[mediaType]
	if ext == "" {
		ext = ".bin"
		candidate := strings.ToLower(filepath.Ext(displayName))
		for _, safe := range []string{".pdf", ".txt", ".csv", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".json"} {
			if candidate == safe {
				ext = safe
				break
			}
		}
	}
	return hex.EncodeToString(digest[:]) + ext
}

func cachedOrDownloadMedia(rootPath, chatID, messageID, mediaType, displayName string, download func() ([]byte, error)) (string, error) {
	mediaMutex.Lock()
	defer mediaMutex.Unlock()
	if err := os.MkdirAll(rootPath, 0700); err != nil {
		return "", err
	}
	root, err := os.OpenRoot(rootPath)
	if err != nil {
		return "", err
	}
	defer root.Close()
	name := mediaStorageName(chatID, messageID, mediaType, displayName)
	absRoot, err := filepath.Abs(rootPath)
	if err != nil {
		return "", err
	}
	info, err := root.Lstat(name)
	if err == nil {
		if !info.Mode().IsRegular() {
			return "", errors.New("cached media must be a regular file")
		}
		file, err := root.Open(name)
		if err != nil {
			return "", err
		}
		actual, err := file.Stat()
		file.Close()
		if err != nil || !actual.Mode().IsRegular() {
			return "", errors.New("invalid cached media")
		}
		return filepath.Join(absRoot, name), nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	data, err := download()
	if err != nil {
		return "", err
	}
	file, err := root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return "", err
	}
	_, writeErr := file.Write(data)
	closeErr := file.Close()
	if writeErr != nil || closeErr != nil {
		root.Remove(name)
		return "", errors.Join(writeErr, closeErr)
	}
	return filepath.Join(absRoot, name), nil
}
