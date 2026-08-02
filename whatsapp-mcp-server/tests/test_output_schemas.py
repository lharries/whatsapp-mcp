"""FastMCP 1.29.0 validates every tool's return value against the output
schema it derives from the tool's return-type annotation. Several tools in
main.py declare `Dict[str, Any]` / `List[Dict[str, Any]]` but actually return
plain dataclasses (or, for `list_messages`, a formatted string) - so every
real call to them fails at runtime with a pydantic validation error, even
though the underlying whatsapp.py functions work fine.

These tests drive calls through the real FastMCP request-handling pipeline
(the same `CallToolRequest` handler a real client hits), so they exercise the
actual output-schema validation rather than merely asserting `isinstance`,
which would not have caught this bug.
"""
import asyncio
import importlib

import pytest
from mcp import types


def _reload_main():
    import main
    return importlib.reload(main)


@pytest.fixture
def seeded_app(seeded_wa):
    """Reload main.py after whatsapp.py has already been reloaded against the
    seeded db (via the `seeded_wa` fixture from conftest.py), so main's tool
    wrappers are bound to the whatsapp functions backed by the seeded db."""
    mod = _reload_main()
    yield mod
    _reload_main()


def call_tool(mod, name, arguments):
    """Invoke a registered tool through the real low-level CallToolRequest
    handler: input-schema check, tool call, then pydantic (FastMCP) and
    jsonschema (lowlevel) output validation - exactly what a real client
    triggers. Returns the CallToolResult (with .isError / .structuredContent)."""
    handler = mod.mcp._mcp_server.request_handlers[types.CallToolRequest]
    request = types.CallToolRequest(
        params=types.CallToolRequestParams(name=name, arguments=arguments)
    )
    result = asyncio.run(handler(request))
    return result.root


def test_search_contacts_output_is_schema_valid(seeded_app):
    result = call_tool(seeded_app, "search_contacts", {"query": "Alice"})

    assert not result.isError, result.content
    assert result.structuredContent is not None
    contacts = result.structuredContent["result"]
    assert len(contacts) == 1
    assert contacts[0]["jid"] == "111@s.whatsapp.net"
    assert contacts[0]["name"] == "Alice"


def test_list_chats_output_is_schema_valid(seeded_app):
    result = call_tool(seeded_app, "list_chats", {})

    assert not result.isError, result.content
    assert result.structuredContent is not None
    chats = result.structuredContent["result"]
    jids = {c["jid"] for c in chats}
    assert jids == {"111@s.whatsapp.net", "222@g.us"}


def test_get_chat_output_is_schema_valid(seeded_app):
    result = call_tool(seeded_app, "get_chat", {"chat_jid": "111@s.whatsapp.net"})

    assert not result.isError, result.content
    assert result.structuredContent is not None
    chat = result.structuredContent["result"]
    assert chat["name"] == "Alice"
    assert chat["last_message"] == "How are you"


def test_get_chat_missing_jid_does_not_crash(seeded_app):
    """Requirement: get_chat on an unknown JID (whatsapp.get_chat returns
    None) must not crash the tool call."""
    result = call_tool(
        seeded_app, "get_chat", {"chat_jid": "does-not-exist@s.whatsapp.net"}
    )

    assert not result.isError, result.content


def test_get_direct_chat_by_contact_output_is_schema_valid(seeded_app):
    result = call_tool(
        seeded_app, "get_direct_chat_by_contact", {"sender_phone_number": "111"}
    )

    assert not result.isError, result.content
    assert result.structuredContent is not None
    assert result.structuredContent["result"]["jid"] == "111@s.whatsapp.net"


def test_get_contact_chats_output_is_schema_valid(seeded_app):
    result = call_tool(
        seeded_app, "get_contact_chats", {"jid": "111@s.whatsapp.net"}
    )

    assert not result.isError, result.content
    assert result.structuredContent is not None
    chats = result.structuredContent["result"]
    assert any(c["jid"] == "111@s.whatsapp.net" for c in chats)


def test_get_message_context_output_is_schema_valid(seeded_app):
    result = call_tool(
        seeded_app, "get_message_context", {"message_id": "m2", "before": 5, "after": 5}
    )

    assert not result.isError, result.content
    assert result.structuredContent is not None
    ctx = result.structuredContent["result"]
    assert ctx["message"]["id"] == "m2"
    assert [m["id"] for m in ctx["before"]] == ["m1"]
    assert [m["id"] for m in ctx["after"]] == ["m3"]


def test_list_messages_output_is_schema_valid(seeded_app):
    result = call_tool(
        seeded_app,
        "list_messages",
        {"chat_jid": "111@s.whatsapp.net", "include_context": False},
    )

    assert not result.isError, result.content
    # list_messages genuinely returns a formatted string; downstream
    # consumers already parse that string, so the tool's output schema must
    # be `str` (FastMCP wraps primitive/str returns as {"result": <str>} in
    # structuredContent), not a list as it was before the fix.
    assert "Hello back" in result.content[0].text
    assert isinstance(result.structuredContent["result"], str)
    assert "Hello back" in result.structuredContent["result"]


def test_get_last_interaction_output_is_schema_valid(seeded_app):
    """Regression test: get_last_interaction was already correctly annotated
    `-> str` and must keep working."""
    result = call_tool(
        seeded_app, "get_last_interaction", {"jid": "111@s.whatsapp.net"}
    )

    assert not result.isError, result.content
    assert "How are you" in result.content[0].text
