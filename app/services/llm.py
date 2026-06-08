"""LLM factory — single source of truth for ChatOpenAI creation.

Provides:
- create_llm() — main factory
- load_llm_client() — backward-compat alias
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import (
    LLM_BASE_URL,
    LLM_DEFAULT_MAX_RETRIES,
    LLM_DEFAULT_MODEL,
    LLM_DEFAULT_RETRY_INITIAL_DELAY,
    LLM_DEFAULT_RETRY_MAX_DELAY,
    LLM_DEFAULT_TEMPERATURE,
    LLM_DEFAULT_TIMEOUT,
    LLM_ENV_PATH,
    LLM_RUNTIME_DEFAULT_CIRCUIT_COOLDOWN,
    LLM_RUNTIME_DEFAULT_CIRCUIT_FAILURES,
    LLM_RUNTIME_DEFAULT_MAX_ATTEMPTS,
    LLM_RUNTIME_DEFAULT_RETRY_INITIAL_DELAY,
    LLM_RUNTIME_DEFAULT_RETRY_MAX_DELAY,
    LLM_RUNTIME_DEFAULT_TIMEOUT,
    load_llm_config,
)

DEFAULT_BASE_URL = LLM_BASE_URL
DEFAULT_MODEL = LLM_DEFAULT_MODEL
DEFAULT_ENV_PATH = LLM_ENV_PATH
DEFAULT_TEMPERATURE = LLM_DEFAULT_TEMPERATURE
DEFAULT_TIMEOUT = LLM_DEFAULT_TIMEOUT
DEFAULT_MAX_RETRIES = LLM_DEFAULT_MAX_RETRIES
DEFAULT_RETRY_INITIAL_DELAY = LLM_DEFAULT_RETRY_INITIAL_DELAY
DEFAULT_RETRY_MAX_DELAY = LLM_DEFAULT_RETRY_MAX_DELAY
DEFAULT_RUNTIME_TIMEOUT = LLM_RUNTIME_DEFAULT_TIMEOUT
DEFAULT_RUNTIME_MAX_ATTEMPTS = LLM_RUNTIME_DEFAULT_MAX_ATTEMPTS
DEFAULT_RUNTIME_RETRY_INITIAL_DELAY = LLM_RUNTIME_DEFAULT_RETRY_INITIAL_DELAY
DEFAULT_RUNTIME_RETRY_MAX_DELAY = LLM_RUNTIME_DEFAULT_RETRY_MAX_DELAY
DEFAULT_RUNTIME_CIRCUIT_FAILURES = LLM_RUNTIME_DEFAULT_CIRCUIT_FAILURES
DEFAULT_RUNTIME_CIRCUIT_COOLDOWN = LLM_RUNTIME_DEFAULT_CIRCUIT_COOLDOWN

_POLICY_ATTR = "_wolf_llm_runtime_policy"


@dataclass(frozen=True)
class LLMRuntimePolicy:
    """Transport-level LLM invocation policy.

    This layer only retries transient invocation failures. JSON/schema parsing
    happens after the model returns and is intentionally not retried here.
    """

    max_attempts: int = DEFAULT_RUNTIME_MAX_ATTEMPTS
    timeout: float | None = DEFAULT_RUNTIME_TIMEOUT
    retry_initial_delay: float = DEFAULT_RUNTIME_RETRY_INITIAL_DELAY
    retry_max_delay: float = DEFAULT_RUNTIME_RETRY_MAX_DELAY
    circuit_failure_threshold: int = DEFAULT_RUNTIME_CIRCUIT_FAILURES
    circuit_cooldown: float = DEFAULT_RUNTIME_CIRCUIT_COOLDOWN


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until: float = 0.0


class LLMCircuitOpenError(RuntimeError):
    """Raised when repeated transient failures open the circuit."""


_CIRCUITS: dict[str, _CircuitState] = {}


def default_runtime_policy() -> LLMRuntimePolicy:
    """Build the default runtime policy without requiring an API key."""
    return LLMRuntimePolicy(
        max_attempts=_env_int("WEREWOLF_LLM_RUNTIME_MAX_ATTEMPTS", DEFAULT_RUNTIME_MAX_ATTEMPTS),
        timeout=_env_float_or_none("WEREWOLF_LLM_TIMEOUT", DEFAULT_RUNTIME_TIMEOUT),
        retry_initial_delay=_env_float(
            "WEREWOLF_LLM_RUNTIME_RETRY_INITIAL_DELAY",
            DEFAULT_RUNTIME_RETRY_INITIAL_DELAY,
        ),
        retry_max_delay=_env_float("WEREWOLF_LLM_RUNTIME_RETRY_MAX_DELAY", DEFAULT_RUNTIME_RETRY_MAX_DELAY),
        circuit_failure_threshold=_env_int(
            "WEREWOLF_LLM_RUNTIME_CIRCUIT_FAILURES",
            DEFAULT_RUNTIME_CIRCUIT_FAILURES,
        ),
        circuit_cooldown=_env_float(
            "WEREWOLF_LLM_RUNTIME_CIRCUIT_COOLDOWN",
            DEFAULT_RUNTIME_CIRCUIT_COOLDOWN,
        ),
    )


def with_runtime_policy(llm: Any, policy: LLMRuntimePolicy) -> Any:
    """Attach a runtime invocation policy to an LLM-like object."""
    try:
        setattr(llm, _POLICY_ATTR, policy)
    except Exception:
        object.__setattr__(llm, _POLICY_ATTR, policy)
    return llm


def get_runtime_policy(llm: Any) -> LLMRuntimePolicy:
    policy = getattr(llm, _POLICY_ATTR, None)
    return policy if isinstance(policy, LLMRuntimePolicy) else default_runtime_policy()


def reset_llm_circuit(circuit_key: str | None = None) -> None:
    """Reset one circuit or all LLM circuits. Primarily useful for tests."""
    if circuit_key is None:
        _CIRCUITS.clear()
    else:
        _CIRCUITS.pop(circuit_key, None)


async def invoke_llm_with_policy(
    llm: Any,
    messages: Any,
    *,
    stage: str = "llm",
    policy: LLMRuntimePolicy | None = None,
    circuit_key: str | None = None,
) -> Any:
    """Invoke ``llm.ainvoke`` with timeout, retry, and circuit-breaker policy."""
    runtime_policy = policy or get_runtime_policy(llm)
    attempts = max(1, int(runtime_policy.max_attempts or 1))
    key = circuit_key or stage
    _raise_if_circuit_open(key)

    delay = max(0.0, float(runtime_policy.retry_initial_delay or 0.0))
    max_delay = max(delay, float(runtime_policy.retry_max_delay or delay))
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            result = await _invoke_once(llm, messages, runtime_policy.timeout)
            _record_circuit_success(key)
            return result
        except Exception as exc:
            _set_attempts(exc, attempt)
            last_exc = exc
            if not _is_retryable_llm_error(exc):
                raise
            if attempt >= attempts:
                _record_circuit_failure(key, runtime_policy)
                raise
            if delay > 0:
                await asyncio.sleep(delay)
                delay = min(max_delay, delay * 2 if delay else max_delay)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("LLM invocation failed without an exception")


def create_llm(
    *,
    model: str | None = None,
    temperature: float | None = None,
    timeout: float | None = None,
    runtime_timeout: float | None = None,
    max_retries: int | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    env_path: str | Path | None = DEFAULT_ENV_PATH,
) -> Any:
    """Create a ChatOpenAI instance configured from environment + overrides.

    All parameters are optional. When omitted, values are read from env vars
    (WEREWOLF_LLM_*) through app.config.load_llm_config().
    """
    cfg = load_llm_config(env_path=env_path, api_key=api_key)

    from langchain_openai import ChatOpenAI

    request_timeout = float(timeout if timeout is not None else cfg["timeout"])
    policy_timeout = float(
        runtime_timeout
        if runtime_timeout is not None
        else timeout
        if timeout is not None
        else cfg["runtime_timeout"]
    )

    llm = ChatOpenAI(
        model=model or cfg["model"],
        temperature=float(temperature if temperature is not None else cfg["temperature"]),
        timeout=request_timeout,
        max_retries=int(max_retries if max_retries is not None else cfg["max_retries"]),
        base_url=base_url or cfg["base_url"],
        api_key=cfg["api_key"],
    )
    return with_runtime_policy(
        llm,
        LLMRuntimePolicy(
            max_attempts=int(cfg["runtime_max_attempts"]),
            timeout=policy_timeout,
            retry_initial_delay=float(cfg["runtime_retry_initial_delay"]),
            retry_max_delay=float(cfg["runtime_retry_max_delay"]),
            circuit_failure_threshold=int(cfg["runtime_circuit_failures"]),
            circuit_cooldown=float(cfg["runtime_circuit_cooldown"]),
        ),
    )


async def _invoke_once(llm: Any, messages: Any, timeout: float | None) -> Any:
    call = llm.ainvoke(messages)
    if timeout is None or float(timeout) <= 0:
        return await call
    return await asyncio.wait_for(call, timeout=float(timeout))


def _raise_if_circuit_open(circuit_key: str) -> None:
    state = _CIRCUITS.get(circuit_key)
    if state is None:
        return
    now = time.monotonic()
    if state.opened_until > now:
        exc = LLMCircuitOpenError(
            f"LLM circuit is open for {circuit_key}; retry after {state.opened_until - now:.1f}s"
        )
        _set_attempts(exc, 0)
        raise exc
    if state.opened_until:
        _CIRCUITS.pop(circuit_key, None)


def _record_circuit_success(circuit_key: str) -> None:
    _CIRCUITS.pop(circuit_key, None)


def _record_circuit_failure(circuit_key: str, policy: LLMRuntimePolicy) -> None:
    threshold = max(0, int(policy.circuit_failure_threshold or 0))
    if threshold <= 0:
        return
    state = _CIRCUITS.setdefault(circuit_key, _CircuitState())
    state.failures += 1
    if state.failures >= threshold:
        state.opened_until = time.monotonic() + max(0.0, float(policy.circuit_cooldown or 0.0))


def _is_retryable_llm_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    name = type(exc).__name__.lower()
    return any(
        marker in name
        for marker in (
            "timeout",
            "connection",
            "ratelimit",
            "rate_limit",
            "apiconnection",
            "internalserver",
            "serviceunavailable",
            "temporarilyunavailable",
        )
    )


def _set_attempts(exc: BaseException, attempts: int) -> None:
    try:
        setattr(exc, "llm_attempts", attempts)
    except Exception:
        pass


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _env_float_or_none(name: str, default: float | None) -> float | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    if raw.strip().lower() in {"none", "null", "0"}:
        return None
    return float(raw)


# Backward-compatible alias for callers that still use the old factory name.
load_llm_client = create_llm
