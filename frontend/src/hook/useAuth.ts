/**
 * Auth hook
 */

import { useEffect } from 'react';
import { useAppDispatch, useAppSelector } from './redux';
import { fetchAuthStatus, fetchQRCode, logout } from '../feature/auth/authSlice';

export function useAuth() {
  const dispatch = useAppDispatch();
  const { authState, isLoading, error } = useAppSelector((state) => state.auth);

  useEffect(() => {
    // Fetch auth status on mount
    dispatch(fetchAuthStatus());

    // Poll for auth status every 10 seconds
    const interval = setInterval(() => {
      dispatch(fetchAuthStatus());
    }, 10000);

    return () => clearInterval(interval);
  }, [dispatch]);

  const refreshQRCode = () => {
    dispatch(fetchQRCode());
  };

  const handleLogout = () => {
    dispatch(logout());
  };

  return {
    authState,
    isLoading,
    error,
    isAuthenticated: authState?.isAuthenticated ?? false,
    isConnected: authState?.isConnected ?? false,
    connectionStatus: authState?.connectionStatus ?? 'disconnected',
    qrCode: authState?.qrCode,
    refreshQRCode,
    logout: handleLogout,
  };
}
