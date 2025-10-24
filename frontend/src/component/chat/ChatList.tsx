/**
 * ChatList component - displays list of all chats
 */

import { useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '../../hook/redux';
import { fetchChatList } from '../../feature/chat/chatSlice';
import { ChatItem } from './ChatItem';

export function ChatList() {
  const dispatch = useAppDispatch();
  const { chatList, loading, error, selectedChatJid } = useAppSelector(
    (state) => state.chat
  );

  useEffect(() => {
    dispatch(fetchChatList());
  }, [dispatch]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <div className="bg-red-50 border border-red-200 rounded p-4 text-red-800">
          <p className="font-semibold">Error loading chats</p>
          <p className="text-sm">{error}</p>
        </div>
      </div>
    );
  }

  if (chatList.length === 0) {
    return (
      <div className="flex items-center justify-center h-full p-4">
        <div className="text-center text-gray-500">
          <p className="text-lg font-semibold">No chats yet</p>
          <p className="text-sm mt-2">
            Start a conversation to see it here
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="divide-y divide-gray-200">
        {chatList.map((chat) => (
          <ChatItem
            key={chat.jid}
            chat={chat}
            isSelected={chat.jid === selectedChatJid}
          />
        ))}
      </div>
    </div>
  );
}
