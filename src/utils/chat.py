import asyncio
import os
import random
import re
from collections import deque

import websockets


class ChatClient:
    """Anonymous Twitch IRC reader. No OAuth required — read-only."""

    def __init__(self):
        self._queue: deque[str] = deque(maxlen=10)
        self._task: asyncio.Task | None = None
        self.channel = os.getenv("TWITCH_CHANNEL", "").strip().lower().lstrip("#")
        if self.channel and not re.fullmatch(r"[a-z0-9_]+", self.channel):
            raise ValueError("TWITCH_CHANNEL must be a channel name, not a URL")

    def enabled(self) -> bool:
        return bool(self.channel)

    def pop(self) -> str | None:
        return self._queue.popleft() if self._queue else None

    def start(self) -> None:
        if self.enabled() and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._read_irc())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _handle_frame(self, raw: str, ws) -> None:
        # Twitch may batch several IRC lines in one WebSocket frame.
        for line in raw.splitlines():
            if line.startswith("PING "):
                await ws.send("PONG " + line[5:] + "\r\n")
                continue
            command = line.split(" ")
            if "RECONNECT" in command[:2]:
                raise ConnectionError("Twitch requested reconnect")
            user, msg = _parse_privmsg(line)
            if user and msg:
                self._queue.append(f"[chat: {user}: {msg[:500]}]")

    async def _read_irc(self) -> None:
        uri = "wss://irc-ws.chat.twitch.tv:443"
        while True:
            try:
                async with websockets.connect(uri, open_timeout=10, close_timeout=2) as ws:
                    nick = f"justinfan{random.randint(10000, 99999)}"
                    await ws.send("PASS SCHMOOPIIE\r\n")
                    await ws.send(f"NICK {nick}\r\n")
                    await ws.send(f"JOIN #{self.channel}\r\n")
                    print(f"[chat] reading #{self.channel}")
                    async for raw in ws:
                        if isinstance(raw, str):
                            await self._handle_frame(raw, ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[chat] disconnected ({type(exc).__name__}), retrying in 10s")
            # Back off even when the server closes the connection normally.
            await asyncio.sleep(10)


_PRIVMSG = re.compile(r"^(?:@\S+ )?:(\w+)![^ ]+ PRIVMSG #[^ ]+ :(.*)$")


def _parse_privmsg(raw: str) -> tuple[str, str]:
    match = _PRIVMSG.fullmatch(raw.rstrip("\r\n"))
    return (match[1], match[2].strip()) if match else ("", "")
