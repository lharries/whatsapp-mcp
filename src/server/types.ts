import { Request } from 'express';

declare global {
  namespace Express {
    interface Request {
      user?: {
        userId: number;
        sessionId: string;
      };
    }
  }
}

export {};
