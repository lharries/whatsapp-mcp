/**
 * Authentication API client
 */

import apiClient from './client';
import type { ApiResponse, AuthState } from '@whatsapp-mcp/common';

export const authApi = {
  async getAuthStatus(): Promise<ApiResponse<AuthState>> {
    const response = await apiClient.get<ApiResponse<AuthState>>('/auth/status');
    return response.data;
  },

  async getQRCode(): Promise<ApiResponse<{ qrCode: string }>> {
    const response = await apiClient.get<ApiResponse<{ qrCode: string }>>('/auth/qr');
    return response.data;
  },

  async logout(): Promise<ApiResponse> {
    const response = await apiClient.post<ApiResponse>('/auth/logout');
    return response.data;
  },
};
