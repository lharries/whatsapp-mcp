/**
 * Chat Redux slice
 */

import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import type { Chat } from '@whatsapp-mcp/common';
import { chatApi } from '../../api/chat.api';

interface ChatSliceState {
  chatList: Chat[];
  selectedChat: Chat | null;
  isLoading: boolean;
  error: string | null;
  currentPage: number;
  hasMore: boolean;
}

const initialState: ChatSliceState = {
  chatList: [],
  selectedChat: null,
  isLoading: false,
  error: null,
  currentPage: 0,
  hasMore: true,
};

// Async thunks
export const fetchChatList = createAsyncThunk(
  'chat/fetchList',
  async (params: { query?: string; limit?: number; page?: number; sortBy?: 'last_active' | 'name' } = {}) => {
    const response = await chatApi.listChat(params);
    return response.data;
  }
);

export const fetchChat = createAsyncThunk(
  'chat/fetch',
  async (chatJid: string) => {
    const response = await chatApi.getChat(chatJid);
    return response.data;
  }
);

// Slice
const chatSlice = createSlice({
  name: 'chat',
  initialState,
  reducers: {
    setSelectedChat: (state, action: PayloadAction<Chat | null>) => {
      state.selectedChat = action.payload;
    },
    updateChat: (state, action: PayloadAction<Chat>) => {
      const index = state.chatList.findIndex(chat => chat.jid === action.payload.jid);
      if (index !== -1) {
        state.chatList[index] = action.payload;
      } else {
        state.chatList.unshift(action.payload);
      }
      // Update selected chat if it's the same
      if (state.selectedChat?.jid === action.payload.jid) {
        state.selectedChat = action.payload;
      }
    },
    clearChatList: (state) => {
      state.chatList = [];
      state.currentPage = 0;
      state.hasMore = true;
    },
    clearError: (state) => {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    // Fetch chat list
    builder.addCase(fetchChatList.pending, (state) => {
      state.isLoading = true;
      state.error = null;
    });
    builder.addCase(fetchChatList.fulfilled, (state, action) => {
      state.isLoading = false;
      if (action.meta.arg.page === 0) {
        state.chatList = action.payload;
      } else {
        state.chatList.push(...action.payload);
      }
      state.currentPage = action.meta.arg.page || 0;
      state.hasMore = action.payload.length === (action.meta.arg.limit || 20);
    });
    builder.addCase(fetchChatList.rejected, (state, action) => {
      state.isLoading = false;
      state.error = action.error.message || 'Failed to fetch chats';
    });

    // Fetch single chat
    builder.addCase(fetchChat.pending, (state) => {
      state.isLoading = true;
      state.error = null;
    });
    builder.addCase(fetchChat.fulfilled, (state, action) => {
      state.isLoading = false;
      state.selectedChat = action.payload;
    });
    builder.addCase(fetchChat.rejected, (state, action) => {
      state.isLoading = false;
      state.error = action.error.message || 'Failed to fetch chat';
    });
  },
});

export const { setSelectedChat, updateChat, clearChatList, clearError } = chatSlice.actions;
export default chatSlice.reducer;
