/**
 * Chat routes
 */

import { Router } from 'express';
import type { ChatController } from '../controller/chat.controller.js';

export function createChatRouter(chatController: ChatController): Router {
  const router = Router();

  /**
   * GET /api/chats
   * List all chats with optional filtering
   * Query params: query, limit, page, sortBy
   */
  router.get('/', chatController.listChat);

  /**
   * GET /api/chats/:chatJid
   * Get specific chat by JID
   */
  router.get('/:chatJid', chatController.getChat);

  /**
   * GET /api/chats/contact/:phoneNumber
   * Get direct chat with a contact by phone number
   */
  router.get('/contact/:phoneNumber', chatController.getDirectChatByContact);

  /**
   * GET /api/chats/by-contact/:jid
   * Get all chats involving a specific contact
   */
  router.get('/by-contact/:jid', chatController.getContactChatList);

  return router;
}
