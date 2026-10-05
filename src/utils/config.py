"""Environment parsing shared by the CLI and clients (never logs secrets)."""

import math
import os
import tempfile
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit


def env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        raise ValueError(f"{name} must be a boolean (1/0, true/false)")
    return value in {"1", "true", "yes", "on"}


def env_number(name: str, default, minimum, maximum=None):
    kind = int if isinstance(default, int) else float
    try:
        value = kind(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a valid {kind.__name__}") from None
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        upper = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be >= {minimum}{upper}")
    return value


def bypass_proxy_for_loopback(host: str | None) -> None:
    """Keep local Ollama and VTube Studio traffic off configured proxies."""
    if not host:
        return
    try:
        is_loopback = ip_address(host).is_loopback
    except ValueError:
        is_loopback = host.rstrip(".").lower() == "localhost"
    if not is_loopback:
        return

    entries = []
    for name in ("NO_PROXY", "no_proxy"):
        entries.extend(item.strip() for item in os.getenv(name, "").split(",") if item.strip())
    if host not in entries:
        entries.append(host)
    value = ",".join(dict.fromkeys(entries))
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    base_url: str | None
    api_key: str = field(repr=False)
    timeout: float
    max_tokens: int
    max_history: int

    @classmethod
    def from_env(cls):
        provider = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
        defaults = {
            "anthropic": (None, "claude-haiku-4-5-20251001"),
            "ollama": ("http://localhost:11434/v1", "llama3.2"),
            "groq": ("https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
            "openrouter": ("https://openrouter.ai/api/v1", None),
            "openai": ("https://api.openai.com/v1", None),
        }
        base, model = defaults.get(provider, (None, None))
        base = os.getenv("LLM_BASE_URL", "").strip() or base
        model = os.getenv("LLM_MODEL", "").strip() or model
        if not model:
            raise ValueError("Set LLM_MODEL to a model available from your provider")
        if provider != "anthropic":
            if not base:
                raise ValueError("Set LLM_BASE_URL for your OpenAI-compatible provider")
            parsed = urlsplit(base)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("LLM_BASE_URL must be an http(s) URL")
        key_name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "LLM_API_KEY"
        key = os.getenv(key_name, "").strip()
        if provider == "ollama" and not key:
            key = "ollama"
        if not key or "your_key" in key or "your-key" in key:
            raise ValueError(f"Set {key_name} in .env or the environment")
        return cls(
            provider,
            model,
            base,
            key,
            env_number("LLM_TIMEOUT", 60.0, 0.1),
            env_number("LLM_MAX_TOKENS", 150, 1),
            env_number("LLM_MAX_HISTORY", 20, 1),
        )


@dataclass(frozen=True)
class RuntimeSettings:
    name: str
    interval: float
    lipsync: bool
    fps: int
    subtitle_path: Path
    retry_delay: float
    max_failures: int

    @classmethod
    def from_env(cls):
        default_subtitle = str(Path(tempfile.gettempdir()) / "tulpamancer_sub.txt")
        return cls(
            os.getenv("CHARACTER_NAME", "Tulpa").strip() or "Tulpa",
            env_number("SPEECH_INTERVAL", 2.0, 0),
            env_bool("LIPSYNC_ENABLED"),
            env_number("LIPSYNC_FPS", 24, 1, 120),
            Path(os.getenv("SUBTITLE_PATH", "").strip() or default_subtitle).expanduser(),
            env_number("RETRY_DELAY", 10.0, 0),
            env_number("MAX_GENERATION_FAILURES", 3, 1),
        )
