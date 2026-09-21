import json, sys
s = json.load(sys.stdin)
new = s["messages_now"] - s["messages_before"]
print(f"running={s['running']} chats {s['chats_done']}/{s['chats_total']} requests={s['requests']} new=+{new} total={s['messages_now']} timeouts={s['timeouts']}")
if s.get("last_error"):
    print("last_error:", s["last_error"])
print("\n".join(s["recent"][-8:]))
