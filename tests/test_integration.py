"""Real local protocol connections; no external services or credentials."""

import asyncio
import json

import websockets
from aiohttp import web

from utils.llm import LLMClient
from utils.vtube import VTubeClient
import utils.vtube as vtube_module


def test_compatible_llm_over_real_http(monkeypatch):
    calls = []

    async def completions(request):
        calls.append(await request.json())
        return web.json_response(
            {
                "id": "local-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Hello from the void."},
                    }
                ],
            }
        )

    async def scenario():
        app = web.Application()
        app.router.add_post("/v1/chat/completions", completions)
        runner = web.AppRunner(app)
        await runner.setup()
        server = await asyncio.get_running_loop().create_server(runner.server, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("LLM_MODEL", "test-model")
        monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{port}/v1")
        client = LLMClient()
        try:
            assert await client.generate("viewer says hello") == "Hello from the void."
            assert await client.generate("next") == "Hello from the void."
            assert [message["role"] for message in calls[1]["messages"]] == [
                "system",
                "user",
                "assistant",
                "user",
            ]
        finally:
            await client.close()
            server.close()
            await server.wait_closed()
            await runner.cleanup()

    asyncio.run(scenario())


def test_real_vtube_socket_auth_and_concurrent_requests(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(vtube_module, "TOKEN_PATH", tmp_path / "token")

    async def handler(ws):
        async for raw in ws:
            request = json.loads(raw)
            kind = request["messageType"]
            seen.append(kind)
            if kind == "AuthenticationTokenRequest":
                data = {"authenticationToken": "local-test-token"}
            elif kind == "AuthenticationRequest":
                data = {"authenticated": True}
            else:
                data = {}
            await ws.send(json.dumps({"requestID": "event", "messageType": "TestEvent"}))
            await ws.send(
                json.dumps(
                    {
                        "requestID": request["requestID"],
                        "messageType": kind.replace("Request", "Response"),
                        "data": data,
                    }
                )
            )

    async def scenario():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setenv("VTUBE_STUDIO_HOST", "127.0.0.1")
            monkeypatch.setenv("VTUBE_STUDIO_PORT", str(port))
            client = VTubeClient()
            try:
                await client.connect()
                assert client.active
                await asyncio.gather(client.set_mouth(0.8), client.trigger_hotkey("talk"))
                assert client.active
            finally:
                await client.disconnect()

    asyncio.run(scenario())
    assert seen == [
        "AuthenticationTokenRequest",
        "AuthenticationRequest",
        "InjectParameterDataRequest",
        "HotkeyTriggerRequest",
    ]
