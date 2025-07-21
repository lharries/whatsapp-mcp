import { MessageStore } from './database';

async function testMessageStore() {
  console.log('Testing MessageStore TypeScript implementation...');

  let store: MessageStore;
  
  try {
    store = await MessageStore.initialize();
    console.log('✓ MessageStore initialized successfully');
  } catch (error) {
    console.error('✗ Failed to initialize MessageStore:', error);
    return;
  }

  try {
    const testChatJID = '1234567890@s.whatsapp.net';
    const testChatName = 'Test Chat';
    const testTimestamp = new Date();

    store.storeChat(testChatJID, testChatName, testTimestamp);
    console.log('✓ Chat stored successfully');

    const testMessageId = 'test-message-1';
    const testSender = '1234567890';
    const testContent = 'Hello, this is a test message!';
    
    store.storeMessage(
      testMessageId,
      testChatJID,
      testSender,
      testContent,
      testTimestamp,
      false,
      '',
      '',
      '',
      null,
      null,
      null,
      0
    );
    console.log('✓ Text message stored successfully');

    const testMediaMessageId = 'test-media-message-1';
    const testMediaContent = 'Check out this image!';
    const testMediaType = 'image';
    const testFilename = 'test-image.jpg';
    
    store.storeMessage(
      testMediaMessageId,
      testChatJID,
      testSender,
      testMediaContent,
      new Date(testTimestamp.getTime() + 1000),
      false,
      testMediaType,
      testFilename,
      'https://example.com/image.jpg',
      Buffer.from('test-media-key'),
      Buffer.from('test-sha256'),
      Buffer.from('test-enc-sha256'),
      12345
    );
    console.log('✓ Media message stored successfully');

    const messages = store.getMessages(testChatJID, 10);
    console.log(`✓ Retrieved ${messages.length} messages`);
    
    if (messages.length !== 2) {
      throw new Error(`Expected 2 messages, got ${messages.length}`);
    }

    const latestMessage = messages[0];
    if (latestMessage.content !== testMediaContent) {
      throw new Error(`Expected latest message content "${testMediaContent}", got "${latestMessage.content}"`);
    }
    if (latestMessage.mediaType !== testMediaType) {
      throw new Error(`Expected media type "${testMediaType}", got "${latestMessage.mediaType}"`);
    }
    console.log('✓ Message content and media type verified');

    const chats = store.getChats();
    console.log(`✓ Retrieved ${Object.keys(chats).length} chats`);
    
    if (!(testChatJID in chats)) {
      throw new Error(`Expected chat ${testChatJID} not found in chats`);
    }
    console.log('✓ Chat retrieval verified');

    const emptyMessageId = 'empty-message';
    store.storeMessage(
      emptyMessageId,
      testChatJID,
      testSender,
      '',
      new Date(),
      false,
      '',
      '',
      '',
      null,
      null,
      null,
      0
    );
    
    const messagesAfterEmpty = store.getMessages(testChatJID, 10);
    if (messagesAfterEmpty.length === 2) {
      console.log('✓ Empty message correctly ignored (not stored)');
    } else {
      throw new Error(`Expected 2 messages after empty message attempt, got ${messagesAfterEmpty.length}`);
    }

    console.log('\n🎉 All tests passed! MessageStore TypeScript implementation is working correctly.');
    
  } catch (error) {
    console.error('✗ Test failed:', error);
  } finally {
    store.close();
    console.log('✓ Database connection closed');
  }
}

testMessageStore().catch(console.error);
