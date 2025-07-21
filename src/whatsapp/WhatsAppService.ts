import { Client, LocalAuth, Events } from 'whatsapp-web.js';
import QRCode from 'qrcode-terminal';
import { MessageStore } from '../database';
import { EventEmitter } from 'events';

export interface WhatsAppDevice {
  userId: number;
  deviceName: string;
  client: Client;
  isConnected: boolean;
  qrCode?: string;
}

export class WhatsAppService extends EventEmitter {
  private messageStore: MessageStore;
  private devices: Map<string, WhatsAppDevice> = new Map();

  constructor(messageStore: MessageStore) {
    super();
    this.messageStore = messageStore;
  }

  async createDeviceSession(userId: number, deviceName: string = 'default'): Promise<string> {
    const deviceKey = `${userId}-${deviceName}`;
    
    if (this.devices.has(deviceKey)) {
      throw new Error('Device session already exists');
    }

    const client = new Client({
      authStrategy: new LocalAuth({
        clientId: deviceKey,
        dataPath: './whatsapp_sessions'
      }),
      puppeteer: {
        args: ['--no-sandbox', '--disable-setuid-sandbox']
      }
    });

    const device: WhatsAppDevice = {
      userId,
      deviceName,
      client,
      isConnected: false
    };

    this.setupClientEventHandlers(device, deviceKey);
    this.devices.set(deviceKey, device);

    this.messageStore.createUserDevice(userId, deviceName);

    await client.initialize();
    return deviceKey;
  }

  private setupClientEventHandlers(device: WhatsAppDevice, deviceKey: string) {
    const { client, userId } = device;

    client.on('qr', (qr) => {
      device.qrCode = qr;
      console.log(`QR Code for user ${userId}, device ${device.deviceName}:`);
      QRCode.generate(qr, { small: true });
      this.emit('qr', { userId, deviceName: device.deviceName, qr });
    });

    client.on('ready', () => {
      device.isConnected = true;
      this.messageStore.updateDeviceConnection(userId, device.deviceName, true);
      console.log(`WhatsApp client ready for user ${userId}`);
      this.emit('ready', { userId, deviceName: device.deviceName });
    });

    client.on('authenticated', () => {
      console.log(`WhatsApp authenticated for user ${userId}`);
      this.emit('authenticated', { userId, deviceName: device.deviceName });
    });

    client.on('disconnected', (reason) => {
      device.isConnected = false;
      this.messageStore.updateDeviceConnection(userId, device.deviceName, false);
      console.log(`WhatsApp disconnected for user ${userId}: ${reason}`);
      this.emit('disconnected', { userId, deviceName: device.deviceName, reason });
    });

    client.on('message', async (message) => {
      await this.handleMessage(device, message);
    });
  }

  private async handleMessage(device: WhatsAppDevice, message: any) {
    const chatJID = message.from;
    const sender = message.author || message.from;
    const content = message.body || '';
    const timestamp = new Date(message.timestamp * 1000);
    const isFromMe = message.fromMe;

    let mediaType = '';
    let filename = '';
    let url = '';
    let mediaKey: Buffer | null = null;
    let fileSHA256: Buffer | null = null;
    let fileEncSHA256: Buffer | null = null;
    let fileLength = 0;

    if (message.hasMedia) {
      const media = await message.downloadMedia();
      mediaType = media.mimetype || '';
      filename = media.filename || '';
    }

    this.messageStore.storeMessage(
      message.id.id,
      chatJID,
      sender,
      content,
      timestamp,
      isFromMe,
      mediaType,
      filename,
      url,
      mediaKey,
      fileSHA256,
      fileEncSHA256,
      fileLength,
      device.userId
    );

    const chatName = (await message.getChat()).name || chatJID;
    this.messageStore.storeChat(chatJID, chatName, timestamp, device.userId);
  }

  getDeviceStatus(userId: number, deviceName: string = 'default'): WhatsAppDevice | null {
    const deviceKey = `${userId}-${deviceName}`;
    return this.devices.get(deviceKey) || null;
  }

  async sendMessage(userId: number, recipient: string, message: string, deviceName: string = 'default'): Promise<boolean> {
    const deviceKey = `${userId}-${deviceName}`;
    const device = this.devices.get(deviceKey);

    if (!device || !device.isConnected) {
      throw new Error('Device not connected');
    }

    try {
      await device.client.sendMessage(recipient, message);
      return true;
    } catch (error) {
      console.error('Failed to send message:', error);
      return false;
    }
  }

  async disconnectDevice(userId: number, deviceName: string = 'default'): Promise<void> {
    const deviceKey = `${userId}-${deviceName}`;
    const device = this.devices.get(deviceKey);

    if (device) {
      await device.client.destroy();
      this.devices.delete(deviceKey);
      this.messageStore.updateDeviceConnection(userId, deviceName, false);
    }
  }
}
