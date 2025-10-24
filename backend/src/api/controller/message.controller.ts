/**
 * Message controller
 */

import type { Request, Response, NextFunction } from 'express';
import type { ApiResponse, Message, MessageFilter, MessageContext } from '@whatsapp-mcp/common';
import { HTTP_STATUS_CODE_MAP, API_ERROR_CODE_MAP } from '@whatsapp-mcp/common';
import type { MessageService } from '../service/message.service.js';
import { ApiError } from '../middleware/error.middleware.js';

export class MessageController {
  constructor(private messageService: MessageService) {}

  listMessage = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const filter: MessageFilter = {
        chatJid: req.query.chatJid as string | undefined,
        query: req.query.query as string | undefined,
        senderPhoneNumber: req.query.senderPhoneNumber as string | undefined,
        after: req.query.after as string | undefined,
        before: req.query.before as string | undefined,
        limit: req.query.limit ? parseInt(req.query.limit as string) : undefined,
        page: req.query.page ? parseInt(req.query.page as string) : undefined,
      };

      const messageList = await this.messageService.listMessage(filter);

      const response: ApiResponse<Message[]> = {
        success: true,
        data: messageList,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  getMessageContext = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { messageId, chatJid } = req.params;
      const before = req.query.before ? parseInt(req.query.before as string) : 5;
      const after = req.query.after ? parseInt(req.query.after as string) : 5;

      const context = await this.messageService.getMessageContext(
        messageId,
        chatJid,
        before,
        after
      );

      if (!context) {
        throw new ApiError(
          HTTP_STATUS_CODE_MAP.NOT_FOUND,
          API_ERROR_CODE_MAP.NOT_FOUND,
          `Message ${messageId} not found in chat ${chatJid}`
        );
      }

      const response: ApiResponse<MessageContext> = {
        success: true,
        data: context,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  sendMessage = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { recipient, message } = req.body;
      const result = await this.messageService.sendMessage(recipient, message);

      const response: ApiResponse = {
        success: result.success,
        message: result.message,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  sendFile = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { recipient, mediaPath, caption } = req.body;
      const result = await this.messageService.sendFile(recipient, mediaPath, caption);

      const response: ApiResponse = {
        success: result.success,
        message: result.message,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  sendAudio = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { recipient, mediaPath } = req.body;
      const result = await this.messageService.sendAudio(recipient, mediaPath);

      const response: ApiResponse = {
        success: result.success,
        message: result.message,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  downloadMedia = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { messageId, chatJid } = req.params;
      const filePath = await this.messageService.downloadMedia(messageId, chatJid);

      if (!filePath) {
        throw new ApiError(
          HTTP_STATUS_CODE_MAP.NOT_FOUND,
          API_ERROR_CODE_MAP.NOT_FOUND,
          'Media not found or already downloaded'
        );
      }

      const response: ApiResponse<{ filePath: string }> = {
        success: true,
        data: { filePath },
        message: 'Media downloaded successfully',
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };
}
