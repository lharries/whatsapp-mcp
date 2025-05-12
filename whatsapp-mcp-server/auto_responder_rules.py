from typing import List, Dict, Any, Optional, Pattern
import re
import json
import os.path

class ResponseRule:
    def __init__(self, 
                 name: str,
                 pattern: str, 
                 response: str,
                 pattern_type: str = "contains",
                 is_regex: bool = False,
                 enabled: bool = True,
                 sender_filter: Optional[str] = None,
                 chat_filter: Optional[str] = None):
        """
        Define a rule for automatic responses.
        
        Args:
            name: Name of the rule for identification
            pattern: Pattern to match in the message
            response: Response template to send
            pattern_type: Type of pattern matching ("text", "exact", "contains")
            is_regex: Whether pattern is a regular expression
            enabled: Whether this rule is active
            sender_filter: Optional filter to only apply to specific senders
            chat_filter: Optional filter to only apply to specific chats
        """
        self.name = name
        self.pattern = pattern
        self.response = response
        self.pattern_type = pattern_type
        self.is_regex = is_regex
        self.enabled = enabled
        self.sender_filter = sender_filter
        self.chat_filter = chat_filter
        
        # Compile regex if needed
        self._regex = None
        if is_regex:
            self._regex = re.compile(pattern, re.IGNORECASE)
            
    def matches(self, message_text: str, sender: str = None, chat_jid: str = None) -> bool:
        """Check if a message matches this rule."""
        if not self.enabled:
            return False
            
        # Check sender filter if specified
        if self.sender_filter and sender and self.sender_filter != sender:
            return False
            
        # Check chat filter if specified
        if self.chat_filter and chat_jid and self.chat_filter != chat_jid:
            return False
            
        # Check message content
        if self.is_regex and self._regex:
            return bool(self._regex.search(message_text))
        
        if self.pattern_type == "exact":
            return message_text.lower() == self.pattern.lower()
        
        if self.pattern_type == "contains":
            return self.pattern.lower() in message_text.lower()
            
        return False
        
    def format_response(self, message_text: str, sender: str = None) -> str:
        """Format the response template with message details."""
        return self.response.format(
            message=message_text,
            sender=sender or "Unknown"
        )

class RuleManager:
    def __init__(self, rules_file: str = "auto_responder_rules.json"):
        self.rules_file = rules_file
        self.rules: List[ResponseRule] = []
        self.load_rules()
        
    def load_rules(self) -> None:
        """Load rules from the rules file."""
        if not os.path.exists(self.rules_file):
            # Create default rules file if it doesn't exist
            self.rules = [
                ResponseRule(
                    name="Hello Response",
                    pattern="hello",
                    response="Hello! This is an automated response.",
                    pattern_type="contains"
                ),
                ResponseRule(
                    name="Help Response",
                    pattern="help",
                    response="This is an automatic response. For assistance, please contact the admin.",
                    pattern_type="contains"
                )
            ]
            self.save_rules()
            return
            
        try:
            with open(self.rules_file, 'r') as f:
                rules_data = json.load(f)
                
            self.rules = []
            for rule_data in rules_data:
                self.rules.append(ResponseRule(
                    name=rule_data.get("name", "Unnamed Rule"),
                    pattern=rule_data.get("pattern", ""),
                    response=rule_data.get("response", ""),
                    pattern_type=rule_data.get("pattern_type", "contains"),
                    is_regex=rule_data.get("is_regex", False),
                    enabled=rule_data.get("enabled", True),
                    sender_filter=rule_data.get("sender_filter"),
                    chat_filter=rule_data.get("chat_filter")
                ))
        except Exception as e:
            print(f"Error loading rules: {e}")
            self.rules = []
            
    def save_rules(self) -> None:
        """Save rules to the rules file."""
        rules_data = []
        for rule in self.rules:
            rules_data.append({
                "name": rule.name,
                "pattern": rule.pattern,
                "response": rule.response,
                "pattern_type": rule.pattern_type,
                "is_regex": rule.is_regex,
                "enabled": rule.enabled,
                "sender_filter": rule.sender_filter,
                "chat_filter": rule.chat_filter
            })
            
        try:
            with open(self.rules_file, 'w') as f:
                json.dump(rules_data, f, indent=2)
        except Exception as e:
            print(f"Error saving rules: {e}")
            
    def check_message(self, message_text: str, sender: str = None, chat_jid: str = None) -> Optional[str]:
        """
        Check if a message matches any rule and return the response if it does.
        
        Returns None if no rule matches.
        """
        for rule in self.rules:
            if rule.matches(message_text, sender, chat_jid):
                return rule.format_response(message_text, sender)
                
        return None
