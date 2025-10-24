/**
 * Message routes
 */

import { Router } from 'express';
import type { MessageController } from '../controller/message.controller.js';
import { validateBody } from '../middleware/validation.middleware.js';
import {
  sendMessageRequestSchema,
  sendFileRequestSchema,
  sendAudioRequestSchema,
} from '@whatsapp-mcp/common';

export function createMessageRouter(messageController: MessageController): Router {
  const router = Router();

  /**
   * GET /api/messages
   * List messages with optional filtering
   * Query params: chatJid, query, senderPhoneNumber, after, before, limit, page
   */
  router.get('/', messageController.listMessage);

  /**
   * GET /api/messages/:chatJid/:messageId/context
   * Get context around a specific message
   * Query params: before, after
   */
  router.get('/:chatJid/:messageId/context', messageController.getMessageContext);

  /**
   * POST /api/messages/send
   * Send a text message
   * Body: { recipient, message }
   */
  router.post('/send', validateBody(sendMessageRequestSchema), messageController.sendMessage);

  /**
   * POST /api/messages/send-file
   * Send a media file
   * Body: { recipient, mediaPath, caption? }
   */
  router.post('/send-file', validateBody(sendFileRequestSchema), messageController.sendFile);

  /**
   * POST /api/messages/send-audio
   * Send an audio message
   * Body: { recipient, mediaPath }
   */
  router.post('/send-audio', validateBody(sendAudioRequestSchema), messageController.sendAudio);

  /**
   * POST /api/messages/:chatJid/:messageId/download
   * Download media from a message
   */
  router.post('/:chatJid/:messageId/download', messageController.downloadMedia);

  return router;
}
