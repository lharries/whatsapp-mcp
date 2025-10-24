/**
 * Media handler for WhatsApp media processing
 */

import fs from 'fs/promises';
import path from 'path';
import { downloadMediaMessage, proto } from '@whiskeysockets/baileys';
import sharp from 'sharp';
import ffmpeg from 'fluent-ffmpeg';
import { v4 as uuidv4 } from 'uuid';
import type { MediaMetadata, MediaType } from '@whatsapp-mcp/common';
import { env } from '../config/environment.js';
import { whatsappLogger } from '../util/logger.js';
import { sanitizeFilename } from '@whatsapp-mcp/common';

export class MediaHandler {
  private mediaPath: string;

  constructor() {
    this.mediaPath = path.resolve(env.whatsappMediaPath);
  }

  async initialize(): Promise<void> {
    // Create media directory if it doesn't exist
    await fs.mkdir(this.mediaPath, { recursive: true });
    whatsappLogger.info(`Media directory initialized at: ${this.mediaPath}`);
  }

  async downloadMedia(message: proto.IWebMessageInfo): Promise<Buffer | null> {
    try {
      const buffer = await downloadMediaMessage(
        message,
        'buffer',
        {},
        {
          logger: whatsappLogger as any,
          reuploadRequest: () => Promise.resolve({} as any),
        }
      );

      return buffer as Buffer;
    } catch (error) {
      whatsappLogger.error('Failed to download media', error);
      return null;
    }
  }

  async saveMedia(
    buffer: Buffer,
    messageId: string,
    mediaType: MediaType,
    filename?: string
  ): Promise<string> {
    const sanitizedFilename = filename ? sanitizeFilename(filename) : `${uuidv4()}.bin`;
    const filePath = path.join(this.mediaPath, sanitizedFilename);

    await fs.writeFile(filePath, buffer);
    whatsappLogger.info(`Media saved: ${filePath}`);

    return filePath;
  }

  async processImage(buffer: Buffer): Promise<Buffer> {
    try {
      const image = sharp(buffer);
      const metadata = await image.metadata();

      // Resize if too large
      if (metadata.width && metadata.width > env.maxImageWidth) {
        return await image
          .resize(env.maxImageWidth, null, { withoutEnlargement: true })
          .toBuffer();
      }

      return buffer;
    } catch (error) {
      whatsappLogger.error('Failed to process image', error);
      return buffer;
    }
  }

  async convertAudioToOpus(inputPath: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const outputPath = `${inputPath}.ogg`;

      ffmpeg(inputPath)
        .audioCodec('libopus')
        .audioBitrate(env.audioBitrate)
        .audioFrequency(env.audioSampleRate)
        .format('ogg')
        .on('end', () => {
          whatsappLogger.info(`Audio converted to Opus: ${outputPath}`);
          resolve(outputPath);
        })
        .on('error', (error) => {
          whatsappLogger.error('Failed to convert audio', error);
          reject(error);
        })
        .save(outputPath);
    });
  }

  async extractMediaInfo(message: proto.IWebMessageInfo): Promise<Partial<MediaMetadata> | null> {
    const messageContent = message.message;
    if (!messageContent) return null;

    const imageMessage = messageContent.imageMessage;
    const videoMessage = messageContent.videoMessage;
    const audioMessage = messageContent.audioMessage;
    const documentMessage = messageContent.documentMessage;
    const stickerMessage = messageContent.stickerMessage;

    if (imageMessage) {
      return {
        mediaType: 'image',
        filename: imageMessage.fileName,
        url: imageMessage.url,
        mimetype: imageMessage.mimetype,
        width: imageMessage.width || undefined,
        height: imageMessage.height || undefined,
        fileLength: Number(imageMessage.fileLength) || undefined,
        caption: imageMessage.caption,
      };
    }

    if (videoMessage) {
      return {
        mediaType: 'video',
        filename: videoMessage.fileName,
        url: videoMessage.url,
        mimetype: videoMessage.mimetype,
        width: videoMessage.width || undefined,
        height: videoMessage.height || undefined,
        duration: videoMessage.seconds || undefined,
        fileLength: Number(videoMessage.fileLength) || undefined,
        caption: videoMessage.caption,
      };
    }

    if (audioMessage) {
      const isVoice = audioMessage.ptt || false;
      return {
        mediaType: isVoice ? 'voice' : 'audio',
        filename: audioMessage.fileName,
        url: audioMessage.url,
        mimetype: audioMessage.mimetype,
        duration: audioMessage.seconds || undefined,
        fileLength: Number(audioMessage.fileLength) || undefined,
      };
    }

    if (documentMessage) {
      return {
        mediaType: 'document',
        filename: documentMessage.fileName,
        url: documentMessage.url,
        mimetype: documentMessage.mimetype,
        pageCount: documentMessage.pageCount || undefined,
        fileLength: Number(documentMessage.fileLength) || undefined,
        caption: documentMessage.caption,
      };
    }

    if (stickerMessage) {
      return {
        mediaType: 'sticker',
        url: stickerMessage.url,
        mimetype: stickerMessage.mimetype,
        width: stickerMessage.width || undefined,
        height: stickerMessage.height || undefined,
        fileLength: Number(stickerMessage.fileLength) || undefined,
      };
    }

    return null;
  }

  getMimeType(filePath: string): string {
    const ext = path.extname(filePath).toLowerCase();
    const mimeTypeMap: Record<string, string> = {
      '.jpg': 'image/jpeg',
      '.jpeg': 'image/jpeg',
      '.png': 'image/png',
      '.gif': 'image/gif',
      '.webp': 'image/webp',
      '.mp4': 'video/mp4',
      '.avi': 'video/x-msvideo',
      '.mov': 'video/quicktime',
      '.mp3': 'audio/mpeg',
      '.wav': 'audio/wav',
      '.ogg': 'audio/ogg',
      '.pdf': 'application/pdf',
      '.doc': 'application/msword',
      '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      '.xls': 'application/vnd.ms-excel',
      '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    };

    return mimeTypeMap[ext] || 'application/octet-stream';
  }

  async readMediaFile(filePath: string): Promise<Buffer> {
    return await fs.readFile(filePath);
  }
}
