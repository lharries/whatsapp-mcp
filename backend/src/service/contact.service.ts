/**
 * Contact service - Business logic for contact operations
 */

import type { Contact } from '@whatsapp-mcp/common';
import { BaseStore } from '../store/base.store.js';

export class ContactService {
  constructor(private store: BaseStore) {}

  async searchContact(query: string): Promise<Contact[]> {
    return await this.store.searchContact(query);
  }

  async getContact(jid: string): Promise<Contact | null> {
    return await this.store.getContact(jid);
  }

  async listContact(): Promise<Contact[]> {
    return await this.store.listContact({
      sortBy: 'name',
      sortOrder: 'asc',
    });
  }
}
