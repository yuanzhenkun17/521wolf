"""Shared storage readiness helpers for locally administered settings."""

from __future__ import annotations

from typing import Any


class SettingsStorageUnavailable(RuntimeError):
    """Raised when Settings storage is configured but not writable."""

    def __init__(self, message: str, *, status: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status or {}


def local_file_storage_status(*, path: str) -> dict[str, Any]:
    return {
        "backend": "local_file",
        "ready": True,
        "read_only": False,
        "reason": "",
        "message": "settings are stored in local JSON files",
        "path": path,
        "actions": [],
    }


def postgres_storage_status(
    *,
    table: str,
    ready: bool,
    reason: str = "",
    message: str = "",
    actions: list[str] | None = None,
    secret_encryption: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "backend": "postgres",
        "ready": bool(ready),
        "read_only": not bool(ready),
        "reason": reason,
        "message": message or ("PostgreSQL settings storage is ready" if ready else "PostgreSQL settings storage is unavailable"),
        "table": table,
        "actions": list(actions or []),
    }
    if secret_encryption is not None:
        payload["secret_encryption"] = secret_encryption
    return payload


def storage_write_available(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict):
        return False
    return bool(status.get("ready")) and not bool(status.get("read_only"))


def assert_storage_write_available(status: dict[str, Any]) -> None:
    if storage_write_available(status):
        return
    message = str(status.get("message") or "settings storage is unavailable")
    raise SettingsStorageUnavailable(message, status=status)
