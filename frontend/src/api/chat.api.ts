/**
 * Chat API client
 */

import apiClient from './client';
import type { ApiResponse, Chat, ChatFilter } from '@whatsapp-mcp/common';

export const chatApi = {
  async listChat(filter?: ChatFilter): Promise<ApiResponse<Chat[]>> {
    const response = await apiClient.get<ApiResponse<Chat[]>>('/chats', {
      params: filter,
    });
    return response.data;
  },

  async getChat(chatJid: string): Promise<ApiResponse<Chat>> {
    const response = await apiClient.get<ApiResponse<Chat>>(`/chats/${chatJid}`);
    return response.data;
  },

  async getDirectChatByContact(phoneNumber: string): Promise<ApiResponse<Chat>> {
    const response = await apiClient.get<ApiResponse<Chat>>(`/chats/contact/${phoneNumber}`);
    return response.data;
  },

  async getContactChatList(jid: string, limit?: number, page?: number): Promise<ApiResponse<Chat[]>> {
    const response = await apiClient.get<ApiResponse<Chat[]>>(`/chats/by-contact/${jid}`, {
      params: { limit, page },
    });
    return response.data;
  },
};
