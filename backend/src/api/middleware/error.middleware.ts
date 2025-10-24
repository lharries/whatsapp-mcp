/**
 * Error handling middleware
 */

import type { Request, Response, NextFunction } from 'express';
import { ZodError } from 'zod';
import type { ApiResponse } from '@whatsapp-mcp/common';
import { API_ERROR_CODE_MAP, HTTP_STATUS_CODE_MAP } from '@whatsapp-mcp/common';
import { apiLogger } from '../util/logger.js';

export class ApiError extends Error {
  constructor(
    public statusCode: number,
    public code: string,
    message: string,
    public details?: Record<string, any>
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function errorHandler(
  err: Error,
  req: Request,
  res: Response,
  next: NextFunction
) {
  apiLogger.error('API Error:', err);

  // Handle Zod validation errors
  if (err instanceof ZodError) {
    const response: ApiResponse = {
      success: false,
      error: {
        code: API_ERROR_CODE_MAP.VALIDATION_ERROR,
        message: 'Validation failed',
        details: err.errors,
      },
      timestamp: new Date(),
    };
    return res.status(HTTP_STATUS_CODE_MAP.BAD_REQUEST).json(response);
  }

  // Handle custom API errors
  if (err instanceof ApiError) {
    const response: ApiResponse = {
      success: false,
      error: {
        code: err.code,
        message: err.message,
        details: err.details,
      },
      timestamp: new Date(),
    };
    return res.status(err.statusCode).json(response);
  }

  // Handle unknown errors
  const response: ApiResponse = {
    success: false,
    error: {
      code: API_ERROR_CODE_MAP.INTERNAL_ERROR,
      message: err.message || 'Internal server error',
    },
    timestamp: new Date(),
  };
  res.status(HTTP_STATUS_CODE_MAP.INTERNAL_SERVER_ERROR).json(response);
}

export function notFoundHandler(req: Request, res: Response) {
  const response: ApiResponse = {
    success: false,
    error: {
      code: API_ERROR_CODE_MAP.NOT_FOUND,
      message: `Route ${req.method} ${req.path} not found`,
    },
    timestamp: new Date(),
  };
  res.status(HTTP_STATUS_CODE_MAP.NOT_FOUND).json(response);
}
