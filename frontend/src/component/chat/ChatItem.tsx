/**
 * ChatItem component - individual chat item in the list
 */

import type { Chat } from '@whatsapp-mcp/common';
import { useAppDispatch } from '../../hook/redux';
import { setSelectedChatJid } from '../../feature/chat/chatSlice';

interface ChatItemProps {
  chat: Chat;
  isSelected: boolean;
}

export function ChatItem({ chat, isSelected }: ChatItemProps) {
  const dispatch = useAppDispatch();

  const handleClick = () => {
    dispatch(setSelectedChatJid(chat.jid));
  };

  const formatTimestamp = (date: Date) => {
    const now = new Date();
    const messageDate = new Date(date);
    const diff = now.getTime() - messageDate.getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));

    if (days === 0) {
      return messageDate.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
      });
    } else if (days === 1) {
      return 'Yesterday';
    } else if (days < 7) {
      return messageDate.toLocaleDateString('en-US', { weekday: 'short' });
    } else {
      return messageDate.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
      });
    }
  };

  return (
    <div
      onClick={handleClick}
      className={`p-4 cursor-pointer hover:bg-gray-50 transition-colors ${
        isSelected ? 'bg-blue-50' : ''
      }`}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
            <h3 className="font-semibold text-gray-900 truncate">
              {chat.name}
            </h3>
            {chat.lastMessageTimestamp && (
              <span className="text-xs text-gray-500 ml-2 flex-shrink-0">
                {formatTimestamp(chat.lastMessageTimestamp)}
              </span>
            )}
          </div>
          {chat.lastMessage && (
            <p className="text-sm text-gray-600 truncate">
              {chat.lastMessage}
            </p>
          )}
        </div>
        {chat.unreadCount > 0 && (
          <div className="ml-2 flex-shrink-0">
            <span className="inline-flex items-center justify-center w-5 h-5 text-xs font-bold text-white bg-green-500 rounded-full">
              {chat.unreadCount > 99 ? '99+' : chat.unreadCount}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
