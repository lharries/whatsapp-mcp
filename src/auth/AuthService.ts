import bcrypt from 'bcrypt';
import jwt from 'jsonwebtoken';
import { MessageStore } from '../database';
import { User, CreateUserRequest, LoginRequest, AuthResponse } from '../database/types';

export class AuthService {
  private messageStore: MessageStore;
  private jwtSecret: string;

  constructor(messageStore: MessageStore, jwtSecret: string) {
    this.messageStore = messageStore;
    this.jwtSecret = jwtSecret;
  }

  async registerUser(request: CreateUserRequest): Promise<AuthResponse> {
    const existingUser = this.messageStore.getUserByUsername(request.username);
    if (existingUser) {
      throw new Error('Username already exists');
    }

    const existingEmail = this.messageStore.getUserByEmail?.(request.email);
    if (existingEmail) {
      throw new Error('Email already exists');
    }

    const saltRounds = 12;
    const passwordHash = await bcrypt.hash(request.password, saltRounds);

    const userId = this.messageStore.createUser(
      request.username,
      request.email,
      passwordHash,
      request.phone_number
    );

    const sessionId = this.generateSessionId();
    const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000); // 7 days

    this.messageStore.createUserSession(sessionId, userId, expiresAt);

    const user = this.messageStore.getUserById(userId)!;
    const token = this.generateJWT(userId, sessionId);

    return {
      user: this.sanitizeUser(user),
      session_id: sessionId,
      expires_at: expiresAt,
      token
    };
  }

  async loginUser(request: LoginRequest): Promise<AuthResponse> {
    const user = this.messageStore.getUserByUsername(request.username);
    if (!user) {
      throw new Error('Invalid username or password');
    }

    const isValidPassword = await bcrypt.compare(request.password, user.password_hash);
    if (!isValidPassword) {
      throw new Error('Invalid username or password');
    }

    this.messageStore.updateUserLastLogin(user.id);

    const sessionId = this.generateSessionId();
    const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);

    this.messageStore.createUserSession(sessionId, user.id, expiresAt);

    const token = this.generateJWT(user.id, sessionId);

    return {
      user: this.sanitizeUser(user),
      session_id: sessionId,
      expires_at: expiresAt,
      token
    };
  }

  validateToken(token: string): { userId: number; sessionId: string } | null {
    try {
      const decoded = jwt.verify(token, this.jwtSecret) as any;
      const session = this.messageStore.getUserSession(decoded.sessionId);
      
      if (!session || !session.is_active || session.expires_at < new Date()) {
        return null;
      }

      return { userId: decoded.userId, sessionId: decoded.sessionId };
    } catch {
      return null;
    }
  }

  private generateJWT(userId: number, sessionId: string): string {
    return jwt.sign({ userId, sessionId }, this.jwtSecret, { expiresIn: '7d' });
  }

  private generateSessionId(): string {
    return require('crypto').randomBytes(32).toString('hex');
  }

  private sanitizeUser(user: User): Omit<User, 'password_hash'> {
    const { password_hash, ...sanitized } = user;
    return sanitized;
  }
}
