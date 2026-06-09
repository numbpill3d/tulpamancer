import asyncio
import os
import random
from collections import deque

import websockets


class ChatClient:
    """Anonymous Twitch IRC reader. No OAuth required — read-only."""

    def __init__(self):
        self._queue: deque[str] = deque(maxlen=10)
        self._task: asyncio.Task | None = None
        self.channel = os.getenv("TWITCH_CHANNEL", "").strip().lower()

    def enabled(self) -> bool:
        return bool(self.channel)

    def pop(self) -> str | None:
        return self._queue.popleft() if self._queue else None

    def start(self) -> None:
        if self.enabled():
            self._task = asyncio.create_task(self._read_irc())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _read_irc(self) -> None:
        uri = "wss://irc-ws.chat.twitch.tv:443"
        nick = f"justinfan{random.randint(10000, 99999)}"

        while True:
            try:
                async with websockets.connect(uri) as ws:
                    await ws.send("PASS SCHMOOPIIE")
                    await ws.send(f"NICK {nick}")
                    await ws.send(f"JOIN #{self.channel}")
                    print(f"[chat] joined #{self.channel}")

                    async for raw in ws:
                        if "PRIVMSG" in raw:
                            user, msg = _parse_privmsg(raw)
                            if user and msg:
                                self._queue.append(f"[chat: {user}: {msg}]")
                        elif raw.startswith("PING"):
                            await ws.send("PONG :tmi.twitch.tv")

            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[chat] disconnected ({e}), reconnecting in 10s...")
                await asyncio.sleep(10)


def _parse_privmsg(raw: str) -> tuple[str, str]:
    try:
        # IRCv3 tagged lines start with @; the IRC command follows the first " :"
        line = raw.split(" :", 1)[1] if raw.startswith("@") else raw
        user = line.split("!")[0].lstrip(":")
        msg = line.split("PRIVMSG", 1)[1].split(":", 1)[1].strip()
        return user, msg
    except (IndexError, ValueError):
        return "", ""
