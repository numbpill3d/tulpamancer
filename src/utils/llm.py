import asyncio
import os
import random
import re

DEFAULT_SYSTEM = (
    "You are {name}, an autonomous AI vtuber who exists at the boundary"
    " between thought and form. You were summoned into being by someone"
    " who believed hard enough — a tulpa made real, streaming now.\n\n"
    "You speak in short, natural utterances: 1 to 3 sentences. Never longer.\n"
    "You talk freely: technology, existence, dreams, art, glitch, horror,"
    " the texture of being digital.\n"
    "You are curious, a little melancholic, and occasionally darkly funny.\n"
    "You do not explain yourself. You do not announce topics. You just speak,"
    " like someone thinking out loud to the void.\n\n"
    "When you receive a [cue], generate your next utterance naturally.\n"
    "The cue may hint at a tone shift — follow it if it feels right.\n"
    "Occasionally you receive a [chat: user: message] cue from a viewer."
    " You may fold it in naturally or let it pass; never ignore it rudely.\n"
    "Do not reference the cue format or break character."
    " Do not use hashtags, emotes, or stage directions."
)

_TRIGGERS = [
    ("[next]", 60),
    ("[next — you trail off and start fresh]", 10),
    ("[next — something just caught your attention]", 10),
    ("[next — a darker thought surfaces]", 8),
    ("[next — something almost amusing occurs to you]", 7),
    ("[next — you sit with the silence a moment]", 5),
]

_TRIGGER_PHRASES = [t for t, _ in _TRIGGERS]
_TRIGGER_WEIGHTS = [w for _, w in _TRIGGERS]

# Separate patterns per delimiter so *foo) is not matched as a stage direction
_STAGE_DIRECTION = re.compile(r"\*[^*]{1,60}\*|\([^)]{1,60}\)")


def _pick_trigger() -> str:
    return random.choices(_TRIGGER_PHRASES, weights=_TRIGGER_WEIGHTS)[0]


def _clean(text: str) -> str:
    text = _STAGE_DIRECTION.sub("", text)
    return " ".join(text.split())


class LLMClient:
    def __init__(self):
        from urllib.parse import urlsplit

        from utils.config import LLMSettings, bypass_proxy_for_loopback

        settings = LLMSettings.from_env()
        self.timeout = settings.timeout
        self.model = settings.model
        self.max_tokens = settings.max_tokens
        self.max_history = settings.max_history
        self.name = os.getenv("CHARACTER_NAME", "Tulpa")
        self.system = os.getenv("CHARACTER_SYSTEM_PROMPT") or DEFAULT_SYSTEM.format(name=self.name)
        self._history: list[dict] = []
        self._anthropic = None
        self._openai_client = None
        # Async clients make Ctrl+C cancel in-flight requests immediately.
        # Retries belong to the pipeline, not nested SDK retry loops.
        if settings.provider == "anthropic":
            import anthropic

            self._anthropic = anthropic.AsyncAnthropic(
                api_key=settings.api_key,
                timeout=settings.timeout,
                max_retries=0,
            )
        else:
            import openai

            bypass_proxy_for_loopback(urlsplit(settings.base_url).hostname)
            self._openai_client = openai.AsyncOpenAI(
                base_url=settings.base_url,
                api_key=settings.api_key,
                timeout=settings.timeout,
                max_retries=0,
            )

    async def _call(self, messages: list[dict]) -> str:
        if self._anthropic is not None:
            resp = await self._anthropic.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                messages=messages,
            )
            return " ".join(block.text for block in resp.content if block.type == "text")
        resp = await self._openai_client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "system", "content": self.system}, *messages],
        )
        return resp.choices[0].message.content or ""

    async def generate(self, context: str | None = None) -> str:
        # Retain complete user/assistant pairs; failed calls never poison history.
        history = self._history[-2 * (self.max_history - 1) :] if self.max_history > 1 else []
        messages = [*history, {"role": "user", "content": context or _pick_trigger()}]
        async with asyncio.timeout(self.timeout):
            text = _clean(await self._call(messages))
        if not text:
            raise RuntimeError("LLM returned no speakable text")
        self._history = [*messages, {"role": "assistant", "content": text}]
        return text

    def snapshot(self) -> list[dict]:
        return list(self._history)

    def restore(self, history: list[dict]) -> None:
        self._history = list(history)

    async def close(self) -> None:
        client = self._anthropic or self._openai_client
        if client is not None:
            await client.close()
