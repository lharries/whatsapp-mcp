/**
 * Environment configuration
 */

import { config } from 'dotenv';
import { StoreType, MCPTransportType } from '@whatsapp-mcp/common';

// Load environment variables
config();

interface EnvironmentConfig {
  // Environment
  nodeEnv: string;
  isDevelopment: boolean;
  isProduction: boolean;

  // Server
  port: number;
  apiPort: number;
  host: string;

  // Data Store
  dataStoreType: StoreType;
  jsonStorePath: string;
  sqliteDbPath?: string;
  mongodbUri?: string;

  // WhatsApp
  whatsappAuthPath: string;
  whatsappMediaPath: string;

  // MCP
  mcpServerName: string;
  mcpServerVersion: string;
  mcpTransportType: MCPTransportType;
  mcpSsePort?: number;

  // API
  enableCors: boolean;
  allowedOriginList: string[];

  // JWT
  jwtSecret: string;
  jwtExpiry: number;
  refreshTokenExpiry: number;

  // WebSocket
  wsHeartbeatInterval: number;
  wsReconnectDelay: number;

  // Logging
  logLevel: string;
  logPretty: boolean;
  logFile?: string;

  // Media Processing
  maxImageWidth: number;
  maxImageHeight: number;
  audioBitrate: string;
  audioSampleRate: number;
}

function getEnv(key: string, defaultValue?: string): string {
  const value = process.env[key];
  if (value === undefined) {
    if (defaultValue !== undefined) {
      return defaultValue;
    }
    throw new Error(`Environment variable ${key} is not set`);
  }
  return value;
}

function getEnvNumber(key: string, defaultValue?: number): number {
  const value = process.env[key];
  if (value === undefined) {
    if (defaultValue !== undefined) {
      return defaultValue;
    }
    throw new Error(`Environment variable ${key} is not set`);
  }
  const parsed = parseInt(value, 10);
  if (isNaN(parsed)) {
    throw new Error(`Environment variable ${key} is not a valid number`);
  }
  return parsed;
}

function getEnvBoolean(key: string, defaultValue: boolean): boolean {
  const value = process.env[key];
  if (value === undefined) {
    return defaultValue;
  }
  return value.toLowerCase() === 'true';
}

const nodeEnv = getEnv('NODE_ENV', 'development');

export const env: EnvironmentConfig = {
  // Environment
  nodeEnv,
  isDevelopment: nodeEnv === 'development',
  isProduction: nodeEnv === 'production',

  // Server
  port: getEnvNumber('PORT', 3000),
  apiPort: getEnvNumber('API_PORT', 8080),
  host: getEnv('HOST', '0.0.0.0'),

  // Data Store
  dataStoreType: getEnv('DATA_STORE_TYPE', 'json') as StoreType,
  jsonStorePath: getEnv('JSON_STORE_PATH', './data/json'),
  sqliteDbPath: process.env.SQLITE_DB_PATH,
  mongodbUri: process.env.MONGODB_URI,

  // WhatsApp
  whatsappAuthPath: getEnv('WHATSAPP_AUTH_PATH', './data/auth'),
  whatsappMediaPath: getEnv('WHATSAPP_MEDIA_PATH', './data/media'),

  // MCP
  mcpServerName: getEnv('MCP_SERVER_NAME', 'whatsapp-mcp-server'),
  mcpServerVersion: getEnv('MCP_SERVER_VERSION', '2.0.0'),
  mcpTransportType: getEnv('MCP_TRANSPORT_TYPE', 'stdio') as MCPTransportType,
  mcpSsePort: process.env.MCP_SSE_PORT ? getEnvNumber('MCP_SSE_PORT') : undefined,

  // API
  enableCors: getEnvBoolean('ENABLE_CORS', true),
  allowedOriginList: getEnv('ALLOWED_ORIGINS', 'http://localhost:5173,http://localhost:3000')
    .split(',')
    .map(origin => origin.trim()),

  // JWT
  jwtSecret: getEnv('JWT_SECRET', 'your-secret-key-change-this-in-production'),
  jwtExpiry: getEnvNumber('JWT_EXPIRY', 3600),
  refreshTokenExpiry: getEnvNumber('REFRESH_TOKEN_EXPIRY', 604800),

  // WebSocket
  wsHeartbeatInterval: getEnvNumber('WS_HEARTBEAT_INTERVAL', 30000),
  wsReconnectDelay: getEnvNumber('WS_RECONNECT_DELAY', 5000),

  // Logging
  logLevel: getEnv('LOG_LEVEL', 'info'),
  logPretty: getEnvBoolean('LOG_PRETTY', true),
  logFile: process.env.LOG_FILE,

  // Media Processing
  maxImageWidth: getEnvNumber('MAX_IMAGE_WIDTH', 1920),
  maxImageHeight: getEnvNumber('MAX_IMAGE_HEIGHT', 1920),
  audioBitrate: getEnv('AUDIO_BITRATE', '32k'),
  audioSampleRate: getEnvNumber('AUDIO_SAMPLE_RATE', 24000),
};
