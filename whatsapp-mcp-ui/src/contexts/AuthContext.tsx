import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { User, AuthResponse } from '../types/api';
import { authAPI } from '../services/api';

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string, phoneNumber?: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const storedToken = localStorage.getItem('whatsapp_mcp_token');
    const storedUser = localStorage.getItem('whatsapp_mcp_user');
    
    if (storedToken && storedUser) {
      setToken(storedToken);
      setUser(JSON.parse(storedUser));
    }
    setIsLoading(false);
  }, []);

  const login = async (username: string, password: string) => {
    const response: AuthResponse = await authAPI.login({ username, password });
    setUser(response.user);
    setToken(response.token);
    localStorage.setItem('whatsapp_mcp_token', response.token);
    localStorage.setItem('whatsapp_mcp_user', JSON.stringify(response.user));
  };

  const register = async (username: string, email: string, password: string, phoneNumber?: string) => {
    const response: AuthResponse = await authAPI.register({ username, email, password, phone_number: phoneNumber });
    setUser(response.user);
    setToken(response.token);
    localStorage.setItem('whatsapp_mcp_token', response.token);
    localStorage.setItem('whatsapp_mcp_user', JSON.stringify(response.user));
  };

  const logout = () => {
    setUser(null);
    setToken(null);
    localStorage.removeItem('whatsapp_mcp_token');
    localStorage.removeItem('whatsapp_mcp_user');
  };

  const value = {
    user,
    token,
    login,
    register,
    logout,
    isLoading,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
