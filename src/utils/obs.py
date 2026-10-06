"""Small OBS WebSocket 5 client for repeatable local scene setup."""

import asyncio
import base64
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path

import websockets


def _local_obs_password() -> str:
    path = Path.home() / ".config/obs-studio/plugin_config/obs-websocket/config.json"
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("server_password", ""))
    except (OSError, ValueError, TypeError):
        return ""


class OBSClient:
    def __init__(self):
        self.host = os.getenv("OBS_HOST", "127.0.0.1")
        self.port = os.getenv("OBS_PORT", "4455")
        self.password = os.getenv("OBS_PASSWORD", "").strip() or _local_obs_password()
        self.scene = os.getenv("OBS_SCENE", "Tulpamancer")
        self.subtitle_source = os.getenv("OBS_SUBTITLE_SOURCE", "Tulpamancer Subtitles")
        self.avatar_source = os.getenv("OBS_AVATAR_SOURCE_NAME", "Screen Capture (PipeWire)")
        self.background_source = os.getenv("OBS_BACKGROUND_SOURCE", "Tulpamancer Background")
        self.accent_source = os.getenv("OBS_ACCENT_SOURCE", "Tulpamancer Red Accent")
        self.subtitle_path = os.getenv("SUBTITLE_PATH", "").strip() or str(
            Path(tempfile.gettempdir()) / "tulpamancer_sub.txt"
        )
        self.timeout = float(os.getenv("OBS_TIMEOUT", "5"))
        self._ws = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(
            f"ws://{self.host}:{self.port}",
            subprotocols=["obswebsocket.json"],
            open_timeout=self.timeout,
            close_timeout=1,
        )
        hello = json.loads(await asyncio.wait_for(self._ws.recv(), self.timeout))
        if hello.get("op") != 0:
            raise RuntimeError("OBS did not send a WebSocket hello")
        data = hello.get("d", {})
        identify = {"rpcVersion": data.get("rpcVersion", 1)}
        auth = data.get("authentication")
        if auth:
            if not self.password:
                raise RuntimeError("OBS WebSocket password is required")
            secret = base64.b64encode(
                hashlib.sha256((self.password + auth["salt"]).encode()).digest()
            ).decode()
            identify["authentication"] = base64.b64encode(
                hashlib.sha256((secret + auth["challenge"]).encode()).digest()
            ).decode()
        await self._ws.send(json.dumps({"op": 1, "d": identify}))
        identified = json.loads(await asyncio.wait_for(self._ws.recv(), self.timeout))
        if identified.get("op") != 2:
            raise RuntimeError("OBS WebSocket authentication failed")

    async def request(self, request_type: str, request_data: dict | None = None) -> dict:
        if self._ws is None:
            raise RuntimeError("OBS is not connected")
        request_id = uuid.uuid4().hex
        await self._ws.send(
            json.dumps(
                {
                    "op": 6,
                    "d": {
                        "requestType": request_type,
                        "requestId": request_id,
                        "requestData": request_data or {},
                    },
                }
            )
        )
        while True:
            response = json.loads(await asyncio.wait_for(self._ws.recv(), self.timeout))
            if response.get("op") != 7 or response.get("d", {}).get("requestId") != request_id:
                continue
            status = response["d"].get("requestStatus", {})
            if not status.get("result"):
                code = status.get("code", "unknown")
                comment = status.get("comment", "")
                raise RuntimeError(f"OBS {request_type} failed ({code}): {comment}".rstrip())
            return response["d"].get("responseData", {})

    async def setup(self) -> None:
        scenes = await self.request("GetSceneList")
        scene_names = {scene["sceneName"] for scene in scenes.get("scenes", [])}
        if self.scene not in scene_names:
            await self.request("CreateScene", {"sceneName": self.scene})

        inputs = await self.request("GetInputList")
        input_names = {item["inputName"] for item in inputs.get("inputs", [])}
        settings = {"text_file": self.subtitle_path} if self.subtitle_path else {}
        if self.subtitle_source in input_names:
            await self.request(
                "SetInputSettings",
                {
                    "inputName": self.subtitle_source,
                    "inputSettings": settings,
                    "overlay": True,
                },
            )
        else:
            await self.request(
                "CreateInput",
                {
                    "sceneName": self.scene,
                    "inputName": self.subtitle_source,
                    "inputKind": os.getenv("OBS_TEXT_SOURCE_KIND", "text_ft2_source_v2"),
                    "inputSettings": settings,
                    "sceneItemEnabled": True,
                },
            )
        await self.request("SetCurrentProgramScene", {"sceneName": self.scene})

        audio_kind = os.getenv("OBS_AUDIO_SOURCE_KIND", "").strip()
        audio_name = os.getenv("OBS_AUDIO_SOURCE_NAME", "").strip()
        audio_device = os.getenv("OBS_AUDIO_SOURCE_DEVICE", "").strip()
        if audio_kind and audio_name:
            audio_settings = {"device_id": audio_device} if audio_device else {}
            if audio_name in input_names:
                await self.request(
                    "SetInputSettings",
                    {"inputName": audio_name, "inputSettings": audio_settings, "overlay": True},
                )
            else:
                await self.request(
                    "CreateInput",
                    {
                        "sceneName": self.scene,
                        "inputName": audio_name,
                        "inputKind": audio_kind,
                        "inputSettings": audio_settings,
                        "sceneItemEnabled": True,
                    },
                )

        await self._setup_composition()

    async def _setup_composition(self) -> None:
        """Keep the avatar scene readable after repeated setup runs."""
        inputs = await self.request("GetInputList")
        input_names = {item["inputName"] for item in inputs.get("inputs", [])}
        color_kind = os.getenv("OBS_COLOR_SOURCE_KIND", "color_source_v3")
        if self.background_source not in input_names:
            await self.request(
                "CreateInput",
                {
                    "sceneName": self.scene,
                    "inputName": self.background_source,
                    "inputKind": color_kind,
                    "inputSettings": {
                        "color": int(os.getenv("OBS_BACKGROUND_COLOR", "0x050507FF"), 0),
                        "width": 1920,
                        "height": 1080,
                    },
                    "sceneItemEnabled": True,
                },
            )
        if self.accent_source not in input_names:
            await self.request(
                "CreateInput",
                {
                    "sceneName": self.scene,
                    "inputName": self.accent_source,
                    "inputKind": color_kind,
                    "inputSettings": {
                        "color": int(os.getenv("OBS_ACCENT_COLOR", "0xD51F3FFF"), 0),
                        "width": 1920,
                        "height": 12,
                    },
                    "sceneItemEnabled": True,
                },
            )
        if self.avatar_source and os.getenv("OBS_AVATAR_KEY_FILTER", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            filters = await self.request("GetSourceFilterList", {"sourceName": self.avatar_source})
            if not any(
                item.get("filterName") == "Remove White Background"
                for item in filters.get("filters", [])
            ):
                await self.request(
                    "CreateSourceFilter",
                    {
                        "sourceName": self.avatar_source,
                        "filterName": "Remove White Background",
                        "filterKind": "color_key_filter",
                        "filterSettings": {
                            "key_color": int(os.getenv("OBS_AVATAR_KEY_COLOR", "0xFFFFFF"), 0),
                            "similarity": 400,
                            "smoothness": 80,
                            "spill": 100,
                        },
                    },
                )
        scene = await self.request("GetSceneItemList", {"sceneName": self.scene})
        ids = {
            item.get("sourceName"): item.get("sceneItemId") for item in scene.get("sceneItems", [])
        }
        for name, index in (
            (self.background_source, 0),
            (self.accent_source, 1),
            (self.avatar_source, 2),
            (self.subtitle_source, 3),
        ):
            if ids.get(name):
                await self.request(
                    "SetSceneItemIndex",
                    {
                        "sceneName": self.scene,
                        "sceneItemId": ids[name],
                        "sceneItemIndex": index,
                    },
                )

    async def stream_status(self) -> dict:
        return await self.request("GetStreamStatus")

    async def stream_service(self) -> dict:
        """Return non-secret stream service metadata for readiness checks."""
        data = await self.request("GetStreamServiceSettings")
        settings = data.get("streamServiceSettings") or {}
        return {
            "type": data.get("streamServiceType", ""),
            "configured": bool(data.get("streamServiceType") and settings),
        }

    async def start_stream(self) -> None:
        await self.request("StartStream")

    async def stop_stream(self) -> None:
        await self.request("StopStream")

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


async def setup_obs() -> None:
    client = OBSClient()
    try:
        await client.connect()
        await client.setup()
        print(f"[obs] scene ready: {client.scene}; subtitle source ready: {client.subtitle_source}")
        if not os.getenv("OBS_AUDIO_SOURCE_KIND", "").strip():
            print(
                "[obs] audio source not created; configure OBS_AUDIO_SOURCE_KIND/NAME for PipeWire"
            )
    finally:
        await client.close()


async def obs_stream_action(action: str) -> None:
    client = OBSClient()
    try:
        await client.connect()
        if action == "status":
            status = await client.stream_status()
            print(
                f"[obs] streaming={status.get('outputActive', False)} "
                f"reconnecting={status.get('outputReconnecting', False)}"
            )
        elif action == "start":
            await client.start_stream()
            print("[obs] stream start requested")
        else:
            await client.stop_stream()
            print("[obs] stream stop requested")
    finally:
        await client.close()
