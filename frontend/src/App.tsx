/**
 * Main App component
 */

import { useEffect, useState } from 'react';
import { useAuth } from './hook/useAuth';
import { useWebSocket } from './hook/useWebSocket';
import { useAppSelector } from './hook/redux';
import { ChatList } from './component/chat/ChatList';
import { MessageList } from './component/message/MessageList';
import { MessageInput } from './component/message/MessageInput';

function App() {
  const { authState, isAuthenticated, connectionStatus, qrCode, logout } = useAuth();
  const { isConnected } = useWebSocket();
  const { selectedChatJid } = useAppSelector((state) => state.chat);
  const { chatList } = useAppSelector((state) => state.chat);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    document.title = 'WhatsApp MCP Client';
  }, []);

  // Find selected chat name
  const selectedChat = chatList.find((chat) => chat.jid === selectedChatJid);

  // QR Code screen
  if (!isAuthenticated && qrCode) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center p-4">
        <div className="bg-white rounded-lg shadow-lg p-8 max-w-md w-full text-center">
          <h1 className="text-2xl font-bold text-gray-900 mb-6">
            WhatsApp MCP Client
          </h1>
          <h2 className="text-xl font-semibold mb-4">
            Scan QR Code to Authenticate
          </h2>
          <div className="flex justify-center mb-4">
            <img
              src={qrCode}
              alt="WhatsApp QR Code"
              className="border-4 border-gray-300 rounded"
            />
          </div>
          <p className="text-gray-600">
            Open WhatsApp on your phone and scan this code
          </p>
        </div>
      </div>
    );
  }

  // Loading screen
  if (!isAuthenticated && !qrCode) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="bg-white rounded-lg shadow-lg p-8 text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-900 mx-auto mb-4"></div>
          <p className="text-gray-600">Connecting to backend...</p>
        </div>
      </div>
    );
  }

  // Main chat interface
  return (
    <div className="h-screen flex flex-col bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow-sm z-10">
        <div className="px-4 py-3 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="p-2 hover:bg-gray-100 rounded-lg lg:hidden"
            >
              <svg
                className="w-6 h-6"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 6h16M4 12h16M4 18h16"
                />
              </svg>
            </button>
            <h1 className="text-xl font-bold text-gray-900">
              WhatsApp MCP Client
            </h1>
          </div>
          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${
                isConnected ? 'bg-green-500' : 'bg-red-500'
              }`} />
              <span className="text-xs text-gray-600">
                WS: {isConnected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${
                connectionStatus === 'ready' || connectionStatus === 'connected'
                  ? 'bg-green-500'
                  : connectionStatus === 'connecting'
                  ? 'bg-yellow-500'
                  : 'bg-red-500'
              }`} />
              <span className="text-xs text-gray-600">
                {connectionStatus}
              </span>
            </div>
            <button
              onClick={logout}
              className="px-3 py-1 text-sm text-red-600 hover:bg-red-50 rounded"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar - Chat List */}
        <aside
          className={`${
            sidebarOpen ? 'block' : 'hidden'
          } lg:block w-full lg:w-80 bg-white border-r border-gray-200 flex flex-col`}
        >
          <div className="p-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Chats</h2>
          </div>
          <div className="flex-1 overflow-hidden">
            <ChatList />
          </div>
        </aside>

        {/* Main Chat Area */}
        <main className="flex-1 flex flex-col bg-gray-50">
          {selectedChatJid ? (
            <>
              {/* Chat Header */}
              <div className="bg-white border-b border-gray-200 px-4 py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => setSidebarOpen(true)}
                      className="p-2 hover:bg-gray-100 rounded-lg lg:hidden"
                    >
                      <svg
                        className="w-5 h-5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M15 19l-7-7 7-7"
                        />
                      </svg>
                    </button>
                    <div>
                      <h3 className="font-semibold text-gray-900">
                        {selectedChat?.name || 'Unknown'}
                      </h3>
                      <p className="text-xs text-gray-500">
                        {selectedChatJid.split('@')[0]}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Messages */}
              <MessageList />

              {/* Message Input */}
              <MessageInput />
            </>
          ) : (
            <div className="flex items-center justify-center h-full">
              <div className="text-center text-gray-500">
                <svg
                  className="mx-auto h-16 w-16 text-gray-400"
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
                <p className="mt-4 text-lg font-semibold">
                  Select a chat to start messaging
                </p>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
