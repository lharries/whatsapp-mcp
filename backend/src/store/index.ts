/**
 * Data store factory
 */

import type { StoreType } from '@whatsapp-mcp/common';
import { BaseStore } from './base.store.js';
import { JsonStore } from './json.store.js';
import { env } from '../config/environment.js';
import { storeLogger } from '../util/logger.js';

export function createStore(type?: StoreType): BaseStore {
  const storeType = type || env.dataStoreType;

  storeLogger.info(`Creating data store of type: ${storeType}`);

  switch (storeType) {
    case 'json':
      return new JsonStore();

    case 'sqlite':
      throw new Error('SQLite store not yet implemented');

    case 'mongodb':
      throw new Error('MongoDB store not yet implemented');

    default:
      throw new Error(`Unknown store type: ${storeType}`);
  }
}

export { BaseStore } from './base.store.js';
export { JsonStore } from './json.store.js';
