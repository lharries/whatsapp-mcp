/**
 * WebSocket server for real-time updates
 */

import { WebSocketServer, WebSocket } from 'ws';
import type { Server } from 'http';
import { env } from '../config/environment.js';
import { apiLogger } from '../util/logger.js';
import type { Message, Chat, ConnectionStatus, ConnectionUpdate } from '@whatsapp-mcp/common';

export interface WebSocketMessage {
  type: 'message' | 'connection_update' | 'chat_update' | 'ping' | 'pong';
  data: any;
  timestamp: Date;
}

export class WhatsAppWebSocketServer {
  private wss?: WebSocketServer;
  private clientSet: Set<WebSocket> = new Set();
  private heartbeatInterval?: NodeJS.Timeout;

  constructor() {}

  initialize(httpServer: Server) {
    this.wss = new WebSocketServer({
      server: httpServer,
      path: '/ws'
    });

    this.wss.on('connection', (ws: WebSocket) => {
      apiLogger.info('WebSocket client connected');
      this.clientSet.add(ws);

      // Send welcome message
      this.sendToClient(ws, {
        type: 'connection_update',
        data: { status: 'connected', message: 'WebSocket connection established' },
        timestamp: new Date(),
      });

      // Handle messages from client
      ws.on('message', (data: Buffer) => {
        try {
          const message = JSON.parse(data.toString());
          this.handleClientMessage(ws, message);
        } catch (error) {
          apiLogger.error('Failed to parse WebSocket message', error);
        }
      });

      // Handle client disconnect
      ws.on('close', () => {
        apiLogger.info('WebSocket client disconnected');
        this.clientSet.delete(ws);
      });

      // Handle errors
      ws.on('error', (error) => {
        apiLogger.error('WebSocket error', error);
        this.clientSet.delete(ws);
      });
    });

    // Start heartbeat
    this.startHeartbeat();

    apiLogger.info('WebSocket server initialized on path /ws');
  }

  private handleClientMessage(ws: WebSocket, message: any) {
    switch (message.type) {
      case 'ping':
        this.sendToClient(ws, {
          type: 'pong',
          data: {},
          timestamp: new Date(),
        });
        break;

      default:
        apiLogger.warn(`Unknown WebSocket message type: ${message.type}`);
    }
  }

  private startHeartbeat() {
    this.heartbeatInterval = setInterval(() => {
      this.clientSet.forEach((ws) => {
        if (ws.readyState === WebSocket.OPEN) {
          this.sendToClient(ws, {
            type: 'ping',
            data: {},
            timestamp: new Date(),
          });
        }
      });
    }, env.wsHeartbeatInterval);
  }

  private sendToClient(ws: WebSocket, message: WebSocketMessage) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
    }
  }

  // Broadcast to all connected clients
  broadcast(message: WebSocketMessage) {
    const payload = JSON.stringify(message);
    this.clientSet.forEach((ws) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(payload);
      }
    });
  }

  // Public methods for WhatsApp events
  broadcastMessage(message: Message) {
    this.broadcast({
      type: 'message',
      data: message,
      timestamp: new Date(),
    });
    apiLogger.debug(`Broadcasted message to ${this.clientSet.size} clients`);
  }

  broadcastChatUpdate(chat: Chat) {
    this.broadcast({
      type: 'chat_update',
      data: chat,
      timestamp: new Date(),
    });
    apiLogger.debug(`Broadcasted chat update to ${this.clientSet.size} clients`);
  }

  broadcastConnectionUpdate(update: ConnectionUpdate) {
    this.broadcast({
      type: 'connection_update',
      data: update,
      timestamp: new Date(),
    });
    apiLogger.info(`Broadcasted connection update: ${update.status}`);
  }

  getClientCount(): number {
    return this.clientSet.size;
  }

  close() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
    }

    this.clientSet.forEach((ws) => {
      ws.close();
    });

    if (this.wss) {
      this.wss.close(() => {
        apiLogger.info('WebSocket server closed');
      });
    }
  }
}
