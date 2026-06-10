"""Persistence boundary for UI settings audit events."""

from __future__ import annotations

import json
from typing import Any

from storage.shared.database import StorageConnection, StorageRow

_AUDIT_COLUMNS = (
    "audit_id",
    "action",
    "entity_kind",
    "entity_id",
    "status",
    "actor",
    "message",
    "details",
    "created_at",
)

_JSON_FIELDS = {"details"}


class SettingsAuditRepository:
    """Append-only CRUD boundary for ``ui_settings_audit_log``."""

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def append(self, event: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO ui_settings_audit_log "
            "(audit_id, action, entity_kind, entity_id, status, actor, message, details, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(
                _json_dumps(event.get(column)) if column in _JSON_FIELDS else event.get(column)
                for column in _AUDIT_COLUMNS
            ),
        )

    def list_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT {_audit_columns_sql()} FROM ui_settings_audit_log "
            "ORDER BY created_at DESC, audit_id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        return [_audit_from_row(row) for row in rows]


def _audit_columns_sql() -> str:
    return ", ".join(_AUDIT_COLUMNS)


def _audit_from_row(row: StorageRow) -> dict[str, Any]:
    item = {key: row[key] for key in row.keys()}
    for field in _JSON_FIELDS:
        item[field] = _json_loads(item.get(field))
    return item


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value
