/**
 * WebSocket hook for real-time updates
 */

import { useEffect } from 'react';
import { websocketClient } from '../api/websocket';
import { useAppDispatch } from './redux';
import { addMessage } from '../feature/message/messageSlice';
import { updateChat } from '../feature/chat/chatSlice';
import { setConnectionStatus } from '../feature/auth/authSlice';

export function useWebSocket() {
  const dispatch = useAppDispatch();

  useEffect(() => {
    // Connect to WebSocket
    websocketClient.connect();

    // Register handlers
    const unsubscribeMessage = websocketClient.onMessage((message) => {
      dispatch(addMessage(message));
    });

    const unsubscribeChatUpdate = websocketClient.onChatUpdate((chat) => {
      dispatch(updateChat(chat));
    });

    const unsubscribeConnectionUpdate = websocketClient.onConnectionUpdate((status) => {
      dispatch(setConnectionStatus(status));
    });

    // Cleanup on unmount
    return () => {
      unsubscribeMessage();
      unsubscribeChatUpdate();
      unsubscribeConnectionUpdate();
      websocketClient.disconnect();
    };
  }, [dispatch]);

  return {
    isConnected: websocketClient.isConnected(),
  };
}
