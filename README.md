# tulpamancer

autonomous ai vtuber. give it a voice, a face, and it runs itself — speaking continuously, animating a live2d or vrm avatar through vtuberstudio, syncing its mouth to audio, writing subtitles for obs, and reacting to twitch chat.

built by [voidrane](https://voidrane.nekoweb.org).

---

## what it does

- **autonomous monologue** — an llm generates the character's speech in a continuous loop, maintaining context across utterances so it flows like a real stream-of-consciousness rather than disconnected fragments
- **pipelined output** — while one utterance plays, the next is already being generated and synthesized in the background. the gap between speech is just your configured pause, not synthesis time
- **lip sync** — amplitude is extracted from each audio file via ffmpeg and fed into vtuberstudio's parameter injection api, driving `MouthOpen` frame-by-frame in sync with playback
- **obs subtitles** — current text is written to a file while speaking and cleared after. point an obs text source at it
- **twitch chat** — connects anonymously (no oauth needed) and injects viewer messages as context so the character can react naturally
- **varied tone** — six weighted trigger phrases rotate through the llm conversation, giving it cues to shift mood, trail off, notice something, or sit in silence before speaking again
- **robust** — vtuberstudio unavailability degrades gracefully. stale auth tokens are detected and replaced automatically. generation failures retry once before pausing

---

## requirements

**system packages**
```
mpv       — audio playback
ffmpeg    — lip sync amplitude extraction
```

**python 3.11+**
```
pip install -r requirements.txt
```

`requirements.txt` pulls in: `anthropic`, `openai`, `edge-tts`, `python-dotenv`, `websockets`

---

## setup

**1. clone**
```bash
git clone https://github.com/numbpill3d/tulpamancer
cd tulpamancer
```

**2. configure**
```bash
cp .env.example .env
```

open `.env` and fill in at minimum — pick one:

**paid (anthropic, default):**
```
ANTHROPIC_API_KEY=sk-ant-...
```

**free (openrouter — free key at openrouter.ai):**
```
LLM_PROVIDER=openrouter
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-...
LLM_MODEL=meta-llama/llama-3.3-70b-instruct:free
```

**free (groq — free key at console.groq.com, very fast):**
```
LLM_PROVIDER=groq
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_...
LLM_MODEL=llama-3.1-8b-instant
```

**free (ollama — local, no key needed):**
```
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2
```

everything else runs on defaults. the character will speak immediately.

**3. run**
```bash
cd src
python main.py
```

ctrl+c to stop cleanly.

---

## vtuberstudio

**enabling the api**

open vtuberstudio → settings → plugins → start api (port 8001)

**connecting**

run tulpamancer. on first launch it sends a plugin auth request — approve it in the vts popup. the token is saved to `~/.config/tulpamancer/vts_token.txt` and reused on future runs.

if the token expires or is revoked, tulpamancer detects the failed auth response, deletes the stale token, and requests a new one automatically.

**hotkeys (optional)**

create two hotkeys in vts for talking and idle animations. copy their ids from settings → hotkeys and paste them into `.env`:
```
VTS_TALKING_HOTKEY=your_hotkey_id
VTS_IDLE_HOTKEY=your_idle_id
```

**lip sync**

tulpamancer drives the `MouthOpen` parameter directly via vts's parameter injection api. it works automatically if your model has a `MouthOpen` parameter mapped. some models use `ParamMouthOpenY` instead — if the mouth doesn't move, change the parameter name in `src/utils/vtube.py:set_mouth()`.

to disable lip sync entirely: `LIPSYNC_ENABLED=0`

**model format**

vtuberstudio accepts vrm (3d) and live2d (cubism) models. if you're building a model from scratch, vroid studio is the fastest path to a usable vrm.

---

## obs subtitles

1. add a **text (gdi+)** source in obs
2. check **read from file**
3. set the file path to whatever `SUBTITLE_PATH` is set to in `.env` (default: `/tmp/tulpamancer_sub.txt`)

text appears when the character starts speaking and clears when they stop.

---

## twitch chat

set `TWITCH_CHANNEL=yourchannel` in `.env`. no token, no bot account needed — tulpamancer reads chat anonymously. incoming messages are queued and injected as context into the next llm call, so the character can fold them in naturally.

---

## character

**quick tuning via `.env`**

| what | variable | example |
|------|----------|---------|
| name | `CHARACTER_NAME` | `Wraithling` |
| voice | `TTS_VOICE` | `en-US-JennyNeural` |
| pitch | `TTS_PITCH` | `+20Hz` |
| speed | `TTS_RATE` | `-15%` |
| pause between lines | `SPEECH_INTERVAL` | `3.0` |
| max words per line | `LLM_MAX_TOKENS` | `120` |

run `edge-tts --list-voices` to browse all available tts voices.

**replacing the persona**

set `CHARACTER_SYSTEM_PROMPT` in `.env` to any system prompt. it completely replaces the default tulpa persona.

**default persona**

the built-in character is named tulpa — an autonomous ai entity that exists at the boundary between thought and form, summoned into being by belief. it speaks freely about technology, existence, dreams, art, glitch aesthetics, and horror. curious, melancholic, occasionally darkly funny. speaks in 1–3 sentence bursts.

---

## how it works

```
llm generates text
  └─ edge-tts synthesizes audio (mp3)
       ├─ ffmpeg extracts per-frame rms amplitude  ─┐
       └─ mpv plays audio                           │
            └─ vts MouthOpen driven from amplitude ─┘
                 ├─ talking hotkey triggered
                 └─ subtitle file written for obs

while current audio plays:
  next llm call + tts render happen in background (pipeline overlap)
```

the double-buffer architecture means slots alternate: while slot a plays, slot b is being written. no read/write race, no stuttering.

---

## config reference

| variable | default | description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic` or any string for openai-compat path |
| `ANTHROPIC_API_KEY` | — | required when `LLM_PROVIDER=anthropic` |
| `LLM_API_KEY` | — | api key for openai-compatible providers |
| `LLM_BASE_URL` | — | base url for openai-compatible api |
| `CHARACTER_NAME` | `Tulpa` | display name |
| `CHARACTER_SYSTEM_PROMPT` | (built-in) | full persona override; leave blank for default |
| `TTS_VOICE` | `en-US-AnaNeural` | edge-tts voice |
| `TTS_PITCH` | `+0Hz` | −100Hz to +100Hz |
| `TTS_RATE` | `-5%` | −100% to +100% |
| `TTS_VOLUME` | `+0%` | −100% to +100% |
| `VTUBE_STUDIO_HOST` | `localhost` | vts host |
| `VTUBE_STUDIO_PORT` | `8001` | vts websocket port |
| `VTS_PLUGIN_NAME` | `tulpamancer` | name shown in vts plugin list |
| `VTS_TALKING_HOTKEY` | — | hotkey id for talking animation |
| `VTS_IDLE_HOTKEY` | — | hotkey id for idle animation |
| `LIPSYNC_ENABLED` | `1` | set `0` to disable |
| `LIPSYNC_FPS` | `24` | vts parameter injection rate |
| `SUBTITLE_PATH` | `/tmp/tulpamancer_sub.txt` | file obs reads for subtitles |
| `TWITCH_CHANNEL` | — | channel name without # |
| `SPEECH_INTERVAL` | `2.0` | seconds of silence between utterances |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | model id (use provider's format for free options) |
| `LLM_MAX_TOKENS` | `150` | max tokens per utterance (~2–3 sentences) |
| `LLM_MAX_HISTORY` | `20` | conversation turns kept in context window |

---

## tests

```bash
python -m pytest tests/ -v
```

34 tests covering:
- chat irc parsing (plain + irv3 tagged messages, edge cases)
- lipsync amplitude extraction (against real synthesized audio)
- llm text cleanup and trigger distribution
- full vtuberstudio protocol via websocket mocks (auth flows, message formats, edge cases)

---

## project structure

```
tulpamancer/
├── src/
│   ├── main.py              — main loop, pipeline orchestration
│   └── utils/
│       ├── llm.py           — llm client (anthropic + openai-compat), triggers, history
│       ├── tts.py           — edge-tts synthesis
│       ├── vtube.py         — vtuberstudio websocket client
│       ├── lipsync.py       — amplitude extraction + vts parameter driver
│       └── chat.py          — anonymous twitch irc reader
├── tests/
│   ├── test_chat.py
│   ├── test_lipsync.py
│   ├── test_llm.py
│   └── test_vtube.py
├── .env.example
└── requirements.txt
```

---

[voidrane.nekoweb.org](https://voidrane.nekoweb.org)
