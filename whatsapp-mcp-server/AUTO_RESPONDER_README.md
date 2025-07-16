# WhatsApp MCP Auto-Responder

This feature adds automatic response capabilities to the WhatsApp MCP server. It allows you to define rules that will automatically send responses to incoming messages based on patterns.

## How It Works

The auto-responder system periodically checks for new WhatsApp messages and matches them against a set of predefined rules. When a message matches a rule, the system automatically sends the configured response.

## Features

- Define multiple response rules with different patterns
- Support for exact matches, contains, and regular expressions
- Filter rules by sender or chat
- Enable/disable individual rules
- Automatic JSON-based configuration storage

## Usage

### Starting the Auto-Responder

To start the auto-responder service:

```python
start_auto_responder()
```

This will start a background thread that periodically checks for new messages.

### Stopping the Auto-Responder

To stop the auto-responder service:

```python
stop_auto_responder()
```

### Adding a Rule

To add a new auto-response rule:

```python
add_auto_responder_rule(
    name="Greeting",             # A unique name for identifying the rule
    pattern="hello",            # The pattern to match in incoming messages
    response="Hello there!",    # The response to send when a match is found
    pattern_type="contains",    # Match type: "contains", "exact", or use is_regex=True
    is_regex=False,             # Whether to treat the pattern as a regular expression
    enabled=True,               # Whether the rule is active
    sender_filter=None,         # Optional: only apply to messages from this sender
    chat_filter=None            # Optional: only apply to messages in this chat
)
```

### Listing Rules

To list all configured rules:

```python
list_auto_responder_rules()
```

### Removing a Rule

To remove a rule by its name:

```python
remove_auto_responder_rule("Greeting")
```

## Advanced Usage

### Using Regular Expressions

You can use regular expressions for more complex pattern matching:

```python
add_auto_responder_rule(
    name="Time Request",
    pattern="what(('s| is) the)? time",
    response="It's currently {current_time}.",
    is_regex=True
)
```

### Using Variables in Responses

Response messages can include variables using Python's format syntax:

```python
add_auto_responder_rule(
    name="Reply to Message",
    pattern="repeat",
    response="You said: {message}"
)
```

Available variables:
- `{message}`: The original message text
- `{sender}`: The sender's identifier

### Filtering by Sender or Chat

You can create rules that only apply to specific senders or chats:

```python
add_auto_responder_rule(
    name="Mom Auto-Reply",
    pattern="where are you",
    response="I'm busy right now, will call you later!",
    sender_filter="1234567890@s.whatsapp.net"  # Your mom's WhatsApp JID
)
```

## Configuration

The rules are stored in `auto_responder_rules.json` in the same directory as the server. This file is created automatically with default rules if it doesn't exist.

## Logs

The auto-responder logs are written to `auto_responder.log` in the same directory as the server. This includes information about rule matches, responses sent, and any errors.
