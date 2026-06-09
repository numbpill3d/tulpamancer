import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.lipsync import extract_amplitudes


def _make_mp3(text: str) -> str:
    """Synthesize text to a temp mp3 using edge-tts. Returns path."""
    import edge_tts

    tmp = tempfile.mktemp(suffix=".mp3")

    async def _synth():
        comm = edge_tts.Communicate(text=text, voice="en-US-AnaNeural")
        await comm.save(tmp)

    asyncio.run(_synth())
    return tmp


@pytest.fixture(scope="module")
def sample_mp3(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("audio") / "sample.mp3")
    asyncio.run(
        __import__("edge_tts")
        .Communicate(text="The digital void stares back.", voice="en-US-AnaNeural")
        .save(path)
    )
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
