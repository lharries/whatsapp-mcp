import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import rateLimit from 'express-rate-limit';
import { MessageStore } from '../database';
import { AuthService } from '../auth/AuthService';
import { WhatsAppService } from '../whatsapp/WhatsAppService';
import './types';

export class WhatsAppMCPServer {
  private app: express.Application;
  private messageStore!: MessageStore;
  private authService!: AuthService;
  private whatsappService!: WhatsAppService;

  constructor() {
    this.app = express();
    this.setupMiddleware();
  }

  async initialize(): Promise<void> {
    this.messageStore = await MessageStore.initialize();
    
    const jwtSecret = process.env.JWT_SECRET || 'your-secret-key-change-in-production';
    this.authService = new AuthService(this.messageStore, jwtSecret);
    this.whatsappService = new WhatsAppService(this.messageStore);

    this.setupRoutes();
  }

  private setupMiddleware(): void {
    this.app.use(helmet());
    this.app.use(cors());
    this.app.use(express.json());

    const limiter = rateLimit({
      windowMs: 15 * 60 * 1000, // 15 minutes
      max: 100 // limit each IP to 100 requests per windowMs
    });
    this.app.use(limiter);

    const authLimiter = rateLimit({
      windowMs: 15 * 60 * 1000,
      max: 5 // limit auth attempts
    });
    this.app.use('/api/auth', authLimiter);
  }

  private setupRoutes(): void {
    this.app.get('/health', (req, res) => {
      res.json({ status: 'ok', timestamp: new Date().toISOString() });
    });

    this.app.post('/api/auth/register', async (req, res) => {
      try {
        const authResponse = await this.authService.registerUser(req.body);
        res.status(201).json(authResponse);
      } catch (error) {
        res.status(400).json({ error: (error as Error).message });
      }
    });

    this.app.post('/api/auth/login', async (req, res) => {
      try {
        const authResponse = await this.authService.loginUser(req.body);
        res.json(authResponse);
      } catch (error) {
        res.status(401).json({ error: (error as Error).message });
      }
    });

    this.app.post('/api/whatsapp/device', this.authenticateToken.bind(this), async (req, res) => {
      try {
        const { userId } = req.user!;
        const { deviceName } = req.body;
        const deviceKey = await this.whatsappService.createDeviceSession(userId, deviceName);
        res.status(201).json({ deviceKey, message: 'Device session created. Scan QR code to authenticate.' });
      } catch (error) {
        res.status(400).json({ error: (error as Error).message });
      }
    });

    this.app.get('/api/whatsapp/device/:deviceName/status', this.authenticateToken.bind(this), (req, res) => {
      const { userId } = req.user!;
      const { deviceName } = req.params;
      const device = this.whatsappService.getDeviceStatus(userId, deviceName);
      
      if (!device) {
        return res.status(404).json({ error: 'Device not found' });
      }

      res.json({
        deviceName: device.deviceName,
        isConnected: device.isConnected,
        hasQR: !!device.qrCode
      });
    });

    this.app.post('/api/whatsapp/send', this.authenticateToken.bind(this), async (req, res) => {
      try {
        const { userId } = req.user!;
        const { recipient, message, deviceName } = req.body;
        const success = await this.whatsappService.sendMessage(userId, recipient, message, deviceName);
        res.json({ success });
      } catch (error) {
        res.status(400).json({ error: (error as Error).message });
      }
    });

    this.app.get('/api/chats', this.authenticateToken.bind(this), (req, res) => {
      const { userId } = req.user!;
      const chats = this.messageStore.getChats(userId);
      res.json(chats);
    });

    this.app.get('/api/chats/:chatJID/messages', this.authenticateToken.bind(this), (req, res) => {
      const { userId } = req.user!;
      const { chatJID } = req.params;
      const limit = parseInt(req.query.limit as string) || 50;
      const messages = this.messageStore.getMessages(chatJID, limit, userId);
      res.json(messages);
    });
  }

  private authenticateToken(req: any, res: any, next: any): void {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.split(' ')[1];

    if (!token) {
      return res.status(401).json({ error: 'Access token required' });
    }

    const validation = this.authService.validateToken(token);
    if (!validation) {
      return res.status(403).json({ error: 'Invalid or expired token' });
    }

    req.user = validation;
    next();
  }

  listen(port: number = 3000): void {
    this.app.listen(port, () => {
      console.log(`WhatsApp MCP Server running on port ${port}`);
    });
  }

  async shutdown(): Promise<void> {
    if (this.messageStore) {
      this.messageStore.close();
    }
  }
}
