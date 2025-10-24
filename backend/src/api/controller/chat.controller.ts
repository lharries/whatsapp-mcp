/**
 * Chat controller
 */

import type { Request, Response, NextFunction } from 'express';
import type { ApiResponse, Chat, ChatFilter } from '@whatsapp-mcp/common';
import { HTTP_STATUS_CODE_MAP, API_ERROR_CODE_MAP } from '@whatsapp-mcp/common';
import type { ChatService } from '../service/chat.service.js';
import { ApiError } from '../middleware/error.middleware.js';

export class ChatController {
  constructor(private chatService: ChatService) {}

  listChat = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const filter: ChatFilter = {
        query: req.query.query as string | undefined,
        limit: req.query.limit ? parseInt(req.query.limit as string) : undefined,
        page: req.query.page ? parseInt(req.query.page as string) : undefined,
        sortBy: req.query.sortBy as 'last_active' | 'name' | undefined,
      };

      const chatList = await this.chatService.listChat(filter);

      const response: ApiResponse<Chat[]> = {
        success: true,
        data: chatList,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  getChat = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { chatJid } = req.params;
      const chat = await this.chatService.getChat(chatJid);

      if (!chat) {
        throw new ApiError(
          HTTP_STATUS_CODE_MAP.NOT_FOUND,
          API_ERROR_CODE_MAP.NOT_FOUND,
          `Chat ${chatJid} not found`
        );
      }

      const response: ApiResponse<Chat> = {
        success: true,
        data: chat,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  getDirectChatByContact = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { phoneNumber } = req.params;
      const chat = await this.chatService.getDirectChatByContact(phoneNumber);

      if (!chat) {
        throw new ApiError(
          HTTP_STATUS_CODE_MAP.NOT_FOUND,
          API_ERROR_CODE_MAP.NOT_FOUND,
          `No direct chat found with ${phoneNumber}`
        );
      }

      const response: ApiResponse<Chat> = {
        success: true,
        data: chat,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  getContactChatList = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { jid } = req.params;
      const limit = req.query.limit ? parseInt(req.query.limit as string) : undefined;
      const page = req.query.page ? parseInt(req.query.page as string) : undefined;

      const chatList = await this.chatService.getContactChatList(jid, limit, page);

      const response: ApiResponse<Chat[]> = {
        success: true,
        data: chatList,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };
}
