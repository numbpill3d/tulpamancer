import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.llm import (
    DEFAULT_SYSTEM,
    _TRIGGER_PHRASES,
    _TRIGGER_WEIGHTS,
    _clean,
    _pick_trigger,
)


def test_clean_strips_asterisk_stage_direction():
    assert _clean("Hello. *sighs* That is all.") == "Hello. That is all."


def test_clean_strips_paren_stage_direction():
    assert _clean("(laughs) what a day") == "what a day"


def test_clean_does_not_strip_cross_delimiter():
    # *foo) is not a stage direction — fixed regex must leave it alone
    assert "*foo)" in _clean("text *foo) more")


def test_clean_collapses_whitespace():
    assert _clean("word   word") == "word word"


def test_clean_passthrough():
    assert _clean("plain text here") == "plain text here"


def test_pick_trigger_returns_string():
    t = _pick_trigger()
    assert isinstance(t, str) and len(t) > 0


def test_trigger_weights_sum_to_100():
    assert sum(_TRIGGER_WEIGHTS) == 100


def test_trigger_most_weighted_is_next():
    max_weight = max(_TRIGGER_WEIGHTS)
    top_phrase = _TRIGGER_PHRASES[_TRIGGER_WEIGHTS.index(max_weight)]
    assert top_phrase == "[next]"


def test_trigger_phrases_and_weights_same_length():
    assert len(_TRIGGER_PHRASES) == len(_TRIGGER_WEIGHTS)


def test_default_system_has_name_placeholder():
    assert "{name}" in DEFAULT_SYSTEM


def test_default_system_formatted():
    formatted = DEFAULT_SYSTEM.format(name="TestBot")
    assert "TestBot" in formatted
    assert "{name}" not in formatted
