/**
 * Authentication types and interfaces
 */

export interface AuthState {
  isAuthenticated: boolean;
  isConnected: boolean;
  qrCode?: string;
  connectionStatus: ConnectionStatus;
  lastConnected?: Date;
  phoneNumber?: string;
}

export type ConnectionStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'qr_required'
  | 'authenticating'
  | 'ready'
  | 'error';

export interface QRCodeData {
  qrCode: string;
  timestamp: Date;
}

export interface ConnectionUpdate {
  status: ConnectionStatus;
  message?: string;
  timestamp: Date;
}

export interface JWTPayload {
  sub: string;
  iat: number;
  exp: number;
}

export interface AuthToken {
  accessToken: string;
  refreshToken?: string;
  expiresIn: number;
}
