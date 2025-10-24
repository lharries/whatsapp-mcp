/**
 * Main entry point for WhatsApp MCP Backend
 */

import { createStore } from './store/index.js';
import { WhatsAppClient } from './whatsapp/client.js';
import { MessageService } from './service/message.service.js';
import { ChatService } from './service/chat.service.js';
import { ContactService } from './service/contact.service.js';
import { WhatsAppMCPServer } from './mcp/server.js';
import { ApiServer } from './api/server.js';
import { WhatsAppWebSocketServer } from './api/websocket.js';
import { logger } from './util/logger.js';
import { env } from './config/environment.js';

async function main() {
  logger.info('Starting WhatsApp MCP Backend...');
  logger.info(`Environment: ${env.nodeEnv}`);
  logger.info(`Data Store Type: ${env.dataStoreType}`);
  logger.info(`MCP Transport: ${env.mcpTransportType}`);
  logger.info(`API Port: ${env.apiPort}`);

  try {
    // Initialize data store
    logger.info('Initializing data store...');
    const store = createStore();
    await store.initialize();

    // Initialize WhatsApp client
    logger.info('Initializing WhatsApp client...');
    const whatsappClient = new WhatsAppClient(store);
    await whatsappClient.initialize();

    // Initialize services
    logger.info('Initializing services...');
    const messageService = new MessageService(store, whatsappClient);
    const chatService = new ChatService(store);
    const contactService = new ContactService(store);

    // Initialize MCP server
    logger.info('Initializing MCP server...');
    const mcpServer = new WhatsAppMCPServer(
      messageService,
      chatService,
      contactService,
      whatsappClient
    );

    // Initialize REST API server
    logger.info('Initializing REST API server...');
    const apiServer = new ApiServer(
      messageService,
      chatService,
      contactService,
      whatsappClient
    );

    // Initialize WebSocket server
    logger.info('Initializing WebSocket server...');
    const wsServer = new WhatsAppWebSocketServer();

    // Start API server first to get HTTP server instance
    await apiServer.start();

    // Initialize WebSocket on the HTTP server
    const httpServer = apiServer.getServer();
    if (httpServer) {
      wsServer.initialize(httpServer);
    }

    // Connect WhatsApp events to WebSocket
    whatsappClient.addEventListener({
      onMessage: (message) => {
        wsServer.broadcastMessage(message);
      },
      onChatUpdate: (chat) => {
        wsServer.broadcastChatUpdate(chat);
      },
      onConnectionUpdate: (status) => {
        wsServer.broadcastConnectionUpdate({
          status,
          timestamp: new Date(),
        });
      },
    });

    // Start MCP server (stdio transport)
    logger.info('Starting MCP server...');
    await mcpServer.start();

    logger.info('✅ WhatsApp MCP Backend started successfully');
    logger.info(`📡 REST API: http://${env.host}:${env.apiPort}`);
    logger.info(`🔌 WebSocket: ws://${env.host}:${env.apiPort}/ws`);
    logger.info(`🤖 MCP Server: stdio transport ready`);
    logger.info(`📊 WebSocket clients: ${wsServer.getClientCount()}`);

    // Handle graceful shutdown
    const shutdown = async () => {
      logger.info('Shutting down...');

      try {
        await whatsappClient.close();
        await apiServer.stop();
        wsServer.close();
        await store.close();

        logger.info('Shutdown complete');
        process.exit(0);
      } catch (error) {
        logger.error('Error during shutdown', error);
        process.exit(1);
      }
    };

    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);

  } catch (error) {
    logger.error('Failed to start backend', error);
    process.exit(1);
  }
}

main();
