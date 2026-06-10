"""Persistence boundary for non-secret UI runtime settings."""

from __future__ import annotations

import json
from typing import Any

from storage.shared.database import StorageConnection, StorageRow

_SETTING_COLUMNS = (
    "setting_key",
    "value_json",
    "updated_at",
    "updated_by",
)

_JSON_FIELDS = {"value_json"}


class RuntimeSettingRepository:
    """CRUD boundary for ``ui_runtime_settings``."""

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def list_settings(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT {_setting_columns_sql()} FROM ui_runtime_settings ORDER BY setting_key",
            (),
        ).fetchall()
        return [_setting_from_row(row) for row in rows]

    def get(self, setting_key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_setting_columns_sql()} FROM ui_runtime_settings WHERE setting_key = ?",
            (setting_key,),
        ).fetchone()
        return _setting_from_row(row) if row is not None else None

    def upsert(
        self,
        *,
        setting_key: str,
        value: Any,
        updated_at: str,
        updated_by: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO ui_runtime_settings "
            "(setting_key, value_json, updated_at, updated_by) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(setting_key) DO UPDATE SET "
            "value_json = excluded.value_json, "
            "updated_at = excluded.updated_at, "
            "updated_by = excluded.updated_by",
            (
                setting_key,
                _json_dumps(value),
                updated_at,
                updated_by,
            ),
        )


def _setting_columns_sql() -> str:
    return ", ".join(_SETTING_COLUMNS)


def _setting_from_row(row: StorageRow) -> dict[str, Any]:
    item = {key: row[key] for key in row.keys()}
    for field in _JSON_FIELDS:
        item[field] = _json_loads(item.get(field))
    return item


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list, bool, int, float)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value
