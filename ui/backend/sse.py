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


def task_event_log_matches_entity(
    task_event_log: Any,
    entity_id: str,
    entity: dict[str, Any],
    *,
    terminal_statuses: set[str],
) -> bool:
    events = task_event_log.replay(entity_id, after_event_id=0)
    if not events:
        return False
    current_status = str(entity.get("status") or "").lower()
    if current_status not in terminal_statuses:
        return True
    latest = events[-1]
    latest_payload = latest.get("payload") if isinstance(latest.get("payload"), dict) else {}
    latest_status = str(latest.get("status") or latest_payload.get("status") or "").lower()
    return latest_status == current_status


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
    # Task events are stored with a global PostgreSQL identity id.  The public
    # SSE contract, however, uses a cursor local to each task stream so clients
    # can resume with Last-Event-ID without knowing unrelated task ids.
    backlog = task_event_log.replay(entity_id, after_event_id=0)
    external_cursor = 0
    internal_cursor = 0
    skipped_terminal = False
    for item in backlog:
        internal_cursor = max(internal_cursor, _event_id(item))
        external_cursor += 1
        name = event_name(item)
        terminal_event = str(item.get("status") or "").lower() in terminal_statuses
        if external_cursor > after_event_id:
            yield _sse(name, item.get("payload") or {}, event_id=external_cursor)
            if terminal_event:
                return
        elif terminal_event:
            skipped_terminal = True
    if skipped_terminal and after_event_id >= external_cursor:
        return

    queue = task_event_log.subscribe(entity_id, after_event_id=internal_cursor)
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                yield ping_sse(ping_payload())
                continue
            external_cursor += 1
            name = event_name(item)
            data = item.get("payload") or {}
            terminal_event = str(item.get("status") or "").lower() in terminal_statuses
            if external_cursor > after_event_id:
                yield _sse(name, data, event_id=external_cursor)
            if terminal_event:
                break
    finally:
        task_event_log.unsubscribe(entity_id, queue)
