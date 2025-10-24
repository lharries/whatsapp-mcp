/**
 * WebSocket client for real-time updates
 */

import type { Message, Chat, ConnectionStatus } from '@whatsapp-mcp/common';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8080/ws';

interface WebSocketMessage {
  type: 'message' | 'connection_update' | 'chat_update' | 'ping' | 'pong';
  data: any;
  timestamp: Date;
}

type MessageHandler = (message: Message) => void;
type ChatUpdateHandler = (chat: Chat) => void;
type ConnectionUpdateHandler = (status: ConnectionStatus) => void;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private messageHandlerList: MessageHandler[] = [];
  private chatUpdateHandlerList: ChatUpdateHandler[] = [];
  private connectionUpdateHandlerList: ConnectionUpdateHandler[] = [];
  private reconnectAttempt = 0;
  private maxReconnectAttempt = 5;
  private reconnectDelay = 5000;
  private reconnectTimer: NodeJS.Timeout | null = null;

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      console.log('WebSocket already connected');
      return;
    }

    console.log('Connecting to WebSocket:', WS_URL);
    this.ws = new WebSocket(WS_URL);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.reconnectAttempt = 0;
    };

    this.ws.onmessage = (event) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data);
        this.handleMessage(message);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    this.ws.onclose = () => {
      console.log('WebSocket closed');
      this.attemptReconnect();
    };
  }

  private handleMessage(message: WebSocketMessage) {
    switch (message.type) {
      case 'message':
        this.messageHandlerList.forEach((handler) => handler(message.data));
        break;

      case 'chat_update':
        this.chatUpdateHandlerList.forEach((handler) => handler(message.data));
        break;

      case 'connection_update':
        this.connectionUpdateHandlerList.forEach((handler) =>
          handler(message.data.status)
        );
        break;

      case 'ping':
        this.sendPong();
        break;

      case 'pong':
        // Heartbeat response received
        break;

      default:
        console.warn('Unknown WebSocket message type:', message.type);
    }
  }

  private attemptReconnect() {
    if (this.reconnectAttempt >= this.maxReconnectAttempt) {
      console.error('Max reconnection attempts reached');
      return;
    }

    this.reconnectAttempt++;
    const delay = this.reconnectDelay * this.reconnectAttempt;
    console.log(`Attempting reconnect in ${delay}ms (attempt ${this.reconnectAttempt}/${this.maxReconnectAttempt})`);

    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  private sendPong() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'pong' }));
    }
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  onMessage(handler: MessageHandler) {
    this.messageHandlerList.push(handler);
    return () => {
      const index = this.messageHandlerList.indexOf(handler);
      if (index > -1) {
        this.messageHandlerList.splice(index, 1);
      }
    };
  }

  onChatUpdate(handler: ChatUpdateHandler) {
    this.chatUpdateHandlerList.push(handler);
    return () => {
      const index = this.chatUpdateHandlerList.indexOf(handler);
      if (index > -1) {
        this.chatUpdateHandlerList.splice(index, 1);
      }
    };
  }

  onConnectionUpdate(handler: ConnectionUpdateHandler) {
    this.connectionUpdateHandlerList.push(handler);
    return () => {
      const index = this.connectionUpdateHandlerList.indexOf(handler);
      if (index > -1) {
        this.connectionUpdateHandlerList.splice(index, 1);
      }
    };
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
}

// Singleton instance
export const websocketClient = new WebSocketClient();
