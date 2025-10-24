/**
 * Authentication Redux slice
 */

import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import type { AuthState, ConnectionStatus } from '@whatsapp-mcp/common';
import { authApi } from '../../api/auth.api';

interface AuthSliceState {
  authState: AuthState | null;
  isLoading: boolean;
  error: string | null;
}

const initialState: AuthSliceState = {
  authState: null,
  isLoading: false,
  error: null,
};

// Async thunks
export const fetchAuthStatus = createAsyncThunk(
  'auth/fetchStatus',
  async () => {
    const response = await authApi.getAuthStatus();
    return response.data;
  }
);

export const fetchQRCode = createAsyncThunk(
  'auth/fetchQRCode',
  async () => {
    const response = await authApi.getQRCode();
    return response.data;
  }
);

export const logout = createAsyncThunk(
  'auth/logout',
  async () => {
    await authApi.logout();
  }
);

// Slice
const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setConnectionStatus: (state, action: PayloadAction<ConnectionStatus>) => {
      if (state.authState) {
        state.authState.connectionStatus = action.payload;
        state.authState.isConnected = action.payload === 'connected' || action.payload === 'ready';
      }
    },
    setQRCode: (state, action: PayloadAction<string | undefined>) => {
      if (state.authState) {
        state.authState.qrCode = action.payload;
      }
    },
    clearError: (state) => {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    // Fetch auth status
    builder.addCase(fetchAuthStatus.pending, (state) => {
      state.isLoading = true;
      state.error = null;
    });
    builder.addCase(fetchAuthStatus.fulfilled, (state, action) => {
      state.isLoading = false;
      state.authState = action.payload;
    });
    builder.addCase(fetchAuthStatus.rejected, (state, action) => {
      state.isLoading = false;
      state.error = action.error.message || 'Failed to fetch auth status';
    });

    // Fetch QR code
    builder.addCase(fetchQRCode.pending, (state) => {
      state.isLoading = true;
      state.error = null;
    });
    builder.addCase(fetchQRCode.fulfilled, (state, action) => {
      state.isLoading = false;
      if (state.authState && action.payload.qrCode) {
        state.authState.qrCode = action.payload.qrCode;
      }
    });
    builder.addCase(fetchQRCode.rejected, (state, action) => {
      state.isLoading = false;
      state.error = action.error.message || 'Failed to fetch QR code';
    });

    // Logout
    builder.addCase(logout.pending, (state) => {
      state.isLoading = true;
      state.error = null;
    });
    builder.addCase(logout.fulfilled, (state) => {
      state.isLoading = false;
      state.authState = null;
    });
    builder.addCase(logout.rejected, (state, action) => {
      state.isLoading = false;
      state.error = action.error.message || 'Failed to logout';
    });
  },
});

export const { setConnectionStatus, setQRCode, clearError } = authSlice.actions;
export default authSlice.reducer;
