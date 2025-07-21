import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Send, Loader2 } from 'lucide-react';
import { whatsappAPI } from '@/services/api';

export const MessageTester: React.FC = () => {
  const [recipient, setRecipient] = useState('');
  const [message, setMessage] = useState('');
  const [deviceName, setDeviceName] = useState('default');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSending(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await whatsappAPI.sendMessage({
        recipient,
        message,
        deviceName,
      });

      if (result.success) {
        setSuccess('Message sent successfully!');
        setMessage('');
        setTimeout(() => setSuccess(null), 5000);
      } else {
        setError('Failed to send message');
      }
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to send message');
    } finally {
      setIsSending(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Send className="h-5 w-5" />
          Send Test Message
        </CardTitle>
        <CardDescription>
          Send a test message through your connected WhatsApp device
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSendMessage} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="recipient">Recipient</Label>
              <Input
                id="recipient"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                placeholder="1234567890@s.whatsapp.net"
                required
              />
              <p className="text-xs text-gray-500">
                Format: phone number with country code + @s.whatsapp.net
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="device-name-msg">Device Name</Label>
              <Input
                id="device-name-msg"
                value={deviceName}
                onChange={(e) => setDeviceName(e.target.value)}
                placeholder="default"
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="message">Message</Label>
            <Textarea
              id="message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Hello from WhatsApp MCP!"
              required
              rows={3}
            />
          </div>
          <Button type="submit" disabled={isSending} className="w-full">
            {isSending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Send Message
          </Button>
        </form>

        {error && (
          <Alert variant="destructive" className="mt-4">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {success && (
          <Alert className="mt-4">
            <AlertDescription>{success}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
};
