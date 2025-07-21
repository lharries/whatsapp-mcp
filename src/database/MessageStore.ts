import Database from 'better-sqlite3';
import * as fs from 'fs';
import * as path from 'path';
import { Message, ChatRow, MessageRow, ChatMap } from './types';

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
    } catch (error) {
      db.close();
      throw new Error(`Failed to create tables: ${error}`);
    }

    return new MessageStore(db);
  }

  close(): void {
    this.db.close();
  }

  storeChat(jid: string, name: string, lastMessageTime: Date): void {
    const stmt = this.db.prepare(
      'INSERT OR REPLACE INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)'
    );
    stmt.run(jid, name, lastMessageTime.toISOString());
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
    fileLength: number
  ): void {
    if (content === '' && mediaType === '') {
      return;
    }

    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO messages 
      (id, chat_jid, sender, content, timestamp, is_from_me, media_type, filename, url, media_key, file_sha256, file_enc_sha256, file_length) 
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
      fileLength
    );
  }

  getMessages(chatJID: string, limit: number): Message[] {
    const stmt = this.db.prepare(
      'SELECT sender, content, timestamp, is_from_me, media_type, filename FROM messages WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT ?'
    );
    
    const rows = stmt.all(chatJID, limit) as Array<{
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

  getChats(): ChatMap {
    const stmt = this.db.prepare(
      'SELECT jid, last_message_time FROM chats ORDER BY last_message_time DESC'
    );
    
    const rows = stmt.all() as Array<{
      jid: string;
      last_message_time: string;
    }>;

    const chats: ChatMap = {};
    for (const row of rows) {
      chats[row.jid] = new Date(row.last_message_time);
    }

    return chats;
  }
}
