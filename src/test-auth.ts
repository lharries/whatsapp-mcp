import { MessageStore } from './database';
import { AuthService } from './auth/AuthService';
import * as fs from 'fs';

async function testAuthentication() {
  console.log('Testing Authentication System...');

  if (fs.existsSync('store/messages.db')) {
    fs.unlinkSync('store/messages.db');
  }

  let store: MessageStore;
  let authService: AuthService;
  
  try {
    store = await MessageStore.initialize();
    authService = new AuthService(store, 'test-secret-key');
    console.log('✓ Authentication system initialized');
  } catch (error) {
    console.error('✗ Failed to initialize:', error);
    return;
  }

  try {
    const registerRequest = {
      username: 'testuser',
      email: 'test@example.com',
      password: 'securepassword123',
      phone_number: '+1234567890'
    };

    const authResponse = await authService.registerUser(registerRequest);
    console.log('✓ User registration successful');
    console.log(`  User ID: ${authResponse.user.id}`);
    console.log(`  Session ID: ${authResponse.session_id}`);

    const validation = authService.validateToken(authResponse.token);
    if (!validation || validation.userId !== authResponse.user.id) {
      throw new Error('Token validation failed');
    }
    console.log('✓ JWT token validation working');

    const loginRequest = {
      username: 'testuser',
      password: 'securepassword123'
    };

    const loginResponse = await authService.loginUser(loginRequest);
    console.log('✓ User login successful');

    try {
      await authService.registerUser(registerRequest);
      throw new Error('Should have failed with duplicate username');
    } catch (error) {
      if ((error as Error).message.includes('already exists')) {
        console.log('✓ Duplicate registration prevention working');
      } else {
        throw error;
      }
    }

    try {
      await authService.loginUser({
        username: 'testuser',
        password: 'wrongpassword'
      });
      throw new Error('Should have failed with wrong password');
    } catch (error) {
      if ((error as Error).message.includes('Invalid username or password')) {
        console.log('✓ Invalid login prevention working');
      } else {
        throw error;
      }
    }

    console.log('\n🎉 All authentication tests passed!');
    
  } catch (error) {
    console.error('✗ Authentication test failed:', error);
  } finally {
    store.close();
    console.log('✓ Database connection closed');
  }
}

testAuthentication().catch(console.error);
