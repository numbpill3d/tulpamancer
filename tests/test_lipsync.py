import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.lipsync import extract_amplitudes


@pytest.fixture(scope="module")
def sample_mp3(tmp_path_factory):
    # Real local audio decoding, with no network or TTS service dependency.
    import math
    import struct
    import wave

    path = str(tmp_path_factory.mktemp("audio") / "sample.wav")
    with wave.open(path, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        samples = [
            int(12000 * (i / 16000) * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(16000)
        ]
        stream.writeframes(struct.pack("<16000h", *samples))
    return path


def test_extract_amplitudes_returns_list(sample_mp3):
    frames = extract_amplitudes(sample_mp3, fps=24)
    assert isinstance(frames, list)
    assert len(frames) > 0


def test_extract_amplitudes_values_normalized(sample_mp3):
    frames = extract_amplitudes(sample_mp3, fps=24)
    assert all(0.0 <= f <= 1.0 for f in frames)


def test_extract_amplitudes_peak_is_one(sample_mp3):
    frames = extract_amplitudes(sample_mp3, fps=24)
    assert max(frames) == pytest.approx(1.0)


def test_extract_amplitudes_fps_affects_count(sample_mp3):
    frames_24 = extract_amplitudes(sample_mp3, fps=24)
    frames_12 = extract_amplitudes(sample_mp3, fps=12)
    assert len(frames_24) > len(frames_12)


def test_extract_amplitudes_has_nonzero_variance(sample_mp3):
    frames = extract_amplitudes(sample_mp3, fps=24)
    assert max(frames) > min(frames), "all frames identical — amplitude detection broken"  # noqa: E501


def test_async_decode_matches_sync(sample_mp3):
    from utils.lipsync import extract_amplitudes_async

    assert asyncio.run(extract_amplitudes_async(sample_mp3)) == extract_amplitudes(sample_mp3)


@pytest.mark.parametrize("fps", [0, -1, 121])
def test_invalid_fps_rejected_before_decode(fps):
    with pytest.raises(ValueError, match="fps"):
        extract_amplitudes("unused.mp3", fps)


def test_silence_does_not_divide_by_zero():
    from utils.lipsync import _envelope

    assert _envelope(b"\x00" * 32000, 24) == [0] * 24


def test_cancel_drive_closes_mouth():
    from unittest.mock import AsyncMock, Mock
    from utils.lipsync import drive

    async def scenario():
        vtube = Mock(active=True, set_mouth=AsyncMock())
        task = asyncio.create_task(drive([1.0] * 100, vtube))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        vtube.set_mouth.assert_awaited_with(0.0)

    asyncio.run(scenario())
