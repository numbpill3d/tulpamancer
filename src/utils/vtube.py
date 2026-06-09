import os
import json
import uuid
from pathlib import Path

TOKEN_PATH = Path.home() / ".config" / "tulpamancer" / "vts_token.txt"


class VTubeClient:
    def __init__(self):
        self.host = os.getenv("VTUBE_STUDIO_HOST", "localhost")
        self.port = int(os.getenv("VTUBE_STUDIO_PORT", "8001"))
        self.plugin_name = os.getenv("VTS_PLUGIN_NAME", "tulpamancer")
        self.talking_hotkey = os.getenv("VTS_TALKING_HOTKEY", "")
        self.idle_hotkey = os.getenv("VTS_IDLE_HOTKEY", "")
        self._ws = None
        self.active = False

    @property
    def _uri(self) -> str:
        return f"ws://{self.host}:{self.port}"

    async def connect(self) -> None:
        try:
            import websockets
            self._ws = await websockets.connect(self._uri)
            await self._authenticate()
            self.active = True
            print("[vtube] connected")
        except Exception as e:
            print(f"[vtube] unavailable ({e}), running without avatar")

    async def _send(self, message_type: str, data: dict | None = None) -> dict:
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": uuid.uuid4().hex[:8],
            "messageType": message_type,
            "data": data or {},
        }
        await self._ws.send(json.dumps(payload))
        return json.loads(await self._ws.recv())

    async def _request_token(self) -> str:
        print("[vtube] requesting auth token — approve in VTubeStudio...")
        resp = await self._send("AuthenticationTokenRequest", {
            "pluginName": self.plugin_name,
            "pluginDeveloper": "tulpamancer",
            "pluginIcon": None,
        })
        token = resp.get("data", {}).get("authenticationToken", "")
        if token:
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_PATH.write_text(token)
        return token

    async def _authenticate(self) -> None:
        token = TOKEN_PATH.read_text().strip() if TOKEN_PATH.exists() else ""

        if not token:
            token = await self._request_token()

        resp = await self._send("AuthenticationRequest", {
            "pluginName": self.plugin_name,
            "pluginDeveloper": "tulpamancer",
            "authenticationToken": token,
        })

        authenticated = resp.get("data", {}).get("authenticated", False)
        if not authenticated:
            # Stale token — nuke it and get a fresh one
            TOKEN_PATH.unlink(missing_ok=True)
            token = await self._request_token()
            await self._send("AuthenticationRequest", {
                "pluginName": self.plugin_name,
                "pluginDeveloper": "tulpamancer",
                "authenticationToken": token,
            })

    async def trigger_hotkey(self, hotkey_id: str) -> None:
        if not self.active or not hotkey_id:
            return
        try:
            await self._send("HotkeyTriggerRequest", {"hotkeyID": hotkey_id})
        except Exception:
            pass

    async def trigger_talking(self) -> None:
        await self.trigger_hotkey(self.talking_hotkey)

    async def trigger_idle(self) -> None:
        await self.trigger_hotkey(self.idle_hotkey)

    async def set_mouth(self, value: float) -> None:
        if not self.active:
            return
        try:
            await self._send("InjectParameterDataRequest", {
                "faceFound": False,
                "mode": "set",
                "parameterValues": [{"id": "MouthOpen", "value": round(value, 3)}],
            })
        except Exception:
            pass

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
