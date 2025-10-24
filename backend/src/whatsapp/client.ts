/**
 * WhatsApp client wrapper using Baileys
 */

import makeWASocket, {
  DisconnectReason,
  WASocket,
  proto,
  isJidGroup,
  isJidUser,
} from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import type { Message, Chat, Contact, ConnectionStatus } from '@whatsapp-mcp/common';
import { phoneNumberToJid, isGroupJid } from '@whatsapp-mcp/common';
import { AuthManager } from './auth.js';
import { MediaHandler } from './mediaHandler.js';
import { whatsappLogger } from '../util/logger.js';
import { BaseStore } from '../store/base.store.js';

export type WhatsAppEventListener = {
  onMessage?: (message: Message) => void;
  onChatUpdate?: (chat: Chat) => void;
  onConnectionUpdate?: (status: ConnectionStatus) => void;
};

export class WhatsAppClient {
  private sock?: WASocket;
  private authManager: AuthManager;
  private mediaHandler: MediaHandler;
  private store: BaseStore;
  private isReady = false;
  private eventListenerList: WhatsAppEventListener[] = [];

  constructor(store: BaseStore) {
    this.store = store;
    this.authManager = new AuthManager();
    this.mediaHandler = new MediaHandler();
  }

  addEventListener(listener: WhatsAppEventListener) {
    this.eventListenerList.push(listener);
  }

  removeEventListener(listener: WhatsAppEventListener) {
    const index = this.eventListenerList.indexOf(listener);
    if (index > -1) {
      this.eventListenerList.splice(index, 1);
    }
  }

  private emitMessage(message: Message) {
    this.eventListenerList.forEach((listener) => {
      listener.onMessage?.(message);
    });
  }

  private emitChatUpdate(chat: Chat) {
    this.eventListenerList.forEach((listener) => {
      listener.onChatUpdate?.(chat);
    });
  }

  private emitConnectionUpdate(status: ConnectionStatus) {
    this.eventListenerList.forEach((listener) => {
      listener.onConnectionUpdate?.(status);
    });
  }

  async initialize(): Promise<void> {
    whatsappLogger.info('Initializing WhatsApp client...');

    // Initialize media handler
    await this.mediaHandler.initialize();

    // Initialize auth state
    const { state, saveCreds } = await this.authManager.initializeAuthState();

    // Create socket
    this.sock = makeWASocket({
      auth: state,
      printQRInTerminal: false,
      logger: whatsappLogger as any,
    });

    // Register event handlers
    this.registerEventHandlers(saveCreds);

    whatsappLogger.info('WhatsApp client initialized');
  }

  private registerEventHandlers(saveCreds: () => Promise<void>) {
    if (!this.sock) return;

    // Connection updates
    this.sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        this.authManager.updateConnectionStatus('qr_required');
        await this.authManager.generateQRCode(qr);
      }

      if (connection === 'close') {
        const shouldReconnect =
          (lastDisconnect?.error as Boom)?.output?.statusCode !== DisconnectReason.loggedOut;

        whatsappLogger.info(`Connection closed. Reconnecting: ${shouldReconnect}`);
        this.authManager.updateConnectionStatus('disconnected');
        this.emitConnectionUpdate('disconnected');

        if (shouldReconnect) {
          await this.initialize();
        }
      } else if (connection === 'open') {
        whatsappLogger.info('Connection opened successfully');
        this.authManager.updateConnectionStatus('connected');
        this.emitConnectionUpdate('connected');
        this.isReady = true;

        // Load initial data
        await this.loadInitialData();
      } else if (connection === 'connecting') {
        this.authManager.updateConnectionStatus('connecting');
        this.emitConnectionUpdate('connecting');
      }
    });

    // Save credentials on update
    this.sock.ev.on('creds.update', saveCreds);

    // Handle incoming messages
    this.sock.ev.on('messages.upsert', async ({ messages, type }) => {
      for (const msg of messages) {
        if (type === 'notify') {
          await this.handleIncomingMessage(msg);
        }
      }
    });

    // Handle message history sync
    this.sock.ev.on('messaging-history.set', async ({ chats, messages, isLatest }) => {
      whatsappLogger.info(`Syncing history: ${chats.length} chats, ${messages.length} messages`);

      for (const chat of chats) {
        await this.storeChat(chat);
      }

      for (const msg of messages) {
        await this.handleIncomingMessage(msg);
      }
    });

    // Handle contact updates
    this.sock.ev.on('contacts.update', async (contacts) => {
      for (const contact of contacts) {
        await this.storeContact(contact);
      }
    });
  }

  private async handleIncomingMessage(msg: proto.IWebMessageInfo) {
    try {
      if (!msg.key.remoteJid || !msg.key.id) return;

      const chatJid = msg.key.remoteJid;
      const messageId = msg.key.id;
      const isFromMe = msg.key.fromMe || false;
      const sender = msg.participant || msg.key.remoteJid;
      const timestamp = msg.messageTimestamp
        ? new Date(Number(msg.messageTimestamp) * 1000)
        : new Date();

      // Extract text content
      let content = '';
      if (msg.message?.conversation) {
        content = msg.message.conversation;
      } else if (msg.message?.extendedTextMessage?.text) {
        content = msg.message.extendedTextMessage.text;
      } else if (msg.message?.imageMessage?.caption) {
        content = msg.message.imageMessage.caption;
      } else if (msg.message?.videoMessage?.caption) {
        content = msg.message.videoMessage.caption;
      }

      // Extract media info
      const mediaInfo = await this.mediaHandler.extractMediaInfo(msg);

      const message: Message = {
        id: messageId,
        chatJid,
        sender,
        content,
        timestamp,
        isFromMe,
        mediaType: mediaInfo?.mediaType,
        filename: mediaInfo?.filename,
        url: mediaInfo?.url,
        caption: mediaInfo?.caption,
        fileLength: mediaInfo?.fileLength,
      };

      // Store message
      await this.store.storeMessage(message);

      // Update chat last message time
      const chat = await this.store.getChat(chatJid);
      if (chat) {
        chat.lastMessageTime = timestamp;
        await this.store.storeChat(chat);
        this.emitChatUpdate(chat);
      }

      // Emit message event
      this.emitMessage(message);

      whatsappLogger.debug(`Message stored: ${messageId} from ${chatJid}`);
    } catch (error) {
      whatsappLogger.error('Failed to handle incoming message', error);
    }
  }

  private async storeChat(chat: any) {
    try {
      const chatData: Chat = {
        jid: chat.id,
        name: chat.name || chat.id,
        lastMessageTime: chat.conversationTimestamp
          ? new Date(chat.conversationTimestamp * 1000)
          : undefined,
        isGroup: isJidGroup(chat.id),
        unreadCount: chat.unreadCount,
      };

      await this.store.storeChat(chatData);
    } catch (error) {
      whatsappLogger.error('Failed to store chat', error);
    }
  }

  private async storeContact(contact: any) {
    try {
      if (!contact.id) return;

      const contactData: Contact = {
        jid: contact.id,
        name: contact.name,
        phoneNumber: contact.id.split('@')[0],
        pushName: contact.notify,
      };

      await this.store.storeContact(contactData);
    } catch (error) {
      whatsappLogger.error('Failed to store contact', error);
    }
  }

  private async loadInitialData() {
    whatsappLogger.info('Loading initial data...');
    this.authManager.updateConnectionStatus('ready');
    this.emitConnectionUpdate('ready');
  }

  async sendMessage(recipient: string, text: string): Promise<proto.WebMessageInfo | null> {
    if (!this.sock || !this.isReady) {
      throw new Error('WhatsApp client is not ready');
    }

    try {
      // Normalize recipient
      let jid = recipient;
      if (!recipient.includes('@')) {
        jid = phoneNumberToJid(recipient);
      }

      const result = await this.sock.sendMessage(jid, { text });
      whatsappLogger.info(`Message sent to ${jid}`);

      return result || null;
    } catch (error) {
      whatsappLogger.error('Failed to send message', error);
      throw error;
    }
  }

  async sendMedia(
    recipient: string,
    mediaPath: string,
    caption?: string
  ): Promise<proto.WebMessageInfo | null> {
    if (!this.sock || !this.isReady) {
      throw new Error('WhatsApp client is not ready');
    }

    try {
      let jid = recipient;
      if (!recipient.includes('@')) {
        jid = phoneNumberToJid(recipient);
      }

      const buffer = await this.mediaHandler.readMediaFile(mediaPath);
      const mimetype = this.mediaHandler.getMimeType(mediaPath);

      let result: proto.WebMessageInfo | undefined;

      if (mimetype.startsWith('image/')) {
        const processedBuffer = await this.mediaHandler.processImage(buffer);
        result = await this.sock.sendMessage(jid, {
          image: processedBuffer,
          caption,
          mimetype,
        });
      } else if (mimetype.startsWith('video/')) {
        result = await this.sock.sendMessage(jid, {
          video: buffer,
          caption,
          mimetype,
        });
      } else if (mimetype.startsWith('audio/')) {
        result = await this.sock.sendMessage(jid, {
          audio: buffer,
          mimetype,
        });
      } else {
        result = await this.sock.sendMessage(jid, {
          document: buffer,
          mimetype,
          fileName: mediaPath.split('/').pop(),
        });
      }

      whatsappLogger.info(`Media sent to ${jid}`);
      return result || null;
    } catch (error) {
      whatsappLogger.error('Failed to send media', error);
      throw error;
    }
  }

  async sendAudio(recipient: string, audioPath: string): Promise<proto.WebMessageInfo | null> {
    if (!this.sock || !this.isReady) {
      throw new Error('WhatsApp client is not ready');
    }

    try {
      let jid = recipient;
      if (!recipient.includes('@')) {
        jid = phoneNumberToJid(recipient);
      }

      // Convert to opus if needed
      let finalPath = audioPath;
      if (!audioPath.endsWith('.ogg')) {
        finalPath = await this.mediaHandler.convertAudioToOpus(audioPath);
      }

      const buffer = await this.mediaHandler.readMediaFile(finalPath);

      const result = await this.sock.sendMessage(jid, {
        audio: buffer,
        mimetype: 'audio/ogg; codecs=opus',
        ptt: true, // Push to talk (voice message)
      });

      whatsappLogger.info(`Voice message sent to ${jid}`);
      return result || null;
    } catch (error) {
      whatsappLogger.error('Failed to send voice message', error);
      throw error;
    }
  }

  async downloadMedia(messageId: string, chatJid: string): Promise<string | null> {
    try {
      const message = await this.store.getMessage(messageId, chatJid);
      if (!message || !message.mediaType) {
        return null;
      }

      // Check if already downloaded
      const existingPath = await this.store.getMediaPath(messageId, chatJid);
      if (existingPath) {
        return existingPath;
      }

      // TODO: Download from WhatsApp
      // This requires fetching the actual message object and downloading
      whatsappLogger.warn('Media download not fully implemented yet');
      return null;
    } catch (error) {
      whatsappLogger.error('Failed to download media', error);
      return null;
    }
  }

  getAuthState() {
    return this.authManager.getAuthState();
  }

  isClientReady(): boolean {
    return this.isReady;
  }

  async close() {
    if (this.sock) {
      await this.sock.logout();
      this.sock = undefined;
      this.isReady = false;
      whatsappLogger.info('WhatsApp client closed');
    }
  }
}
