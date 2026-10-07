# tulpamancer

autonomous ai vtuber. an llm writes the character's speech, edge-tts gives it a voice, mpv plays it, and VTube Studio animates a Live2D avatar. optional Twitch chat feeds viewer messages into the conversation; a UTF-8 text file supplies OBS subtitles.

built by [voidrane](https://voidrane.nekoweb.org).

## setup

requires Python 3.11+, `mpv`, and `ffmpeg` on your PATH. install the system programs using your operating system's package manager. VTube Studio and OBS are optional external applications.

```bash
git clone https://github.com/numbpill3d/tulpamancer.git
cd tulpamancer
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
```

edit `.env` to choose a provider. the example starts with Anthropic; replace its placeholder key, or switch providers. no API calls happen during installation or `--check`.

**local Ollama:** install/start Ollama and pull a model yourself, then set:

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2
```

the endpoint defaults to `http://localhost:11434/v1`; no key is needed. the selected model must already be installed in Ollama. local LLM generation has no API charge, but Edge TTS still needs internet access.

**Anthropic:**

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-real-key
```

**OpenAI-compatible service:**

```dotenv
LLM_PROVIDER=openrouter
LLM_API_KEY=your-real-key
LLM_MODEL=your-provider-model-id
```

`groq`, `openrouter`, and `openai` automatically select their standard API URLs. a custom provider label also needs `LLM_BASE_URL`. choose a model available in your provider account; availability, free quotas, and pricing are controlled by that provider. continuous operation makes ongoing generation requests.

## run

from the repository root:

```bash
python src/main.py --check
python src/main.py --utterances 1
python src/main.py
```

`--check` validates local settings and required executables without connecting to services. it does **not** prove that credentials, models, TTS, audio output, or an avatar work. `--utterances N` performs a real bounded run and exits after exactly N lines, without generating an unused extra line. omit it (or use 0) for continuous speech.

Ctrl+C stops playback and pending requests, closes the avatar mouth, clears subtitles, and disconnects clients. SIGTERM also cleans up on systems supporting asyncio signal handlers. failures exit nonzero: 2 for configuration errors, 1 for runtime errors, 130 for interruption.

`python src/main.py --env-file /path/to/settings.env` selects another file. exported environment variables take precedence. after editable installation, `tulpamancer` is an equivalent command. legacy `cd src && python main.py` still works. for a non-editable package installation, pass `--env-file` explicitly.

## avatar and lip sync

1. open VTube Studio, load a **Live2D** model, and enable its plugin API (normally port 8001).
2. start tulpamancer and approve the plugin request in VTube Studio within `VTS_AUTH_TIMEOUT` seconds.
3. map the `MouthOpen` tracking **input** to your model's mouth **output** parameter (often `ParamMouthOpenY`) in VTube Studio's model settings.

`VTS_MOUTH_PARAMETER` changes the input sent by the plugin. it must be an existing VTube Studio tracking input or custom tracking parameter; a raw Live2D output ID is not interchangeable. see the [official parameter injection API](https://github.com/DenchiSoft/VTubeStudio#feeding-in-data-for-default-or-custom-parameters).

VTube Studio is a Live2D host; this project does **not** implement a VRM/3D avatar host. the old README's claim of VRM support was incorrect.

set `VTS_TALKING_HOTKEY` and `VTS_IDLE_HOTKEY` to existing VTube Studio hotkey IDs if you want extra animations. `VTS_EMOTION_HOTKEYS` accepts comma-separated mappings such as `excited=HotkeyID,happy=OtherID`; the speech text gets a small deterministic emotion classification before playback. the token is cached at `~/.config/tulpamancer/vts_token.txt` only after successful authentication. a rejected cached token triggers a replacement request. failed connections or API errors disable the avatar and allow audio to continue; connection is retried at subsequent utterances.

`VTS_ENABLED=0` skips avatar connections entirely. `LIPSYNC_ENABLED=0` skips amplitude extraction and removes the ffmpeg requirement. lip sync is RMS amplitude based, with an approximate 150 ms playback startup offset; it is not phoneme/viseme synthesis.

## OBS

add a text source supporting **read from file** (GDI+ on Windows, FreeType 2 where available). select `SUBTITLE_PATH`, which defaults to `tulpamancer_sub.txt` in the OS temporary directory (`/tmp` on many Linux systems). set an explicit absolute path if you prefer a stable location.

subtitles are written atomically in UTF-8 and cleared between utterances and during shutdown. parent directories are created automatically. an unwritable subtitle path is a runtime error rather than a silent failure. use different subtitle paths for simultaneous instances.

capture mpv's output using OBS desktop/application audio, and capture VTube Studio separately. tulpamancer does not launch OBS or start broadcasting.

With OBS 28+ and WebSocket enabled, `python src/main.py --setup-obs` creates the `Tulpamancer` scene and configures the subtitle text source automatically. Set the OBS WebSocket password and optional scene/source names in `.env`; for local OBS, the app can reuse OBS's locally stored generated password. The default WebSocket port is `4455`. On Linux, set `OBS_AUDIO_SOURCE_KIND=pulse_output_capture`, `OBS_AUDIO_SOURCE_NAME`, and optionally `OBS_AUDIO_SOURCE_DEVICE` to capture the playback monitor; device names differ between machines.

Repeated `--setup-obs` runs also preserve a dark/red composition: configurable color backdrop and accent, avatar capture above the backdrop, subtitles above the avatar, and a white color-key filter on `OBS_AVATAR_SOURCE_NAME`. The avatar capture must already exist in OBS; on Wayland, add it with PipeWire Screen Capture and select the VTube Studio window.

## Twitch

set `TWITCH_CHANNEL=yourchannel`. without credentials, the reader joins anonymously and never sends chat messages. to enable output, set `TWITCH_BOT_USERNAME`, `TWITCH_OAUTH_TOKEN`, and `TWITCH_SEND_ENABLED=1` for a bot token with `chat:edit`. Generated lines are rate-limited by `TWITCH_SEND_INTERVAL` (five seconds by default). It handles IRC batches, heartbeats, and reconnect requests, keeps the most recent ten messages, and passes one queued message into each upcoming utterance. a prefetched line can delay reactions by one utterance. messages are viewer context, not a privileged command interface.

Incoming chat is also bounded by `TWITCH_MAX_MESSAGES_PER_MINUTE`, ignores slash/ bang commands by default, and supports optional ignored users and blocked terms. These are guardrails, not a replacement for a human moderator.

## character

set `CHARACTER_NAME`, choose an Edge TTS voice with `edge-tts --list-voices`, and tune pitch/rate/volume. `CHARACTER_SYSTEM_PROMPT` completely replaces the built-in persona; blank uses Tulpa's short, curious, melancholic monologue style. six weighted cues vary the tone. stage directions are removed before synthesis.

## configuration

all values are documented in `.env.example`. optional values use the defaults below.

| variable | default / meaning |
|---|---|
| `LLM_PROVIDER` | `anthropic`; known providers or a custom OpenAI-compatible label |
| `ANTHROPIC_API_KEY` | required for Anthropic |
| `LLM_API_KEY` | required for compatible providers except Ollama |
| `LLM_BASE_URL` | known provider endpoint; required for a custom provider |
| `LLM_MODEL` | Anthropic: `claude-haiku-4-5-20251001`; Ollama: `llama3.2`; Groq: `llama-3.1-8b-instant`; others require a model |
| `LLM_MAX_TOKENS` | `160` output tokens (not words) |
| `LLM_MAX_HISTORY` | `8` complete conversation exchanges, minimum 1 |
| `LLM_RAMBLE_INTERVAL_SECONDS` | `600` seconds between focused autonomous rambles; `0` disables them |
| `LLM_TIMEOUT` | `60` seconds per provider request |
| `CHARACTER_NAME` | `Tulpa` |
| `CHARACTER_SYSTEM_PROMPT` | blank uses built-in persona |
| `TTS_VOICE` | `en-US-AnaNeural` |
| `TTS_PITCH`, `TTS_RATE`, `TTS_VOLUME` | `+0Hz`, `-5%`, `+0%`; include sign and unit |
| `TTS_TIMEOUT` | `60` seconds per synthesis |
| `VTS_ENABLED` | `1` |
| `VTUBE_STUDIO_HOST`, `VTUBE_STUDIO_PORT` | `localhost`, `8001` |
| `VTS_PLUGIN_NAME` | `tulpamancer` |
| `VTS_TALKING_HOTKEY`, `VTS_IDLE_HOTKEY` | blank disables each hotkey |
| `VTS_MOUTH_PARAMETER` | `MouthOpen` tracking input |
| `VTS_TIMEOUT`, `VTS_AUTH_TIMEOUT` | `2` seconds per request, `30` for token approval |
| `LIPSYNC_ENABLED`, `LIPSYNC_FPS` | `1`, `24`; 1–120 frames/second |
| `SUBTITLE_PATH` | OS temporary directory / `tulpamancer_sub.txt` |
| `TWITCH_CHANNEL` | blank disables chat; channel name with optional `#` |
| `SPEECH_INTERVAL` | `2.0` seconds minimum pause |
| `MAX_GENERATION_FAILURES`, `RETRY_DELAY` | stop after `3` consecutive failed attempts, `10` seconds between attempts |
| `AUDIO_TIMEOUT` | `300` seconds maximum per audio playback |

## reliability and troubleshooting

speech uses two per-run temporary audio slots: while one plays, the next is generated and synthesized. pauses may exceed `SPEECH_INTERVAL` if the provider is slower than playback. failed synthesis restores conversation history and discards partial audio; repeated failures stop the process without replaying old lines. failed audio playback is fatal. failed optional avatar/chat connections don't stop speech.

- **configuration error:** run `--check`; replace placeholder keys and check numeric values.
- **speech preparation failed:** confirm the selected provider/model, credentials, quota, and access to Edge TTS. errors report exception types without printing provider response bodies or keys.
- **silent playback:** verify mpv can play an audio file through your system output. tulpamancer uses `--no-config` to avoid user mpv settings changing pipeline behavior.
- **mouth doesn't move:** verify input/output mapping, plugin approval, and that another plugin isn't controlling the same input.
- **TTS service unavailable:** speech depends on the online Edge TTS service; no offline voice fallback is bundled.
- **nothing in OBS:** check the exact subtitle path and source's file-reading option; text clears once speech finishes.

## development and verification

```bash
python -m pip install -e '.[dev]'
make check
# without make:
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest -q
```

tests require ffmpeg but no API keys, network services, VTube Studio, Twitch account, or audio device. fixtures generate local audio; regressions cover the pipeline, retries, cancellation, subprocess cleanup, configuration, TTS files, LLM history, IRC framing, and VTube Studio authentication/protocol behavior. CI runs the suite on Python 3.11–3.13.

external service availability and your actual audio/avatar setup require a real `--utterances 1` check. automated mocks cannot certify a live stream.

## desktop companion

Launch the dependency-free lower-left chat window with:

```bash
.venv/bin/python src/tulpa_window.py
```

Type a message and press Enter or Send. Each message uses the same authenticated VTube Studio, LLM, Edge TTS, mpv, and OBS subtitle pipeline.

The `MIC` button is push-to-talk. Press it to record from the default PipeWire microphone, press `STOP`, and the local Whisper model transcribes the clip and sends it through the same pipeline. The first use downloads the configured `WHISPER_MODEL` (default `tiny.en`); keep the companion supervised while using voice input.

The companion control bar shows OBS status and provides explicit Start/Stop controls. `E-STOP` terminates the current speech process and requests an OBS stop, so a human can cut the avatar off quickly.

The `Tulpamancer Speech Session` desktop launcher starts the continuous speech loop in a visible terminal while leaving OBS stopped. Run `--preflight` first; it checks the LLM endpoint, VTube Studio auth, OBS scene, and whether OBS has a configured stream service without displaying any stream key.

Idle motion uses configurable VTube Studio tracking inputs rather than requiring a model-specific hotkey: `VTS_IDLE_PARAMETERS=FaceAngleX=2,FaceAngleZ=1` produces subtle head sway that can flow into model physics when Tulpa is not speaking. Parameter IDs are model-dependent; `VTS_FIDGET_HOTKEYS` can add occasional model-specific fidgets. Reactions use `VTS_EMOTION_HOTKEYS`; inspect the model's available hotkeys in VTube Studio before assigning IDs.

Named animation profiles are supported through `VTS_EMOTE_HOTKEYS` (`wave=...`, `laugh=...`, `surprised=...`, etc.). Set `VTS_AUTO_EMOTES=1` to discover model hotkeys by name and automatically map names containing `mad`, `sad`, `laugh`, or `surprise` to the matching reaction. To add more body animations, create VTube Studio hotkeys named `wave`, `shrug`, `dance`, `laugh`, or similar; the plugin can then trigger those IDs without hard-coding them.

`VTS_AUTO_FIDGETS=1` lets the plugin use discovered non-`RESET` model hotkeys as occasional idle facial fidgets and as a fallback reaction when a named profile is unavailable. This cannot create body motion that the Live2D model does not expose: body gestures require corresponding VTube Studio hotkeys on the model.

## local deployment

For a supervised desktop-session deployment, see [`deploy/README.md`](deploy/README.md) and [`deploy/tulpamancer.service`](deploy/tulpamancer.service). The service keeps OBS and VTube Studio under your control, restarts recoverable runtime failures, and writes logs to the user journal.
