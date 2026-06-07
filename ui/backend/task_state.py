"""Background-task state helpers for the UI backend."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.util.time import beijing_now_iso


def _set_task_contract(
    entity: dict[str, Any],
    *,
    stop_requested: bool | None = None,
    cancelled: bool | None = None,
    interrupted: bool | None = None,
    failed: bool | None = None,
) -> None:
    if stop_requested is not None:
        entity["stop_requested"] = bool(stop_requested)
    if cancelled is not None:
        entity["cancelled"] = bool(cancelled)
        if cancelled:
            entity["cancelled_at"] = entity.get("cancelled_at") or beijing_now_iso()
    if interrupted is not None:
        entity["interrupted"] = bool(interrupted)
        if interrupted:
            entity["interrupted_at"] = entity.get("interrupted_at") or beijing_now_iso()
    if failed is not None:
        entity["failed"] = bool(failed)


def _last_event_id_from_request(request: Request) -> int:
    raw = (
        request.query_params.get("last_event_id")
        or request.query_params.get("lastEventId")
        or request.headers.get("last-event-id")
        or request.headers.get("Last-Event-ID")
    )
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _history_query_requested(request: Request) -> bool:
    return any(key in request.query_params for key in ("limit", "offset", "source", "status"))


def _filter_values(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    values = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return values or None


def _match_filter(value: Any, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    return str(value or "").lower() in allowed


def _pagination(
    items: list[dict[str, Any]],
    *,
    limit: int | None,
    offset: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(items)
    start = max(0, int(offset or 0))
    if limit is None:
        page = items[start:]
        resolved_limit = None
    else:
        resolved_limit = max(0, int(limit))
        page = items[start : start + resolved_limit]
    return page, {
        "total": total,
        "offset": start,
        "limit": resolved_limit,
        "returned": len(page),
        "has_more": start + len(page) < total,
    }


def _history_time_key(item: dict[str, Any]) -> str:
    return str(
        item.get("log_time")
        or item.get("finished_at")
        or item.get("last_heartbeat_at")
        or item.get("started_at")
        or item.get("game_id")
        or item.get("run_id")
        or item.get("batch_id")
        or ""
    )


def _background_source(entity: dict[str, Any]) -> str:
    if entity.get("run_id"):
        return "evolution"
    if str(entity.get("kind") or "").startswith("benchmark"):
        return "benchmark"
    return "evolution"
