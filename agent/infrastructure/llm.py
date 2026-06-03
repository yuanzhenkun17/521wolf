"""Model adapter — LLM interface for the agent runtime.

Defines the ``ModelAdapter`` protocol and the default
``ChatCompletionClient`` backed by the OpenAI SDK.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv

from agent.infrastructure.tracing import tracing_enabled


DEFAULT_BASE_URL = "https://router.shengsuanyun.com/api/v1"
DEFAULT_MODEL = "ali/qwen3.5-flash"
DEFAULT_ENV_PATH = Path(".env")


class ModelAdapter(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Return assistant content for a chat-completion style request."""


@dataclass
class ChatCompletionClient:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 45.0
    temperature: float = 0.4
    thinking: str = "disabled"
    max_retries: int = 5
    retry_initial_delay: float = 1.0
    retry_max_delay: float = 30.0

    _client: Any | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def _get_client(self) -> Any:
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    client_cls = _async_openai_client()
                    self._client = client_cls(
                        api_key=self.api_key,
                        base_url=self.base_url,
                        timeout=self.timeout,
                    )
        return self._client

    async def complete(self, messages: list[dict[str, str]]) -> str:
        client = await self._get_client()
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.thinking:
            kwargs["extra_body"] = {"thinking": {"type": self.thinking}}
        attempt = 0
        while True:
            try:
                response = await client.chat.completions.create(**kwargs)
                if not response.choices:
                    raise ValueError("LLM returned empty choices")
                return response.choices[0].message.content or ""
            except Exception as exc:
                attempt += 1
                if attempt > self.max_retries or not _is_retryable_llm_error(exc):
                    raise
                await asyncio.sleep(_retry_delay(exc, attempt, self.retry_initial_delay, self.retry_max_delay))


@dataclass
class LimitedModelAdapter:
    """Model adapter wrapper that bounds concurrent LLM requests."""

    inner: ModelAdapter
    semaphore: asyncio.Semaphore

    async def complete(self, messages: list[dict[str, str]]) -> str:
        async with self.semaphore:
            return await self.inner.complete(messages)


@dataclass
class AsyncRateLimiter:
    """Simple process-local request pacer for RPM-style provider limits."""

    requests_per_minute: int
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _next_at: float = field(default=0.0, init=False, repr=False)

    async def wait(self) -> None:
        if self.requests_per_minute <= 0:
            return
        interval = 60.0 / float(self.requests_per_minute)
        async with self._lock:
            now = time.monotonic()
            wait_for = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + interval
        if wait_for > 0:
            await asyncio.sleep(wait_for)


@dataclass
class RateLimitedModelAdapter:
    """Model adapter wrapper that spaces requests over time."""

    inner: ModelAdapter
    limiter: AsyncRateLimiter

    async def complete(self, messages: list[dict[str, str]]) -> str:
        await self.limiter.wait()
        return await self.inner.complete(messages)


def limit_model_adapter(
    model: ModelAdapter,
    semaphore: asyncio.Semaphore | None,
) -> ModelAdapter:
    """Wrap *model* with a concurrency limiter when a semaphore is provided."""
    if semaphore is None:
        return model
    if _has_semaphore_limiter(model, semaphore):
        return model
    return LimitedModelAdapter(inner=model, semaphore=semaphore)


def rate_limit_model_adapter(
    model: ModelAdapter,
    limiter: AsyncRateLimiter | None,
) -> ModelAdapter:
    """Wrap *model* with an RPM limiter when one is provided."""
    if limiter is None:
        return model
    if _has_rate_limiter(model, limiter):
        return model
    return RateLimitedModelAdapter(inner=model, limiter=limiter)


def default_rate_limiter_from_env() -> AsyncRateLimiter | None:
    """Build an RPM limiter from WEREWOLF_LLM_RPM when configured."""
    load_dotenv(DEFAULT_ENV_PATH)
    raw = os.environ.get("WEREWOLF_LLM_RPM")
    if not raw:
        return None
    try:
        rpm = int(raw)
    except ValueError:
        return None
    return AsyncRateLimiter(rpm) if rpm > 0 else None


def load_llm_client(
    env_path: str | Path | None = DEFAULT_ENV_PATH,
    *,
    model_name: str | None = None,
    temperature: float | None = None,
) -> ChatCompletionClient:
    if env_path is not None:
        load_dotenv(Path(env_path))
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
        thinking=os.environ.get("WEREWOLF_LLM_THINKING") or "disabled",
        max_retries=int(os.environ.get("WEREWOLF_LLM_MAX_RETRIES") or 5),
        retry_initial_delay=float(os.environ.get("WEREWOLF_LLM_RETRY_INITIAL_DELAY") or 1.0),
        retry_max_delay=float(os.environ.get("WEREWOLF_LLM_RETRY_MAX_DELAY") or 30.0),
    )




def _async_openai_client() -> Any:
    if tracing_enabled():
        from langfuse.openai import AsyncOpenAI

        return AsyncOpenAI
    from openai import AsyncOpenAI

    return AsyncOpenAI



def _is_retryable_llm_error(exc: Exception) -> bool:
    status = _error_status_code(exc)
    if status == 429 or (status is not None and 500 <= status <= 599):
        return True
    text = str(exc).lower()
    return (
        "rate limit" in text
        or "too many requests" in text
        or "429" in text
        or "timeout" in text
        or "temporarily unavailable" in text
    )


def _has_semaphore_limiter(model: ModelAdapter, semaphore: asyncio.Semaphore) -> bool:
    current: Any = model
    while current is not None:
        if isinstance(current, LimitedModelAdapter) and current.semaphore is semaphore:
            return True
        current = getattr(current, "inner", None)
    return False


def _has_rate_limiter(model: ModelAdapter, limiter: AsyncRateLimiter) -> bool:
    current: Any = model
    while current is not None:
        if isinstance(current, RateLimitedModelAdapter) and current.limiter is limiter:
            return True
        current = getattr(current, "inner", None)
    return False


def _error_status_code(exc: Exception) -> int | None:
    for obj in (exc, getattr(exc, "response", None)):
        status = getattr(obj, "status_code", None)
        if status is None:
            status = getattr(obj, "status", None)
        if status is not None:
            try:
                return int(status)
            except (TypeError, ValueError):
                pass
    return None


def _retry_delay(exc: Exception, attempt: int, initial: float, maximum: float) -> float:
    retry_after = _retry_after_seconds(exc)
    if retry_after is not None:
        return min(maximum, max(0.0, retry_after))
    base = min(maximum, initial * (2 ** max(0, attempt - 1)))
    jitter = random.uniform(0.0, min(1.0, base * 0.25))
    return min(maximum, base + jitter)


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers: Any = getattr(response, "headers", None)
    if not headers:
        headers = getattr(exc, "headers", None)
    if not headers:
        return None
    value = None
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
