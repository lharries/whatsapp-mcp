"""Query functions must work against a real sqlite schema (chats + messages)."""


def test_list_chats_returns_seeded_chats(seeded_wa):
    chats = seeded_wa.list_chats()
    jids = {c.jid for c in chats}
    assert jids == {"111@s.whatsapp.net", "222@g.us"}


def test_list_chats_sorted_by_last_active(seeded_wa):
    chats = seeded_wa.list_chats(sort_by="last_active")
    assert [c.jid for c in chats] == ["111@s.whatsapp.net", "222@g.us"]


def test_get_chat_returns_metadata(seeded_wa):
    chat = seeded_wa.get_chat("111@s.whatsapp.net")
    assert chat is not None
    assert chat.name == "Alice"
    assert chat.last_message == "How are you"


def test_get_chat_missing_returns_none(seeded_wa):
    assert seeded_wa.get_chat("does-not-exist@s.whatsapp.net") is None


def test_search_contacts_matches_name(seeded_wa):
    contacts = seeded_wa.search_contacts("Alice")
    assert len(contacts) == 1
    assert contacts[0].jid == "111@s.whatsapp.net"


def test_search_contacts_excludes_groups(seeded_wa):
    contacts = seeded_wa.search_contacts("Team")
    assert contacts == []


def test_get_direct_chat_by_contact(seeded_wa):
    chat = seeded_wa.get_direct_chat_by_contact("111")
    assert chat is not None
    assert chat.jid == "111@s.whatsapp.net"


def test_get_contact_chats(seeded_wa):
    chats = seeded_wa.get_contact_chats("111@s.whatsapp.net")
    assert any(c.jid == "111@s.whatsapp.net" for c in chats)


def test_get_last_interaction(seeded_wa):
    text = seeded_wa.get_last_interaction("111@s.whatsapp.net")
    assert "How are you" in text


def test_get_message_context(seeded_wa):
    context = seeded_wa.get_message_context("m2", before=5, after=5)
    assert context.message.id == "m2"
    assert [m.id for m in context.before] == ["m1"]
    assert [m.id for m in context.after] == ["m3"]


def test_list_messages_by_query_without_context(seeded_wa):
    result = seeded_wa.list_messages(query="Hello", include_context=False)
    assert "Hello back" in result


def test_list_messages_with_context_includes_neighbours(seeded_wa):
    result = seeded_wa.list_messages(
        chat_jid="111@s.whatsapp.net",
        include_context=True,
        context_before=1,
        context_after=1,
    )
    assert "Hi" in result
    assert "Hello back" in result
    assert "How are you" in result


def test_list_messages_with_context_reuses_a_single_connection(seeded_wa, monkeypatch):
    """Regression test: list_messages used to open a fresh sqlite3 connection
    per matched message (via get_message_context) to build the context window.
    With limit=20 that's up to ~21 connections per call. It must now reuse the
    single connection already open for the outer query."""
    connect_calls = []
    original_connect = seeded_wa.sqlite3.connect

    def counting_connect(*args, **kwargs):
        connect_calls.append((args, kwargs))
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(seeded_wa.sqlite3, "connect", counting_connect)

    result = seeded_wa.list_messages(
        chat_jid="111@s.whatsapp.net",
        include_context=True,
        context_before=1,
        context_after=1,
    )

    assert "How are you" in result
    assert len(connect_calls) == 1
