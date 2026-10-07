import asyncio
import os
import random
import re
import time
from collections import deque

import websockets


class ChatClient:
    """Twitch IRC reader with optional authenticated output."""

    def __init__(self):
        self._queue: deque[str] = deque(maxlen=10)
        self._task: asyncio.Task | None = None
        self._message_event = asyncio.Event()
        self.channel = os.getenv("TWITCH_CHANNEL", "").strip().lower().lstrip("#")
        self.username = os.getenv("TWITCH_BOT_USERNAME", "").strip().lower()
        self.oauth_token = os.getenv("TWITCH_OAUTH_TOKEN", "").strip()
        self.send_enabled = os.getenv("TWITCH_SEND_ENABLED", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            self.send_interval = max(1.0, float(os.getenv("TWITCH_SEND_INTERVAL", "5")))
        except ValueError:
            raise ValueError("TWITCH_SEND_INTERVAL must be a valid number") from None
        self.can_send = bool(
            self.send_enabled and self.channel and self.username and self.oauth_token
        )
        self._ws = None
        self._last_send = 0.0
        self.ignored_users = {
            user.strip().lower()
            for user in os.getenv("TWITCH_IGNORED_USERS", "").split(",")
            if user.strip()
        }
        self.blocked_terms = {
            term.strip().lower()
            for term in os.getenv("TWITCH_BLOCKED_TERMS", "").split(",")
            if term.strip()
        }
        try:
            self.max_messages_per_minute = max(
                1, int(os.getenv("TWITCH_MAX_MESSAGES_PER_MINUTE", "30"))
            )
        except ValueError:
            raise ValueError("TWITCH_MAX_MESSAGES_PER_MINUTE must be an integer") from None
        self._received: deque[float] = deque(maxlen=100)
        if self.channel and not re.fullmatch(r"[a-z0-9_]+", self.channel):
            raise ValueError("TWITCH_CHANNEL must be a channel name, not a URL")

    def enabled(self) -> bool:
        return bool(self.channel)

    def pop(self) -> str | None:
        message = self._queue.popleft() if self._queue else None
        if message:
            print("[chat] delivering viewer message to Tulpa")
        return message

    async def wait_for_message(self) -> None:
        """Wake a speech prefetch when a viewer message is waiting."""
        while not self._queue:
            await self._message_event.wait()
            self._message_event.clear()
        self._message_event.clear()

    def start(self) -> None:
        if self.enabled() and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._read_irc())

    async def send_message(self, message: str) -> bool:
        """Send a chat line when authenticated; return whether it was sent.

        The reader connection is deliberately kept separate from output so a
        transient send failure cannot interrupt the speech loop.
        """
        if not self.can_send or not message.strip():
            return False
        wait = self.send_interval - (time.monotonic() - self._last_send)
        if wait > 0:
            await asyncio.sleep(wait)
        # Twitch IRC output needs a live authenticated connection.  Keep the
        # operation bounded and use the same connection used by the reader.
        ws = self._ws
        if ws is None:
            return False
        try:
            line = " ".join(message.split())[:500]
            await ws.send(f"PRIVMSG #{self.channel} :{line}\r\n")
            self._last_send = time.monotonic()
            return True
        except Exception as exc:
            print(f"[chat] send failed ({type(exc).__name__})")
            return False

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
            if " 001 " in line:
                print(f"[chat] Twitch IRC accepted connection for #{self.channel}")
                continue
            if " NOTICE " in line:
                notice = line.split(" :", 1)[-1].strip()
                print(f"[chat] Twitch notice: {notice[:200]}")
                continue
            command = line.split(" ")
            if "RECONNECT" in command[:2]:
                raise ConnectionError("Twitch requested reconnect")
            user, msg = _parse_privmsg(line)
            if user and msg and self._accept_message(user, msg):
                self._queue.append(f"[chat: {user}: {msg[:500]}]")
                print(f"[chat] queued message from {user}")
                self._message_event.set()

    def _accept_message(self, user: str, message: str) -> bool:
        now = time.monotonic()
        while self._received and now - self._received[0] >= 60:
            self._received.popleft()
        if (
            user.lower() in self.ignored_users
            or len(self._received) >= self.max_messages_per_minute
        ):
            return False
        clean = "".join(char for char in message if char.isprintable()).strip()
        if not clean or clean.startswith(("!", "/")):
            return False
        lowered = clean.lower()
        if any(term in lowered for term in self.blocked_terms):
            return False
        self._received.append(now)
        return True

    async def _read_irc(self) -> None:
        uri = "wss://irc-ws.chat.twitch.tv:443"
        while True:
            try:
                async with websockets.connect(uri, open_timeout=10, close_timeout=2) as ws:
                    nick = self.username or f"justinfan{random.randint(10000, 99999)}"
                    password = f"oauth:{self.oauth_token}" if self.can_send else "SCHMOOPIIE"
                    await ws.send(f"PASS {password}\r\n")
                    await ws.send(f"NICK {nick}\r\n")
                    await ws.send(f"JOIN #{self.channel}\r\n")
                    self._ws = ws
                    print(f"[chat] reading #{self.channel}")
                    async for raw in ws:
                        if isinstance(raw, str):
                            await self._handle_frame(raw, ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[chat] disconnected ({type(exc).__name__}), retrying in 10s")
            finally:
                self._ws = None
            # Back off even when the server closes the connection normally.
            await asyncio.sleep(10)


_PRIVMSG = re.compile(r"^(?:@\S+ )?:(\w+)![^ ]+ PRIVMSG #[^ ]+ :(.*)$")


def _parse_privmsg(raw: str) -> tuple[str, str]:
    match = _PRIVMSG.fullmatch(raw.rstrip("\r\n"))
    return (match[1], match[2].strip()) if match else ("", "")
