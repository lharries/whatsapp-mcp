package main

import (
	"context"
	"fmt"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/proto/waHistorySync"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types/events"
)

func (b *Bridge) StartUserHandler(ctx context.Context, uc *UserClient) {
	go b.handleQRChannel(ctx, uc)

	for {
		select {
		case <-uc.StopChan:
			b.logger.Infof("User %s handler stopped", uc.UserID)
			return
		case <-ctx.Done():
			return
		default:
			b.handleUserStatus(ctx, uc)
		}
	}
}

func (b *Bridge) handleQRChannel(ctx context.Context, uc *UserClient) {
	for {
		select {
		case <-uc.StopChan:
			return
		case <-ctx.Done():
			return
		case qr := <-uc.QRChan:
			if err := b.api.PushQR(ctx, toUserID(uc.UserID), qr.ImageData, qr.ExpiresAt); err != nil {
				b.logger.Errorf("Failed to push QR to Django for user %s: %v", uc.UserID, err)
			} else {
				b.logger.Infof("QR pushed to Django for user %s", uc.UserID)
			}
		}
	}
}

func (b *Bridge) handleUserStatus(ctx context.Context, uc *UserClient) {
	status := uc.GetStatus()

	switch status {
	case "pending_init_request":
		b.handlePendingInitRequest(ctx, uc)
	case "pending_handshake":
		b.handlePendingHandshake(ctx, uc)
	case "connected":
		b.handleConnected(ctx, uc)
	case "sync_error":
		b.handleSyncError(ctx, uc)
	default:
		time.Sleep(5 * time.Second)
	}
}

func (b *Bridge) handlePendingInitRequest(ctx context.Context, uc *UserClient) {
	if uc.Client.Store.ID != nil {
		uc.SetStatus("pending_handshake")
		return
	}

	qrChan, err := uc.Client.GetQRChannel(ctx)
	if err != nil {
		b.logger.Errorf("Failed to get QR channel for user %s: %v", uc.UserID, err)
		time.Sleep(5 * time.Second)
		return
	}

	for {
		select {
		case <-uc.StopChan:
			return
		case <-ctx.Done():
			return
		case evt := <-qrChan:
			if evt.Event == "code" && evt.Code != "" {
				qr := &QRCodeEvent{
					UserID:    uc.UserID,
					ImageData: evt.Code,
					ExpiresAt: time.Now().Add(60 * time.Second),
				}
				select {
				case uc.QRChan <- qr:
				default:
				}
				b.logger.Infof("QR code generated for user %s", uc.UserID)
			} else if evt.Event == "success" {
				uc.SetStatus("connected")
				if err := b.api.UpdateUserStatus(ctx, toUserID(uc.UserID), "connected"); err != nil {
					b.logger.Errorf("Failed to update status to connected for user %s: %v", uc.UserID, err)
				}
				b.logger.Infof("User %s successfully authenticated", uc.UserID)
				b.setupEventHandler(uc)
				return
			}
		}
	}
}

func (b *Bridge) handlePendingHandshake(ctx context.Context, uc *UserClient) {
	if uc.Client.IsConnected() {
		uc.SetStatus("connected")
		b.api.UpdateUserStatus(ctx, toUserID(uc.UserID), "connected")
		b.setupEventHandler(uc)
		return
	}

	if err := uc.Client.Connect(); err != nil {
		b.logger.Errorf("Failed to connect for user %s: %v", uc.UserID, err)
		time.Sleep(5 * time.Second)
		return
	}

	uc.SetStatus("connected")
	b.api.UpdateUserStatus(ctx, toUserID(uc.UserID), "connected")
	b.setupEventHandler(uc)
}

func (b *Bridge) handleConnected(ctx context.Context, uc *UserClient) {
	if !uc.Client.IsConnected() {
		uc.Client.Disconnect()
		if err := uc.Client.Connect(); err != nil {
			b.logger.Errorf("Failed to reconnect for user %s: %v", uc.UserID, err)
			uc.SetStatus("sync_error")
			b.api.UpdateUserStatus(ctx, toUserID(uc.UserID), "sync_error")
			return
		}
		uc.SetStatus("connected")
		b.api.UpdateUserStatus(ctx, toUserID(uc.UserID), "connected")
	}

	time.Sleep(30 * time.Second)
}

func (b *Bridge) handleSyncError(ctx context.Context, uc *UserClient) {
	if err := uc.Client.Connect(); err != nil {
		b.logger.Errorf("Failed to reconnect from sync_error for user %s: %v", uc.UserID, err)
		time.Sleep(30 * time.Second)
		return
	}
	uc.SetStatus("connected")
	b.api.UpdateUserStatus(ctx, toUserID(uc.UserID), "connected")
}

func (b *Bridge) setupEventHandler(uc *UserClient) {
	uc.Client.AddEventHandler(func(evt interface{}) {
		switch v := evt.(type) {
		case *events.Message:
			b.handleIncomingMessage(uc, v)
		case *events.HistorySync:
			b.handleHistorySync(uc, v)
		case *events.Connected:
			b.logger.Infof("User %s connected to WhatsApp", uc.UserID)
		case *events.LoggedOut:
			b.logger.Warnf("User %s logged out", uc.UserID)
			uc.SetStatus("pending_init_request")
		}
	})
}

func (b *Bridge) handleIncomingMessage(uc *UserClient, msg *events.Message) {
	info := msg.Info
	if info.Chat.String() == "" {
		return
	}

	storedMsg := &UserMessage{
		ID:        info.ID,
		ChatJID:   info.Chat.String(),
		Sender:    info.Sender.String(),
		Content:   extractTextContent(msg.Message),
		Timestamp: time.Now(),
		IsFromMe:  info.IsFromMe,
	}

	if err := uc.MessageStore.SaveMessage(storedMsg); err != nil {
		b.logger.Errorf("Failed to save message for user %s: %v", uc.UserID, err)
	}
}

func (b *Bridge) handleHistorySync(uc *UserClient, sync *events.HistorySync) {
	b.logger.Infof("History sync started for user %s", uc.UserID)

	if sync.Data == nil || len(sync.Data.Conversations) == 0 {
		b.logger.Infof("No conversations to sync for user %s", uc.UserID)
		return
	}

	b.logger.Infof("Received history sync event with %d conversations for user %s", len(sync.Data.Conversations), uc.UserID)

	syncedCount := 0

	for _, conversation := range sync.Data.Conversations {
		if conversation.ID == nil {
			continue
		}

		chatJID := *conversation.ID
		name := b.getChatName(uc, chatJID, conversation)

		messages := conversation.Messages
		if len(messages) == 0 {
			continue
		}

		latestMsg := messages[0]
		if latestMsg == nil || latestMsg.Message == nil {
			continue
		}

		timestamp := time.Time{}
		if ts := latestMsg.Message.GetMessageTimestamp(); ts != 0 {
			timestamp = time.Unix(int64(ts), 0)
		} else {
			continue
		}

		chat := &UserChat{
			JID:             chatJID,
			Name:            name,
			LastMessageTime: timestamp,
		}
		if err := uc.MessageStore.SaveChat(chat); err != nil {
			b.logger.Errorf("Failed to save chat %s: %v", chatJID, err)
			continue
		}

		for _, msg := range messages {
			if msg == nil || msg.Message == nil {
				continue
			}

			webMsg := msg.Message
			protoMsg := webMsg.Message

			content := b.extractHistoryMessageContent(protoMsg)
			mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength := b.extractMediaInfo(protoMsg)

			if content == "" && mediaType == "" {
				continue
			}

			var sender string
			isFromMe := false
			if webMsg.Key != nil {
				if webMsg.Key.FromMe != nil {
					isFromMe = *webMsg.Key.FromMe
				}
				if !isFromMe && webMsg.Key.Participant != nil && *webMsg.Key.Participant != "" {
					sender = *webMsg.Key.Participant
				} else if isFromMe && uc.Client != nil && uc.Client.Store != nil && uc.Client.Store.ID != nil {
					sender = uc.Client.Store.ID.User
				} else {
					sender = chatJID
				}
			} else {
				sender = chatJID
			}

			msgID := ""
			if webMsg.Key != nil && webMsg.Key.ID != nil {
				msgID = *webMsg.Key.ID
			}

			msgTimestamp := time.Time{}
			if webMsg.MessageTimestamp != nil && *webMsg.MessageTimestamp != 0 {
				msgTimestamp = time.Unix(int64(*webMsg.MessageTimestamp), 0)
			} else {
				continue
			}

			storedMsg := &UserMessage{
				ID:          msgID,
				ChatJID:     chatJID,
				Sender:      sender,
				Content:     content,
				Timestamp:   msgTimestamp,
				IsFromMe:    isFromMe,
				MediaType:   mediaType,
				Filename:    filename,
				URL:         url,
				MediaKey:    mediaKey,
				FileSHA256:  fileSHA256,
				FileEncSHA2: fileEncSHA256,
				FileLength:  int64(fileLength),
			}

			if err := uc.MessageStore.SaveMessage(storedMsg); err != nil {
				b.logger.Warnf("Failed to store history message for user %s: %v", uc.UserID, err)
			} else {
				syncedCount++
			}
		}
	}

	b.logger.Infof("History sync complete for user %s. Stored %d messages.", uc.UserID, syncedCount)
}

func (b *Bridge) getChatName(uc *UserClient, chatJID string, conversation *waHistorySync.Conversation) string {
	if conversation == nil {
		return chatJID
	}
	if name := conversation.GetName(); name != "" {
		return name
	}
	if name := conversation.GetDisplayName(); name != "" {
		return name
	}
	if name := conversation.GetUsername(); name != "" {
		return name
	}
	return chatJID
}

func (b *Bridge) extractHistoryMessageContent(msg *proto.Message) string {
	if msg == nil {
		return ""
	}
	if conv := msg.GetConversation(); conv != "" {
		return conv
	}
	if ext := msg.GetExtendedTextMessage(); ext != nil {
		return ext.GetText()
	}
	return ""
}

func (b *Bridge) extractMediaInfo(msg *proto.Message) (mediaType, filename, url string, mediaKey, fileSHA256, fileEncSHA256 []byte, fileLength uint64) {
	if msg == nil {
		return
	}

	var generateFilename func(ext string) string
	generateFilename = func(ext string) string {
		return fmt.Sprintf("media_%s.%s", time.Now().Format("20060102_150405"), ext)
	}

	if imgMsg := msg.GetImageMessage(); imgMsg != nil {
		mediaType = "image"
		filename = generateFilename("jpg")
		url = imgMsg.GetURL()
		mediaKey = imgMsg.GetMediaKey()
		fileSHA256 = imgMsg.GetFileSHA256()
		fileEncSHA256 = imgMsg.GetFileEncSHA256()
		fileLength = imgMsg.GetFileLength()
	} else if vidMsg := msg.GetVideoMessage(); vidMsg != nil {
		mediaType = "video"
		filename = generateFilename("mp4")
		url = vidMsg.GetURL()
		mediaKey = vidMsg.GetMediaKey()
		fileSHA256 = vidMsg.GetFileSHA256()
		fileEncSHA256 = vidMsg.GetFileEncSHA256()
		fileLength = vidMsg.GetFileLength()
	} else if audioMsg := msg.GetAudioMessage(); audioMsg != nil {
		mediaType = "audio"
		filename = generateFilename("ogg")
		url = audioMsg.GetURL()
		mediaKey = audioMsg.GetMediaKey()
		fileSHA256 = audioMsg.GetFileSHA256()
		fileEncSHA256 = audioMsg.GetFileEncSHA256()
		fileLength = audioMsg.GetFileLength()
	} else if docMsg := msg.GetDocumentMessage(); docMsg != nil {
		mediaType = "document"
		filename = docMsg.GetFileName()
		if filename == "" {
			filename = generateFilename("bin")
		}
		url = docMsg.GetURL()
		mediaKey = docMsg.GetMediaKey()
		fileSHA256 = docMsg.GetFileSHA256()
		fileEncSHA256 = docMsg.GetFileEncSHA256()
		fileLength = docMsg.GetFileLength()
	}

	return
}

func extractTextContent(msg *proto.Message) string {
	if msg == nil {
		return ""
	}
	if text := msg.GetConversation(); text != "" {
		return text
	}
	if extended := msg.GetExtendedTextMessage(); extended != nil {
		return extended.GetText()
	}
	return ""
}

func (b *Bridge) initUserClient(uc *UserClient) error {
	storeDir := "store/" + uc.UserID
	container, err := sqlstore.New(context.Background(), "sqlite3", "file:"+storeDir+"/whatsapp.db?_foreign_keys=on", b.logger)
	if err != nil {
		return fmt.Errorf("failed to create store: %w", err)
	}

	device, err := container.GetFirstDevice(context.Background())
	if err != nil {
		device = container.NewDevice()
	}

	uc.Client = whatsmeow.NewClient(device, b.logger)
	return nil
}

func toUserID(userID string) int {
	var id int
	for _, c := range userID {
		if c >= '0' && c <= '9' {
			id = id*10 + int(c-'0')
		}
	}
	return id
}