import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { MessageCircle, RefreshCw } from 'lucide-react';
import { chatAPI } from '@/services/api';
import { ChatMap } from '@/types/api';

export const ChatList: React.FC = () => {
  const [chats, setChats] = useState<ChatMap>({});
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadChats = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const chatData = await chatAPI.getChats();
      setChats(chatData);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to load chats');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadChats();
  }, []);

  const formatChatName = (jid: string) => {
    if (jid.includes('@g.us')) {
      return jid.split('@')[0] + ' (Group)';
    }
    return jid.split('@')[0];
  };

  const chatEntries = Object.entries(chats).sort(
    ([, a], [, b]) => new Date(b).getTime() - new Date(a).getTime()
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageCircle className="h-5 w-5" />
          Your Chats
        </CardTitle>
        <CardDescription>
          View your WhatsApp conversations
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex justify-between items-center mb-4">
          <p className="text-sm text-gray-600">
            {chatEntries.length} chat{chatEntries.length !== 1 ? 's' : ''}
          </p>
          <Button variant="outline" size="sm" onClick={loadChats} disabled={isLoading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>

        {chatEntries.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <MessageCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p>No chats found</p>
            <p className="text-sm">Send a message to start!</p>
          </div>
        ) : (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {chatEntries.map(([jid, lastMessageTime]) => (
              <div
                key={jid}
                className="p-3 border rounded-lg hover:bg-gray-50 cursor-pointer transition-colors"
              >
                <div className="flex justify-between items-start">
                  <div>
                    <p className="font-medium">{formatChatName(jid)}</p>
                    <p className="text-xs text-gray-500">{jid}</p>
                  </div>
                  <p className="text-xs text-gray-500">
                    {new Date(lastMessageTime).toLocaleString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}

        {error && (
          <Alert variant="destructive" className="mt-4">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
};
