# tulpamancer

autonomous AI vtuber. speaks continuously on its own, animates a VTubeStudio model with lip sync, outputs subtitles for OBS, and optionally reacts to Twitch chat.

---

## requirements

**system**
- python 3.11+
- `mpv` — audio playback
- `ffmpeg` — lip sync audio analysis

**python**
```
pip install -r requirements.txt
```

packages: `anthropic`, `edge-tts`, `python-dotenv`, `websockets`

---

## setup

**1. configure**
```bash
cp .env.example .env
```
open `.env` and set at minimum:
```
ANTHROPIC_API_KEY=sk-ant-...
```
everything else has sane defaults.

**2. run**
```bash
cd src
python main.py
```

the character starts speaking immediately. ctrl+c to stop cleanly.

---

## VTubeStudio setup

1. open VTubeStudio and load your model (VRM or Live2D)
2. enable the WebSocket API: **Settings → Plugins → Start API (port 8001)**
3. run tulpamancer — it will request plugin access on first launch, approve it in the VTS popup
4. the auth token is saved to `~/.config/tulpamancer/vts_token.txt` for future runs

**hotkeys (optional)**

in VTubeStudio, create hotkeys for talking and idle animations:
- Settings → Hotkeys → create two hotkeys, note their IDs
- set `VTS_TALKING_HOTKEY` and `VTS_IDLE_HOTKEY` in `.env`

**lip sync**

lip sync drives the `MouthOpen` parameter directly via VTS parameter injection.
it works automatically if your model has a `MouthOpen` parameter mapped.
if the avatar's mouth doesn't move, check that the parameter name matches in VTS
(some models use `ParamMouthOpenY` instead — you can override in `vtube.py:set_mouth`).

to disable lip sync: `LIPSYNC_ENABLED=0`

---

## OBS subtitles

1. in OBS, add a **Text (GDI+)** source
2. check **"Read from file"**
3. point it at the path in `SUBTITLE_PATH` (default: `/tmp/tulpamancer_sub.txt`)
4. style it however you like — tulpamancer writes text when speaking and clears it after

---

## Twitch chat

set `TWITCH_CHANNEL=yourchannel` in `.env`.

tulpamancer connects anonymously (no token, read-only). incoming messages are queued and injected into the LLM as context so the character can react naturally to chat.

---

## character customization

**quick changes** — edit `.env`:
- `CHARACTER_NAME` — what the character is called
- `TTS_VOICE` — run `edge-tts --list-voices` to browse, pick any `en-US-*` or other locale
- `TTS_PITCH` / `TTS_RATE` — voice tuning (-50% to +50%, -100Hz to +100Hz)
- `SPEECH_INTERVAL` — seconds of silence between utterances (default 2.0)
- `LLM_MAX_TOKENS` — max length per utterance (default 150 ≈ 2-3 sentences)

**full persona replacement** — set `CHARACTER_SYSTEM_PROMPT` in `.env` to any system prompt.
it fully replaces the built-in Tulpa persona.

---

## config reference

| variable | default | description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | required |
| `CHARACTER_NAME` | `Tulpa` | display name |
| `CHARACTER_SYSTEM_PROMPT` | (built-in) | full persona override |
| `TTS_VOICE` | `en-US-AnaNeural` | edge-tts voice |
| `TTS_PITCH` | `+0Hz` | voice pitch |
| `TTS_RATE` | `-5%` | speech rate |
| `TTS_VOLUME` | `+0%` | volume |
| `VTUBE_STUDIO_HOST` | `localhost` | VTS host |
| `VTUBE_STUDIO_PORT` | `8001` | VTS port |
| `VTS_PLUGIN_NAME` | `tulpamancer` | plugin display name in VTS |
| `VTS_TALKING_HOTKEY` | — | hotkey ID for talking animation |
| `VTS_IDLE_HOTKEY` | — | hotkey ID for idle animation |
| `LIPSYNC_ENABLED` | `1` | set `0` to disable |
| `LIPSYNC_FPS` | `24` | parameter injection rate |
| `SUBTITLE_PATH` | `/tmp/tulpamancer_sub.txt` | OBS text source file |
| `TWITCH_CHANNEL` | — | channel name (no #) |
| `SPEECH_INTERVAL` | `2.0` | pause between utterances (seconds) |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | Anthropic model |
| `LLM_MAX_TOKENS` | `150` | max tokens per utterance |
| `LLM_MAX_HISTORY` | `20` | conversation turns kept in context |

---

## how it works

```
LLM (claude haiku)
  └─ generates next utterance
       └─ edge-tts → mp3
            ├─ ffmpeg → wav → RMS envelope (lip sync frames)
            └─ mpv plays audio
                 ├─ VTS MouthOpen parameter driven from envelope
                 ├─ VTS talking hotkey triggered
                 └─ subtitle file written for OBS
```

the pipeline overlaps: while one utterance plays, the next LLM call and TTS render happen in the background. gaps between speech are only as long as `SPEECH_INTERVAL`.
