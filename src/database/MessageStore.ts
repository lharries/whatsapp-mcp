import Database from 'better-sqlite3';
import * as fs from 'fs';
import * as path from 'path';
import { Message, ChatRow, MessageRow, ChatMap, User } from './types';
import { MigrationManager } from './MigrationManager';

export class MessageStore {
  private db: Database.Database;

  private constructor(db: Database.Database) {
    this.db = db;
  }

  static async initialize(): Promise<MessageStore> {
    const storeDir = 'store';
    if (!fs.existsSync(storeDir)) {
      fs.mkdirSync(storeDir, { recursive: true });
    }

    const db = new Database('store/messages.db', {
      fileMustExist: false
    });

    db.pragma('foreign_keys = ON');

    const createTablesSQL = `
      CREATE TABLE IF NOT EXISTS chats (
        jid TEXT PRIMARY KEY,
        name TEXT,
        last_message_time TIMESTAMP
      );
      
      CREATE TABLE IF NOT EXISTS messages (
        id TEXT,
        chat_jid TEXT,
        sender TEXT,
        content TEXT,
        timestamp TIMESTAMP,
        is_from_me BOOLEAN,
        media_type TEXT,
        filename TEXT,
        url TEXT,
        media_key BLOB,
        file_sha256 BLOB,
        file_enc_sha256 BLOB,
        file_length INTEGER,
        PRIMARY KEY (id, chat_jid),
        FOREIGN KEY (chat_jid) REFERENCES chats(jid)
      );
    `;

    try {
      db.exec(createTablesSQL);
      
      const migrationManager = new MigrationManager(db);
      await migrationManager.runMigrations();
    } catch (error) {
      db.close();
      throw new Error(`Failed to create tables or run migrations: ${error}`);
    }

    return new MessageStore(db);
  }

  close(): void {
    this.db.close();
  }

  storeChat(jid: string, name: string, lastMessageTime: Date, userId: number): void {
    const stmt = this.db.prepare(
      'INSERT OR REPLACE INTO chats (jid, name, last_message_time, user_id) VALUES (?, ?, ?, ?)'
    );
    stmt.run(jid, name, lastMessageTime.toISOString(), userId);
  }

  storeChatLegacy(jid: string, name: string, lastMessageTime: Date): void {
    this.storeChat(jid, name, lastMessageTime, 1);
  }

  storeMessage(
    id: string,
    chatJID: string,
    sender: string,
    content: string,
    timestamp: Date,
    isFromMe: boolean,
    mediaType: string,
    filename: string,
    url: string,
    mediaKey: Buffer | null,
    fileSHA256: Buffer | null,
    fileEncSHA256: Buffer | null,
    fileLength: number,
    userId: number
  ): void {
    if (content === '' && mediaType === '') {
      return;
    }

    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO messages 
      (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length, user_id) 
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(
      id,
      chatJID,
      sender,
      content,
      timestamp.toISOString(),
      isFromMe ? 1 : 0,
      mediaType || '',
      filename || '',
      url || '',
      mediaKey,
      fileSHA256,
      fileEncSHA256,
      fileLength,
      userId
    );
  }

  storeMessageLegacy(
    id: string,
    chatJID: string,
    sender: string,
    content: string,
    timestamp: Date,
    isFromMe: boolean,
    mediaType: string,
    filename: string,
    url: string,
    mediaKey: Buffer | null,
    fileSHA256: Buffer | null,
    fileEncSHA256: Buffer | null,
    fileLength: number
  ): void {
    this.storeMessage(id, chatJID, sender, content, timestamp, isFromMe, 
      mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength, 1);
  }

  getMessages(chatJID: string, limit: number, userId: number): Message[] {
    const stmt = this.db.prepare(
      'SELECT sender, content, timestamp, is_from_me, media_type, filename FROM messages WHERE chat_jid = ? AND user_id = ? ORDER BY timestamp DESC LIMIT ?'
    );
    
    const rows = stmt.all(chatJID, userId, limit) as Array<{
      sender: string;
      content: string;
      timestamp: string;
      is_from_me: number;
      media_type: string;
      filename: string;
    }>;

    return rows.map(row => ({
      time: new Date(row.timestamp),
      sender: row.sender,
      content: row.content,
      isFromMe: Boolean(row.is_from_me),
      mediaType: row.media_type,
      filename: row.filename
    }));
  }

  getMessagesLegacy(chatJID: string, limit: number): Message[] {
    return this.getMessages(chatJID, limit, 1);
  }

  getChats(userId: number): ChatMap {
    const stmt = this.db.prepare(
      'SELECT jid, last_message_time FROM chats WHERE user_id = ? ORDER BY last_message_time DESC'
    );
    
    const rows = stmt.all(userId) as Array<{
      jid: string;
      last_message_time: string;
    }>;

    const chats: ChatMap = {};
    for (const row of rows) {
      chats[row.jid] = new Date(row.last_message_time);
    }

    return chats;
  }

  getChatsLegacy(): ChatMap {
    return this.getChats(1);
  }

  createUser(username: string, email: string, passwordHash: string, phoneNumber?: string): number {
    const stmt = this.db.prepare(`
      INSERT INTO users (username, email, password_hash, phone_number, created_at, updated_at)
      VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    `);
    const result = stmt.run(username, email, passwordHash, phoneNumber || null);
    return result.lastInsertRowid as number;
  }

  getUserById(userId: number): User | null {
    const stmt = this.db.prepare(`
      SELECT id, username, email, password_hash, phone_number, whatsapp_jid, 
             created_at, updated_at, is_active, last_login
      FROM users WHERE id = ? AND is_active = 1
    `);
    const row = stmt.get(userId) as any;
    if (!row) return null;
    
    return {
      id: row.id,
      username: row.username,
      email: row.email,
      password_hash: row.password_hash,
      phone_number: row.phone_number,
      whatsapp_jid: row.whatsapp_jid,
      created_at: new Date(row.created_at),
      updated_at: new Date(row.updated_at),
      is_active: Boolean(row.is_active),
      last_login: row.last_login ? new Date(row.last_login) : null
    };
  }

  getUserByUsername(username: string): User | null {
    const stmt = this.db.prepare(`
      SELECT id, username, email, password_hash, phone_number, whatsapp_jid,
             created_at, updated_at, is_active, last_login
      FROM users WHERE username = ? AND is_active = 1
    `);
    const row = stmt.get(username) as any;
    if (!row) return null;
    
    return {
      id: row.id,
      username: row.username,
      email: row.email,
      password_hash: row.password_hash,
      phone_number: row.phone_number,
      whatsapp_jid: row.whatsapp_jid,
      created_at: new Date(row.created_at),
      updated_at: new Date(row.updated_at),
      is_active: Boolean(row.is_active),
      last_login: row.last_login ? new Date(row.last_login) : null
    };
  }

  updateUserLastLogin(userId: number): void {
    const stmt = this.db.prepare(`
      UPDATE users SET last_login = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `);
    stmt.run(userId);
  }

  getUserByEmail(email: string): User | null {
    const stmt = this.db.prepare(`
      SELECT id, username, email, password_hash, phone_number, whatsapp_jid,
             created_at, updated_at, is_active, last_login
      FROM users WHERE email = ? AND is_active = 1
    `);
    const row = stmt.get(email) as any;
    if (!row) return null;
    
    return {
      id: row.id,
      username: row.username,
      email: row.email,
      password_hash: row.password_hash,
      phone_number: row.phone_number,
      whatsapp_jid: row.whatsapp_jid,
      created_at: new Date(row.created_at),
      updated_at: new Date(row.updated_at),
      is_active: Boolean(row.is_active),
      last_login: row.last_login ? new Date(row.last_login) : null
    };
  }

  createUserSession(sessionId: string, userId: number, expiresAt: Date, userAgent?: string, ipAddress?: string): void {
    const stmt = this.db.prepare(`
      INSERT INTO user_sessions (id, user_id, expires_at, user_agent, ip_address)
      VALUES (?, ?, ?, ?, ?)
    `);
    stmt.run(sessionId, userId, expiresAt.toISOString(), userAgent || null, ipAddress || null);
  }

  getUserSession(sessionId: string): any | null {
    const stmt = this.db.prepare(`
      SELECT id, user_id, created_at, expires_at, is_active, user_agent, ip_address
      FROM user_sessions WHERE id = ? AND is_active = 1
    `);
    const row = stmt.get(sessionId) as any;
    if (!row) return null;
    
    return {
      id: row.id,
      user_id: row.user_id,
      created_at: new Date(row.created_at),
      expires_at: new Date(row.expires_at),
      is_active: Boolean(row.is_active),
      user_agent: row.user_agent,
      ip_address: row.ip_address
    };
  }

  createUserDevice(userId: number, deviceName: string): number {
    const stmt = this.db.prepare(`
      INSERT INTO user_devices (user_id, device_name, created_at)
      VALUES (?, ?, CURRENT_TIMESTAMP)
    `);
    const result = stmt.run(userId, deviceName);
    return result.lastInsertRowid as number;
  }

  updateDeviceConnection(userId: number, deviceName: string, isConnected: boolean): void {
    const stmt = this.db.prepare(`
      UPDATE user_devices 
      SET is_connected = ?, last_connected = CURRENT_TIMESTAMP
      WHERE user_id = ? AND device_name = ?
    `);
    stmt.run(isConnected ? 1 : 0, userId, deviceName);
  }
}
