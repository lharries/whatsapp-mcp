/**
 * MessageItem component - individual message bubble
 */

import type { Message } from '@whatsapp-mcp/common';
import { MessageBubble } from './MessageBubble';

interface MessageItemProps {
  message: Message;
}

export function MessageItem({ message }: MessageItemProps) {
  const isFromMe = message.isFromMe;

  return (
    <div
      className={`flex ${isFromMe ? 'justify-end' : 'justify-start'}`}
    >
      <div className={`max-w-[70%] ${isFromMe ? 'items-end' : 'items-start'}`}>
        {!isFromMe && (
          <p className="text-xs text-gray-600 mb-1 px-2">
            {message.sender.split('@')[0]}
          </p>
        )}
        <MessageBubble message={message} />
      </div>
    </div>
  );
}
