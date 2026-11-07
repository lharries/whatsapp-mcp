#!/usr/bin/env python3
"""Example agent-side webhook consumer.

Receives the bridge's inbound-message webhook and turns it into a decision loop:
"Tysen said X — here's a draft, approve?" It prints the event and, if the bridge
has an owner JID, asks for approval through the MCP tool (or the bridge REST API).

Run:  python3 examples/webhook_agent.py            # listens on 127.0.0.1:8090
Point the bridge at it:  WEBHOOK_URL=http://127.0.0.1:8090/wa

This is a starting point — wire `handle_message` into your agent.
"""
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
PORT = int(os.environ.get("AGENT_PORT", "8090"))


def verify(body: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def handle_message(evt: dict) -> None:
    """Where your agent goes. `evt` is the bridge's WebhookPayload."""
    who = evt.get("chat_name") or evt.get("sender")
    text = evt.get("text") or f"[{evt.get('media_type', 'media')}]"
    print(f"\n[{evt.get('account')}] {who} ({evt['chat_jid']}): {text}")
    # 1. decide a draft reply (your model here)
    # 2. ask the owner to approve it (request_reply_approval / bridge /api/send to WA_OWNER_JID)
    # 3. send it once approved (send_message), then the chat leaves the outbox


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if not verify(body, self.headers.get("X-WA-Signature", "")):
            self.send_response(401)
            self.end_headers()
            return
        try:
            handle_message(json.loads(body))
        except Exception as e:  # never fail the bridge's retry
            print(f"handler error: {e}")
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # quiet
        pass


if __name__ == "__main__":
    print(f"listening on 127.0.0.1:{PORT} (POST /wa)")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
