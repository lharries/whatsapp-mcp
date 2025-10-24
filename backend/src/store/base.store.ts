/**
 * Base data store - Abstract interface for all storage implementations
 */

import type { IDataStore } from '@whatsapp-mcp/common';

export abstract class BaseStore implements IDataStore {
  abstract initialize(): Promise<void>;
  abstract close(): Promise<void>;

  // Chats
  abstract storeChat(chat: any): Promise<void>;
  abstract getChat(jid: string): Promise<any>;
  abstract listChat(options?: any): Promise<any[]>;
  abstract deleteChat(jid: string): Promise<void>;

  // Messages
  abstract storeMessage(message: any): Promise<void>;
  abstract getMessage(id: string, chatJid: string): Promise<any>;
  abstract listMessage(chatJid: string, options?: any): Promise<any[]>;
  abstract searchMessage(query: string, options?: any): Promise<any[]>;
  abstract deleteMessage(id: string, chatJid: string): Promise<void>;

  // Contacts
  abstract storeContact(contact: any): Promise<void>;
  abstract getContact(jid: string): Promise<any>;
  abstract listContact(options?: any): Promise<any[]>;
  abstract searchContact(query: string): Promise<any[]>;
  abstract deleteContact(jid: string): Promise<void>;

  // Media
  abstract storeMediaMetadata(messageId: string, metadata: any): Promise<void>;
  abstract getMediaPath(messageId: string, chatJid: string): Promise<string | null>;
  abstract getMediaMetadata(messageId: string, chatJid: string): Promise<any>;
}
