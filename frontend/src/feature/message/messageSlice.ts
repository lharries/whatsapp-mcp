/**
 * Message Redux slice
 */

import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import type { Message } from '@whatsapp-mcp/common';
import { messageApi } from '../../api/message.api';

interface MessageSliceState {
  messageList: Message[];
  isLoading: boolean;
  isSending: boolean;
  error: string | null;
  currentPage: number;
  hasMore: boolean;
  selectedChatJid: string | null;
}

const initialState: MessageSliceState = {
  messageList: [],
  isLoading: false,
  isSending: false,
  error: null,
  currentPage: 0,
  hasMore: true,
  selectedChatJid: null,
};

// Async thunks
export const fetchMessageList = createAsyncThunk(
  'message/fetchList',
  async (params: { chatJid?: string; query?: string; limit?: number; page?: number }) => {
    const response = await messageApi.listMessage(params);
    return response.data;
  }
);

export const sendMessage = createAsyncThunk(
  'message/send',
  async (params: { recipient: string; message: string }) => {
    const response = await messageApi.sendMessage(params.recipient, params.message);
    return response;
  }
);

export const sendFile = createAsyncThunk(
  'message/sendFile',
  async (params: { recipient: string; mediaPath: string; caption?: string }) => {
    const response = await messageApi.sendFile(params.recipient, params.mediaPath, params.caption);
    return response;
  }
);

export const sendAudio = createAsyncThunk(
  'message/sendAudio',
  async (params: { recipient: string; mediaPath: string }) => {
    const response = await messageApi.sendAudio(params.recipient, params.mediaPath);
    return response;
  }
);

// Slice
const messageSlice = createSlice({
  name: 'message',
  initialState,
  reducers: {
    addMessage: (state, action: PayloadAction<Message>) => {
      const exists = state.messageList.some(msg => msg.id === action.payload.id);
      if (!exists) {
        state.messageList.push(action.payload);
      }
    },
    setMessageList: (state, action: PayloadAction<Message[]>) => {
      state.messageList = action.payload;
    },
    setSelectedChatJid: (state, action: PayloadAction<string | null>) => {
      state.selectedChatJid = action.payload;
      state.messageList = [];
      state.currentPage = 0;
      state.hasMore = true;
    },
    clearMessageList: (state) => {
      state.messageList = [];
      state.currentPage = 0;
      state.hasMore = true;
    },
    clearError: (state) => {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    // Fetch message list
    builder.addCase(fetchMessageList.pending, (state) => {
      state.isLoading = true;
      state.error = null;
    });
    builder.addCase(fetchMessageList.fulfilled, (state, action) => {
      state.isLoading = false;
      if (action.meta.arg.page === 0) {
        state.messageList = action.payload;
      } else {
        state.messageList.push(...action.payload);
      }
      state.currentPage = action.meta.arg.page || 0;
      state.hasMore = action.payload.length === (action.meta.arg.limit || 20);
    });
    builder.addCase(fetchMessageList.rejected, (state, action) => {
      state.isLoading = false;
      state.error = action.error.message || 'Failed to fetch messages';
    });

    // Send message
    builder.addCase(sendMessage.pending, (state) => {
      state.isSending = true;
      state.error = null;
    });
    builder.addCase(sendMessage.fulfilled, (state) => {
      state.isSending = false;
    });
    builder.addCase(sendMessage.rejected, (state, action) => {
      state.isSending = false;
      state.error = action.error.message || 'Failed to send message';
    });

    // Send file
    builder.addCase(sendFile.pending, (state) => {
      state.isSending = true;
      state.error = null;
    });
    builder.addCase(sendFile.fulfilled, (state) => {
      state.isSending = false;
    });
    builder.addCase(sendFile.rejected, (state, action) => {
      state.isSending = false;
      state.error = action.error.message || 'Failed to send file';
    });

    // Send audio
    builder.addCase(sendAudio.pending, (state) => {
      state.isSending = true;
      state.error = null;
    });
    builder.addCase(sendAudio.fulfilled, (state) => {
      state.isSending = false;
    });
    builder.addCase(sendAudio.rejected, (state, action) => {
      state.isSending = false;
      state.error = action.error.message || 'Failed to send audio';
    });
  },
});

export const { addMessage, setMessageList, setSelectedChatJid, clearMessageList, clearError } = messageSlice.actions;
export default messageSlice.reducer;
