import axios from 'axios';
import { AuthResponse, CreateUserRequest, LoginRequest, WhatsAppDeviceStatus, SendMessageRequest, ChatMap, Message } from '../types/api';

const API_BASE = 'http://localhost:3000/api';

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('whatsapp_mcp_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const authAPI = {
  register: async (data: CreateUserRequest): Promise<AuthResponse> => {
    const response = await api.post('/auth/register', data);
    return response.data;
  },

  login: async (data: LoginRequest): Promise<AuthResponse> => {
    const response = await api.post('/auth/login', data);
    return response.data;
  },
};

export const whatsappAPI = {
  createDevice: async (deviceName: string): Promise<{ deviceKey: string; message: string }> => {
    const response = await api.post('/whatsapp/device', { deviceName });
    return response.data;
  },

  getDeviceStatus: async (deviceName: string): Promise<WhatsAppDeviceStatus> => {
    const response = await api.get(`/whatsapp/device/${deviceName}/status`);
    return response.data;
  },

  sendMessage: async (data: SendMessageRequest): Promise<{ success: boolean }> => {
    const response = await api.post('/whatsapp/send', data);
    return response.data;
  },
};

export const chatAPI = {
  getChats: async (): Promise<ChatMap> => {
    const response = await api.get('/chats');
    return response.data;
  },

  getMessages: async (chatJID: string, limit: number = 50): Promise<Message[]> => {
    const response = await api.get(`/chats/${encodeURIComponent(chatJID)}/messages?limit=${limit}`);
    return response.data;
  },
};
