import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Loader2, Smartphone, CheckCircle, XCircle, Clock } from 'lucide-react';
import QRCode from 'react-qr-code';
import { whatsappAPI } from '@/services/api';
import { WhatsAppDeviceStatus } from '@/types/api';

export const DeviceManager: React.FC = () => {
  const [deviceName, setDeviceName] = useState('default');
  const [deviceStatus, setDeviceStatus] = useState<WhatsAppDeviceStatus | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    let interval: NodeJS.Timeout;
    
    if (isPolling && deviceStatus && !deviceStatus.isConnected) {
      interval = setInterval(async () => {
        try {
          const status = await whatsappAPI.getDeviceStatus(deviceName);
          setDeviceStatus(status);
          
          if (status.isConnected) {
            setIsPolling(false);
            setSuccess('WhatsApp connected successfully!');
            setTimeout(() => setSuccess(null), 5000);
          }
        } catch (err) {
          console.error('Polling error:', err);
        }
      }, 3000);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isPolling, deviceStatus, deviceName]);

  const handleCreateDevice = async () => {
    setIsCreating(true);
    setError(null);
    setSuccess(null);

    try {
      await whatsappAPI.createDevice(deviceName);
      setSuccess('Device session created! Waiting for QR code...');
      setIsPolling(true);
      
      setTimeout(async () => {
        try {
          const status = await whatsappAPI.getDeviceStatus(deviceName);
          setDeviceStatus(status);
        } catch (err) {
          console.error('Failed to get initial status:', err);
        }
      }, 2000);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to create device session');
    } finally {
      setIsCreating(false);
    }
  };

  const handleCheckStatus = async () => {
    setError(null);
    try {
      const status = await whatsappAPI.getDeviceStatus(deviceName);
      setDeviceStatus(status);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to get device status');
    }
  };

  const getStatusIcon = () => {
    if (!deviceStatus) return <Smartphone className="h-4 w-4" />;
    if (deviceStatus.isConnected) return <CheckCircle className="h-4 w-4 text-green-500" />;
    if (deviceStatus.hasQR) return <Clock className="h-4 w-4 text-yellow-500" />;
    return <XCircle className="h-4 w-4 text-red-500" />;
  };

  const getStatusText = () => {
    if (!deviceStatus) return 'Unknown';
    if (deviceStatus.isConnected) return 'Connected';
    if (deviceStatus.hasQR) return 'Waiting for QR scan';
    return 'Disconnected';
  };

  const getStatusVariant = () => {
    if (!deviceStatus) return 'secondary';
    if (deviceStatus.isConnected) return 'default';
    if (deviceStatus.hasQR) return 'secondary';
    return 'destructive';
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Smartphone className="h-5 w-5" />
          WhatsApp Device Management
        </CardTitle>
        <CardDescription>
          Connect your WhatsApp account to send and receive messages
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex gap-4 items-end">
          <div className="flex-1">
            <Label htmlFor="device-name">Device Name</Label>
            <Input
              id="device-name"
              value={deviceName}
              onChange={(e) => setDeviceName(e.target.value)}
              placeholder="default"
            />
          </div>
          <Button onClick={handleCreateDevice} disabled={isCreating}>
            {isCreating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Connect Device
          </Button>
          <Button variant="outline" onClick={handleCheckStatus}>
            Check Status
          </Button>
        </div>

        {deviceStatus && (
          <div className="space-y-4">
            <div className="flex items-center justify-between p-4 border rounded-lg">
              <div className="flex items-center gap-3">
                {getStatusIcon()}
                <div>
                  <p className="font-medium">Device: {deviceStatus.deviceName}</p>
                  <p className="text-sm text-gray-600">QR Available: {deviceStatus.hasQR ? 'Yes' : 'No'}</p>
                </div>
              </div>
              <Badge variant={getStatusVariant()}>{getStatusText()}</Badge>
            </div>

            {deviceStatus.hasQR && !deviceStatus.isConnected && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">Scan QR Code with WhatsApp</CardTitle>
                  <CardDescription>
                    <ol className="list-decimal list-inside space-y-1 text-sm">
                      <li>Open WhatsApp on your phone</li>
                      <li>Go to Settings → Linked Devices</li>
                      <li>Tap "Link a Device"</li>
                      <li>Scan the QR code below</li>
                    </ol>
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex justify-center">
                  <div className="p-4 bg-white rounded-lg border">
                    {isPolling ? (
                      <div className="flex flex-col items-center gap-4">
                        <QRCode value="placeholder-qr-code" size={200} />
                        <div className="flex items-center gap-2 text-sm text-gray-600">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Waiting for scan...
                        </div>
                      </div>
                    ) : (
                      <div className="w-[200px] h-[200px] flex items-center justify-center bg-gray-100 rounded">
                        <p className="text-gray-500">QR Code Loading...</p>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {success && (
          <Alert>
            <AlertDescription>{success}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
};
