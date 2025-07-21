import { MessageStore } from './database';
import * as fs from 'fs';

async function testMultiUserFunctionality() {
  console.log('Testing Multi-User MessageStore implementation...');

  if (fs.existsSync('store/messages.db')) {
    fs.unlinkSync('store/messages.db');
  }

  let store: MessageStore;
  
  try {
    store = await MessageStore.initialize();
    console.log('✓ MessageStore initialized with migrations');
  } catch (error) {
    console.error('✗ Failed to initialize MessageStore:', error);
    return;
  }

  try {
    const user1Id = store.createUser('alice', 'alice@example.com', 'hashedpassword1', '+1234567890');
    const user2Id = store.createUser('bob', 'bob@example.com', 'hashedpassword2', '+0987654321');
    console.log(`✓ Created users: ${user1Id}, ${user2Id}`);

    const alice = store.getUserById(user1Id);
    const bob = store.getUserByUsername('bob');
    
    if (!alice || !bob) {
      throw new Error('Failed to retrieve created users');
    }
    console.log('✓ User retrieval working');

    const testTimestamp = new Date();
    store.storeChat('alice-chat@s.whatsapp.net', 'Alice Chat', testTimestamp, user1Id);
    store.storeChat('bob-chat@s.whatsapp.net', 'Bob Chat', testTimestamp, user2Id);
    console.log('✓ User-specific chats stored');

    store.storeMessage(
      'msg-alice-1', 'alice-chat@s.whatsapp.net', 'alice-sender',
      'Hello from Alice!', testTimestamp, false, '', '', '',
      null, null, null, 0, user1Id
    );

    store.storeMessage(
      'msg-bob-1', 'bob-chat@s.whatsapp.net', 'bob-sender',
      'Hello from Bob!', testTimestamp, false, '', '', '',
      null, null, null, 0, user2Id
    );
    console.log('✓ User-specific messages stored');

    const aliceChats = store.getChats(user1Id);
    const aliceMessages = store.getMessages('alice-chat@s.whatsapp.net', 10, user1Id);
    
    if (Object.keys(aliceChats).length !== 1 || !('alice-chat@s.whatsapp.net' in aliceChats)) {
      throw new Error('Alice should only see her own chat');
    }
    
    if (aliceMessages.length !== 1 || aliceMessages[0].content !== 'Hello from Alice!') {
      throw new Error('Alice should only see her own messages');
    }
    console.log('✓ User data isolation working');

    const bobChats = store.getChats(user2Id);
    const bobMessages = store.getMessages('bob-chat@s.whatsapp.net', 10, user2Id);
    
    if (Object.keys(bobChats).length !== 1 || !('bob-chat@s.whatsapp.net' in bobChats)) {
      throw new Error('Bob should only see his own chat');
    }
    
    if (bobMessages.length !== 1 || bobMessages[0].content !== 'Hello from Bob!') {
      throw new Error('Bob should only see his own messages');
    }
    console.log('✓ Bob data isolation working');

    const aliceCannotSeeBobMessages = store.getMessages('bob-chat@s.whatsapp.net', 10, user1Id);
    if (aliceCannotSeeBobMessages.length !== 0) {
      throw new Error('Alice should not be able to see Bob\'s messages');
    }
    console.log('✓ Cross-user access prevention working');

    store.storeChatLegacy('legacy-chat@s.whatsapp.net', 'Legacy Chat', testTimestamp);
    store.storeMessageLegacy(
      'legacy-msg-1', 'legacy-chat@s.whatsapp.net', 'legacy-sender',
      'Legacy message', testTimestamp, false, '', '', '',
      null, null, null, 0
    );
    
    const legacyChats = store.getChatsLegacy();
    const legacyMessages = store.getMessagesLegacy('legacy-chat@s.whatsapp.net', 10);
    
    if (!('legacy-chat@s.whatsapp.net' in legacyChats)) {
      throw new Error('Legacy chat storage failed');
    }
    
    if (legacyMessages.length !== 1 || legacyMessages[0].content !== 'Legacy message') {
      throw new Error('Legacy message storage failed');
    }
    console.log('✓ Backward compatibility working');

    console.log('\n🎉 All multi-user tests passed! Database schema migration successful.');
    
  } catch (error) {
    console.error('✗ Multi-user test failed:', error);
  } finally {
    store.close();
    console.log('✓ Database connection closed');
  }
}

testMultiUserFunctionality().catch(console.error);
