/**
 * Zod schemas for message validation
 */

import { z } from 'zod';
import {
  MEDIA_TYPE_LIST,
  DEFAULT_MESSAGE_LIMIT,
  DEFAULT_PAGE,
  MAX_MESSAGE_LIMIT,
  DEFAULT_CONTEXT_BEFORE,
  DEFAULT_CONTEXT_AFTER,
} from '../constant/index.js';

export const mediaTypeSchema = z.enum(MEDIA_TYPE_LIST);

export const messageSchema = z.object({
  id: z.string(),
  chatJid: z.string(),
  sender: z.string(),
  senderName: z.string().optional(),
  content: z.string(),
  timestamp: z.date(),
  isFromMe: z.boolean(),
  mediaType: mediaTypeSchema.optional(),
  filename: z.string().optional(),
  url: z.string().url().optional(),
  mediaKey: z.instanceof(Uint8Array).optional(),
  fileSha256: z.instanceof(Uint8Array).optional(),
  fileEncSha256: z.instanceof(Uint8Array).optional(),
  fileLength: z.number().int().positive().optional(),
  caption: z.string().optional(),
});

export const messageFilterSchema = z.object({
  after: z.string().datetime().optional(),
  before: z.string().datetime().optional(),
  senderPhoneNumber: z.string().optional(),
  chatJid: z.string().optional(),
  query: z.string().optional(),
  limit: z.number().int().positive().max(MAX_MESSAGE_LIMIT).default(DEFAULT_MESSAGE_LIMIT),
  page: z.number().int().nonnegative().default(DEFAULT_PAGE),
  includeContext: z.boolean().default(true),
  contextBefore: z.number().int().nonnegative().default(DEFAULT_CONTEXT_BEFORE),
  contextAfter: z.number().int().nonnegative().default(DEFAULT_CONTEXT_AFTER),
});

export const sendMessageRequestSchema = z.object({
  recipient: z.string().min(1, 'Recipient is required'),
  message: z.string().min(1, 'Message is required'),
});

export const sendFileRequestSchema = z.object({
  recipient: z.string().min(1, 'Recipient is required'),
  mediaPath: z.string().min(1, 'Media path is required'),
  caption: z.string().optional(),
});

export const sendAudioRequestSchema = z.object({
  recipient: z.string().min(1, 'Recipient is required'),
  mediaPath: z.string().min(1, 'Media path is required'),
});

export const downloadMediaRequestSchema = z.object({
  messageId: z.string().min(1, 'Message ID is required'),
  chatJid: z.string().min(1, 'Chat JID is required'),
});

export const messageContextRequestSchema = z.object({
  messageId: z.string().min(1, 'Message ID is required'),
  before: z.number().int().nonnegative().default(DEFAULT_CONTEXT_BEFORE),
  after: z.number().int().nonnegative().default(DEFAULT_CONTEXT_AFTER),
});
