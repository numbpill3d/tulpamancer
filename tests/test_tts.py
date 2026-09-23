import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

import utils.tts as module


def test_success_replaces_audio_atomically(tmp_path, monkeypatch):
    path = tmp_path / "speech.mp3"
    path.write_bytes(b"previous")

    async def save(temporary):
        assert path.read_bytes() == b"previous"
        Path(temporary).write_bytes(b"new audio")

    monkeypatch.setattr(module.edge_tts, "Communicate", Mock(return_value=Mock(save=save)))
    asyncio.run(module.TTSClient().speak("hello", str(path)))
    assert path.read_bytes() == b"new audio"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("failure", [RuntimeError("network"), asyncio.CancelledError()])
def test_failure_preserves_previous_audio_and_removes_partial(tmp_path, monkeypatch, failure):
    path = tmp_path / "speech.mp3"
    path.write_bytes(b"previous")
    monkeypatch.setattr(
        module.edge_tts, "Communicate", Mock(return_value=Mock(save=AsyncMock(side_effect=failure)))
    )
    with pytest.raises(type(failure)):
        asyncio.run(module.TTSClient().speak("hello", str(path)))
    assert path.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [path]


def test_empty_tts_output_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(module.edge_tts, "Communicate", Mock(return_value=Mock(save=AsyncMock())))
    with pytest.raises(RuntimeError, match="empty"):
        asyncio.run(module.TTSClient().speak("hello", str(tmp_path / "a.mp3")))
    assert not list(tmp_path.iterdir())
