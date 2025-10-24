/**
 * Pino logger configuration
 */

import pino from 'pino';
import { env } from '../config/environment.js';

const pinoConfig: pino.LoggerOptions = {
  level: env.logLevel,
  ...(env.logPretty && env.isDevelopment
    ? {
        transport: {
          target: 'pino-pretty',
          options: {
            colorize: true,
            translateTime: 'HH:MM:ss Z',
            ignore: 'pid,hostname',
          },
        },
      }
    : {}),
  ...(env.logFile
    ? {
        transport: {
          targets: [
            {
              target: 'pino-pretty',
              options: {
                colorize: true,
                translateTime: 'HH:MM:ss Z',
                ignore: 'pid,hostname',
              },
              level: env.logLevel,
            },
            {
              target: 'pino/file',
              options: {
                destination: env.logFile,
              },
              level: env.logLevel,
            },
          ],
        },
      }
    : {}),
};

export const logger = pino(pinoConfig);

// Create child loggers for different modules
export const createChildLogger = (module: string) => {
  return logger.child({ module });
};

// Export commonly used child loggers
export const whatsappLogger = createChildLogger('whatsapp');
export const mcpLogger = createChildLogger('mcp');
export const apiLogger = createChildLogger('api');
export const storeLogger = createChildLogger('store');
