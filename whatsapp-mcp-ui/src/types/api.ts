export interface User {
  id: number;
  username: string;
  email: string;
  phone_number: string | null;
  whatsapp_jid: string | null;
  created_at: string;
  updated_at: string;
  is_active: boolean;
  last_login: string | null;
}

export interface AuthResponse {
  user: User;
  session_id: string;
  expires_at: string;
  token: string;
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

export interface WhatsAppDeviceStatus {
  deviceName: string;
  isConnected: boolean;
  hasQR: boolean;
  qrCode?: string;
}

export interface SendMessageRequest {
  recipient: string;
  message: string;
  deviceName?: string;
}

export interface ChatMap {
  [jid: string]: string;
}

export interface Message {
  time: string;
  sender: string;
  content: string;
  isFromMe: boolean;
  mediaType: string;
  filename: string;
}
