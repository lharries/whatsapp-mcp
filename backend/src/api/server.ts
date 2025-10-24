/**
 * Express API server
 */

import express, { type Express } from 'express';
import cors from 'cors';
import { env } from '../config/environment.js';
import { apiLogger } from '../util/logger.js';
import { errorHandler, notFoundHandler } from './middleware/error.middleware.js';
import { requestLogger } from './middleware/validation.middleware.js';

// Controllers
import { AuthController } from './controller/auth.controller.js';
import { ChatController } from './controller/chat.controller.js';
import { MessageController } from './controller/message.controller.js';
import { ContactController } from './controller/contact.controller.js';

// Routes
import { createAuthRouter } from './route/auth.route.js';
import { createChatRouter } from './route/chat.route.js';
import { createMessageRouter } from './route/message.route.js';
import { createContactRouter } from './route/contact.route.js';

// Services
import type { MessageService } from '../service/message.service.js';
import type { ChatService } from '../service/chat.service.js';
import type { ContactService } from '../service/contact.service.js';
import type { WhatsAppClient } from '../whatsapp/client.js';

export class ApiServer {
  private app: Express;
  private server?: ReturnType<typeof import('http').createServer>;

  constructor(
    private messageService: MessageService,
    private chatService: ChatService,
    private contactService: ContactService,
    private whatsappClient: WhatsAppClient
  ) {
    this.app = express();
    this.setupMiddleware();
    this.setupRoutes();
    this.setupErrorHandling();
  }

  private setupMiddleware() {
    // CORS
    if (env.enableCors) {
      this.app.use(
        cors({
          origin: env.allowedOriginList,
          credentials: true,
        })
      );
    }

    // Body parsing
    this.app.use(express.json());
    this.app.use(express.urlencoded({ extended: true }));

    // Request logging
    this.app.use(requestLogger);
  }

  private setupRoutes() {
    // Health check
    this.app.get('/health', (req, res) => {
      res.json({
        success: true,
        data: {
          status: 'healthy',
          timestamp: new Date(),
          uptime: process.uptime(),
        },
      });
    });

    // Initialize controllers
    const authController = new AuthController(this.whatsappClient);
    const chatController = new ChatController(this.chatService);
    const messageController = new MessageController(this.messageService);
    const contactController = new ContactController(this.contactService);

    // API routes
    this.app.use('/api/auth', createAuthRouter(authController));
    this.app.use('/api/chats', createChatRouter(chatController));
    this.app.use('/api/messages', createMessageRouter(messageController));
    this.app.use('/api/contacts', createContactRouter(contactController));

    // API documentation endpoint
    this.app.get('/api', (req, res) => {
      res.json({
        success: true,
        data: {
          name: 'WhatsApp MCP API',
          version: '2.0.0',
          endpoints: {
            auth: {
              'GET /api/auth/status': 'Get authentication status',
              'GET /api/auth/qr': 'Get QR code for authentication',
              'POST /api/auth/logout': 'Logout from WhatsApp',
            },
            chats: {
              'GET /api/chats': 'List all chats',
              'GET /api/chats/:chatJid': 'Get specific chat',
              'GET /api/chats/contact/:phoneNumber': 'Get direct chat by phone',
              'GET /api/chats/by-contact/:jid': 'Get all chats with contact',
            },
            messages: {
              'GET /api/messages': 'List messages',
              'GET /api/messages/:chatJid/:messageId/context': 'Get message context',
              'POST /api/messages/send': 'Send text message',
              'POST /api/messages/send-file': 'Send media file',
              'POST /api/messages/send-audio': 'Send audio message',
              'POST /api/messages/:chatJid/:messageId/download': 'Download media',
            },
            contacts: {
              'GET /api/contacts': 'List all contacts',
              'GET /api/contacts/search': 'Search contacts',
            },
          },
        },
      });
    });
  }

  private setupErrorHandling() {
    // 404 handler
    this.app.use(notFoundHandler);

    // Error handler (must be last)
    this.app.use(errorHandler);
  }

  async start(): Promise<void> {
    return new Promise((resolve) => {
      this.server = this.app.listen(env.apiPort, env.host, () => {
        apiLogger.info(`API server listening on http://${env.host}:${env.apiPort}`);
        apiLogger.info(`API documentation available at http://${env.host}:${env.apiPort}/api`);
        resolve();
      });
    });
  }

  async stop(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.server) {
        this.server.close((err) => {
          if (err) {
            reject(err);
          } else {
            apiLogger.info('API server stopped');
            resolve();
          }
        });
      } else {
        resolve();
      }
    });
  }

  getApp(): Express {
    return this.app;
  }

  getServer() {
    return this.server;
  }
}
