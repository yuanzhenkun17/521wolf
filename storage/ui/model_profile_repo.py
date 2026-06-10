"""Persistence boundary for encrypted UI model profile settings."""

from __future__ import annotations

import json
from typing import Any

from storage.shared.database import StorageConnection, StorageRow

_PROFILE_COLUMNS = (
    "profile_id",
    "name",
    "provider",
    "base_url",
    "model",
    "api_key_ciphertext",
    "api_key_kid",
    "api_key_masked",
    "temperature",
    "timeout_seconds",
    "max_retries",
    "enabled",
    "default_scopes",
    "capabilities",
    "metadata",
    "created_at",
    "updated_at",
    "last_tested_at",
    "last_test_status",
    "last_test_error",
)

_JSON_FIELDS = {"default_scopes", "capabilities", "metadata"}


class ModelProfileRepository:
    """CRUD boundary for ``ui_model_profiles``.

    The schema is owned by Alembic. API keys are accepted only as encrypted
    ciphertext; plaintext secrets must never cross this repository boundary.
    """

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def list_profiles(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT {_profile_columns_sql()} FROM ui_model_profiles "
            "ORDER BY created_at ASC, profile_id",
            (),
        ).fetchall()
        return [_profile_from_row(row) for row in rows]

    def get(self, profile_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_profile_columns_sql()} FROM ui_model_profiles WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        return _profile_from_row(row) if row is not None else None

    def upsert(self, profile: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO ui_model_profiles "
            "(profile_id, name, provider, base_url, model, "
            "api_key_ciphertext, api_key_kid, api_key_masked, "
            "temperature, timeout_seconds, max_retries, enabled, "
            "default_scopes, capabilities, metadata, created_at, updated_at, "
            "last_tested_at, last_test_status, last_test_error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(profile_id) DO UPDATE SET "
            "name = excluded.name, "
            "provider = excluded.provider, "
            "base_url = excluded.base_url, "
            "model = excluded.model, "
            "api_key_ciphertext = excluded.api_key_ciphertext, "
            "api_key_kid = excluded.api_key_kid, "
            "api_key_masked = excluded.api_key_masked, "
            "temperature = excluded.temperature, "
            "timeout_seconds = excluded.timeout_seconds, "
            "max_retries = excluded.max_retries, "
            "enabled = excluded.enabled, "
            "default_scopes = excluded.default_scopes, "
            "capabilities = excluded.capabilities, "
            "metadata = excluded.metadata, "
            "updated_at = excluded.updated_at, "
            "last_tested_at = excluded.last_tested_at, "
            "last_test_status = excluded.last_test_status, "
            "last_test_error = excluded.last_test_error",
            _profile_params(profile),
        )

    def set_api_key(
        self,
        *,
        profile_id: str,
        ciphertext: str,
        key_id: str,
        masked: str,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            "UPDATE ui_model_profiles SET "
            "api_key_ciphertext = ?, api_key_kid = ?, api_key_masked = ?, updated_at = ? "
            "WHERE profile_id = ?",
            (ciphertext, key_id, masked, updated_at, profile_id),
        )

    def clear_api_key(self, *, profile_id: str, updated_at: str) -> None:
        self._conn.execute(
            "UPDATE ui_model_profiles SET "
            "api_key_ciphertext = NULL, api_key_kid = NULL, api_key_masked = '', updated_at = ? "
            "WHERE profile_id = ?",
            (updated_at, profile_id),
        )

    def delete(self, profile_id: str) -> None:
        self._conn.execute("DELETE FROM ui_model_profiles WHERE profile_id = ?", (profile_id,))


def _profile_columns_sql() -> str:
    return ", ".join(_PROFILE_COLUMNS)


def _profile_params(profile: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _json_dumps(profile.get(column)) if column in _JSON_FIELDS else profile.get(column)
        for column in _PROFILE_COLUMNS
    )


def _profile_from_row(row: StorageRow) -> dict[str, Any]:
    item = {key: row[key] for key in row.keys()}
    for field in _JSON_FIELDS:
        item[field] = _json_loads(item.get(field))
    item["enabled"] = bool(item.get("enabled", True))
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
