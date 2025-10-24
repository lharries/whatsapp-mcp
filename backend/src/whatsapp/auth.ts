/**
 * WhatsApp authentication manager
 */

import { useMultiFileAuthState } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import QRCodeTerminal from 'qrcode-terminal';
import { env } from '../config/environment.js';
import { whatsappLogger } from '../util/logger.js';
import type { AuthState, QRCodeData, ConnectionStatus } from '@whatsapp-mcp/common';

export class AuthManager {
  private qrCodeCallback?: (qrData: QRCodeData) => void;
  private connectionStatusCallback?: (status: ConnectionStatus) => void;
  private currentQRCode?: string;
  private currentStatus: ConnectionStatus = 'disconnected';

  async initializeAuthState() {
    const authPath = env.whatsappAuthPath;
    whatsappLogger.info(`Initializing auth state from: ${authPath}`);

    const { state, saveCreds } = await useMultiFileAuthState(authPath);
    return { state, saveCreds };
  }

  async generateQRCode(qr: string): Promise<string> {
    this.currentQRCode = qr;

    // Display QR in terminal
    if (env.isDevelopment) {
      QRCodeTerminal.generate(qr, { small: true });
    }

    // Generate QR as data URL for API
    const qrDataUrl = await QRCode.toDataURL(qr);

    const qrData: QRCodeData = {
      qrCode: qrDataUrl,
      timestamp: new Date(),
    };

    whatsappLogger.info('QR code generated');

    // Notify listeners
    if (this.qrCodeCallback) {
      this.qrCodeCallback(qrData);
    }

    return qrDataUrl;
  }

  setQRCodeCallback(callback: (qrData: QRCodeData) => void) {
    this.qrCodeCallback = callback;
  }

  setConnectionStatusCallback(callback: (status: ConnectionStatus) => void) {
    this.connectionStatusCallback = callback;
  }

  updateConnectionStatus(status: ConnectionStatus) {
    this.currentStatus = status;
    whatsappLogger.info(`Connection status updated: ${status}`);

    if (this.connectionStatusCallback) {
      this.connectionStatusCallback(status);
    }
  }

  getCurrentQRCode(): string | undefined {
    return this.currentQRCode;
  }

  getCurrentStatus(): ConnectionStatus {
    return this.currentStatus;
  }

  getAuthState(): AuthState {
    return {
      isAuthenticated: this.currentStatus === 'ready' || this.currentStatus === 'connected',
      isConnected: this.currentStatus === 'connected' || this.currentStatus === 'ready',
      qrCode: this.currentQRCode,
      connectionStatus: this.currentStatus,
      lastConnected: this.currentStatus === 'ready' ? new Date() : undefined,
    };
  }
}
