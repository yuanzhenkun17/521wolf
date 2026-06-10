"""Background task event log and replay buffer."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Callable

from app.util.json import to_jsonable
from app.util.time import beijing_now_iso
from storage.postgres.unit_of_work import from_connection_factory
from storage.ui import TaskEventRepository

_log = logging.getLogger(__name__)


class TaskEventLog:
    """Small append-only event stream for evolution and benchmark tasks."""

    def __init__(
        self,
        *,
        connection_factory: Callable[[], Any],
        max_backlog: int = 2048,
        compact_every: int = 512,
    ) -> None:
        self._connection_factory = connection_factory
        self.max_backlog = max_backlog
        self.compact_every = compact_every
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._next_event_id = 1
        self._subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
        self._events_since_compact = 0
        self._compact_pending = False

    def load(self) -> None:
        conn = None
        try:
            conn = self._connection_factory()
            rows = TaskEventRepository(conn).list_recent(limit=self.max_backlog)
        except Exception:  # noqa: BLE001 - event replay is best-effort UI metadata
            _log.warning("failed to load task events from PostgreSQL", exc_info=True)
            return
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 - cleanup is best-effort
                    pass
        events = [_event_from_row(row) for row in reversed(rows)]
        with self._lock:
            self._events = events[-self.max_backlog :]
            self._next_event_id = max([_event_id(item) for item in self._events] or [0]) + 1
            self._events_since_compact = 0
            self._compact_pending = False

    def publish(self, entity: dict[str, Any], event: str | None = None) -> dict[str, Any]:
        payload = _task_event_payload(entity)
        with self._lock:
            event_id = self._next_event_id
            self._next_event_id += 1
            item = to_jsonable({
                "id": event_id,
                "event": event or _task_event_name(payload.get("status")),
                "entity_id": _task_entity_id(entity),
                "entity_kind": entity.get("kind"),
                "status": payload.get("status"),
                "created_at": beijing_now_iso(),
                "payload": payload,
            })
            try:
                stored_event_id = self._append_event_locked(item)
            except Exception:  # noqa: BLE001 - task event replay is best-effort UI metadata
                _log.warning("failed to append task event to PostgreSQL", exc_info=True)
            else:
                item["id"] = stored_event_id
                self._next_event_id = max(self._next_event_id, stored_event_id + 1)
                self._events_since_compact += 1
            self._events.append(item)
            if len(self._events) > self.max_backlog:
                del self._events[: len(self._events) - self.max_backlog]
            if self._should_compact_locked():
                try:
                    self._compact_locked()
                except Exception:  # noqa: BLE001 - replay compaction should not block live UI updates
                    self._compact_pending = True
                    _log.warning("failed to compact PostgreSQL task event backlog", exc_info=True)
            entity_id = str(item["entity_id"])
            subscribers = self._live_subscribers_locked(entity_id)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_put_queue_nowait, queue, item)
            except RuntimeError:
                self.unsubscribe(entity_id, queue)
        return item

    def compact(self) -> None:
        """Rewrite the replay log to the current in-memory backlog."""
        with self._lock:
            self._compact_locked()

    def has_events(self, entity_id: str) -> bool:
        with self._lock:
            return any(item.get("entity_id") == entity_id for item in self._events)

    def subscriber_count(self, entity_id: str | None = None) -> int:
        with self._lock:
            if entity_id is not None:
                subscribers = self._live_subscribers_locked(entity_id)
                return len(subscribers)
            total = 0
            for key in list(self._subscribers):
                total += len(self._live_subscribers_locked(key))
            return total

    def replay(self, entity_id: str, *, after_event_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(item)
                for item in self._events
                if item.get("entity_id") == entity_id and _event_id(item) > after_event_id
            ]

    def subscribe(
        self,
        entity_id: str,
        *,
        after_event_id: int = 0,
        max_queue_size: int = 512,
    ) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        with self._lock:
            backlog = [
                dict(item)
                for item in self._events
                if item.get("entity_id") == entity_id and _event_id(item) > after_event_id
            ]
            queue: asyncio.Queue = asyncio.Queue(maxsize=max(max_queue_size, len(backlog) + 16))
            for item in backlog:
                _put_queue_nowait(queue, item)
            self._subscribers.setdefault(entity_id, []).append((loop, queue))
        return queue

    def unsubscribe(self, entity_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            subscribers = self._subscribers.get(entity_id)
            if not subscribers:
                return
            self._subscribers[entity_id] = [
                (loop, existing)
                for loop, existing in subscribers
                if existing is not queue
            ]
            if not self._subscribers[entity_id]:
                self._subscribers.pop(entity_id, None)

    def _append_event_locked(self, item: dict[str, Any]) -> int:
        with from_connection_factory(self._connection_factory) as tx:
            event_id = TaskEventRepository(tx.connection).append(item)
            tx.commit()
            return event_id

    def _should_compact_locked(self) -> bool:
        if self._compact_pending:
            return True
        if self.compact_every > 0 and self._events_since_compact >= self.compact_every:
            return True
        return False

    def _compact_locked(self) -> None:
        if len(self._events) >= self.max_backlog:
            cutoff = _event_id(self._events[0])
            with from_connection_factory(self._connection_factory) as tx:
                TaskEventRepository(tx.connection).delete_before_id(cutoff)
                tx.commit()
        self._events_since_compact = 0
        self._compact_pending = False

    def _live_subscribers_locked(self, entity_id: str) -> list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]:
        subscribers = self._subscribers.get(entity_id)
        if not subscribers:
            return []
        live = [(loop, queue) for loop, queue in subscribers if not loop.is_closed()]
        if live:
            self._subscribers[entity_id] = live
        else:
            self._subscribers.pop(entity_id, None)
        return list(live)


def _task_entity_id(entity: dict[str, Any]) -> str:
    return str(entity.get("run_id") or entity.get("batch_id") or entity.get("task_id") or "")


def _task_event_name(status: Any) -> str:
    status_text = str(status or "").lower()
    if status_text in {
        "reviewing",
        "promoted",
        "rejected",
        "failed",
        "completed",
        "succeeded",
        "cancelled",
        "interrupted",
    }:
        return status_text
    return "progress"


def _task_event_payload(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        key: to_jsonable(entity.get(key))
        for key in (
            "kind",
            "schema_version",
            "run_id",
            "batch_id",
            "task_id",
            "role",
            "roles",
            "status",
            "priority",
            "attempt",
            "max_attempts",
            "lease_owner",
            "lease_expires_at",
            "stop_requested",
            "cancelled",
            "interrupted",
            "failed",
            "started_at",
            "queued_at",
            "updated_at",
            "finished_at",
            "last_heartbeat_at",
            "cancelled_at",
            "interrupted_at",
            "current_stage",
            "progress",
            "overall_progress",
            "stage_progress",
            "run_summaries",
            "battle_result",
            "diagnostics",
            "recommendation",
            "error",
            "config",
            "result",
        )
        if key in entity
    }


def _event_id(item: dict[str, Any]) -> int:
    try:
        return int(item.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def _put_queue_nowait(queue: asyncio.Queue, item: dict[str, Any]) -> None:
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            pass


def _event_from_row(row: Any) -> dict[str, Any]:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return to_jsonable(
        {
            "id": int(row["id"]),
            "event": row["event"],
            "entity_id": row["entity_id"],
            "entity_kind": row["entity_kind"],
            "status": row["status"],
            "created_at": row["created_at"],
            "payload": payload if isinstance(payload, dict) else {},
        }
    )
