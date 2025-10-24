/**
 * Contact types and interfaces
 */

export interface Contact {
  jid: string;
  name?: string;
  phoneNumber: string;
  pushName?: string;
  isBlocked?: boolean;
  profilePictureUrl?: string;
}

export interface ContactSearchResult {
  contactList: Contact[];
  total: number;
}
