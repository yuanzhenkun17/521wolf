"""Shared utilities for runner modules.

Collects the common patterns duplicated across game_runner, selfplay_runner,
role_evolution_runner, and batch_role_evolution_runner:

  - RunnerStatus enum (common lifecycle status strings)
  - is_rate_limit_error re-export (from agent.common.errors)
  - sse_events_stream helper (the SSE subscribe/yield/unsubscribe pattern)
  - retry_on_rate_limit helper (the max_retries + exponential backoff pattern)
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any, AsyncGenerator, Awaitable, Callable, TypeVar

from agent.common.errors import is_rate_limit_error

_log = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# RunnerStatus — common lifecycle states
# ---------------------------------------------------------------------------


class RunnerStatus(str, Enum):
    """Common status strings shared across all runner types.

    Each runner may define additional domain-specific statuses beyond these,
    but the core lifecycle (queued -> running -> completed/failed) is
    universal.
    """

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    RATE_LIMITED = "rate_limited"

    # Convenience sets for common status checks
    @classmethod
    def active_statuses(cls) -> set[str]:
        """Statuses that indicate a run is still in progress."""
        return {cls.QUEUED.value, cls.RUNNING.value, cls.RATE_LIMITED.value}

    @classmethod
    def terminal_statuses(cls) -> set[str]:
        """Statuses that indicate a run has finished (no more updates)."""
        return {cls.COMPLETED.value, cls.FAILED.value}


# ---------------------------------------------------------------------------
# Default retry parameters
# ---------------------------------------------------------------------------

DEFAULT_MAX_RETRIES: int = 5
DEFAULT_RETRY_WAIT_BASE: int = 30  # seconds; wait = base * (attempt + 1)


# ---------------------------------------------------------------------------
# SSE event streaming
# ---------------------------------------------------------------------------


async def sse_events_stream(
    subscribe_fn: Callable[[str], asyncio.Queue],
    unsubscribe_fn: Callable[[str, asyncio.Queue], None],
    entity_id: str,
    terminal_kinds: set[str] | None = None,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted events for an entity until a terminal event arrives.

    This encapsulates the subscribe/yield/unsubscribe pattern used by
    ``RoleEvolutionRunner.sse_events`` and
    ``RoleBatchEvolutionRunner.sse_events``.

    Parameters
    ----------
    subscribe_fn:
        Callable that returns a queue for the given entity_id
        (typically ``self.subscribe`` from ``SSEMixin``).
    unsubscribe_fn:
        Callable that removes the queue for the given entity_id
        (typically ``self.unsubscribe`` from ``SSEMixin``).
    entity_id:
        The run/batch/game ID to subscribe to.
    terminal_kinds:
        Set of event ``kind`` values that signal stream completion.
        When a terminal event arrives, it is yielded and then the stream
        ends.  Defaults to ``{"failed"}``.
    """
    if terminal_kinds is None:
        terminal_kinds = {"failed"}

    queue = subscribe_fn(entity_id)
    try:
        while True:
            item = await queue.get()
            kind = item["kind"]
            payload = json.dumps(item["payload"], ensure_ascii=False)
            # Terminal events keep their concrete name so the frontend
            # can detect completion; all others are unified under "progress".
            event_name = kind if kind in terminal_kinds else "progress"
            yield f"event: {event_name}\ndata: {payload}\n\n"
            if kind in terminal_kinds:
                break
    finally:
        unsubscribe_fn(entity_id, queue)


# ---------------------------------------------------------------------------
# Retry-on-rate-limit helper
# ---------------------------------------------------------------------------


async def retry_on_rate_limit(
    fn: Callable[..., Awaitable[T]],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    wait_base: int = DEFAULT_RETRY_WAIT_BASE,
    run_id: str = "",
    on_rate_limited: Callable[[str, int, int], Awaitable[None] | None] | None = None,
    on_final_failure: Callable[[str, Exception], Awaitable[None] | None] | None = None,
) -> T:
    """Call *fn* with automatic retry on rate-limit (429) errors.

    The wait time between retries scales linearly:
    ``wait = wait_base * (attempt + 1)``.

    Parameters
    ----------
    fn:
        The async callable to execute.  It is called with no arguments;
        bind any required arguments with ``functools.partial`` if needed.
    max_retries:
        Maximum number of attempts before giving up.
    wait_base:
        Base wait time in seconds.  Actual wait = ``wait_base * (attempt+1)``.
    run_id:
        Identifier for logging purposes.
    on_rate_limited:
        Optional callback invoked when a rate-limit error is detected
        but retries remain.  Receives ``(run_id, attempt, max_retries)``.
        If the callback returns an awaitable, it is awaited before the
        sleep.  Use this to set ``status = "rate_limited"`` and broadcast
        the state.
    on_final_failure:
        Optional callback invoked when all retries are exhausted or a
        non-rate-limit error occurs.  Receives ``(run_id, exception)``.
        If the callback returns an awaitable, it is awaited.

    Returns
    -------
    The result of *fn* on success.

    Raises
    ------
    The last exception if all retries are exhausted or a non-rate-limit
    error occurs.
    """
    for attempt in range(max_retries):
        try:
            return await fn()
        except Exception as exc:
            is_last_attempt = attempt >= max_retries - 1
            if is_rate_limit_error(exc) and not is_last_attempt:
                wait = wait_base * (attempt + 1)
                _log.warning(
                    "Rate limited on run %s, retrying in %ds (attempt %d/%d)",
                    run_id, wait, attempt + 1, max_retries,
                )
                if on_rate_limited is not None:
                    result = on_rate_limited(run_id, attempt, max_retries)
                    if asyncio.iscoroutine(result):
                        await result
                await asyncio.sleep(wait)
                continue
            # Not rate-limited, or last attempt — report failure
            if on_final_failure is not None:
                result = on_final_failure(run_id, exc)
                if asyncio.iscoroutine(result):
                    await result
            raise