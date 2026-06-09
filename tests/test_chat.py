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
