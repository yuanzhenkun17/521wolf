"""Callable invocation helpers for evolution dependency injection."""

from __future__ import annotations

import inspect
from typing import Any, Callable


async def call_battle_runner(
    battle_runner: Callable,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Call injected battle runners without forcing every optional kwarg."""
    return await call_with_supported_kwargs(battle_runner, *args, **kwargs)


async def call_selfplay_runner(
    selfplay_runner: Callable,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Call injected selfplay runners without forcing every optional kwarg."""
    return await call_with_supported_kwargs(selfplay_runner, *args, **kwargs)


async def call_with_supported_kwargs(
    func: Callable,
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return await func(*args, **kwargs)

    accepts_kwargs = any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values()
    )
    if accepts_kwargs:
        return await func(*args, **kwargs)

    filtered = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return await func(*args, **filtered)
