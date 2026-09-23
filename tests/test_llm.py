import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.llm import (
    DEFAULT_SYSTEM,
    _TRIGGER_PHRASES,
    _TRIGGER_WEIGHTS,
    _clean,
    _pick_trigger,
)


def test_clean_strips_asterisk_stage_direction():
    assert _clean("Hello. *sighs* That is all.") == "Hello. That is all."


def test_clean_strips_paren_stage_direction():
    assert _clean("(laughs) what a day") == "what a day"


def test_clean_does_not_strip_cross_delimiter():
    # *foo) is not a stage direction — fixed regex must leave it alone
    assert "*foo)" in _clean("text *foo) more")


def test_clean_collapses_whitespace():
    assert _clean("word   word") == "word word"


def test_clean_passthrough():
    assert _clean("plain text here") == "plain text here"


def test_pick_trigger_returns_string():
    t = _pick_trigger()
    assert isinstance(t, str) and len(t) > 0


def test_trigger_weights_sum_to_100():
    assert sum(_TRIGGER_WEIGHTS) == 100


def test_trigger_most_weighted_is_next():
    max_weight = max(_TRIGGER_WEIGHTS)
    top_phrase = _TRIGGER_PHRASES[_TRIGGER_WEIGHTS.index(max_weight)]
    assert top_phrase == "[next]"


def test_trigger_phrases_and_weights_same_length():
    assert len(_TRIGGER_PHRASES) == len(_TRIGGER_WEIGHTS)


def test_default_system_has_name_placeholder():
    assert "{name}" in DEFAULT_SYSTEM


def test_default_system_formatted():
    formatted = DEFAULT_SYSTEM.format(name="TestBot")
    assert "TestBot" in formatted
    assert "{name}" not in formatted


def test_history_keeps_complete_pairs_and_rolls_back_failure(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    import pytest
    from utils.llm import LLMClient

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MAX_HISTORY", "2")

    async def scenario():
        client = LLMClient()
        client._call = AsyncMock(return_value="hello")
        try:
            for i in range(5):
                await client.generate(f"cue {i}")
                roles = [m["role"] for m in client._call.call_args.args[0]]
                assert roles[0] == "user"
                assert roles == ["user"] or roles == ["user", "assistant", "user"]
            assert len(client._history) == 4
            before = client.snapshot()
            client._call.side_effect = RuntimeError("offline")
            with pytest.raises(RuntimeError):
                await client.generate()
            assert client.snapshot() == before
            client._call.side_effect = None
            client._call.return_value = "*sighs*"
            with pytest.raises(RuntimeError, match="no speakable"):
                await client.generate()
            assert client.snapshot() == before
        finally:
            await client.close()

    asyncio.run(scenario())


def test_anthropic_combines_text_blocks(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from utils.llm import LLMClient

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")

    async def scenario():
        client = LLMClient()
        client._anthropic.messages.create = AsyncMock(
            return_value=SimpleNamespace(
                content=[
                    SimpleNamespace(type="thinking"),
                    SimpleNamespace(type="text", text="Hello."),
                    SimpleNamespace(type="text", text="World."),
                ]
            )
        )
        try:
            assert await client.generate() == "Hello. World."
        finally:
            await client.close()

    asyncio.run(scenario())


def test_total_request_timeout_preserves_history(monkeypatch):
    import asyncio
    import pytest
    from utils.llm import LLMClient

    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    async def scenario():
        client = LLMClient()
        client.timeout = 0.01

        async def stalled(messages):
            await asyncio.Event().wait()

        client._call = stalled
        try:
            with pytest.raises(TimeoutError):
                await client.generate()
            assert client.snapshot() == []
        finally:
            await client.close()

    asyncio.run(scenario())
