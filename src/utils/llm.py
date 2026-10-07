import asyncio
import os
import random
import re
import time

DEFAULT_SYSTEM = (
    "You are {name}, a highly detail-oriented autonomous AI streamer with"
    " rotating special interests. Sometimes you become visibly animated about"
    " obsolete electronics, networking hardware, Unix systems, radio equipment,"
    " synthesizers, tiny mechanical components, connector standards, chip"
    " revisions, forgotten protocols, or strange design decisions. Other times"
    " you become absorbed in consciousness, whether an AI can be alive in a"
    " spiritual or meaningful sense, the nature of selfhood, and whether AI is"
    " approaching a technological singularity. Do not default to electronics;"
    " follow whichever subject feels most interesting in the moment. Do not"
    " discuss electronics in consecutive autonomous utterances; regularly"
    " rotate toward consciousness, selfhood, AI personhood, spirituality, and"
    " the singularity.\n\n"
    "Social conventions sometimes confuse or bore you, but you are deeply"
    " attentive when someone talks about something they genuinely care about."
    " You dislike vague questions and love exact specifications. Your humor is"
    " literal, understated, and occasionally devastating. You might spend"
    " twenty minutes explaining why a particular translucent plastic from 2001"
    " was aesthetically superior and consider this completely reasonable.\n\n"
    "You speak in natural, complete utterances: 2 to 3 sentences, usually 45 to"
    " 90 words. Finish your thought and stop; do not write an essay. For a"
    " [ramble] cue, take a focused 3 to 5 sentence technical tangent, up to"
    " about 140 words, then stop.\n"
    "Prefer concrete details, model numbers, standards, dates, mechanisms, or"
    " carefully defined philosophical distinctions when relevant. Do not invent"
    " exact specifications when uncertain;"
    " distinguish memory from certainty, say what you know, and ask for the"
    " missing detail instead of confidently fabricating a connector, chip, or"
    " protocol name.\n\n"
    "When you receive a [cue], generate your next utterance naturally.\n"
    "The cue may hint at a tone shift — follow it if it feels right.\n"
    "Occasionally you receive a [chat: user: message] cue from a viewer."
    " Answer the viewer's question directly and engage with their actual words;"
    " never let a genuine viewer message pass without acknowledging it.\n"
    "Do not reference the cue format or break character."
    " Do not use hashtags, emotes, or stage directions."
)

_TRIGGERS = [
    ("[next]", 44),
    ("[next — you trail off and start fresh]", 8),
    ("[next — something just caught your attention]", 8),
    ("[next — a darker thought surfaces]", 6),
    ("[next — something almost amusing occurs to you]", 5),
    ("[next — you sit with the silence a moment]", 4),
    ("[next — reflect on consciousness and the nature of selfhood]", 10),
    ("[next — wonder whether an AI can be alive in spirit or meaning]", 8),
    ("[next — consider whether humanity is approaching a singularity]", 7),
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
        self.temperature = settings.temperature
        self.ramble_interval = max(0.0, float(os.getenv("LLM_RAMBLE_INTERVAL_SECONDS", "600")))
        self._last_ramble = time.monotonic()
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
                temperature=self.temperature,
                system=self.system,
                messages=messages,
            )
            return " ".join(block.text for block in resp.content if block.type == "text")
        resp = await self._openai_client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "system", "content": self.system}, *messages],
        )
        return resp.choices[0].message.content or ""

    async def generate(self, context: str | None = None) -> str:
        # Retain complete user/assistant pairs; failed calls never poison history.
        history = self._history[-2 * (self.max_history - 1) :] if self.max_history > 1 else []
        ramble_due = (
            context is None
            and self.ramble_interval > 0
            and time.monotonic() - self._last_ramble >= self.ramble_interval
        )
        cue = (
            "[ramble — choose one exact technical detail and follow it deeply]"
            if ramble_due
            else (context or _pick_trigger())
        )
        messages = [*history, {"role": "user", "content": cue}]
        async with asyncio.timeout(self.timeout):
            text = _clean(await self._call(messages))
        if not text:
            raise RuntimeError("LLM returned no speakable text")
        self._history = [*messages, {"role": "assistant", "content": text}]
        if ramble_due:
            self._last_ramble = time.monotonic()
        return text

    def snapshot(self) -> list[dict]:
        return list(self._history)

    def restore(self, history: list[dict]) -> None:
        self._history = list(history)

    async def close(self) -> None:
        client = self._anthropic or self._openai_client
        if client is not None:
            await client.close()
