"""Append-only audit log for local settings changes."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.util.redaction import redact
from app.util.time import beijing_now_iso
from storage.ui import SettingsAuditRepository

_MAX_FILE_EVENTS = 500


class SettingsAuditStore:
    def __init__(self, root: Path, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self._root = Path(root)
        self._path = self._root / "settings-audit-log.json"
        self._connection_factory = connection_factory

    @classmethod
    def from_backend_store(cls, store: Any) -> "SettingsAuditStore":
        paths = getattr(store, "paths", None)
        data_dir = Path(getattr(paths, "data_dir", Path("data")))
        connection_factory = getattr(store, "_open_ui_task_connection", None)
        return cls(data_dir / "settings", connection_factory=connection_factory if callable(connection_factory) else None)

    def list_payload(self, *, limit: int = 50) -> dict[str, Any]:
        return {
            "kind": "settings_audit_log",
            "schema_version": 1,
            "events": self.list_events(limit=limit),
        }

    def list_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(int(limit), 200))
        backend = self._backend()
        if backend is not None:
            return backend.list_events(limit=normalized_limit)
        payload = _read_json(self._path, {"schema_version": 1, "events": []})
        events = payload.get("events") if isinstance(payload, dict) else []
        rows = [dict(item) for item in events] if isinstance(events, list) else []
        return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)[:normalized_limit]

    def record(
        self,
        *,
        action: str,
        entity_kind: str,
        entity_id: str,
        status: str = "ok",
        message: str = "",
        details: dict[str, Any] | None = None,
        actor: str = "settings_admin",
    ) -> dict[str, Any]:
        event = {
            "audit_id": f"settings_audit_{uuid.uuid4().hex}",
            "action": _safe_text(action),
            "entity_kind": _safe_text(entity_kind),
            "entity_id": _safe_text(entity_id),
            "status": _safe_text(status or "ok"),
            "actor": _safe_text(actor or "settings_admin"),
            "message": _safe_text(message),
            "details": _redacted_details(details or {}),
            "created_at": beijing_now_iso(),
        }
        self._append(event)
        return event

    def record_best_effort(self, **kwargs: Any) -> None:
        try:
            self.record(**kwargs)
        except Exception:
            return

    def _append(self, event: dict[str, Any]) -> None:
        backend = self._backend()
        if backend is not None:
            backend.append(event)
            return
        payload = _read_json(self._path, {"schema_version": 1, "events": []})
        events = payload.get("events") if isinstance(payload, dict) else []
        rows = [dict(item) for item in events] if isinstance(events, list) else []
        rows.append(event)
        rows = sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)[:_MAX_FILE_EVENTS]
        _write_json(self._path, {"schema_version": 1, "events": rows})

    def _backend(self) -> "_PostgresSettingsAuditBackend | None":
        if self._connection_factory is None:
            return None
        try:
            conn = self._connection_factory()
        except Exception:
            return None
        try:
            table_exists = getattr(conn, "table_exists", None)
            if not callable(table_exists) or not table_exists("ui_settings_audit_log"):
                return None
        except Exception:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return _PostgresSettingsAuditBackend(self._connection_factory)


class _PostgresSettingsAuditBackend:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def list_events(self, *, limit: int) -> list[dict[str, Any]]:
        conn = self._connection_factory()
        try:
            return SettingsAuditRepository(conn).list_events(limit=limit)
        finally:
            conn.close()

    def append(self, event: dict[str, Any]) -> None:
        conn = self._connection_factory()
        try:
            SettingsAuditRepository(conn).append(event)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def settings_audit_details_for_profile(profile: dict[str, Any] | None, *, fields: list[str] | None = None) -> dict[str, Any]:
    source = profile if isinstance(profile, dict) else {}
    details: dict[str, Any] = {
        "profile_id": source.get("profile_id"),
        "name": source.get("name"),
        "provider": source.get("provider"),
        "model": source.get("model"),
        "enabled": source.get("enabled"),
        "has_api_key": bool(source.get("has_api_key") or source.get("api_key_masked")),
        "model_config_hash": source.get("model_config_hash"),
    }
    if fields is not None:
        details["fields"] = sorted({field for field in fields if field not in {"api_key", "clear_api_key"}})
        if "api_key" in fields:
            details["api_key_changed"] = True
        if "clear_api_key" in fields:
            details["api_key_cleared"] = True
    return {key: value for key, value in details.items() if value is not None}


def _redacted_details(details: dict[str, Any]) -> dict[str, Any]:
    redacted = redact(details, context="diagnostic")
    return redacted if isinstance(redacted, dict) else {}


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)
