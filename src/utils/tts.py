import asyncio
import os
import re
import tempfile
from pathlib import Path

import edge_tts

from utils.config import env_number


class TTSClient:
    def __init__(self):
        self.voice = os.getenv("TTS_VOICE", "en-US-GuyNeural").strip()
        if not self.voice:
            raise ValueError("TTS_VOICE must not be empty")
        self.pitch = os.getenv("TTS_PITCH", "+0Hz")
        self.rate = os.getenv("TTS_RATE", "-5%")
        self.volume = os.getenv("TTS_VOLUME", "+0%")
        for name, value, unit in (
            ("TTS_PITCH", self.pitch, "Hz"),
            ("TTS_RATE", self.rate, "%"),
            ("TTS_VOLUME", self.volume, "%"),
        ):
            if not re.fullmatch(r"[+-]\d+" + unit, value):
                raise ValueError(f"{name} must have a sign and unit, e.g. +0{unit}")
        self.timeout = env_number("TTS_TIMEOUT", 60.0, 0.1)

    async def speak(self, text: str, output_path: str) -> None:
        if not text.strip():
            raise ValueError("Cannot synthesize empty speech")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(suffix=".mp3", dir=path.parent)
        os.close(fd)
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                pitch=self.pitch,
                rate=self.rate,
                volume=self.volume,
            )
            async with asyncio.timeout(self.timeout):
                await communicate.save(temporary)
            if Path(temporary).stat().st_size == 0:
                raise RuntimeError("TTS returned an empty audio file")
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
