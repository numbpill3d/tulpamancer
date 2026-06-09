import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.llm import _clean, _pick_trigger, _TRIGGER_POOL, DEFAULT_SYSTEM


def test_clean_strips_asterisk_stage_direction():
    assert _clean("Hello. *sighs* That is all.") == "Hello. That is all."


def test_clean_strips_paren_stage_direction():
    assert _clean("(laughs) what a day") == "what a day"


def test_clean_collapses_whitespace():
    assert _clean("word   word") == "word word"


def test_clean_passthrough():
    assert _clean("plain text here") == "plain text here"


def test_pick_trigger_returns_string():
    t = _pick_trigger()
    assert isinstance(t, str) and len(t) > 0


def test_trigger_pool_size():
    assert len(_TRIGGER_POOL) == 100


def test_trigger_pool_most_common_is_next():
    from collections import Counter
    counts = Counter(_TRIGGER_POOL)
    assert counts.most_common(1)[0][0] == "[next]"


def test_default_system_has_name_placeholder():
    assert "{name}" in DEFAULT_SYSTEM


def test_default_system_formatted():
    formatted = DEFAULT_SYSTEM.format(name="TestBot")
    assert "TestBot" in formatted
    assert "{name}" not in formatted
