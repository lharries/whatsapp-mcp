/**
 * Zod schemas for chat validation
 */

import { z } from 'zod';
import {
  CHAT_SORT_FIELD_LIST,
  DEFAULT_CHAT_LIMIT,
  DEFAULT_PAGE,
  MAX_CHAT_LIMIT,
} from '../constant/index.js';

export const chatSortFieldSchema = z.enum(CHAT_SORT_FIELD_LIST);

export const chatSchema = z.object({
  jid: z.string(),
  name: z.string(),
  lastMessageTime: z.date().optional(),
  isGroup: z.boolean(),
  participantList: z.array(z.object({
    jid: z.string(),
    name: z.string().optional(),
    isAdmin: z.boolean().optional(),
  })).optional(),
  unreadCount: z.number().int().nonnegative().optional(),
});

export const chatFilterSchema = z.object({
  query: z.string().optional(),
  limit: z.number().int().positive().max(MAX_CHAT_LIMIT).default(DEFAULT_CHAT_LIMIT),
  page: z.number().int().nonnegative().default(DEFAULT_PAGE),
  includeLastMessage: z.boolean().default(true),
  sortBy: chatSortFieldSchema.default('last_active'),
});

export const getChatRequestSchema = z.object({
  chatJid: z.string().min(1, 'Chat JID is required'),
  includeLastMessage: z.boolean().default(true),
});

export const getDirectChatByContactRequestSchema = z.object({
  senderPhoneNumber: z.string().min(1, 'Phone number is required'),
});

export const getContactChatsRequestSchema = z.object({
  jid: z.string().min(1, 'JID is required'),
  limit: z.number().int().positive().max(MAX_CHAT_LIMIT).default(DEFAULT_CHAT_LIMIT),
  page: z.number().int().nonnegative().default(DEFAULT_PAGE),
});
