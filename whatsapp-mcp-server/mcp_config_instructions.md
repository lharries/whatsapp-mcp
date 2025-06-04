# WhatsApp MCP Safety Configuration

## Claude Desktop Configuration

Add these instructions to your Claude Desktop MCP configuration to enforce message sending safety:

### Option 1: Claude Desktop Config with Instructions

Update your `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "whatsapp": {
      "command": "/Users/dave/.local/bin/uv",
      "args": [
        "--directory",
        "/Users/dave/CODE/whatsapp-mcp/whatsapp-mcp-server", 
        "run",
        "main.py"
      ],
      "instructions": "CRITICAL RULE: Always require explicit user permission before sending any WhatsApp message.\n\nThe assistant MUST ALWAYS:\n1. Show the exact message to be sent\n2. Clearly state the recipient (name and phone number/JID)\n3. Ask \"Do I have your permission to send this message?\"\n4. Wait for explicit confirmation (e.g., \"yes\", \"send it\", \"approved\")\n5. Only proceed after receiving clear permission\n\nNEVER:\n- Send messages without explicit permission\n- Assume permission based on context\n- Send follow-up messages without asking again\n- Proceed if the user's response is ambiguous\n\nExample interaction:\nAssistant: \"I'd like to send this message:\n[Message content]\nTo: [Recipient name] ([phone number])\nDo I have your permission to send this message?\"\nUser: \"Yes\" \n[Only then proceed with sending]"
    }
  }
}
```

### Option 2: System Prompt Integration

If your MCP setup doesn't support the `instructions` field, add this to your system prompt or conversation:

```
WHATSAPP SAFETY RULES:

CRITICAL RULE: Always require explicit user permission before sending any WhatsApp message.

The assistant MUST ALWAYS:
1. Use preview_message first to show the exact message to be sent
2. Clearly state the recipient (name and phone number/JID)
3. Ask "Do I have your permission to send this message?"
4. Wait for explicit confirmation (e.g., "yes", "send it", "approved")
5. Only use confirm_and_send_message after receiving clear permission

NEVER:
- Use send_message directly without preview and confirmation
- Send messages without explicit permission
- Assume permission based on context
- Send follow-up messages without asking again
- Proceed if the user's response is ambiguous

WORKFLOW:
1. User requests to send a message
2. Use preview_message(recipient, message)
3. Show preview details to user
4. Ask: "Do I have your permission to send this message?"
5. Wait for explicit "yes" or equivalent
6. Use confirm_and_send_message(preview_id)
```

## Built-in Safety Features

The WhatsApp MCP server now includes these safety features:

### Safety Tools
- `preview_message(recipient, message)` - Preview before sending
- `confirm_and_send_message(preview_id)` - Send after confirmation
- `preview_file(recipient, media_path)` - Preview file before sending
- `confirm_and_send_file(preview_id)` - Send file after confirmation
- `confirm_and_send_audio(preview_id)` - Send audio after confirmation

### Management Tools
- `get_safety_status()` - Check current safety configuration
- `list_pending_messages()` - See all pending operations
- `cancel_pending_message(preview_id)` - Cancel a pending operation
- `clear_all_pending()` - Clear all pending operations
- `toggle_safety_mode()` - Enable/disable safety (not recommended)

### Safety Behavior
- **Default**: All sending requires preview + confirmation
- **Preview**: Shows recipient info, message content, and compatibility
- **Expiration**: Pending operations expire after 5 minutes
- **One-time use**: Each preview_id can only be used once

## Example Safe Workflow

```
User: "Send a message to John saying 'Hi there!'"Assistant: I'll execute preview_message("john", "Hi there!")

Result shows:
- Preview ID: abc12345
- Recipient: John Smith (6598876543)
- Message: "Hi there!"
- Group Type: personal chat (compatible) 