import asyncio
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from utils.chat import ChatClient
from utils.lipsync import drive, extract_amplitudes
from utils.llm import LLMClient
from utils.tts import TTSClient
from utils.vtube import VTubeClient

SLOTS = [
    Path(tempfile.gettempdir()) / "tulpamancer_0.mp3",
    Path(tempfile.gettempdir()) / "tulpamancer_1.mp3",
]


def _write_subtitle(path: Path, text: str) -> None:
    try:
        path.write_text(text)
    except OSError:
        pass


async def play_audio(path: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "mpv", "--no-terminal", "--no-video", str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode != 0:
        print(f"[audio] mpv exited {proc.returncode} for {path.name}")


async def prepare(
    llm: LLMClient,
    tts: TTSClient,
    path: Path,
    fps: int,
    lipsync: bool,
    context: str | None = None,
) -> tuple[str, list[float]]:
    """Generate utterance, synthesize TTS, extract lipsync frames.
    Runs concurrently with audio playback of the previous slot."""
    text = await asyncio.to_thread(llm.generate, context)
    await tts.speak(text, str(path))
    frames: list[float] = []
    if lipsync:
        try:
            frames = await asyncio.to_thread(extract_amplitudes, str(path), fps)
        except Exception as e:
            print(f"[lipsync] amplitude extraction failed: {e}")
    return text, frames


async def main() -> None:
    load_dotenv(Path(__file__).parent.parent / ".env")

    name = os.getenv("CHARACTER_NAME", "Tulpa")
    interval = float(os.getenv("SPEECH_INTERVAL", "2.0"))
    lipsync = os.getenv("LIPSYNC_ENABLED", "1") not in ("0", "false", "no")
    lipsync_fps = int(os.getenv("LIPSYNC_FPS", "24"))
    subtitle_path = Path(
        os.getenv("SUBTITLE_PATH", "/tmp/tulpamancer_sub.txt")
    )

    llm = LLMClient()
    tts = TTSClient()
    vtube = VTubeClient()
    chat = ChatClient()

    await vtube.connect()
    chat.start()

    if chat.enabled():
        print(f"[chat] reading twitch #{chat.channel}")
    print(f"[tulpamancer] {name} is live — ctrl+c to stop\n")

    slot = 0
    try:
        text, frames = await prepare(llm, tts, SLOTS[slot], lipsync_fps, lipsync)
    except Exception as e:
        print(f"[error] startup failed: {e}")
        await chat.stop()
        await vtube.disconnect()
        return

    next_task: asyncio.Task | None = None

    try:
        while True:
            next_slot = 1 - slot
            chat_ctx = chat.pop()
            next_task = asyncio.create_task(
                prepare(llm, tts, SLOTS[next_slot], lipsync_fps, lipsync, chat_ctx)
            )

            _write_subtitle(subtitle_path, text)
            print(f"[{name}] {text}\n")
            await vtube.trigger_talking()
            await asyncio.gather(
                play_audio(SLOTS[slot]),
                drive(frames, vtube, lipsync_fps),
            )
            await vtube.trigger_idle()
            _write_subtitle(subtitle_path, "")

            await asyncio.sleep(interval)

            try:
                text, frames = await next_task
            except Exception as e:
                print(f"[warn] generation failed ({e}), retrying...")
                try:
                    text, frames = await prepare(
                        llm, tts, SLOTS[next_slot], lipsync_fps, lipsync, chat_ctx
                    )
                except Exception as e2:
                    print(f"[warn] retry failed ({e2}), pausing 10s...")
                    await asyncio.sleep(10)
                    continue

            slot = next_slot

    except (KeyboardInterrupt, asyncio.CancelledError):
        if next_task and not next_task.done():
            next_task.cancel()
        _write_subtitle(subtitle_path, "")
        print(f"\n[tulpamancer] {name} goes quiet.")
    finally:
        await chat.stop()
        await vtube.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
