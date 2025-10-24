/**
 * MessageBubble component - styled message content with media support
 */

import type { Message } from '@whatsapp-mcp/common';
import { useState } from 'react';

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isFromMe = message.isFromMe;
  const [imageError, setImageError] = useState(false);

  const formatTime = (date: Date) => {
    return new Date(date).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  const renderMedia = () => {
    if (!message.mediaType) return null;

    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:3001';

    switch (message.mediaType) {
      case 'image':
        if (message.mediaUrl && !imageError) {
          return (
            <div className="mb-2">
              <img
                src={`${baseUrl}${message.mediaUrl}`}
                alt="Image message"
                className="rounded-lg max-w-full h-auto"
                onError={() => setImageError(true)}
              />
            </div>
          );
        }
        return (
          <div className="mb-2 p-4 bg-gray-200 rounded-lg text-gray-600 text-sm">
            📷 Image (preview unavailable)
          </div>
        );

      case 'video':
        return (
          <div className="mb-2">
            {message.mediaUrl ? (
              <video
                src={`${baseUrl}${message.mediaUrl}`}
                controls
                className="rounded-lg max-w-full"
              />
            ) : (
              <div className="p-4 bg-gray-200 rounded-lg text-gray-600 text-sm">
                🎥 Video (preview unavailable)
              </div>
            )}
          </div>
        );

      case 'audio':
        return (
          <div className="mb-2">
            {message.mediaUrl ? (
              <audio
                src={`${baseUrl}${message.mediaUrl}`}
                controls
                className="w-full"
              />
            ) : (
              <div className="p-2 bg-gray-200 rounded-lg text-gray-600 text-sm flex items-center gap-2">
                🎵 Audio message
                {message.mediaDuration && (
                  <span className="text-xs">
                    ({Math.floor(message.mediaDuration)}s)
                  </span>
                )}
              </div>
            )}
          </div>
        );

      case 'document':
        return (
          <div className="mb-2 p-3 bg-gray-200 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-2xl">📄</span>
              <div className="flex-1">
                <p className="text-sm font-semibold text-gray-900">
                  {message.mediaFilename || 'Document'}
                </p>
                {message.mediaSize && (
                  <p className="text-xs text-gray-600">
                    {(message.mediaSize / 1024).toFixed(1)} KB
                  </p>
                )}
              </div>
            </div>
          </div>
        );

      default:
        return (
          <div className="mb-2 p-2 bg-gray-200 rounded-lg text-gray-600 text-sm">
            📎 Media message
          </div>
        );
    }
  };

  return (
    <div
      className={`rounded-lg px-4 py-2 shadow-sm ${
        isFromMe
          ? 'bg-green-500 text-white'
          : 'bg-white text-gray-900'
      }`}
    >
      {renderMedia()}
      {message.content && (
        <p className="text-sm whitespace-pre-wrap break-words">
          {message.content}
        </p>
      )}
      <div className="flex items-center justify-end gap-1 mt-1">
        <span
          className={`text-xs ${
            isFromMe ? 'text-green-100' : 'text-gray-500'
          }`}
        >
          {formatTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}
