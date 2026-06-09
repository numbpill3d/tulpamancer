import os
import edge_tts

class TTSClient:
    def __init__(self):
        self.voice = os.getenv("TTS_VOICE", "en-US-AnaNeural")
        self.pitch = os.getenv("TTS_PITCH", "+0Hz")
        self.rate = os.getenv("TTS_RATE", "-5%")
        self.volume = os.getenv("TTS_VOLUME", "+0%")

    async def speak(self, text: str, output_path: str) -> None:
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            pitch=self.pitch,
            rate=self.rate,
            volume=self.volume,
        )
        await communicate.save(output_path)
