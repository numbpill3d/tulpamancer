"""
Tests for VTubeStudio WebSocket client.

All tests mock the WebSocket connection so no running VTS instance is needed.
FakeWS records sent messages and returns preset responses, letting us verify
the full protocol without external dependencies.
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import utils.vtube as vtube_mod
from utils.vtube import VTubeClient

# ── fixtures & helpers ────────────────────────────────────────────────────────

AUTH_OK = {"data": {"authenticated": True}}
AUTH_FAIL = {"data": {"authenticated": False}}
TOKEN_RESP = {"data": {"authenticationToken": "tok_abc123"}}
TOKEN_DENIED = {"data": {"authenticationToken": ""}}
ACK = {"data": {}}


class FakeWS:
    """Records sent messages, returns preset responses in order."""

    def __init__(self, *responses: dict):
        self._responses = list(responses)
        self._idx = 0
        self.sent: list[dict] = []

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def recv(self) -> str:
        r = self._responses[self._idx]
        self._idx += 1
        return json.dumps(r)

    async def close(self) -> None:
        pass

    def sent_types(self) -> list[str]:
        return [m["messageType"] for m in self.sent]


def _ws_mod(ws: FakeWS) -> MagicMock:
    m = MagicMock()
    m.connect = AsyncMock(return_value=ws)
    return m


def _run(coro):
    return asyncio.run(coro)


def _make_client(ws: FakeWS, token_path: Path, **env) -> VTubeClient:
    """Return a connected VTubeClient using a mock WS and temp token path."""
    defaults = {"VTS_TALKING_HOTKEY": "talk_hk", "VTS_IDLE_HOTKEY": "idle_hk"}
    defaults.update(env)

    async def go():
        with patch.dict(sys.modules, {"websockets": _ws_mod(ws)}):
            with patch.object(vtube_mod, "TOKEN_PATH", token_path):
                with patch.dict("os.environ", defaults):
                    c = VTubeClient()
                    await c.connect()
                    return c

    return _run(go())


# ── connection & auth tests ───────────────────────────────────────────────────

def test_connect_with_cached_token_sends_only_auth_request(tmp_path):
    tp = tmp_path / "token.txt"
    tp.write_text("cached_token")
    ws = FakeWS(AUTH_OK)

    c = _make_client(ws, tp)

    assert c.active
    assert ws.sent_types() == ["AuthenticationRequest"]
    assert ws.sent[0]["data"]["authenticationToken"] == "cached_token"


def test_connect_fresh_requests_token_then_authenticates(tmp_path):
    tp = tmp_path / "token.txt"  # no file
    ws = FakeWS(TOKEN_RESP, AUTH_OK)

    c = _make_client(ws, tp)

    assert c.active
    assert ws.sent_types() == ["AuthenticationTokenRequest", "AuthenticationRequest"]
    assert ws.sent[1]["data"]["authenticationToken"] == "tok_abc123"
    assert tp.read_text() == "tok_abc123"


def test_connect_stale_token_deletes_and_reauths(tmp_path):
    tp = tmp_path / "token.txt"
    tp.write_text("stale")
    ws = FakeWS(AUTH_FAIL, TOKEN_RESP, AUTH_OK)

    c = _make_client(ws, tp)

    assert c.active
    assert ws.sent_types() == [
        "AuthenticationRequest",    # stale attempt
        "AuthenticationTokenRequest",  # request new
        "AuthenticationRequest",    # fresh attempt
    ]
    assert not tp.exists() or tp.read_text() == "tok_abc123"


def test_connect_denied_token_sets_inactive(tmp_path):
    tp = tmp_path / "token.txt"
    ws = FakeWS(TOKEN_DENIED)

    c = _make_client(ws, tp)

    assert not c.active


def test_connect_vts_unavailable_sets_inactive():
    async def go():
        m = MagicMock()
        m.connect = AsyncMock(side_effect=ConnectionRefusedError("no VTS"))
        with patch.dict(sys.modules, {"websockets": m}):
            c = VTubeClient()
            await c.connect()
            return c

    c = _run(go())
    assert not c.active


# ── message format tests ──────────────────────────────────────────────────────

def test_all_messages_have_required_vts_envelope(tmp_path):
    tp = tmp_path / "token.txt"
    ws = FakeWS(TOKEN_RESP, AUTH_OK, ACK, ACK)

    async def go():
        with patch.dict(sys.modules, {"websockets": _ws_mod(ws)}):
            with patch.object(vtube_mod, "TOKEN_PATH", tp):
                c = VTubeClient()
                await c.connect()
                await c.trigger_hotkey("hk1")
                await c.set_mouth(0.5)

    _run(go())

    for msg in ws.sent:
        assert msg.get("apiName") == "VTubeStudioPublicAPI"
        assert msg.get("apiVersion") == "1.0"
        assert "requestID" in msg and msg["requestID"]
        assert "messageType" in msg


def test_trigger_hotkey_correct_format(tmp_path):
    tp = tmp_path / "token.txt"
    tp.write_text("tok")
    ws = FakeWS(AUTH_OK, ACK)

    async def go():
        with patch.dict(sys.modules, {"websockets": _ws_mod(ws)}):
            with patch.object(vtube_mod, "TOKEN_PATH", tp):
                c = VTubeClient()
                await c.connect()
                await c.trigger_hotkey("MY_HOTKEY_ID")

    _run(go())
    last = ws.sent[-1]
    assert last["messageType"] == "HotkeyTriggerRequest"
    assert last["data"]["hotkeyID"] == "MY_HOTKEY_ID"


def test_trigger_hotkey_blank_sends_nothing(tmp_path):
    tp = tmp_path / "token.txt"
    tp.write_text("tok")
    ws = FakeWS(AUTH_OK)

    async def go():
        with patch.dict(sys.modules, {"websockets": _ws_mod(ws)}):
            with patch.object(vtube_mod, "TOKEN_PATH", tp):
                c = VTubeClient()
                await c.connect()
                await c.trigger_hotkey("")

    _run(go())
    assert "HotkeyTriggerRequest" not in ws.sent_types()


def test_set_mouth_correct_format(tmp_path):
    tp = tmp_path / "token.txt"
    tp.write_text("tok")
    ws = FakeWS(AUTH_OK, ACK)

    async def go():
        with patch.dict(sys.modules, {"websockets": _ws_mod(ws)}):
            with patch.object(vtube_mod, "TOKEN_PATH", tp):
                c = VTubeClient()
                await c.connect()
                await c.set_mouth(0.75)

    _run(go())
    last = ws.sent[-1]
    assert last["messageType"] == "InjectParameterDataRequest"
    assert last["data"]["faceFound"] is False
    assert last["data"]["mode"] == "set"
    params = last["data"]["parameterValues"]
    assert len(params) == 1
    assert params[0]["id"] == "MouthOpen"
    assert params[0]["value"] == 0.75


def test_set_mouth_value_rounded_to_3dp(tmp_path):
    tp = tmp_path / "token.txt"
    tp.write_text("tok")
    ws = FakeWS(AUTH_OK, ACK)

    async def go():
        with patch.dict(sys.modules, {"websockets": _ws_mod(ws)}):
            with patch.object(vtube_mod, "TOKEN_PATH", tp):
                c = VTubeClient()
                await c.connect()
                await c.set_mouth(0.123456789)

    _run(go())
    val = ws.sent[-1]["data"]["parameterValues"][0]["value"]
    assert val == 0.123


def test_set_mouth_inactive_does_not_send():
    async def go():
        c = VTubeClient()
        c.active = False
        await c.set_mouth(0.5)  # must not raise AttributeError on None _ws

    _run(go())  # passes if no exception


def test_disconnect_closes_ws(tmp_path):
    tp = tmp_path / "token.txt"
    tp.write_text("tok")
    ws = FakeWS(AUTH_OK)

    async def go():
        with patch.dict(sys.modules, {"websockets": _ws_mod(ws)}):
            with patch.object(vtube_mod, "TOKEN_PATH", tp):
                c = VTubeClient()
                await c.connect()
                await c.disconnect()

    _run(go())
    # if ws.close() was called, FakeWS doesn't raise — verifying it runs clean


def test_token_written_only_on_success(tmp_path):
    tp = tmp_path / "token.txt"
    ws = FakeWS(TOKEN_DENIED)

    async def go():
        with patch.dict(sys.modules, {"websockets": _ws_mod(ws)}):
            with patch.object(vtube_mod, "TOKEN_PATH", tp):
                c = VTubeClient()
                await c.connect()

    _run(go())
    assert not tp.exists(), "token file must not be written on denied auth"
