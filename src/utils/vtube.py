import asyncio
import json
import os
import uuid
from pathlib import Path

import websockets

from utils.config import env_bool, env_number

TOKEN_PATH = Path.home() / ".config" / "tulpamancer" / "vts_token.txt"


class VTubeClient:
    def __init__(self):
        self.host = os.getenv("VTUBE_STUDIO_HOST", "localhost")
        self.port = env_number("VTUBE_STUDIO_PORT", 8001, 1, 65535)
        self.plugin_name = os.getenv("VTS_PLUGIN_NAME", "tulpamancer")
        self.talking_hotkey = os.getenv("VTS_TALKING_HOTKEY", "")
        self.idle_hotkey = os.getenv("VTS_IDLE_HOTKEY", "")
        self.mouth_parameter = os.getenv("VTS_MOUTH_PARAMETER", "MouthOpen")
        self.enabled = env_bool("VTS_ENABLED")
        self.timeout = env_number("VTS_TIMEOUT", 2.0, 0.1)
        self.auth_timeout = env_number("VTS_AUTH_TIMEOUT", 30.0, 0.1)
        self._uri = f"ws://{self.host}:{self.port}"
        self._ws = None
        self._lock = asyncio.Lock()
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

    async def set_mouth(self, value: float) -> None:
        if not self.active:
            return
        await self._optional_send(
            "InjectParameterDataRequest",
            {
                "faceFound": False,
                "mode": "set",
                "parameterValues": [
                    {
                        "id": self.mouth_parameter,
                        "value": round(max(0.0, min(value, 1.0)), 3),
                    }
                ],
            },
        )

    async def disconnect(self) -> None:
        self.active = False
        ws, self._ws = self._ws, None
        if ws:
            try:
                async with asyncio.timeout(self.timeout):
                    await ws.close()
            except Exception:
                pass
