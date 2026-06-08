"""SSE helpers for the UI backend."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any


def _event_id(envelope: dict[str, Any]) -> int:
    try:
        return int(envelope.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def _sse(event: str, payload: Any, *, event_id: int | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def sse_after_cursor(event: str, payload: Any, *, event_id: int, last_event_id: int) -> str | None:
    if event_id <= last_event_id:
        return None
    return _sse(event, payload, event_id=event_id)


def ping_sse(payload: Any) -> str:
    return _sse("ping", payload)


async def stream_queue_sse(
    queue: asyncio.Queue,
    *,
    ping_payload: Callable[[], Any],
    event_name: Callable[[dict[str, Any]], str],
    terminal: Callable[[dict[str, Any], str], bool],
    payload: Callable[[dict[str, Any]], Any] | None = None,
    timeout_seconds: float = 15,
    include_zero_event_id: bool = False,
    skip_none_payload: bool = False,
) -> AsyncIterator[str]:
    payload = payload or (lambda item: item.get("payload"))
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            yield ping_sse(ping_payload())
            continue
        name = event_name(item)
        item_event_id = _event_id(item)
        data = payload(item)
        terminal_event = terminal(item, name)
        if data is None and skip_none_payload:
            if terminal_event:
                break
            continue
        yield _sse(name, data, event_id=item_event_id if item_event_id or include_zero_event_id else None)
        if terminal_event:
            break


async def stream_task_event_log_sse(
    task_event_log: Any,
    entity_id: str,
    *,
    after_event_id: int,
    ping_payload: Callable[[], Any],
    event_name: Callable[[dict[str, Any]], str],
    terminal_statuses: set[str],
    timeout_seconds: float = 15,
) -> AsyncIterator[str]:
    queue = task_event_log.subscribe(entity_id, after_event_id=after_event_id)
    try:
        async for frame in stream_queue_sse(
            queue,
            ping_payload=ping_payload,
            event_name=event_name,
            payload=lambda item: item.get("payload") or {},
            terminal=lambda item, _name: str(item.get("status") or "").lower() in terminal_statuses,
            timeout_seconds=timeout_seconds,
            include_zero_event_id=True,
        ):
            yield frame
    finally:
        task_event_log.unsubscribe(entity_id, queue)
