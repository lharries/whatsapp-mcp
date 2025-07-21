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
  user_id: number;
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
  user_id: number;
}

export interface ChatMap {
  [jid: string]: Date;
}

export interface User {
  id: number;
  username: string;
  email: string;
  password_hash: string;
  phone_number: string | null;
  whatsapp_jid: string | null;
  created_at: Date;
  updated_at: Date;
  is_active: boolean;
  last_login: Date | null;
}

export interface UserSession {
  id: string;
  user_id: number;
  created_at: Date;
  expires_at: Date;
  is_active: boolean;
  user_agent: string | null;
  ip_address: string | null;
}

export interface UserDevice {
  id: number;
  user_id: number;
  device_name: string;
  whatsapp_session_data: string | null;
  is_connected: boolean;
  last_connected: Date | null;
  created_at: Date;
}

export interface CreateUserRequest {
  username: string;
  email: string;
  password: string;
  phone_number?: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface AuthResponse {
  user: Omit<User, 'password_hash'>;
  session_id: string;
  expires_at: Date;
}
