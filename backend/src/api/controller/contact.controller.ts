/**
 * Contact controller
 */

import type { Request, Response, NextFunction } from 'express';
import type { ApiResponse, Contact } from '@whatsapp-mcp/common';
import { HTTP_STATUS_CODE_MAP } from '@whatsapp-mcp/common';
import type { ContactService } from '../service/contact.service.js';

export class ContactController {
  constructor(private contactService: ContactService) {}

  searchContact = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const { query } = req.query;
      const contactList = await this.contactService.searchContact(query as string);

      const response: ApiResponse<Contact[]> = {
        success: true,
        data: contactList,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };

  listContact = async (req: Request, res: Response, next: NextFunction) => {
    try {
      const contactList = await this.contactService.listContact();

      const response: ApiResponse<Contact[]> = {
        success: true,
        data: contactList,
        timestamp: new Date(),
      };

      res.status(HTTP_STATUS_CODE_MAP.OK).json(response);
    } catch (error) {
      next(error);
    }
  };
}
