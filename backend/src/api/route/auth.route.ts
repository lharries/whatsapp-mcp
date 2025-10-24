/**
 * Authentication routes
 */

import { Router } from 'express';
import type { AuthController } from '../controller/auth.controller.js';

export function createAuthRouter(authController: AuthController): Router {
  const router = Router();

  /**
   * GET /api/auth/status
   * Get current authentication status
   */
  router.get('/status', authController.getAuthStatus);

  /**
   * GET /api/auth/qr
   * Get current QR code for authentication
   */
  router.get('/qr', authController.getQRCode);

  /**
   * POST /api/auth/logout
   * Logout and disconnect from WhatsApp
   */
  router.post('/logout', authController.logout);

  return router;
}
