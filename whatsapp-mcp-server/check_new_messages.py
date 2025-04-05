import websocket
import json
import time
from whatsapp import send_message  # Import the send_message function

DEFAULT_CONTACT = "912266006022"
DEFAULT_MESSAGE = "hi"
current_contact = DEFAULT_CONTACT

def on_message(ws, message):
    try:
        # Parse the incoming message
        data = json.loads(message)
        sender = data.get("Sender")
        content = data.get("Content")
        is_from_me = data.get("IsFromMe")

        print(f"New message received:")
        print(f"Time: {data['Time']}")
        print(f"Sender: {sender}")
        print(f"Content: {content}")
        print(f"IsFromMe: {is_from_me}")
        print("-" * 40)

        # If the message is from the current contact and not from us, prompt for a response
        if sender == current_contact and not is_from_me:
            new_message = input("Enter your response: ")
            success, status = send_message(current_contact, new_message)
            if success:
                print("Message sent successfully!")
            else:
                print(f"Failed to send message: {status}")
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
    # Send the default message to the default contact
    success, status = send_message(DEFAULT_CONTACT, DEFAULT_MESSAGE)
    if success:
        print(f"Default message sent to {DEFAULT_CONTACT}: {DEFAULT_MESSAGE}")
    else:
        print(f"Failed to send default message: {status}")

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
