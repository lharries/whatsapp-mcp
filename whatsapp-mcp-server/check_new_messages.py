import websocket
import json
import time

def on_message(ws, message):
    try:
        # Parse the incoming message
        data = json.loads(message)
        print(f"New message received:")
        print(f"Time: {data['Time']}")
        print(f"Sender: {data['Sender']}")
        print(f"Content: {data['Content']}")
        print(f"IsFromMe: {data['IsFromMe']}")
        print("-" * 40)
    except json.JSONDecodeError:
        print("Failed to decode message:", message)

def on_error(ws, error):
    print("WebSocket error:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket connection closed. Reconnecting in 5 seconds...")
    time.sleep(5)
    connect_to_websocket()  # Reconnect on closure

def on_open(ws):
    print("Connected to WebSocket server. Listening for new messages...")

def connect_to_websocket():
    ws_url = "ws://localhost:8081/ws/messages"  # Update the URL if needed
    websocket.enableTrace(True)
    ws = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.on_open = on_open
    ws.run_forever()

if __name__ == "__main__":
    connect_to_websocket()
