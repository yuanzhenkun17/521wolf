"""Mixin for SSE (Server-Sent Events) queue management."""

from __future__ import annotations

import asyncio
from typing import Any


class SSEMixin:
    """Provides subscribe/unsubscribe/_broadcast for SSE event queues."""

    def __init__(self) -> None:
        self._sse_queues: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, entity_id: str) -> asyncio.Queue:
        """Subscribe to SSE events for an entity. Returns a queue."""
        queue: asyncio.Queue = asyncio.Queue()
        self._sse_queues.setdefault(entity_id, []).append(queue)
        return queue

    def unsubscribe(self, entity_id: str, queue: asyncio.Queue) -> None:
        """Remove a queue from the subscriber list."""
        queues = self._sse_queues.get(entity_id, [])
        try:
            queues.remove(queue)
        except ValueError:
            pass

    def _broadcast(self, entity_id: str, event: str, data: dict[str, Any]) -> None:
        """Push an event to all SSE queues for an entity."""
        for queue in self._sse_queues.get(entity_id, []):
            queue.put_nowait({"event": event, "data": data})