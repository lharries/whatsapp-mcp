/**
 * Contact routes
 */

import { Router } from 'express';
import type { ContactController } from '../controller/contact.controller.js';

export function createContactRouter(contactController: ContactController): Router {
  const router = Router();

  /**
   * GET /api/contacts
   * List all contacts
   */
  router.get('/', contactController.listContact);

  /**
   * GET /api/contacts/search
   * Search contacts by name or phone
   * Query params: query (required)
   */
  router.get('/search', contactController.searchContact);

  return router;
}
