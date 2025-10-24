/**
 * Message types and interfaces
 */

export interface Message {
  id: string;
  chatJid: string;
  sender: string;
  senderName?: string;
  content: string;
  timestamp: Date;
  isFromMe: boolean;
  mediaType?: MediaType;
  filename?: string;
  url?: string;
  mediaKey?: Uint8Array;
  fileSha256?: Uint8Array;
  fileEncSha256?: Uint8Array;
  fileLength?: number;
  caption?: string;
}

export type MediaType =
  | 'image'
  | 'video'
  | 'audio'
  | 'document'
  | 'sticker'
  | 'voice';

export interface MediaMetadata {
  messageId: string;
  chatJid: string;
  mediaType: MediaType;
  filename?: string;
  url?: string;
  mediaKey?: Uint8Array;
  fileSha256?: Uint8Array;
  fileEncSha256?: Uint8Array;
  fileLength?: number;
  localPath?: string;
  mimetype?: string;
  width?: number;
  height?: number;
  duration?: number;
  pageCount?: number;
  caption?: string;
}

export interface MessageContext {
  targetMessage: Message;
  messageListBefore: Message[];
  messageListAfter: Message[];
  chat: {
    jid: string;
    name: string;
  };
}

export interface SendMessageRequest {
  recipient: string;
  message: string;
}

export interface SendFileRequest {
  recipient: string;
  mediaPath: string;
  caption?: string;
}

export interface SendAudioRequest {
  recipient: string;
  mediaPath: string;
}

export interface DownloadMediaRequest {
  messageId: string;
  chatJid: string;
}

export interface MessageFilter {
  after?: string;
  before?: string;
  senderPhoneNumber?: string;
  chatJid?: string;
  query?: string;
  limit?: number;
  page?: number;
  includeContext?: boolean;
  contextBefore?: number;
  contextAfter?: number;
}
