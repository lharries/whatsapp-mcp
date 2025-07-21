import { WhatsAppMCPServer } from './app';

async function main() {
  const server = new WhatsAppMCPServer();
  
  try {
    await server.initialize();
    
    const port = parseInt(process.env.PORT || '3000');
    server.listen(port);
    
    console.log(`🚀 WhatsApp MCP Server started on port ${port}`);
    console.log(`📱 Multi-user WhatsApp authentication ready`);
    
    process.on('SIGINT', async () => {
      console.log('\n🛑 Shutting down server...');
      await server.shutdown();
      process.exit(0);
    });
    
  } catch (error) {
    console.error('❌ Failed to start server:', error);
    process.exit(1);
  }
}

main().catch(console.error);
