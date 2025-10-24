/**
 * Contact API client
 */

import apiClient from './client';
import type { ApiResponse, Contact } from '@whatsapp-mcp/common';

export const contactApi = {
  async listContact(): Promise<ApiResponse<Contact[]>> {
    const response = await apiClient.get<ApiResponse<Contact[]>>('/contacts');
    return response.data;
  },

  async searchContact(query: string): Promise<ApiResponse<Contact[]>> {
    const response = await apiClient.get<ApiResponse<Contact[]>>('/contacts/search', {
      params: { query },
    });
    return response.data;
  },
};
