"""Lightweight cached index for UI game history rows."""

from __future__ import annotations

import threading
from typing import Any, Callable


SOURCE_KEYS = ("normal", "benchmark", "evolution")
HISTORY_INDEX_SCHEMA_VERSION = 1


class GameHistoryIndex:
    """Cache list-page rows without caching full game details."""

    def __init__(
        self,
        path: object | None,
        *,
        build_rows: Callable[[], list[dict[str, Any]]],
        fingerprint: Callable[[], dict[str, Any]],
    ) -> None:
        self.path = path
        self._build_rows = build_rows
        self._fingerprint = fingerprint
        self._lock = threading.Lock()
        self._rows: list[dict[str, Any]] | None = None
        self._fingerprint_value: str | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._rows = None
            self._fingerprint_value = None

    def rows(self) -> list[dict[str, Any]]:
        fingerprint = _stable_json(self._fingerprint())
        with self._lock:
            if self._rows is not None and self._fingerprint_value == fingerprint:
                return [dict(row) for row in self._rows]

            rows = [dict(row) for row in self._build_rows()]
            self._rows = rows
            self._fingerprint_value = fingerprint
            return [dict(row) for row in rows]


def source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in SOURCE_KEYS}
    for row in rows:
        source = _source(row)
        if source not in counts:
            counts[source] = 0
        counts[source] += 1
    return {"all": len(rows), **{key: counts.get(key, 0) for key in SOURCE_KEYS}}


def history_facets(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    status_counts: dict[str, int] = {}
    source_facet = source_counts(rows)
    for row in rows:
        status = str(row.get("status") or "unknown").lower()
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "source": source_facet,
        "status": status_counts,
    }


def _source(row: dict[str, Any]) -> str:
    return str(row.get("log_source") or "normal").lower()


def _stable_json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
