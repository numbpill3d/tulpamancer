"""Local push-to-talk recording and Whisper transcription."""

import os
import subprocess
import tempfile
from pathlib import Path


class VoiceInput:
    def __init__(self):
        self.model_name = os.getenv("WHISPER_MODEL", "tiny.en").strip() or "tiny.en"
        self._process: subprocess.Popen | None = None
        self._path: Path | None = None
        self._model = None

    @property
    def recording(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.recording:
            return
        handle = tempfile.NamedTemporaryFile(
            prefix="tulpamancer-voice-", suffix=".wav", delete=False
        )
        handle.close()
        self._path = Path(handle.name)
        self._process = subprocess.Popen(
            [
                "pw-record",
                "--rate",
                "16000",
                "--channels",
                "1",
                "--format",
                "s16",
                str(self._path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_and_transcribe(self) -> str:
        process, path = self._process, self._path
        self._process = None
        self._path = None
        if process is None or path is None:
            return ""
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if not path.exists() or path.stat().st_size < 100:
            path.unlink(missing_ok=True)
            return ""
        try:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            segments, _ = self._model.transcribe(str(path), beam_size=1, vad_filter=True)
            return " ".join(segment.text.strip() for segment in segments).strip()
        finally:
            path.unlink(missing_ok=True)
