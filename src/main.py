"""Autonomous speech pipeline and command-line entry point."""

import argparse
import asyncio
import contextlib
import inspect
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from utils.chat import ChatClient
from utils.config import LLMSettings, RuntimeSettings, env_number
from utils.lipsync import drive, extract_amplitudes_async
from utils.llm import LLMClient
from utils.emotion import detect_emote
from utils.obs import OBSClient, obs_stream_action, setup_obs
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
    set_speaking = getattr(vtube, "set_speaking", None)
    if set_speaking is not None:
        result = set_speaking(True)
        if inspect.isawaitable(result):
            await result
    await vtube.trigger_talking()
    mouth = asyncio.create_task(drive(frames, vtube, fps))
    try:
        await play_audio(path)
    finally:
        mouth.cancel()
        await asyncio.gather(mouth, return_exceptions=True)
        await vtube.set_mouth(0.0)
        await vtube.trigger_idle()
        if set_speaking is not None:
            result = set_speaking(False)
            if inspect.isawaitable(result):
                await result


async def run_pipeline(settings, llm, tts, vtube, chat, utterances=0, first_context=None):
    """Run until interrupted (0) or after exactly N completed utterances."""
    next_task = None
    try:
        _write_subtitle(settings.subtitle_path, "")
        await vtube.connect()
        start_idle = getattr(vtube, "start_idle_motion", None)
        if start_idle is not None:
            start_idle()
        chat.start()
        print(f"[tulpamancer] {settings.name} is live — ctrl+c to stop\n")
        # Per-run audio slots avoid races between separate app instances.
        with tempfile.TemporaryDirectory(prefix="tulpamancer-") as directory:
            slots = [Path(directory) / f"{i}.mp3" for i in range(2)]
            slot, completed = 0, 0
            next_task = asyncio.create_task(
                prepare_with_retry(
                    llm,
                    tts,
                    slots[slot],
                    settings,
                    first_context if first_context is not None else chat.pop(),
                )
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
                    send_chat = getattr(chat, "send_message", None)
                    if send_chat is not None:
                        result = send_chat(text)
                        if inspect.isawaitable(result):
                            await result
                    _write_subtitle(settings.subtitle_path, text)
                    try:
                        emotion = getattr(vtube, "trigger_emotion", None)
                        if emotion is not None:
                            result = emotion(detect_emote(text))
                            if inspect.isawaitable(result):
                                await result
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


async def main(settings=None, utterances=0, first_context=None):
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
            settings,
            LLMClient(),
            TTSClient(),
            VTubeClient(),
            ChatClient(),
            utterances,
            first_context,
        )
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGTERM)


async def preflight(settings) -> int:
    """Probe local services without generating speech or starting a stream."""
    failures = 0
    llm = LLMSettings.from_env()
    parsed = urlsplit(llm.base_url or "")
    if llm.provider == "ollama" and parsed.hostname and parsed.port:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(parsed.hostname, parsed.port), timeout=2
            )
            writer.close()
            await writer.wait_closed()
            print(f"[preflight] LLM {llm.provider} reachable at {parsed.hostname}:{parsed.port}")
        except Exception:
            failures += 1
            print(f"[preflight] FAIL LLM {llm.provider} at {parsed.hostname}:{parsed.port}")
    else:
        print(f"[preflight] LLM provider configured: {llm.provider}")

    vtube = VTubeClient()
    if vtube.enabled:
        await vtube.connect()
        if vtube.active:
            print("[preflight] VTube Studio authenticated")
        else:
            failures += 1
            print("[preflight] FAIL VTube Studio is unavailable")
        await vtube.disconnect()
    else:
        print("[preflight] VTube Studio disabled")

    obs = OBSClient()
    try:
        await obs.connect()
        status = await obs.stream_status()
        service = await obs.stream_service()
        print(
            f"[preflight] OBS reachable; streaming={status.get('outputActive', False)} "
            f"scene={obs.scene}"
        )
        if service["configured"]:
            print(f"[preflight] OBS stream service configured: {service['type']}")
        else:
            failures += 1
            print("[preflight] FAIL OBS stream service is not configured")
    except Exception:
        failures += 1
        print("[preflight] FAIL OBS WebSocket is unavailable")
    finally:
        await obs.close()

    print(
        "[preflight] READY" if not failures else f"[preflight] BLOCKED ({failures} check(s) failed)"
    )
    return 0 if not failures else 1


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Autonomous AI VTuber speech, avatar, and chat")
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parent.parent / ".env"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check local configuration without making API calls"
    )
    parser.add_argument(
        "--preflight", action="store_true", help="Probe local LLM, avatar, and OBS without speaking"
    )
    parser.add_argument(
        "--setup-obs", action="store_true", help="Create/update the Tulpamancer scene in OBS"
    )
    parser.add_argument(
        "--obs-status", action="store_true", help="Show whether OBS is currently streaming"
    )
    parser.add_argument("--start-stream", action="store_true", help="Start the OBS stream")
    parser.add_argument("--stop-stream", action="store_true", help="Stop the OBS stream")
    parser.add_argument("--message", help="Give Tulpa a message to answer on the first utterance")
    parser.add_argument(
        "--utterances", type=int, default=0, metavar="N", help="Stop after N lines (0 = continuous)"
    )
    args = parser.parse_args(argv)
    if args.utterances < 0:
        parser.error("--utterances must be >= 0")
    obs_actions = sum((args.obs_status, args.start_stream, args.stop_stream))
    if args.setup_obs and obs_actions or obs_actions > 1:
        parser.error("choose one OBS action")
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
        if args.preflight:
            return asyncio.run(preflight(settings))
        if args.setup_obs:
            asyncio.run(setup_obs())
            return 0
        if args.obs_status or args.start_stream or args.stop_stream:
            action = "status" if args.obs_status else "start" if args.start_stream else "stop"
            asyncio.run(obs_stream_action(action))
            return 0
        asyncio.run(main(settings, args.utterances, args.message))
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
