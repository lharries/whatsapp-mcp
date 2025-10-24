/**
 * Zod schemas for contact validation
 */

import { z } from 'zod';

export const contactSchema = z.object({
  jid: z.string(),
  name: z.string().optional(),
  phoneNumber: z.string(),
  pushName: z.string().optional(),
  isBlocked: z.boolean().optional(),
  profilePictureUrl: z.string().url().optional(),
});

export const searchContactsRequestSchema = z.object({
  query: z.string().min(1, 'Search query is required'),
});

export const getLastInteractionRequestSchema = z.object({
  jid: z.string().min(1, 'JID is required'),
});
