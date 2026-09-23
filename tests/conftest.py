import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    # A developer's real credentials/settings must not affect offline tests.
    for name in tuple(os.environ):
        if name.startswith(
            ("LLM_", "ANTHROPIC_", "TTS_", "VTS_", "VTUBE_", "LIPSYNC_", "TWITCH_", "CHARACTER_")
        ) or name in {
            "SPEECH_INTERVAL",
            "SUBTITLE_PATH",
            "RETRY_DELAY",
            "MAX_GENERATION_FAILURES",
            "AUDIO_TIMEOUT",
        }:
            monkeypatch.delenv(name)
