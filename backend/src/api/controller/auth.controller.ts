/**
 * Authentication controller
 */

import type { Request, Response, NextFunction } from 'express';
import type { ApiResponse, AuthState } from '@whatsapp-mcp/common';
import { HTTP_STATUS_CODE_MAP } from '@whatsapp-mcp/common';
import type { WhatsAppClient } from '../whatsapp/client.js';

export class AuthController {
  constructor(private whatsappClient: WhatsAppClient) {}

  getAuthStatus = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const authState: AuthState = this.whatsappClient.getAuthState();

      const response: ApiResponse<AuthState> = {
        success: true,
        data: authState,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  getQRCode = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const authState = this.whatsappClient.getAuthState();

      if (!authState.qrCode) {
        const response: ApiResponse = {
          success: false,
          message: 'No QR code available. Client may already be authenticated.',
          timestamp: new Date(),
        };
        return res.status(HTTP_STATUS_CODE_MAP.NOT_FOUND).json(response);
      }

      const response: ApiResponse<{ qrCode: string }> = {
        success: true,
        data: { qrCode: authState.qrCode },
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  logout = async (req: Request, res: Response, next: NextFunction) => {
    try {
      await this.whatsappClient.close();

      const response: ApiResponse = {
        success: true,
        message: 'Logged out successfully',
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };
}
