# Local deployment

This deployment runs Tulpamancer as a systemd **user** service inside the logged-in desktop session. It is intended for a personal stream workstation: VTube Studio, OBS, mpv audio, and the LLM service remain desktop-side dependencies.

## First launch

From the repository root:

```bash
.venv/bin/python src/main.py --check
.venv/bin/python src/main.py --preflight
.venv/bin/python src/main.py --utterances 1
```

The bounded run is the required live smoke test. Confirm that the LLM answers, Edge TTS creates audio, mpv plays it, the subtitle file appears, and the avatar moves if VTube Studio is enabled. Fix any issue before enabling continuous operation.

`--preflight` probes the configured local LLM endpoint, VTube Studio authentication, and OBS WebSocket without speaking or starting a broadcast. It is also available as the `Tulpamancer Preflight` desktop launcher.

The `Tulpamancer Speech Session` desktop launcher starts the continuous speech loop in a visible Konsole window. It does not start OBS; use the companion's confirmed OBS Start control only after reviewing the preflight result and scene.

For the default local setup, start the configured Ollama-compatible endpoint and confirm that the configured model is installed. For a remote provider, set its key and model in `.env` instead.

## Enable the service

Make sure `.env` has `VTS_ENABLED=1` after testing VTube Studio manually. Then install and enable the user unit:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/tulpamancer.service ~/.config/systemd/user/tulpamancer.service
systemctl --user daemon-reload
systemctl --user enable --now tulpamancer.service
```

Inspect it with:

```bash
systemctl --user status tulpamancer.service
journalctl --user -u tulpamancer.service -f
```

Stop it with:

```bash
systemctl --user disable --now tulpamancer.service
```

The service deliberately does not launch OBS or VTube Studio. Start those in the graphical session first. It also does not configure Twitch moderation or publish a broadcast; Twitch input is optional and read-only.

## Recovery

The service retries after runtime failures. Configuration errors and intentional interruption are not restarted. If the LLM, TTS, or VTube Studio is unavailable, run the bounded smoke test manually so the concrete dependency failure is visible before restarting the service.
