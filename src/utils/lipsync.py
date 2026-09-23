import asyncio
import contextlib
import struct
import subprocess
import time


_RATE = 16000


def _command(audio_path):
    return [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        audio_path,
        "-ar",
        str(_RATE),
        "-ac",
        "1",
        "-f",
        "s16le",
        "pipe:1",
    ]


def _envelope(raw: bytes, fps: int) -> list[float]:
    if not 1 <= fps <= 120:
        raise ValueError("fps must be between 1 and 120")
    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
    rms_values = []
    # Fractional boundaries avoid cumulative drift when fps doesn't divide 16000.
    for frame in range((len(samples) * fps + _RATE - 1) // _RATE):
        chunk = samples[frame * _RATE // fps : (frame + 1) * _RATE // fps]
        if chunk:
            rms_values.append((sum(x * x for x in chunk) / len(chunk)) ** 0.5)
    peak = max(rms_values, default=1.0) or 1.0
    return [min(value / peak, 1.0) for value in rms_values]


def extract_amplitudes(audio_path: str, fps: int = 24) -> list[float]:
    """Decode audio to mono PCM and compute a normalized RMS envelope."""
    if not 1 <= fps <= 120:
        raise ValueError("fps must be between 1 and 120")
    result = subprocess.run(_command(audio_path), capture_output=True, check=True, timeout=30)
    return _envelope(result.stdout, fps)


async def extract_amplitudes_async(audio_path: str, fps: int = 24) -> list[float]:
    """Cancellable decoder for the live pipeline."""
    if not 1 <= fps <= 120:
        raise ValueError("fps must be between 1 and 120")
    proc = await asyncio.create_subprocess_exec(
        *_command(audio_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(30):
            raw, _ = await proc.communicate()
        if proc.returncode:
            raise RuntimeError("ffmpeg could not decode speech audio")
        return _envelope(raw, fps)
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()


async def drive(frames: list[float], vtube, fps: int = 24) -> None:
    """Drive the tracking input while audio plays; always close the mouth."""
    if not 1 <= fps <= 120:
        raise ValueError("fps must be between 1 and 120")
    if not frames or not vtube.active:
        return
    try:
        await asyncio.sleep(0.15)  # Approximate mpv startup latency.
        start = time.monotonic()
        sent = -1
        while vtube.active:
            idx = int((time.monotonic() - start) * fps)
            if idx >= len(frames):
                break
            if idx > sent:
                await vtube.set_mouth(frames[idx])
                sent = idx
            await asyncio.sleep(0.4 / fps)
    finally:
        await vtube.set_mouth(0.0)
