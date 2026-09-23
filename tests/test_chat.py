import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.chat import _parse_privmsg


def test_plain_privmsg():
    raw = ":alice!alice@alice.tmi.twitch.tv PRIVMSG #chan :hello world"
    user, msg = _parse_privmsg(raw)
    assert user == "alice"
    assert msg == "hello world"


def test_message_with_colon():
    raw = ":bob!bob@bob.tmi.twitch.tv PRIVMSG #chan :wait: what?"
    user, msg = _parse_privmsg(raw)
    assert user == "bob"
    assert msg == "wait: what?"


def test_tagged_privmsg():
    raw = (
        "@badge-info=;badges=;color=#FF0000 "
        ":carol!carol@carol.tmi.twitch.tv PRIVMSG #chan :tagged message"
    )
    user, msg = _parse_privmsg(raw)
    assert user == "carol"
    assert msg == "tagged message"


def test_invalid_returns_empty():
    assert _parse_privmsg("garbage") == ("", "")
    assert _parse_privmsg("") == ("", "")
    assert _parse_privmsg("PING :tmi.twitch.tv") == ("", "")


def test_whitespace_stripped():
    raw = ":dave!dave@dave.tmi.twitch.tv PRIVMSG #chan :  leading space"
    _, msg = _parse_privmsg(raw)
    assert msg == "leading space"


def test_batch_handles_ping_and_all_messages():
    import asyncio
    from unittest.mock import AsyncMock
    from utils.chat import ChatClient

    client = ChatClient()
    ws = AsyncMock()
    asyncio.run(
        client._handle_frame(
            "PING :heartbeat\r\n:alice!a@host PRIVMSG #chan :one\r\n"
            ":bob!b@host PRIVMSG #chan :two\r\n",
            ws,
        )
    )
    ws.send.assert_awaited_once_with("PONG :heartbeat\r\n")
    assert client.pop() == "[chat: alice: one]"
    assert client.pop() == "[chat: bob: two]"
    assert client.pop() is None


def test_privmsg_in_message_is_not_a_command():
    assert _parse_privmsg(":server NOTICE #chan :PRIVMSG :spoof") == ("", "")


def test_channel_normalized(monkeypatch):
    from utils.chat import ChatClient

    monkeypatch.setenv("TWITCH_CHANNEL", " #SomeChannel ")
    assert ChatClient().channel == "somechannel"


def test_reconnect_message_requests_new_connection():
    import asyncio
    import pytest
    from unittest.mock import AsyncMock
    from utils.chat import ChatClient

    with pytest.raises(ConnectionError):
        asyncio.run(ChatClient()._handle_frame(":tmi.twitch.tv RECONNECT", AsyncMock()))
