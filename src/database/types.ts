export interface Message {
  time: Date;
  sender: string;
  content: string;
  isFromMe: boolean;
  mediaType: string;
  filename: string;
}

export interface ChatRow {
  jid: string;
  name: string;
  last_message_time: Date;
}

export interface MessageRow {
  id: string;
  chat_jid: string;
  sender: string;
  content: string;
  timestamp: Date;
  is_from_me: boolean;
  media_type: string;
  filename: string;
  url: string;
  media_key: Buffer | null;
  file_sha256: Buffer | null;
  file_enc_sha256: Buffer | null;
  file_length: number;
}

export interface ChatMap {
  [jid: string]: Date;
}
