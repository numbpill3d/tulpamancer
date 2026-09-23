"""Autonomous speech pipeline and command-line entry point."""

import argparse
import asyncio
import contextlib
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from utils.chat import ChatClient
from utils.config import LLMSettings, RuntimeSettings, env_number
from utils.lipsync import drive, extract_amplitudes_async
from utils.llm import LLMClient
from utils.tts import TTSClient
from utils.vtube import VTubeClient


def _write_subtitle(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tulpamancer-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


async def play_audio(path: Path) -> None:
    timeout = env_number("AUDIO_TIMEOUT", 300.0, 1)
    proc = await asyncio.create_subprocess_exec(
        "mpv",
        "--no-config",
        "--no-terminal",
        "--no-video",
        "--",
        str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(timeout):
            await proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"mpv exited {proc.returncode}; check your audio output")
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()


async def prepare(llm, tts, path: Path, fps: int, lipsync: bool, context=None):
    """Only commit conversation history after speech has been synthesized."""
    history = llm.snapshot()
    try:
        text = await llm.generate(context)
        await tts.speak(text, str(path))
        frames = []
        if lipsync:
            try:
                frames = await extract_amplitudes_async(str(path), fps)
            except Exception as exc:
                print(f"[lipsync] extraction failed ({type(exc).__name__}); continuing with audio")
        return text, frames
    except BaseException:
        llm.restore(history)
        raise


async def prepare_with_retry(llm, tts, path, settings, context=None):
    for attempt in range(settings.max_failures):
        try:
            return await prepare(llm, tts, path, settings.fps, settings.lipsync, context)
        except Exception as exc:
            if attempt + 1 >= settings.max_failures:
                raise RuntimeError(
                    f"Speech preparation failed {settings.max_failures} times "
                    f"({type(exc).__name__}); check provider, model, and TTS connectivity"
                ) from None
            print(f"[speech] preparation failed ({type(exc).__name__}); retrying")
            await asyncio.sleep(settings.retry_delay)


async def speak_utterance(path, frames, vtube, fps):
    # The audio process owns the duration. Never leave a lip-sync task behind.
    await vtube.trigger_talking()
    mouth = asyncio.create_task(drive(frames, vtube, fps))
    try:
        await play_audio(path)
    finally:
        mouth.cancel()
        await asyncio.gather(mouth, return_exceptions=True)
        await vtube.set_mouth(0.0)
        await vtube.trigger_idle()


async def run_pipeline(settings, llm, tts, vtube, chat, utterances=0):
    """Run until interrupted (0) or after exactly N completed utterances."""
    next_task = None
    try:
        _write_subtitle(settings.subtitle_path, "")
        await vtube.connect()
        chat.start()
        print(f"[tulpamancer] {settings.name} is live — ctrl+c to stop\n")
        # Per-run audio slots avoid races between separate app instances.
        with tempfile.TemporaryDirectory(prefix="tulpamancer-") as directory:
            slots = [Path(directory) / f"{i}.mp3" for i in range(2)]
            slot, completed = 0, 0
            next_task = asyncio.create_task(
                prepare_with_retry(llm, tts, slots[slot], settings, chat.pop())
            )
            try:
                while not utterances or completed < utterances:
                    text, frames = await next_task
                    next_task = None
                    if not utterances or completed + 1 < utterances:
                        next_task = asyncio.create_task(
                            prepare_with_retry(llm, tts, slots[1 - slot], settings, chat.pop())
                        )
                    if not vtube.active:
                        await vtube.connect()
                    print(f"[{settings.name}] {text}\n")
                    _write_subtitle(settings.subtitle_path, text)
                    try:
                        await speak_utterance(slots[slot], frames, vtube, settings.fps)
                    finally:
                        _write_subtitle(settings.subtitle_path, "")
                    completed += 1
                    if next_task is not None:
                        await asyncio.sleep(settings.interval)
                    slot = 1 - slot
            finally:
                if next_task is not None:
                    next_task.cancel()
                    await asyncio.gather(next_task, return_exceptions=True)
    finally:
        # Each cleanup runs even if a previous cleanup fails.
        with contextlib.suppress(OSError):
            _write_subtitle(settings.subtitle_path, "")
        await asyncio.gather(chat.stop(), vtube.disconnect(), llm.close(), return_exceptions=True)
        print(f"[tulpamancer] {settings.name} goes quiet.")


def check_configuration(settings) -> list[str]:
    errors = []
    for constructor in (LLMSettings.from_env, TTSClient, VTubeClient, ChatClient):
        try:
            constructor()
        except ValueError as exc:
            errors.append(str(exc))
    try:
        env_number("AUDIO_TIMEOUT", 300.0, 1)
    except ValueError as exc:
        errors.append(str(exc))
    for binary in ("mpv", "ffmpeg") if settings.lipsync else ("mpv",):
        if not shutil.which(binary):
            errors.append(f"Install {binary} and put it on PATH")
    if settings.subtitle_path.is_dir():
        errors.append("SUBTITLE_PATH must be a file, not a directory")
    return errors


async def main(settings=None, utterances=0):
    settings = settings or RuntimeSettings.from_env()
    # SIGTERM from a service manager gets the same cleanup as Ctrl+C.
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    installed = False
    try:
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
        installed = True
    except (NotImplementedError, RuntimeError):
        pass
    try:
        await run_pipeline(
            settings, LLMClient(), TTSClient(), VTubeClient(), ChatClient(), utterances
        )
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGTERM)


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Autonomous AI VTuber speech, avatar, and chat")
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parent.parent / ".env"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check local configuration without making API calls"
    )
    parser.add_argument(
        "--utterances", type=int, default=0, metavar="N", help="Stop after N lines (0 = continuous)"
    )
    args = parser.parse_args(argv)
    if args.utterances < 0:
        parser.error("--utterances must be >= 0")
    load_dotenv(args.env_file)
    try:
        settings = RuntimeSettings.from_env()
        errors = check_configuration(settings)
        if errors:
            for error in errors:
                print(f"[config] {error}", file=sys.stderr)
            return 2
        if args.check:
            print(
                "[check] Local configuration and executables OK. No service connections were attempted."
            )
            return 0
        asyncio.run(main(settings, args.utterances))
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 130
    except ValueError as exc:
        print(f"[config] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Provider exception bodies can contain sensitive request data.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f"[error] {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
