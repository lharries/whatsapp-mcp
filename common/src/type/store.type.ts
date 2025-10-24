/**
 * Data store types and interfaces
 */

import type { Chat } from './chat.type.js';
import type { Message } from './message.type.js';
import type { Contact } from './contact.type.js';
import type { MediaMetadata } from './message.type.js';

export type StoreType = 'json' | 'sqlite' | 'mongodb';

export interface StoreConfig {
  type: StoreType;
  path?: string;
  uri?: string;
  options?: Record<string, any>;
}

export interface ListOptions {
  limit?: number;
  offset?: number;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  filter?: Record<string, any>;
}

export interface IDataStore {
  // Lifecycle
  initialize(): Promise<void>;
  close(): Promise<void>;

  // Chats
  storeChat(chat: Chat): Promise<void>;
  getChat(jid: string): Promise<Chat | null>;
  listChat(options?: ListOptions): Promise<Chat[]>;
  deleteChat(jid: string): Promise<void>;

  // Messages
  storeMessage(message: Message): Promise<void>;
  getMessage(id: string, chatJid: string): Promise<Message | null>;
  listMessage(chatJid: string, options?: ListOptions): Promise<Message[]>;
  searchMessage(query: string, options?: ListOptions): Promise<Message[]>;
  deleteMessage(id: string, chatJid: string): Promise<void>;

  // Contacts
  storeContact(contact: Contact): Promise<void>;
  getContact(jid: string): Promise<Contact | null>;
  listContact(options?: ListOptions): Promise<Contact[]>;
  searchContact(query: string): Promise<Contact[]>;
  deleteContact(jid: string): Promise<void>;

  // Media
  storeMediaMetadata(messageId: string, metadata: MediaMetadata): Promise<void>;
  getMediaPath(messageId: string, chatJid: string): Promise<string | null>;
  getMediaMetadata(messageId: string, chatJid: string): Promise<MediaMetadata | null>;
}
