/**
 * Redux store configuration
 */

import { configureStore } from '@reduxjs/toolkit';
import authReducer from '../feature/auth/authSlice';
import chatReducer from '../feature/chat/chatSlice';
import messageReducer from '../feature/message/messageSlice';
import uiReducer from '../feature/ui/uiSlice';

export const store = configureStore({
  reducer: {
    auth: authReducer,
    chat: chatReducer,
    message: messageReducer,
    ui: uiReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        // Ignore these action types
        ignoredActions: ['message/setMessageList', 'chat/setChatList'],
        // Ignore these paths in the state
        ignoredPaths: ['message.messageList', 'chat.chatList'],
      },
    }),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
