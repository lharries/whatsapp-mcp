import React from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LogOut, User } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { DeviceManager } from '@/components/WhatsApp/DeviceManager';
import { MessageTester } from '@/components/WhatsApp/MessageTester';
import { ChatList } from '@/components/WhatsApp/ChatList';

export const Dashboard: React.FC = () => {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="max-w-6xl mx-auto space-y-6">
        <Card>
          <CardHeader>
            <div className="flex justify-between items-center">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <User className="h-5 w-5" />
                  Welcome, {user?.username}!
                </CardTitle>
                <CardDescription>
                  WhatsApp MCP - Multi-User Management Platform
                </CardDescription>
              </div>
              <Button variant="outline" onClick={logout}>
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </Button>
            </div>
          </CardHeader>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-6">
            <DeviceManager />
            <MessageTester />
          </div>
          <div>
            <ChatList />
          </div>
        </div>
      </div>
    </div>
  );
};
