/**
 * Message API client
 */

import apiClient from './client';
import type { ApiResponse, Message, MessageFilter, MessageContext } from '@whatsapp-mcp/common';

export const messageApi = {
  async listMessage(filter?: MessageFilter): Promise<ApiResponse<Message[]>> {
    const response = await apiClient.get<ApiResponse<Message[]>>('/messages', {
      params: filter,
    });
    return response.data;
  },

  async getMessageContext(
    chatJid: string,
    messageId: string,
    before?: number,
    after?: number
  ): Promise<ApiResponse<MessageContext>> {
    const response = await apiClient.get<ApiResponse<MessageContext>>(
      `/messages/${chatJid}/${messageId}/context`,
      {
        params: { before, after },
      }
    );
    return response.data;
  },

  async sendMessage(recipient: string, message: string): Promise<ApiResponse> {
    const response = await apiClient.post<ApiResponse>('/messages/send', {
      recipient,
      message,
    });
    return response.data;
  },

  async sendFile(recipient: string, mediaPath: string, caption?: string): Promise<ApiResponse> {
    const response = await apiClient.post<ApiResponse>('/messages/send-file', {
      recipient,
      mediaPath,
      caption,
    });
    return response.data;
  },

  async sendAudio(recipient: string, mediaPath: string): Promise<ApiResponse> {
    const response = await apiClient.post<ApiResponse>('/messages/send-audio', {
      recipient,
      mediaPath,
    });
    return response.data;
  },

  async downloadMedia(chatJid: string, messageId: string): Promise<ApiResponse<{ filePath: string }>> {
    const response = await apiClient.post<ApiResponse<{ filePath: string }>>(
      `/messages/${chatJid}/${messageId}/download`
    );
    return response.data;
  },
};
