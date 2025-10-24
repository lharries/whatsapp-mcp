/**
 * MCP Server implementation with dual transport support
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { MessageService } from '../service/message.service.js';
import { ChatService } from '../service/chat.service.js';
import { ContactService } from '../service/contact.service.js';
import { WhatsAppClient } from '../whatsapp/client.js';
import { env } from '../config/environment.js';
import { mcpLogger } from '../util/logger.js';
import type { MCPToolResponse } from '@whatsapp-mcp/common';

export class WhatsAppMCPServer {
  private server: Server;

  constructor(
    private messageService: MessageService,
    private chatService: ChatService,
    private contactService: ContactService,
    private whatsappClient: WhatsAppClient
  ) {
    this.server = new Server(
      {
        name: env.mcpServerName,
        version: env.mcpServerVersion,
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.registerHandlers();
  }

  private registerHandlers() {
    // List available tools
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        {
          name: 'search_contacts',
          description: 'Search WhatsApp contacts by name or phone number',
          inputSchema: {
            type: 'object',
            properties: {
              query: { type: 'string', description: 'Search term for contact name or phone' },
            },
            required: ['query'],
          },
        },
        {
          name: 'list_messages',
          description: 'List WhatsApp messages with filters',
          inputSchema: {
            type: 'object',
            properties: {
              chatJid: { type: 'string', description: 'Chat JID to filter messages' },
              query: { type: 'string', description: 'Search query for message content' },
              limit: { type: 'number', description: 'Maximum messages to return', default: 20 },
              page: { type: 'number', description: 'Page number for pagination', default: 0 },
            },
          },
        },
        {
          name: 'list_chats',
          description: 'List available WhatsApp chats',
          inputSchema: {
            type: 'object',
            properties: {
              query: { type: 'string', description: 'Search query for chat names' },
              limit: { type: 'number', description: 'Maximum chats to return', default: 20 },
              page: { type: 'number', description: 'Page number', default: 0 },
              sortBy: { type: 'string', enum: ['last_active', 'name'], default: 'last_active' },
            },
          },
        },
        {
          name: 'get_chat',
          description: 'Get specific chat information by JID',
          inputSchema: {
            type: 'object',
            properties: {
              chatJid: { type: 'string', description: 'Chat JID' },
            },
            required: ['chatJid'],
          },
        },
        {
          name: 'get_direct_chat_by_contact',
          description: 'Get direct chat with a contact by phone number',
          inputSchema: {
            type: 'object',
            properties: {
              senderPhoneNumber: { type: 'string', description: 'Phone number' },
            },
            required: ['senderPhoneNumber'],
          },
        },
        {
          name: 'get_contact_chats',
          description: 'Get all chats involving a specific contact',
          inputSchema: {
            type: 'object',
            properties: {
              jid: { type: 'string', description: 'Contact JID' },
              limit: { type: 'number', default: 20 },
              page: { type: 'number', default: 0 },
            },
            required: ['jid'],
          },
        },
        {
          name: 'get_last_interaction',
          description: 'Get the most recent interaction with a contact',
          inputSchema: {
            type: 'object',
            properties: {
              jid: { type: 'string', description: 'Contact JID' },
            },
            required: ['jid'],
          },
        },
        {
          name: 'get_message_context',
          description: 'Get context around a specific message',
          inputSchema: {
            type: 'object',
            properties: {
              messageId: { type: 'string', description: 'Message ID' },
              chatJid: { type: 'string', description: 'Chat JID' },
              before: { type: 'number', description: 'Messages before', default: 5 },
              after: { type: 'number', description: 'Messages after', default: 5 },
            },
            required: ['messageId', 'chatJid'],
          },
        },
        {
          name: 'send_message',
          description: 'Send a text message to a contact or group',
          inputSchema: {
            type: 'object',
            properties: {
              recipient: { type: 'string', description: 'Phone number or JID' },
              message: { type: 'string', description: 'Message text' },
            },
            required: ['recipient', 'message'],
          },
        },
        {
          name: 'send_file',
          description: 'Send a file (image, video, document) to a recipient',
          inputSchema: {
            type: 'object',
            properties: {
              recipient: { type: 'string', description: 'Phone number or JID' },
              mediaPath: { type: 'string', description: 'File path' },
              caption: { type: 'string', description: 'Optional caption' },
            },
            required: ['recipient', 'mediaPath'],
          },
        },
        {
          name: 'send_audio_message',
          description: 'Send an audio file as a voice message',
          inputSchema: {
            type: 'object',
            properties: {
              recipient: { type: 'string', description: 'Phone number or JID' },
              mediaPath: { type: 'string', description: 'Audio file path' },
            },
            required: ['recipient', 'mediaPath'],
          },
        },
        {
          name: 'download_media',
          description: 'Download media from a message',
          inputSchema: {
            type: 'object',
            properties: {
              messageId: { type: 'string', description: 'Message ID' },
              chatJid: { type: 'string', description: 'Chat JID' },
            },
            required: ['messageId', 'chatJid'],
          },
        },
        {
          name: 'get_auth_status',
          description: 'Get WhatsApp authentication status',
          inputSchema: {
            type: 'object',
            properties: {},
          },
        },
      ],
    }));

    // Handle tool calls
    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        let result: MCPToolResponse;

        switch (name) {
          case 'search_contacts':
            const contactList = await this.contactService.searchContact(args.query as string);
            result = { success: true, data: contactList };
            break;

          case 'list_messages':
            const messageList = await this.messageService.listMessage(args as any);
            result = { success: true, data: messageList };
            break;

          case 'list_chats':
            const chatList = await this.chatService.listChat(args as any);
            result = { success: true, data: chatList };
            break;

          case 'get_chat':
            const chat = await this.chatService.getChat(args.chatJid as string);
            result = { success: true, data: chat };
            break;

          case 'get_direct_chat_by_contact':
            const directChat = await this.chatService.getDirectChatByContact(
              args.senderPhoneNumber as string
            );
            result = { success: true, data: directChat };
            break;

          case 'get_contact_chats':
            const contactChatList = await this.chatService.getContactChatList(
              args.jid as string,
              args.limit as number,
              args.page as number
            );
            result = { success: true, data: contactChatList };
            break;

          case 'get_last_interaction':
            const lastInteraction = await this.chatService.getLastInteraction(args.jid as string);
            result = { success: true, data: lastInteraction };
            break;

          case 'get_message_context':
            const context = await this.messageService.getMessageContext(
              args.messageId as string,
              args.chatJid as string,
              args.before as number,
              args.after as number
            );
            result = { success: true, data: context };
            break;

          case 'send_message':
            const sendResult = await this.messageService.sendMessage(
              args.recipient as string,
              args.message as string
            );
            result = sendResult;
            break;

          case 'send_file':
            const fileResult = await this.messageService.sendFile(
              args.recipient as string,
              args.mediaPath as string,
              args.caption as string | undefined
            );
            result = fileResult;
            break;

          case 'send_audio_message':
            const audioResult = await this.messageService.sendAudio(
              args.recipient as string,
              args.mediaPath as string
            );
            result = audioResult;
            break;

          case 'download_media':
            const filePath = await this.messageService.downloadMedia(
              args.messageId as string,
              args.chatJid as string
            );
            result = {
              success: !!filePath,
              data: filePath ? { filePath } : undefined,
              message: filePath ? 'Media downloaded' : 'Media not found',
            };
            break;

          case 'get_auth_status':
            const authState = this.whatsappClient.getAuthState();
            result = { success: true, data: authState };
            break;

          default:
            result = { success: false, error: `Unknown tool: ${name}` };
        }

        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      } catch (error: any) {
        mcpLogger.error(`Tool execution failed: ${name}`, error);
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify({ success: false, error: error.message }, null, 2),
            },
          ],
          isError: true,
        };
      }
    });
  }

  async start() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    mcpLogger.info('MCP server started with stdio transport');
  }
}
