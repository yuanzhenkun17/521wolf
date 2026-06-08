"""Central configuration for the app/ layer.

Consolidates LLM constants, env-var loading, and path configuration for the
current app runtime.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------

LLM_BASE_URL = "https://router.shengsuanyun.com/api/v1"
LLM_DEFAULT_MODEL = "ali/qwen3.5-flash"
LLM_DEFAULT_TEMPERATURE = 0.4
LLM_DEFAULT_TIMEOUT = 45.0
LLM_DEFAULT_MAX_RETRIES = 0
LLM_DEFAULT_RETRY_INITIAL_DELAY = 1.0
LLM_DEFAULT_RETRY_MAX_DELAY = 30.0
LLM_RUNTIME_DEFAULT_MAX_ATTEMPTS = 1
LLM_RUNTIME_DEFAULT_TIMEOUT = LLM_DEFAULT_TIMEOUT
LLM_RUNTIME_DEFAULT_RETRY_INITIAL_DELAY = 0.25
LLM_RUNTIME_DEFAULT_RETRY_MAX_DELAY = 2.0
LLM_RUNTIME_DEFAULT_CIRCUIT_FAILURES = 3
LLM_RUNTIME_DEFAULT_CIRCUIT_COOLDOWN = 30.0
PROMPT_DEFAULT_MAX_TOTAL_CHARS = 24000
PROMPT_DEFAULT_MAX_MESSAGE_CHARS = 8000
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LLM_ENV_PATH = _PROJECT_ROOT / ".env"


# ---------------------------------------------------------------------------
# TTS configuration
# ---------------------------------------------------------------------------

TTS_BASE_URL = "https://api.xiaomimimo.com/v1"
TTS_DEFAULT_MODEL = "mimo-v2.5-tts"
TTS_DEFAULT_FORMAT = "wav"
TTS_DEFAULT_VOICE = "mimo_default"
TTS_DEFAULT_TIMEOUT = 60.0
TTS_DEFAULT_MAX_CHARS = 320
TTS_DEFAULT_AUTH_HEADER = "api-key"
TTS_DEFAULT_STYLE = (
    "自然、清晰、有临场感的中文狼人杀玩家发言，语速适中，情绪克制但有辨识度。"
)


def load_llm_config(
    env_path: str | Path | None = LLM_ENV_PATH,
    *,
    api_key: str | None = None,
) -> dict:
    """Load LLM configuration from environment and the configured .env file.

    Passing ``env_path=None`` skips dotenv loading, which keeps tests and
    explicit environment-only callers deterministic.
    """
    if env_path is not None:
        load_dotenv(Path(env_path), override=False)

    resolved_api_key = api_key or os.environ.get("WEREWOLF_LLM_API_KEY")
    if not resolved_api_key:
        raise RuntimeError(
            "Missing LLM API key. Set WEREWOLF_LLM_API_KEY in .env or environment."
        )

    timeout = float(os.environ.get("WEREWOLF_LLM_TIMEOUT") or LLM_DEFAULT_TIMEOUT)
    runtime_timeout = timeout

    return {
        "api_key": resolved_api_key,
        "base_url": os.environ.get("WEREWOLF_LLM_BASE_URL") or LLM_BASE_URL,
        "model": os.environ.get("WEREWOLF_LLM_MODEL") or LLM_DEFAULT_MODEL,
        "timeout": timeout,
        "temperature": float(os.environ.get("WEREWOLF_LLM_TEMPERATURE") or LLM_DEFAULT_TEMPERATURE),
        "thinking": os.environ.get("WEREWOLF_LLM_THINKING") or "disabled",
        "max_retries": int(os.environ.get("WEREWOLF_LLM_MAX_RETRIES") or LLM_DEFAULT_MAX_RETRIES),
        "retry_initial_delay": float(os.environ.get("WEREWOLF_LLM_RETRY_INITIAL_DELAY") or LLM_DEFAULT_RETRY_INITIAL_DELAY),
        "retry_max_delay": float(os.environ.get("WEREWOLF_LLM_RETRY_MAX_DELAY") or LLM_DEFAULT_RETRY_MAX_DELAY),
        "runtime_max_attempts": int(os.environ.get("WEREWOLF_LLM_RUNTIME_MAX_ATTEMPTS") or LLM_RUNTIME_DEFAULT_MAX_ATTEMPTS),
        "runtime_timeout": runtime_timeout,
        "runtime_retry_initial_delay": float(os.environ.get("WEREWOLF_LLM_RUNTIME_RETRY_INITIAL_DELAY") or LLM_RUNTIME_DEFAULT_RETRY_INITIAL_DELAY),
        "runtime_retry_max_delay": float(os.environ.get("WEREWOLF_LLM_RUNTIME_RETRY_MAX_DELAY") or LLM_RUNTIME_DEFAULT_RETRY_MAX_DELAY),
        "runtime_circuit_failures": int(os.environ.get("WEREWOLF_LLM_RUNTIME_CIRCUIT_FAILURES") or LLM_RUNTIME_DEFAULT_CIRCUIT_FAILURES),
        "runtime_circuit_cooldown": float(os.environ.get("WEREWOLF_LLM_RUNTIME_CIRCUIT_COOLDOWN") or LLM_RUNTIME_DEFAULT_CIRCUIT_COOLDOWN),
    }


def load_tts_config(
    env_path: str | Path | None = LLM_ENV_PATH,
    *,
    api_key: str | None = None,
) -> dict:
    """Load server-side TTS configuration from environment and .env."""
    if env_path is not None:
        load_dotenv(Path(env_path), override=False)

    resolved_api_key = api_key or os.environ.get("WEREWOLF_TTS_API_KEY")
    if not resolved_api_key:
        raise RuntimeError(
            "Missing TTS API key. Set WEREWOLF_TTS_API_KEY in .env or environment."
        )

    voice_pool = [
        item.strip()
        for item in (os.environ.get("WEREWOLF_TTS_VOICE_POOL") or "").split(",")
        if item.strip()
    ]

    return {
        "api_key": resolved_api_key,
        "base_url": (os.environ.get("WEREWOLF_TTS_BASE_URL") or TTS_BASE_URL).rstrip("/"),
        "model": os.environ.get("WEREWOLF_TTS_MODEL") or TTS_DEFAULT_MODEL,
        "format": os.environ.get("WEREWOLF_TTS_FORMAT") or TTS_DEFAULT_FORMAT,
        "voice": os.environ.get("WEREWOLF_TTS_VOICE") or TTS_DEFAULT_VOICE,
        "voice_pool": voice_pool,
        "auth_header": os.environ.get("WEREWOLF_TTS_AUTH_HEADER") or TTS_DEFAULT_AUTH_HEADER,
        "timeout": float(os.environ.get("WEREWOLF_TTS_TIMEOUT") or TTS_DEFAULT_TIMEOUT),
        "max_chars": int(os.environ.get("WEREWOLF_TTS_MAX_CHARS") or TTS_DEFAULT_MAX_CHARS),
        "style": os.environ.get("WEREWOLF_TTS_STYLE") or TTS_DEFAULT_STYLE,
    }


# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------


@dataclass
class PathConfig:
    """All project directories derived from a single *root*."""

    root: Path = _PROJECT_ROOT

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def games_dir(self) -> Path:
        return self.runs_dir / "games"

    @property
    def selfplay_dir(self) -> Path:
        return self.runs_dir / "selfplay"

    @property
    def evolution_dir(self) -> Path:
        return self.runs_dir / "evolution"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def versions_dir(self) -> Path:
        return self.data_dir / "versions"

    @property
    def registry_dir(self) -> Path:
        return self.data_dir / "registry"


DEFAULT_PATHS = PathConfig()
