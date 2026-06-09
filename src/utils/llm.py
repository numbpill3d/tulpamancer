import os
import random
import re
import anthropic

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

_TRIGGER_POOL = [t for t, w in _TRIGGERS for _ in range(w)]

_STAGE_DIRECTION = re.compile(r"[\*\(][^\*\)]{1,40}[\*\)]")


def _pick_trigger() -> str:
    return random.choice(_TRIGGER_POOL)


def _clean(text: str) -> str:
    text = _STAGE_DIRECTION.sub("", text)
    return " ".join(text.split())


class LLMClient:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "150"))
        self.max_history = int(os.getenv("LLM_MAX_HISTORY", "20")) * 2
        self.name = os.getenv("CHARACTER_NAME", "Tulpa")
        self.system = (
            os.getenv("CHARACTER_SYSTEM_PROMPT")
            or DEFAULT_SYSTEM.format(name=self.name)
        )
        self._history: list[dict] = []

    def generate(self, context: str | None = None) -> str:
        trigger = context or _pick_trigger()
        self._history.append({"role": "user", "content": trigger})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system,
            messages=self._history[-self.max_history:],
        )

        text = _clean(response.content[0].text)
        self._history.append({"role": "assistant", "content": text})

        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]

        return text
