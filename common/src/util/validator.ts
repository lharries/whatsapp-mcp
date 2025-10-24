/**
 * Validation utilities
 */

import { WHATSAPP_JID_REGEX, PHONE_NUMBER_REGEX } from '../constant/index.js';

export function isValidWhatsAppJid(jid: string): boolean {
  return WHATSAPP_JID_REGEX.test(jid);
}

export function isValidPhoneNumber(phoneNumber: string): boolean {
  return PHONE_NUMBER_REGEX.test(phoneNumber);
}

export function normalizePhoneNumber(phoneNumber: string): string {
  // Remove all non-digit characters
  return phoneNumber.replace(/\D/g, '');
}

export function phoneNumberToJid(phoneNumber: string): string {
  const normalized = normalizePhoneNumber(phoneNumber);
  return `${normalized}@s.whatsapp.net`;
}

export function jidToPhoneNumber(jid: string): string | null {
  const match = jid.match(/^(\d+)@/);
  return match ? match[1] : null;
}

export function isGroupJid(jid: string): boolean {
  return jid.endsWith('@g.us');
}

export function isIndividualJid(jid: string): boolean {
  return jid.endsWith('@s.whatsapp.net');
}
