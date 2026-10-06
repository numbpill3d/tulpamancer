"""Small deterministic emotion classifier for avatar hotkeys."""

import re


_WORDS = {
    "wave": ("hello", "hi there", "welcome", "goodbye", "bye"),
    "laugh": ("lol", "lmao", "haha", "hehe"),
    "excited": ("!!!", "excited", "amazing", "yay", "woah", "finally"),
    "happy": ("glad", "happy", "love", "wonderful", "thank"),
    "sad": ("sad", "sorry", "lonely", "miss", "hurt"),
    "angry": ("angry", "hate", "furious", "mad"),
    "surprised": ("surprise", "shocked", "unexpected", "wait, what"),
    "confused": ("confused", "wonder", "how does", "what do you mean"),
    "love": ("adore", "dear", "precious", "beautiful"),
}


def detect_emote(text: str) -> str:
    """Choose a named animation profile from the generated line."""
    lowered = text.lower()
    for emote, words in _WORDS.items():
        if any(
            word in lowered if word == "!!!" else re.search(rf"\b{re.escape(word)}\b", lowered)
            for word in words
        ):
            return emote
    return "neutral"


def detect_emotion(text: str) -> str:
    return detect_emote(text)
