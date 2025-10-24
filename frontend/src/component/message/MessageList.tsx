/**
 * MessageList component - displays messages for selected chat
 */

import { useEffect, useRef } from 'react';
import { useAppDispatch, useAppSelector } from '../../hook/redux';
import { fetchMessageList } from '../../feature/message/messageSlice';
import { MessageItem } from './MessageItem';

export function MessageList() {
  const dispatch = useAppDispatch();
  const { messageList, loading, error, selectedChatJid } = useAppSelector(
    (state) => state.message
  );
  const { selectedChatJid: chatJid } = useAppSelector((state) => state.chat);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Fetch messages when chat is selected
  useEffect(() => {
    if (chatJid) {
      dispatch(fetchMessageList({ chatJid }));
    }
  }, [chatJid, dispatch]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messageList]);

  if (!chatJid) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50">
        <div className="text-center text-gray-500">
          <svg
            className="mx-auto h-12 w-12 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
          <p className="mt-4 text-lg font-semibold">No chat selected</p>
          <p className="text-sm mt-2">
            Select a chat from the sidebar to start messaging
          </p>
        </div>
      </div>
    );
  }

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
          <p className="font-semibold">Error loading messages</p>
          <p className="text-sm">{error}</p>
        </div>
      </div>
    );
  }

  // Filter messages for selected chat
  const chatMessageList = messageList.filter(
    (msg) => msg.chatJid === selectedChatJid
  );

  if (chatMessageList.length === 0) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50">
        <div className="text-center text-gray-500">
          <p className="text-lg font-semibold">No messages yet</p>
          <p className="text-sm mt-2">
            Send a message to start the conversation
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 bg-gray-50">
      <div className="space-y-2">
        {chatMessageList.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
