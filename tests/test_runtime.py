import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

import main
from utils.config import RuntimeSettings


class FakeLLM:
    def __init__(self):
        self.history = []
        self.generated = 0
        self.close = AsyncMock()

    def snapshot(self):
        return list(self.history)

    def restore(self, history):
        self.history = list(history)

    async def generate(self, context=None):
        self.generated += 1
        text = f"line {self.generated}"
        self.history.append(text)
        return text


def clients(tmp_path):
    llm = FakeLLM()

    async def synth(text, output):
        Path(output).write_text(text)

    tts = Mock(speak=AsyncMock(side_effect=synth))
    vtube = Mock(
        active=True,
        connect=AsyncMock(),
        disconnect=AsyncMock(),
        trigger_talking=AsyncMock(),
        trigger_idle=AsyncMock(),
        set_mouth=AsyncMock(),
    )
    chat = Mock(start=Mock(), stop=AsyncMock(), pop=Mock(return_value="viewer context"))
    settings = replace(
        RuntimeSettings.from_env(),
        interval=0,
        lipsync=False,
        subtitle_path=tmp_path / "obs" / "subtitle.txt",
        retry_delay=0,
    )
    return settings, llm, tts, vtube, chat


def test_finite_pipeline_writes_subtitles_and_cleans_slots(tmp_path, monkeypatch):
    settings, llm, tts, vtube, chat = clients(tmp_path)
    played = []

    async def play(path):
        assert settings.subtitle_path.read_text() == path.read_text()
        played.append(path)
        await asyncio.sleep(0)

    monkeypatch.setattr(main, "play_audio", play)
    asyncio.run(main.run_pipeline(settings, llm, tts, vtube, chat, utterances=3))
    assert llm.generated == 3  # No extra billable prefetch after the final line.
    assert len(played) == 3
    assert played[0] == played[2] and played[0] != played[1]
    assert not played[0].parent.exists()
    assert settings.subtitle_path.read_text() == ""
    llm.close.assert_awaited_once()
    chat.stop.assert_awaited_once()
    vtube.disconnect.assert_awaited_once()


def test_failed_tts_rolls_back_llm_history(tmp_path):
    settings, llm, tts, vtube, chat = clients(tmp_path)
    tts.speak.side_effect = RuntimeError("TTS failure")
    with pytest.raises(RuntimeError):
        asyncio.run(main.prepare(llm, tts, tmp_path / "speech.mp3", 24, False))
    assert llm.history == []


def test_repeated_failure_never_replays_previous_audio(tmp_path, monkeypatch):
    settings, llm, tts, vtube, chat = clients(tmp_path)
    count = 0

    async def synth(text, path):
        nonlocal count
        count += 1
        if count > 1:
            raise RuntimeError("offline")
        Path(path).write_text(text)

    tts.speak.side_effect = synth
    play = AsyncMock()
    monkeypatch.setattr(main, "play_audio", play)
    with pytest.raises(RuntimeError, match="failed 3 times"):
        asyncio.run(main.run_pipeline(settings, llm, tts, vtube, chat))
    assert play.await_count == 1
    assert count == 4
    assert llm.history == ["line 1"]
    assert settings.subtitle_path.read_text() == ""
    chat.stop.assert_awaited_once()


def test_cancellation_stops_prefetch_and_clears_subtitles(tmp_path, monkeypatch):
    settings, llm, tts, vtube, chat = clients(tmp_path)
    playback_started = asyncio.Event()
    prefetch_started = asyncio.Event()
    prefetch_stopped = asyncio.Event()
    original = llm.generate

    async def generate(context=None):
        if llm.generated:
            prefetch_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                prefetch_stopped.set()
        return await original(context)

    llm.generate = generate

    async def play(path):
        playback_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "play_audio", play)

    async def scenario():
        task = asyncio.create_task(main.run_pipeline(settings, llm, tts, vtube, chat))
        await playback_started.wait()
        await prefetch_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert prefetch_stopped.is_set()
    assert settings.subtitle_path.read_text() == ""
    vtube.trigger_idle.assert_awaited_once()
    llm.close.assert_awaited_once()


def test_playback_failure_cleans_everything(tmp_path, monkeypatch):
    settings, llm, tts, vtube, chat = clients(tmp_path)
    monkeypatch.setattr(main, "play_audio", AsyncMock(side_effect=RuntimeError("mpv failed")))
    with pytest.raises(RuntimeError, match="mpv failed"):
        asyncio.run(main.run_pipeline(settings, llm, tts, vtube, chat, utterances=1))
    assert settings.subtitle_path.read_text() == ""
    vtube.trigger_idle.assert_awaited_once()
    chat.stop.assert_awaited_once()


def test_cancel_audio_terminates_child(tmp_path, monkeypatch):
    started = asyncio.Event()
    proc = Mock(returncode=None)

    async def wait():
        started.set()
        if proc.returncode is None:
            await asyncio.Event().wait()
        return proc.returncode

    proc.wait = wait
    proc.terminate.side_effect = lambda: setattr(proc, "returncode", -15)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))

    async def scenario():
        task = asyncio.create_task(main.play_audio(tmp_path / "a.mp3"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    proc.terminate.assert_called_once()


def test_audio_nonzero_is_fatal(tmp_path, monkeypatch):
    proc = Mock(returncode=2, wait=AsyncMock())
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    with pytest.raises(RuntimeError, match="mpv exited 2"):
        asyncio.run(main.play_audio(tmp_path / "a.mp3"))


def test_check_never_contacts_a_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(main.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(main, "main", AsyncMock(side_effect=AssertionError("must not run")))
    assert main.cli(["--check", "--env-file", str(tmp_path / "missing")]) == 0


def test_missing_key_returns_configuration_error(monkeypatch, tmp_path, capsys):
    assert main.cli(["--check", "--env-file", str(tmp_path / "missing")]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
