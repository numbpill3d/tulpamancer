import asyncio
import json
import math
import os
import random
import uuid
from pathlib import Path

import websockets

from utils.config import bypass_proxy_for_loopback, env_bool, env_number

TOKEN_PATH = Path.home() / ".config" / "tulpamancer" / "vts_token.txt"


def _emotion_hotkeys(raw: str) -> dict[str, str]:
    result = {}
    for item in raw.split(","):
        if "=" in item:
            name, hotkey = (part.strip() for part in item.split("=", 1))
            if name and hotkey:
                result[name.lower()] = hotkey
    return result


def _idle_parameters(raw: str) -> dict[str, float]:
    result = {}
    for item in raw.split(","):
        if "=" in item:
            parameter, amplitude = (part.strip() for part in item.split("=", 1))
            try:
                if parameter and amplitude:
                    result[parameter] = float(amplitude)
            except ValueError:
                raise ValueError("VTS_IDLE_PARAMETERS must use parameter=number pairs") from None
    return result


class VTubeClient:
    def __init__(self):
        self.host = os.getenv("VTUBE_STUDIO_HOST", "localhost")
        self.port = env_number("VTUBE_STUDIO_PORT", 8001, 1, 65535)
        self.plugin_name = os.getenv("VTS_PLUGIN_NAME", "tulpamancer")
        self.talking_hotkey = os.getenv("VTS_TALKING_HOTKEY", "")
        self.idle_hotkey = os.getenv("VTS_IDLE_HOTKEY", "")
        self.emotion_hotkeys = _emotion_hotkeys(os.getenv("VTS_EMOTION_HOTKEYS", ""))
        self.emote_hotkeys = _emotion_hotkeys(os.getenv("VTS_EMOTE_HOTKEYS", ""))
        self.auto_emotes = env_bool("VTS_AUTO_EMOTES", False)
        self.auto_fidgets = env_bool("VTS_AUTO_FIDGETS", False)
        self.fidget_hotkeys = tuple(
            item.strip() for item in os.getenv("VTS_FIDGET_HOTKEYS", "").split(",") if item.strip()
        )
        self.fidget_min = env_number("VTS_FIDGET_MIN_SECONDS", 25.0, 5.0)
        self.fidget_max = env_number("VTS_FIDGET_MAX_SECONDS", 55.0, self.fidget_min)
        self.idle_parameters = _idle_parameters(os.getenv("VTS_IDLE_PARAMETERS", ""))
        self.mouth_parameter = os.getenv("VTS_MOUTH_PARAMETER", "MouthOpen")
        self.enabled = env_bool("VTS_ENABLED")
        self.timeout = env_number("VTS_TIMEOUT", 2.0, 0.1)
        self.auth_timeout = env_number("VTS_AUTH_TIMEOUT", 30.0, 0.1)
        self._uri = f"ws://{self.host}:{self.port}"
        bypass_proxy_for_loopback(self.host)
        self._ws = None
        self._lock = asyncio.Lock()
        self._idle_task: asyncio.Task | None = None
        self._speaking = False
        self._auto_emote_hotkeys: dict[str, list[str]] = {}
        self._auto_fidget_hotkeys: list[str] = []
        self.active = False

    async def connect(self) -> None:
        if not self.enabled or self.active:
            return
        try:
            self._ws = await websockets.connect(
                self._uri,
                open_timeout=self.timeout,
                close_timeout=1,
            )
            await self._authenticate()
            await self._load_emote_hotkeys()
            self.active = True
            print("[vtube] connected")
        except asyncio.CancelledError:
            await self.disconnect()
            raise
        except Exception as exc:
            await self.disconnect()
            print(f"[vtube] unavailable ({type(exc).__name__}), running without avatar")

    async def _send(self, message_type: str, data: dict | None = None) -> dict:
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": uuid.uuid4().hex,
            "messageType": message_type,
            "data": data if data is not None else {},
        }
        timeout = (
            self.auth_timeout if message_type == "AuthenticationTokenRequest" else self.timeout
        )
        # Serialize send/receive pairs so hotkeys and lip sync cannot steal replies.
        async with self._lock, asyncio.timeout(timeout):
            if self._ws is None:
                raise ConnectionError("VTube Studio is disconnected")
            await self._ws.send(json.dumps(payload))
            while True:
                response = json.loads(await self._ws.recv())
                if response.get("requestID") != payload["requestID"]:
                    continue  # Unsolicited events and late replies aren't our response.
                if response.get("messageType") == "APIError":
                    error_id = response.get("data", {}).get("errorID", "unknown")
                    raise RuntimeError(f"VTube Studio API error {error_id}")
                return response

    async def _request_token(self) -> str:
        print("[vtube] requesting auth token — approve in VTube Studio...")
        resp = await self._send(
            "AuthenticationTokenRequest",
            {
                "pluginName": self.plugin_name,
                "pluginDeveloper": "tulpamancer",
            },
        )
        token = resp.get("data", {}).get("authenticationToken", "")
        if not token:
            raise RuntimeError("VTube Studio denied plugin access or returned no token")
        return token

    async def _authenticate(self) -> None:
        cached = TOKEN_PATH.read_text().strip() if TOKEN_PATH.exists() else ""
        token = cached or await self._request_token()
        for attempt in range(2):
            resp = await self._send(
                "AuthenticationRequest",
                {
                    "pluginName": self.plugin_name,
                    "pluginDeveloper": "tulpamancer",
                    "authenticationToken": token,
                },
            )
            if resp.get("data", {}).get("authenticated") is True:
                if token != cached:
                    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
                    TOKEN_PATH.write_text(token, encoding="utf-8")
                return
            if not cached or attempt:
                raise RuntimeError("VTube Studio rejected authentication")
            token = await self._request_token()

    async def _load_emote_hotkeys(self) -> None:
        if not self.auto_emotes:
            return
        try:
            response = await self._send("HotkeysInCurrentModelRequest")
        except Exception as exc:
            # Discovery is a convenience; it must never prevent speech from
            # starting when a model/plugin does not support the request.
            print(f"[vtube] emote discovery unavailable ({type(exc).__name__}); continuing")
            return
        for hotkey in response.get("data", {}).get("availableHotkeys", []):
            hotkey_id = hotkey.get("hotkeyID", "")
            name = hotkey.get("name", "").lower()
            if not hotkey_id or not name:
                continue
            if name != "reset":
                self._auto_fidget_hotkeys.append(hotkey_id)
            labels = {name}
            if any(word in name for word in ("mad", "angry", "rage")):
                labels.add("angry")
            if any(word in name for word in ("sad", "low eye", "cry")):
                labels.add("sad")
            if any(word in name for word in ("laugh", "haha", "joy")):
                labels.add("laugh")
            if any(word in name for word in ("surprise", "shock", "wide")):
                labels.add("surprised")
            for label in labels:
                self._auto_emote_hotkeys.setdefault(label, []).append(hotkey_id)

    async def trigger_hotkey(self, hotkey_id: str) -> None:
        if not self.active or not hotkey_id:
            return
        await self._optional_send("HotkeyTriggerRequest", {"hotkeyID": hotkey_id})

    async def _optional_send(self, message_type: str, data: dict) -> None:
        try:
            await self._send(message_type, data)
        except Exception as exc:
            print(
                f"[vtube] {message_type} failed ({type(exc).__name__}); reconnecting next utterance"
            )
            await self.disconnect()

    async def trigger_talking(self) -> None:
        await self.trigger_hotkey(self.talking_hotkey)

    async def trigger_idle(self) -> None:
        await self.trigger_hotkey(self.idle_hotkey)

    async def trigger_emotion(self, emotion: str) -> None:
        """Fire the configured or auto-discovered hotkey for a detected emote."""
        label = emotion.lower()
        hotkey = self.emote_hotkeys.get(label) or self.emotion_hotkeys.get(label)
        if not hotkey:
            choices = self._auto_emote_hotkeys.get(label, [])
            hotkey = random.choice(choices) if choices else ""
        if not hotkey and self.auto_fidgets and self._auto_fidget_hotkeys:
            hotkey = random.choice(self._auto_fidget_hotkeys)
        await self.trigger_hotkey(hotkey)

    async def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking

    def start_idle_motion(self) -> None:
        if (
            self.fidget_hotkeys or self.idle_parameters or (self.auto_fidgets and self.auto_emotes)
        ) and self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_motion_loop())

    async def _idle_motion_loop(self) -> None:
        try:
            phase = random.uniform(0, math.tau)
            while True:
                if self.idle_parameters and self.active and not self._speaking:
                    # Keep the VTS websocket available for lip-sync and hotkeys.
                    # A few smooth updates per second are plenty for idle sway.
                    phase += 0.35
                    await self.set_parameters(
                        {
                            parameter: amplitude * math.sin(phase * (1 + index * 0.37))
                            for index, (parameter, amplitude) in enumerate(
                                self.idle_parameters.items()
                            )
                        }
                    )
                    await asyncio.sleep(0.35)
                    continue
                await asyncio.sleep(random.uniform(self.fidget_min, self.fidget_max))
                if self.active and not self._speaking:
                    choices = self.fidget_hotkeys or (
                        self._auto_fidget_hotkeys if self.auto_fidgets else []
                    )
                    if choices:
                        await self.trigger_hotkey(random.choice(choices))
        except asyncio.CancelledError:
            raise

    async def stop_idle_motion(self) -> None:
        task, self._idle_task = self._idle_task, None
        if task is not None:
            if task is asyncio.current_task():
                return
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def set_mouth(self, value: float) -> None:
        await self.set_parameters({self.mouth_parameter: round(max(0.0, min(value, 1.0)), 3)})

    async def set_parameters(self, values: dict[str, float]) -> None:
        if not self.active:
            return
        await self._optional_send(
            "InjectParameterDataRequest",
            {
                "faceFound": False,
                "mode": "set",
                "parameterValues": [
                    {"id": parameter, "value": round(value, 3)}
                    for parameter, value in values.items()
                ],
            },
        )

    async def disconnect(self) -> None:
        await self.stop_idle_motion()
        self.active = False
        ws, self._ws = self._ws, None
        if ws:
            try:
                async with asyncio.timeout(self.timeout):
                    await ws.close()
            except Exception:
                pass
