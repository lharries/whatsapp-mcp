/**
 * JSON file-based data store implementation
 */

import fs from 'fs/promises';
import path from 'path';
import type { Chat, Message, Contact, MediaMetadata, ListOptions } from '@whatsapp-mcp/common';
import { BaseStore } from './base.store.js';
import { env } from '../config/environment.js';
import { storeLogger } from '../util/logger.js';

interface JsonData {
  chatMap: Record<string, Chat>;
  messageMap: Record<string, Message[]>; // Keyed by chatJid
  contactMap: Record<string, Contact>;
  mediaMetadataMap: Record<string, MediaMetadata>; // Keyed by messageId
}

export class JsonStore extends BaseStore {
  private data: JsonData = {
    chatMap: {},
    messageMap: {},
    contactMap: {},
    mediaMetadataMap: {},
  };

  private storePath: string;
  private chatFilePath: string;
  private messageFilePath: string;
  private contactFilePath: string;
  private mediaFilePath: string;

  constructor() {
    super();
    this.storePath = path.resolve(env.jsonStorePath);
    this.chatFilePath = path.join(this.storePath, 'chats.json');
    this.messageFilePath = path.join(this.storePath, 'messages.json');
    this.contactFilePath = path.join(this.storePath, 'contacts.json');
    this.mediaFilePath = path.join(this.storePath, 'media.json');
  }

  async initialize(): Promise<void> {
    storeLogger.info('Initializing JSON store...');

    // Create store directory if it doesn't exist
    await fs.mkdir(this.storePath, { recursive: true });

    // Load existing data
    await this.loadData();

    storeLogger.info('JSON store initialized successfully');
  }

  async close(): Promise<void> {
    storeLogger.info('Closing JSON store...');
    await this.saveData();
    storeLogger.info('JSON store closed successfully');
  }

  private async loadData(): Promise<void> {
    try {
      const [chatData, messageData, contactData, mediaData] = await Promise.all([
        this.readJsonFile<Record<string, Chat>>(this.chatFilePath),
        this.readJsonFile<Record<string, Message[]>>(this.messageFilePath),
        this.readJsonFile<Record<string, Contact>>(this.contactFilePath),
        this.readJsonFile<Record<string, MediaMetadata>>(this.mediaFilePath),
      ]);

      this.data = {
        chatMap: chatData || {},
        messageMap: messageData || {},
        contactMap: contactData || {},
        mediaMetadataMap: mediaData || {},
      };

      storeLogger.info('Data loaded from JSON files');
    } catch (error) {
      storeLogger.warn('Failed to load some data files, starting fresh', error);
    }
  }

  private async saveData(): Promise<void> {
    await Promise.all([
      this.writeJsonFile(this.chatFilePath, this.data.chatMap),
      this.writeJsonFile(this.messageFilePath, this.data.messageMap),
      this.writeJsonFile(this.contactFilePath, this.data.contactMap),
      this.writeJsonFile(this.mediaFilePath, this.data.mediaMetadataMap),
    ]);
  }

  private async readJsonFile<T>(filePath: string): Promise<T | null> {
    try {
      const data = await fs.readFile(filePath, 'utf-8');
      return JSON.parse(data, this.reviver) as T;
    } catch (error: any) {
      if (error.code === 'ENOENT') {
        return null;
      }
      throw error;
    }
  }

  private async writeJsonFile(filePath: string, data: any): Promise<void> {
    await fs.writeFile(filePath, JSON.stringify(data, this.replacer, 2), 'utf-8');
  }

  // Custom JSON reviver to handle Dates and Uint8Arrays
  private reviver(key: string, value: any): any {
    if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value)) {
      return new Date(value);
    }
    if (value && typeof value === 'object' && value.__type === 'Uint8Array') {
      return new Uint8Array(value.data);
    }
    return value;
  }

  // Custom JSON replacer to handle Dates and Uint8Arrays
  private replacer(key: string, value: any): any {
    if (value instanceof Date) {
      return value.toISOString();
    }
    if (value instanceof Uint8Array) {
      return {
        __type: 'Uint8Array',
        data: Array.from(value),
      };
    }
    return value;
  }

  // Chats
  async storeChat(chat: Chat): Promise<void> {
    this.data.chatMap[chat.jid] = chat;
    await this.writeJsonFile(this.chatFilePath, this.data.chatMap);
  }

  async getChat(jid: string): Promise<Chat | null> {
    return this.data.chatMap[jid] || null;
  }

  async listChat(options: ListOptions = {}): Promise<Chat[]> {
    let chatList = Object.values(this.data.chatMap);

    // Apply filtering
    if (options.filter) {
      chatList = chatList.filter((chat) => {
        return Object.entries(options.filter!).every(([key, value]) => {
          return (chat as any)[key] === value;
        });
      });
    }

    // Apply sorting
    if (options.sortBy) {
      chatList.sort((a, b) => {
        const aVal = (a as any)[options.sortBy!];
        const bVal = (b as any)[options.sortBy!];
        if (aVal < bVal) return options.sortOrder === 'desc' ? 1 : -1;
        if (aVal > bVal) return options.sortOrder === 'desc' ? -1 : 1;
        return 0;
      });
    }

    // Apply pagination
    const offset = options.offset || 0;
    const limit = options.limit || chatList.length;
    return chatList.slice(offset, offset + limit);
  }

  async deleteChat(jid: string): Promise<void> {
    delete this.data.chatMap[jid];
    await this.writeJsonFile(this.chatFilePath, this.data.chatMap);
  }

  // Messages
  async storeMessage(message: Message): Promise<void> {
    if (!this.data.messageMap[message.chatJid]) {
      this.data.messageMap[message.chatJid] = [];
    }

    // Remove existing message with same id if exists
    this.data.messageMap[message.chatJid] = this.data.messageMap[message.chatJid].filter(
      (m) => m.id !== message.id
    );

    this.data.messageMap[message.chatJid].push(message);
    await this.writeJsonFile(this.messageFilePath, this.data.messageMap);
  }

  async getMessage(id: string, chatJid: string): Promise<Message | null> {
    const messageList = this.data.messageMap[chatJid] || [];
    return messageList.find((m) => m.id === id) || null;
  }

  async listMessage(chatJid: string, options: ListOptions = {}): Promise<Message[]> {
    let messageList = this.data.messageMap[chatJid] || [];

    // Apply filtering
    if (options.filter) {
      messageList = messageList.filter((message) => {
        return Object.entries(options.filter!).every(([key, value]) => {
          return (message as any)[key] === value;
        });
      });
    }

    // Apply sorting (default: by timestamp desc)
    messageList.sort((a, b) => {
      const aVal = options.sortBy ? (a as any)[options.sortBy] : a.timestamp;
      const bVal = options.sortBy ? (b as any)[options.sortBy] : b.timestamp;
      if (aVal < bVal) return options.sortOrder === 'asc' ? -1 : 1;
      if (aVal > bVal) return options.sortOrder === 'asc' ? 1 : -1;
      return 0;
    });

    // Apply pagination
    const offset = options.offset || 0;
    const limit = options.limit || messageList.length;
    return messageList.slice(offset, offset + limit);
  }

  async searchMessage(query: string, options: ListOptions = {}): Promise<Message[]> {
    const allMessageList: Message[] = [];
    const lowerQuery = query.toLowerCase();

    // Search across all chats
    for (const messageList of Object.values(this.data.messageMap)) {
      const matchingMessageList = messageList.filter(
        (message) =>
          message.content.toLowerCase().includes(lowerQuery) ||
          message.sender.toLowerCase().includes(lowerQuery)
      );
      allMessageList.push(...matchingMessageList);
    }

    // Apply sorting
    allMessageList.sort((a, b) => {
      const aVal = options.sortBy ? (a as any)[options.sortBy] : a.timestamp;
      const bVal = options.sortBy ? (b as any)[options.sortBy] : b.timestamp;
      if (aVal < bVal) return options.sortOrder === 'asc' ? -1 : 1;
      if (aVal > bVal) return options.sortOrder === 'asc' ? 1 : -1;
      return 0;
    });

    // Apply pagination
    const offset = options.offset || 0;
    const limit = options.limit || allMessageList.length;
    return allMessageList.slice(offset, offset + limit);
  }

  async deleteMessage(id: string, chatJid: string): Promise<void> {
    if (this.data.messageMap[chatJid]) {
      this.data.messageMap[chatJid] = this.data.messageMap[chatJid].filter((m) => m.id !== id);
      await this.writeJsonFile(this.messageFilePath, this.data.messageMap);
    }
  }

  // Contacts
  async storeContact(contact: Contact): Promise<void> {
    this.data.contactMap[contact.jid] = contact;
    await this.writeJsonFile(this.contactFilePath, this.data.contactMap);
  }

  async getContact(jid: string): Promise<Contact | null> {
    return this.data.contactMap[jid] || null;
  }

  async listContact(options: ListOptions = {}): Promise<Contact[]> {
    let contactList = Object.values(this.data.contactMap);

    // Apply filtering
    if (options.filter) {
      contactList = contactList.filter((contact) => {
        return Object.entries(options.filter!).every(([key, value]) => {
          return (contact as any)[key] === value;
        });
      });
    }

    // Apply sorting
    if (options.sortBy) {
      contactList.sort((a, b) => {
        const aVal = (a as any)[options.sortBy!];
        const bVal = (b as any)[options.sortBy!];
        if (aVal < bVal) return options.sortOrder === 'desc' ? 1 : -1;
        if (aVal > bVal) return options.sortOrder === 'desc' ? -1 : 1;
        return 0;
      });
    }

    // Apply pagination
    const offset = options.offset || 0;
    const limit = options.limit || contactList.length;
    return contactList.slice(offset, offset + limit);
  }

  async searchContact(query: string): Promise<Contact[]> {
    const lowerQuery = query.toLowerCase();
    return Object.values(this.data.contactMap).filter(
      (contact) =>
        contact.name?.toLowerCase().includes(lowerQuery) ||
        contact.phoneNumber.includes(query) ||
        contact.pushName?.toLowerCase().includes(lowerQuery)
    );
  }

  async deleteContact(jid: string): Promise<void> {
    delete this.data.contactMap[jid];
    await this.writeJsonFile(this.contactFilePath, this.data.contactMap);
  }

  // Media
  async storeMediaMetadata(messageId: string, metadata: MediaMetadata): Promise<void> {
    this.data.mediaMetadataMap[messageId] = metadata;
    await this.writeJsonFile(this.mediaFilePath, this.data.mediaMetadataMap);
  }

  async getMediaPath(messageId: string, chatJid: string): Promise<string | null> {
    const metadata = this.data.mediaMetadataMap[messageId];
    return metadata?.localPath || null;
  }

  async getMediaMetadata(messageId: string, chatJid: string): Promise<MediaMetadata | null> {
    return this.data.mediaMetadataMap[messageId] || null;
  }
}
