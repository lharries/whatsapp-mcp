/**
 * Shared constants
 */

export const DEFAULT_MESSAGE_LIMIT = 20;
export const DEFAULT_CHAT_LIMIT = 20;
export const DEFAULT_CONTACT_LIMIT = 50;
export const DEFAULT_PAGE = 0;

export const MAX_MESSAGE_LIMIT = 100;
export const MAX_CHAT_LIMIT = 100;
export const MAX_CONTACT_LIMIT = 200;

export const DEFAULT_CONTEXT_BEFORE = 5;
export const DEFAULT_CONTEXT_AFTER = 5;

export const WHATSAPP_JID_REGEX = /^(\d+)@(s\.whatsapp\.net|g\.us)$/;
export const PHONE_NUMBER_REGEX = /^\d{10,15}$/;

export const MEDIA_TYPE_LIST = ['image', 'video', 'audio', 'document', 'sticker', 'voice'] as const;

export const CONNECTION_STATUS_LIST = [
  'disconnected',
  'connecting',
  'connected',
  'qr_required',
  'authenticating',
  'ready',
  'error'
] as const;

export const CHAT_SORT_FIELD_LIST = ['last_active', 'name'] as const;

export const STORE_TYPE_LIST = ['json', 'sqlite', 'mongodb'] as const;

export const MCP_TRANSPORT_TYPE_LIST = ['stdio', 'sse'] as const;

export const API_ERROR_CODE_MAP = {
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  NOT_FOUND: 'NOT_FOUND',
  UNAUTHORIZED: 'UNAUTHORIZED',
  FORBIDDEN: 'FORBIDDEN',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
  WHATSAPP_ERROR: 'WHATSAPP_ERROR',
  STORAGE_ERROR: 'STORAGE_ERROR',
  MEDIA_ERROR: 'MEDIA_ERROR',
} as const;

export const HTTP_STATUS_CODE_MAP = {
  OK: 200,
  CREATED: 201,
  NO_CONTENT: 204,
  BAD_REQUEST: 400,
  UNAUTHORIZED: 401,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  INTERNAL_SERVER_ERROR: 500,
} as const;

export const DEFAULT_JWT_EXPIRY = 3600; // 1 hour in seconds
export const DEFAULT_REFRESH_TOKEN_EXPIRY = 604800; // 7 days in seconds

export const DEFAULT_WEBSOCKET_HEARTBEAT_INTERVAL = 30000; // 30 seconds
export const DEFAULT_WEBSOCKET_RECONNECT_DELAY = 5000; // 5 seconds

export const SUPPORTED_IMAGE_MIME_TYPE_LIST = [
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/gif'
] as const;

export const SUPPORTED_VIDEO_MIME_TYPE_LIST = [
  'video/mp4',
  'video/3gpp',
  'video/quicktime'
] as const;

export const SUPPORTED_AUDIO_MIME_TYPE_LIST = [
  'audio/ogg; codecs=opus',
  'audio/mpeg',
  'audio/mp4',
  'audio/wav'
] as const;

export const SUPPORTED_DOCUMENT_MIME_TYPE_LIST = [
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
] as const;
