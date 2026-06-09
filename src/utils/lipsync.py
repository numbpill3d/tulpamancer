import asyncio
import os
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path


def extract_amplitudes(audio_path: str, fps: int = 24) -> list[float]:
    """Convert mp3 → wav via ffmpeg, compute per-frame RMS amplitude envelope."""
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg", "-i", audio_path,
                "-ar", "16000", "-ac", "1",
                "-acodec", "pcm_s16le",
                tmp, "-y",
            ],
            capture_output=True,
            check=True,
        )
        with wave.open(tmp, "rb") as wf:
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    finally:
        Path(tmp).unlink(missing_ok=True)

    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
    spf = max(rate // fps, 1)

    rms_values: list[float] = []
    for i in range(0, len(samples), spf):
        chunk = samples[i : i + spf]
        rms = (sum(x * x for x in chunk) / len(chunk)) ** 0.5
        rms_values.append(rms)

    peak = max(rms_values, default=1.0) or 1.0
    return [min(v / peak, 1.0) for v in rms_values]


async def drive(frames: list[float], vtube, fps: int = 24) -> None:
    """Drive VTS MouthOpen in sync with audio. Runs alongside play_audio via gather."""
    if not frames or not vtube.active:
        return

    await asyncio.sleep(0.15)  # mpv startup latency compensation

    frame_s = 1.0 / fps
    start = time.monotonic()
    sent = -1

    while True:
        elapsed = time.monotonic() - start
        idx = int(elapsed * fps)
        if idx >= len(frames):
            break
        if idx > sent:
            await vtube.set_mouth(frames[idx])
            sent = idx
        await asyncio.sleep(frame_s * 0.4)

    await vtube.set_mouth(0.0)
