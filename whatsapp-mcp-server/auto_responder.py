import time
import datetime
import threading
from typing import List, Dict, Any, Optional
import logging

from whatsapp import list_messages, send_message
from auto_responder_rules import RuleManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("auto_responder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("auto_responder")

class AutoResponder:
    def __init__(self, check_interval: int = 60, rules_file: str = "auto_responder_rules.json"):
        """
        Initialize the auto responder service.
        
        Args:
            check_interval: How often to check for new messages (in seconds)
            rules_file: Path to the rules configuration file
        """
        self.check_interval = check_interval
        self.rule_manager = RuleManager(rules_file)
        self.last_check_time = datetime.datetime.now().isoformat()
        self.running = False
        self.thread = None
        self.processed_message_ids = set()
        
    def start(self):
        """Start the auto responder service."""
        if self.running:
            logger.warning("Auto responder is already running")
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run_loop)
        self.thread.daemon = True
        self.thread.start()
        logger.info("Auto responder started")
        
    def stop(self):
        """Stop the auto responder service."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)
        logger.info("Auto responder stopped")
        
    def _run_loop(self):
        """Main loop that periodically checks for new messages."""
        while self.running:
            try:
                self._check_and_respond()
            except Exception as e:
                logger.error(f"Error in auto responder: {e}")
                
            # Sleep until next check
            time.sleep(self.check_interval)
            
    def _check_and_respond(self):
        """Check for new messages and respond if rules match."""
        current_time = datetime.datetime.now().isoformat()
        
        try:
            # Get messages after the last check time
            messages = list_messages(
                after=self.last_check_time,
                limit=50,
                include_context=False
            )
            
            logger.info(f"Checking {len(messages)} new messages")
            
            # Process each message
            for message in messages:
                # Skip messages we've already processed
                if message.get("id") in self.processed_message_ids:
                    continue
                    
                # Skip messages from ourselves
                if message.get("is_from_me", False):
                    continue
                
                # Check if message matches any rule
                message_text = message.get("content", "")
                sender = message.get("sender", "")
                chat_jid = message.get("chat_jid", "")
                
                response = self.rule_manager.check_message(message_text, sender, chat_jid)
                
                if response:
                    logger.info(f"Rule matched for message: {message_text}")
                    logger.info(f"Sending response to {chat_jid}: {response}")
                    
                    # Send the response
                    send_result = send_message(chat_jid, response)
                    
                    if send_result and send_result.get("success"):
                        logger.info("Response sent successfully")
                    else:
                        logger.error(f"Failed to send response: {send_result}")
                        
                # Mark message as processed
                self.processed_message_ids.add(message.get("id"))
                
                # Limit the size of the processed messages set
                if len(self.processed_message_ids) > 1000:
                    self.processed_message_ids = set(list(self.processed_message_ids)[-500:])
            
        except Exception as e:
            logger.error(f"Error checking messages: {e}")
            
        finally:
            # Update the last check time
            self.last_check_time = current_time
