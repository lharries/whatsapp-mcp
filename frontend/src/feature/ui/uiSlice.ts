/**
 * UI state Redux slice
 */

import { createSlice, PayloadAction } from '@reduxjs/toolkit';

interface Notification {
  id: string;
  type: 'success' | 'error' | 'info' | 'warning';
  message: string;
  duration?: number;
}

interface UiSliceState {
  sidebarOpen: boolean;
  notificationList: Notification[];
  theme: 'light' | 'dark';
}

const initialState: UiSliceState = {
  sidebarOpen: true,
  notificationList: [],
  theme: 'light',
};

// Slice
const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    toggleSidebar: (state) => {
      state.sidebarOpen = !state.sidebarOpen;
    },
    setSidebarOpen: (state, action: PayloadAction<boolean>) => {
      state.sidebarOpen = action.payload;
    },
    addNotification: (state, action: PayloadAction<Omit<Notification, 'id'>>) => {
      const notification: Notification = {
        ...action.payload,
        id: Date.now().toString() + Math.random().toString(36).substring(7),
      };
      state.notificationList.push(notification);
    },
    removeNotification: (state, action: PayloadAction<string>) => {
      state.notificationList = state.notificationList.filter(
        (notif) => notif.id !== action.payload
      );
    },
    clearNotificationList: (state) => {
      state.notificationList = [];
    },
    setTheme: (state, action: PayloadAction<'light' | 'dark'>) => {
      state.theme = action.payload;
    },
    toggleTheme: (state) => {
      state.theme = state.theme === 'light' ? 'dark' : 'light';
    },
  },
});

export const {
  toggleSidebar,
  setSidebarOpen,
  addNotification,
  removeNotification,
  clearNotificationList,
  setTheme,
  toggleTheme,
} = uiSlice.actions;

export default uiSlice.reducer;
