/**
 * Chat types and interfaces
 */

import type { Message } from './message.type.js';

export interface Chat {
  jid: string;
  name: string;
  lastMessageTime?: Date;
  isGroup: boolean;
  participantList?: Participant[];
  unreadCount?: number;
  lastMessage?: Message;
}

export interface Participant {
  jid: string;
  name?: string;
  isAdmin?: boolean;
}

export interface ChatFilter {
  query?: string;
  limit?: number;
  page?: number;
  includeLastMessage?: boolean;
  sortBy?: ChatSortField;
}

export type ChatSortField = 'last_active' | 'name';

export interface ChatWithLastMessage extends Chat {
  lastMessage: Message;
}
