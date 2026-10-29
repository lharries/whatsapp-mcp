import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

SEND_TOOLS = {"send_message", "send_file", "send_audio_message"}
READ_TOOLS = {
    "search_contacts", "list_messages", "list_chats", "get_chat", "get_direct_chat_by_contact",
    "get_contact_chats", "get_last_interaction", "get_message_context", "download_media",
}


def registered_tools(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("WHATSAPP_MCP_READ_ONLY", raising=False)
    else:
        monkeypatch.setenv("WHATSAPP_MCP_READ_ONLY", value)
    sys.modules.pop("main", None)
    import main
    return {tool.name for tool in asyncio.run(main.mcp.list_tools())}


@pytest.mark.parametrize("value", [None, "", "0", "false", "no"])
def test_all_tools_by_default(monkeypatch, value):
    assert registered_tools(monkeypatch, value) == READ_TOOLS | SEND_TOOLS


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_read_only_hides_send_tools(monkeypatch, value):
    assert registered_tools(monkeypatch, value) == READ_TOOLS
