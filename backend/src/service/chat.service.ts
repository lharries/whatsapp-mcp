/**
 * Chat service - Business logic for chat operations
 */

import type { Chat, ChatFilter } from '@whatsapp-mcp/common';
import { BaseStore } from '../store/base.store.js';
import { DEFAULT_CHAT_LIMIT, DEFAULT_PAGE } from '@whatsapp-mcp/common';

export class ChatService {
  constructor(private store: BaseStore) {}

  async listChat(filter: ChatFilter = {}): Promise<Chat[]> {
    const {
      query,
      limit = DEFAULT_CHAT_LIMIT,
      page = DEFAULT_PAGE,
      sortBy = 'last_active',
    } = filter;

    const chatList = await this.store.listChat({
      limit,
      offset: page * limit,
      sortBy: sortBy === 'last_active' ? 'lastMessageTime' : 'name',
      sortOrder: 'desc',
    });

    if (query) {
      return chatList.filter((chat) =>
        chat.name.toLowerCase().includes(query.toLowerCase())
      );
    }

    return chatList;
  }

  async getChat(jid: string): Promise<Chat | null> {
    return await this.store.getChat(jid);
  }

  async getDirectChatByContact(phoneNumber: string): Promise<Chat | null> {
    const jid = `${phoneNumber}@s.whatsapp.net`;
    return await this.store.getChat(jid);
  }

  async getContactChatList(jid: string, limit = DEFAULT_CHAT_LIMIT, page = DEFAULT_PAGE): Promise<Chat[]> {
    // Get all chats and filter by participant
    const allChatList = await this.store.listChat({
      limit: 1000, // High limit to get all
      offset: 0,
    });

    // Filter chats where the contact is a participant
    const filteredChatList = allChatList.filter((chat) => {
      if (chat.isGroup) {
        return chat.participantList?.some((p) => p.jid === jid);
      }
      return chat.jid === jid;
    });

    // Apply pagination
    const offset = page * limit;
    return filteredChatList.slice(offset, offset + limit);
  }

  async getLastInteraction(jid: string): Promise<string> {
    const chatList = await this.store.listChat({
      limit: 1,
      offset: 0,
      filter: { jid },
      sortBy: 'lastMessageTime',
      sortOrder: 'desc',
    });

    const chat = chatList[0];
    if (!chat || !chat.lastMessageTime) {
      return `No interactions found with ${jid}`;
    }

    const messageList = await this.store.listMessage(jid, {
      limit: 1,
      offset: 0,
      sortBy: 'timestamp',
      sortOrder: 'desc',
    });

    const lastMessage = messageList[0];
    if (!lastMessage) {
      return `Last interaction was at ${chat.lastMessageTime.toISOString()}`;
    }

    return `Last message: "${lastMessage.content}" at ${lastMessage.timestamp.toISOString()}`;
  }
}
