import pytest

from utils.config import LLMSettings, RuntimeSettings, env_bool


@pytest.mark.parametrize("value", ["FALSE", "0", "No", "off"])
def test_false_flags_ignore_case(monkeypatch, value):
    monkeypatch.setenv("LIPSYNC_ENABLED", value)
    assert not env_bool("LIPSYNC_ENABLED")


@pytest.mark.parametrize(
    "key,value",
    [
        ("LIPSYNC_FPS", "0"),
        ("LIPSYNC_FPS", "121"),
        ("SPEECH_INTERVAL", "-1"),
        ("SPEECH_INTERVAL", "nan"),
        ("SPEECH_INTERVAL", "inf"),
        ("MAX_GENERATION_FAILURES", "0"),
        ("LIPSYNC_ENABLED", "maybe"),
    ],
)
def test_invalid_runtime_values(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        RuntimeSettings.from_env()


def test_ollama_needs_no_key_and_uses_local_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    settings = LLMSettings.from_env()
    assert settings.api_key == "ollama"
    assert settings.base_url == "http://localhost:11434/v1"
    assert settings.model == "llama3.2"


def test_unknown_provider_needs_explicit_model_and_url(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    with pytest.raises(ValueError, match="LLM_MODEL"):
        LLMSettings.from_env()
    monkeypatch.setenv("LLM_MODEL", "test")
    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        LLMSettings.from_env()


def test_placeholder_key_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_key_here")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        LLMSettings.from_env()
