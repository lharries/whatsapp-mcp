/**
 * Message service - Business logic for message operations
 */

import type { Message, MessageFilter, MessageContext } from '@whatsapp-mcp/common';
import { BaseStore } from '../store/base.store.js';
import { WhatsAppClient } from '../whatsapp/client.js';
import { DEFAULT_MESSAGE_LIMIT, DEFAULT_PAGE } from '@whatsapp-mcp/common';

export class MessageService {
  constructor(
    private store: BaseStore,
    private whatsappClient: WhatsAppClient
  ) {}

  async listMessage(filter: MessageFilter = {}): Promise<Message[]> {
    const {
      chatJid,
      query,
      limit = DEFAULT_MESSAGE_LIMIT,
      page = DEFAULT_PAGE,
      senderPhoneNumber,
      after,
      before,
    } = filter;

    if (query) {
      return await this.store.searchMessage(query, {
        limit,
        offset: page * limit,
        sortBy: 'timestamp',
        sortOrder: 'desc',
      });
    }

    if (chatJid) {
      const messageList = await this.store.listMessage(chatJid, {
        limit,
        offset: page * limit,
        sortBy: 'timestamp',
        sortOrder: 'desc',
      });

      return messageList.filter((msg) => {
        if (senderPhoneNumber && !msg.sender.includes(senderPhoneNumber)) return false;
        if (after && new Date(msg.timestamp) < new Date(after)) return false;
        if (before && new Date(msg.timestamp) > new Date(before)) return false;
        return true;
      });
    }

    return [];
  }

  async getMessageContext(
    messageId: string,
    chatJid: string,
    before = 5,
    after = 5
  ): Promise<MessageContext | null> {
    const targetMessage = await this.store.getMessage(messageId, chatJid);
    if (!targetMessage) return null;

    const allMessageList = await this.store.listMessage(chatJid, {
      sortBy: 'timestamp',
      sortOrder: 'asc',
    });

    const targetIndex = allMessageList.findIndex((m) => m.id === messageId);
    if (targetIndex === -1) return null;

    const messageListBefore = allMessageList.slice(Math.max(0, targetIndex - before), targetIndex);
    const messageListAfter = allMessageList.slice(targetIndex + 1, targetIndex + 1 + after);

    const chat = await this.store.getChat(chatJid);

    return {
      targetMessage,
      messageListBefore,
      messageListAfter,
      chat: {
        jid: chatJid,
        name: chat?.name || chatJid,
      },
    };
  }

  async sendMessage(recipient: string, text: string): Promise<{ success: boolean; message: string }> {
    try {
      await this.whatsappClient.sendMessage(recipient, text);
      return {
        success: true,
        message: `Message sent to ${recipient}`,
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.message || 'Failed to send message',
      };
    }
  }

  async sendFile(
    recipient: string,
    mediaPath: string,
    caption?: string
  ): Promise<{ success: boolean; message: string }> {
    try {
      await this.whatsappClient.sendMedia(recipient, mediaPath, caption);
      return {
        success: true,
        message: `File sent to ${recipient}`,
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.message || 'Failed to send file',
      };
    }
  }

  async sendAudio(recipient: string, audioPath: string): Promise<{ success: boolean; message: string }> {
    try {
      await this.whatsappClient.sendAudio(recipient, audioPath);
      return {
        success: true,
        message: `Voice message sent to ${recipient}`,
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.message || 'Failed to send voice message',
      };
    }
  }

  async downloadMedia(messageId: string, chatJid: string): Promise<string | null> {
    return await this.whatsappClient.downloadMedia(messageId, chatJid);
  }
}
