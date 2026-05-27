"""Model adapter — LLM interface for the agent runtime.

Defines the ``ModelAdapter`` protocol and the default
``ChatCompletionClient`` backed by the OpenAI SDK.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from langfuse.openai import AsyncOpenAI


DEFAULT_BASE_URL = "https://router.shengsuanyun.com/api/v1"
DEFAULT_MODEL = "ali/qwen3.5-flash"
DEFAULT_ENV_PATH = Path(".env")


class ModelAdapter(Protocol):
    async def complete(self, messages: list[dict[str, str]], *, name: str = "") -> str:
        """Return assistant content for a chat-completion style request."""


@dataclass
class ChatCompletionClient:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 45.0
    temperature: float = 0.4

    _client: AsyncOpenAI | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = AsyncOpenAI(
                        api_key=self.api_key,
                        base_url=self.base_url,
                        timeout=self.timeout,
                    )
        return self._client

    async def complete(self, messages: list[dict[str, str]], *, name: str = "") -> str:
        client = await self._get_client()
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if name:
            kwargs["name"] = name
        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content


def load_llm_client(
    env_path: str | Path | None = DEFAULT_ENV_PATH,
    *,
    model_name: str | None = None,
    temperature: float | None = None,
) -> ChatCompletionClient:
    if env_path is not None:
        _load_dotenv(Path(env_path))
    api_key = os.environ.get("WEREWOLF_LLM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing LLM API key. Set WEREWOLF_LLM_API_KEY in .env or environment."
        )
    return ChatCompletionClient(
        api_key=api_key,
        base_url=os.environ.get("WEREWOLF_LLM_BASE_URL") or DEFAULT_BASE_URL,
        model=os.environ.get("WEREWOLF_LLM_MODEL") or model_name or DEFAULT_MODEL,
        timeout=float(os.environ.get("WEREWOLF_LLM_TIMEOUT") or 45.0),
        temperature=float(
            os.environ.get("WEREWOLF_LLM_TEMPERATURE")
            or (temperature if temperature is not None else 0.4)
        ),
    )


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from .env into os.environ without overriding existing vars."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = _strip_env_value(value.strip())
        os.environ.setdefault(key, value)


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if " #" in value:
        return value.split(" #", 1)[0].rstrip()
    return value
