"""Local non-secret runtime variable settings for the UI settings console."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.util.time import beijing_now_iso
from storage.ui import RuntimeSettingRepository
from ui.backend.settings_storage import (
    assert_storage_write_available,
    local_file_storage_status,
    postgres_storage_status,
    storage_write_available,
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_SETTINGS_ADMIN_KEYS = ("SETTINGS_ADMIN_ENABLED", "SETTINGS_ADMIN_TOKEN")
_LLM_ENV_LOCK_KEYS = ("WEREWOLF_LLM_API_KEY", "WEREWOLF_LLM_BASE_URL", "WEREWOLF_LLM_MODEL")
WORKFLOW_GAME_CONCURRENCY_KEY = "WEREWOLF_GAME_CONCURRENCY"


@dataclass(frozen=True, slots=True)
class RuntimeVariableDefinition:
    key: str
    label: str
    value_type: str
    default: bool | int | float | str
    state: str
    description: str
    editable: bool = True
    minimum: float | None = None
    maximum: float | None = None
    env_key: str | None = None

    @property
    def lock_key(self) -> str:
        return self.env_key or self.key


_RUNTIME_VARIABLES: tuple[RuntimeVariableDefinition, ...] = (
    RuntimeVariableDefinition(
        key="TASK_WORKER_REQUIRED",
        label="长任务 Worker 必需",
        value_type="boolean",
        default=False,
        state="immediate",
        description="开启后 task worker 心跳异常会让 API health 变为错误，并阻断 Benchmark/Evolution。",
    ),
    RuntimeVariableDefinition(
        key="WOLF_USE_PG_TASK_QUEUE",
        label="PostgreSQL 长任务队列",
        value_type="boolean",
        default=False,
        state="next_task",
        description="开启后新 Benchmark/Evolution 任务进入 PostgreSQL durable queue。",
    ),
    RuntimeVariableDefinition(
        key=WORKFLOW_GAME_CONCURRENCY_KEY,
        label="多局并发数",
        value_type="integer",
        default=0,
        state="next_task",
        description="控制 Benchmark、自进化训练和自进化对战的并发对局数；0 表示使用系统默认。",
        minimum=0,
        maximum=64,
    ),
    RuntimeVariableDefinition(
        key="HEALTH_LLM_PROBE_TTL_SECONDS",
        label="模型探活成功缓存",
        value_type="integer",
        default=300,
        state="immediate",
        description="LLM 连接探活成功后的缓存秒数。",
        minimum=0,
        maximum=3600,
    ),
    RuntimeVariableDefinition(
        key="HEALTH_LLM_PROBE_FAILURE_TTL_SECONDS",
        label="模型探活失败缓存",
        value_type="integer",
        default=60,
        state="immediate",
        description="LLM 连接探活失败后的缓存秒数。",
        minimum=0,
        maximum=3600,
    ),
)

_RUNTIME_VARIABLE_BY_KEY = {definition.key: definition for definition in _RUNTIME_VARIABLES}


class SettingsRuntimeVariableStore:
    def __init__(self, root: Path, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self._root = Path(root)
        self._path = self._root / "runtime-variables.json"
        self._connection_factory = connection_factory
        self._backend_status_cache: tuple[float, "_PostgresRuntimeVariableBackend | None", dict[str, Any]] | None = None

    @classmethod
    def from_backend_store(cls, store: Any) -> "SettingsRuntimeVariableStore":
        paths = getattr(store, "paths", None)
        data_dir = Path(getattr(paths, "data_dir", Path("data")))
        connection_factory = getattr(store, "_open_ui_task_connection", None)
        return cls(data_dir / "settings", connection_factory=connection_factory if callable(connection_factory) else None)

    def list_payload(self) -> dict[str, Any]:
        storage_status = self.storage_status()
        return {
            "kind": "settings_runtime_variables",
            "schema_version": 1,
            "variables": self.list_variables(),
            "admin": _settings_admin_payload(storage={"runtime_variables": storage_status}),
            "storage": {"runtime_variables": storage_status},
        }

    def storage_status(self) -> dict[str, Any]:
        _backend, status = self._backend_with_status()
        return status

    def list_variables(self) -> list[dict[str, Any]]:
        values = self._read_values()
        return [
            *_admin_variables(),
            _llm_env_lock_variable(),
            *[self._variable_payload(definition, values) for definition in _RUNTIME_VARIABLES],
        ]

    def update_variable(self, key: str, value: Any) -> dict[str, Any]:
        normalized_key = str(key or "").strip()
        definition = _RUNTIME_VARIABLE_BY_KEY.get(normalized_key)
        if definition is None or not definition.editable:
            raise FileNotFoundError("runtime variable is not editable")
        if _env_present(definition.lock_key):
            raise PermissionError("runtime variable is locked by environment")
        coerced = _coerce_value(definition, value)
        self._write_value(definition.key, coerced)
        values = self._read_values()
        return self._variable_payload(definition, values)

    def value(self, key: str, default: Any = None) -> Any:
        definition = _RUNTIME_VARIABLE_BY_KEY.get(str(key or "").strip())
        if definition is None:
            return default
        env_value = os.environ.get(definition.lock_key)
        if _env_present(definition.lock_key):
            return _coerce_value(definition, env_value)
        values = self._read_values()
        if definition.key in values:
            return _coerce_value(definition, values[definition.key])
        return definition.default if definition.default is not None else default

    def _variable_payload(
        self,
        definition: RuntimeVariableDefinition,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        env_locked = _env_present(definition.lock_key)
        if env_locked:
            raw_value = _coerce_value(definition, os.environ.get(definition.lock_key))
            source = "environment"
        elif definition.key in values:
            raw_value = _coerce_value(definition, values[definition.key])
            source = "settings"
        else:
            raw_value = definition.default
            source = "default"
        return {
            "key": definition.key,
            "label": definition.label,
            "value": _display_value(raw_value),
            "raw_value": raw_value,
            "value_type": definition.value_type,
            "state": "env_locked" if env_locked else definition.state,
            "locked": env_locked,
            "editable": definition.editable and not env_locked,
            "secret": False,
            "source": source,
            "description": definition.description,
            "minimum": definition.minimum,
            "maximum": definition.maximum,
            "updated_at": _updated_at_for(definition.key, values),
        }

    def _read_values(self) -> dict[str, Any]:
        backend = self._backend()
        if backend is not None:
            return backend.read_values()
        payload = _read_json(self._path, {"schema_version": 1, "settings": {}})
        settings = payload.get("settings") if isinstance(payload, dict) else {}
        return dict(settings) if isinstance(settings, dict) else {}

    def _write_value(self, key: str, value: Any) -> None:
        assert_storage_write_available(self.storage_status())
        backend = self._backend()
        if backend is not None:
            backend.write_value(key, value)
            return
        payload = _read_json(self._path, {"schema_version": 1, "settings": {}, "updated_at": {}})
        settings = payload.get("settings") if isinstance(payload, dict) else {}
        updated_at = payload.get("updated_at") if isinstance(payload, dict) else {}
        if not isinstance(settings, dict):
            settings = {}
        if not isinstance(updated_at, dict):
            updated_at = {}
        settings[key] = value
        updated_at[key] = beijing_now_iso()
        _write_json(self._path, {"schema_version": 1, "settings": settings, "updated_at": updated_at})

    def _backend(self) -> "_PostgresRuntimeVariableBackend | None":
        backend, _status = self._backend_with_status()
        return backend

    def _backend_with_status(self) -> tuple["_PostgresRuntimeVariableBackend | None", dict[str, Any]]:
        cached = self._backend_status_cache
        if cached is not None and cached[0] > time.monotonic():
            return cached[1], dict(cached[2])
        if self._connection_factory is None:
            return None, local_file_storage_status(path=str(self._path))
        try:
            conn = self._connection_factory()
        except Exception as exc:
            return None, postgres_storage_status(
                table="ui_runtime_settings",
                ready=False,
                reason="connection_unavailable",
                message=f"PostgreSQL runtime settings storage cannot be reached: {type(exc).__name__}",
                actions=["verify PostgreSQL connectivity for UI runtime settings"],
            )
        try:
            table_exists = getattr(conn, "table_exists", None)
            if not callable(table_exists):
                return None, postgres_storage_status(
                    table="ui_runtime_settings",
                    ready=False,
                    reason="schema_check_unavailable",
                    message="PostgreSQL runtime settings storage cannot verify ui_runtime_settings.",
                    actions=["upgrade the UI storage adapter so table_exists is available"],
                )
            if not table_exists("ui_runtime_settings"):
                return None, postgres_storage_status(
                    table="ui_runtime_settings",
                    ready=False,
                    reason="missing_table",
                    message="PostgreSQL settings table ui_runtime_settings is missing.",
                    actions=["run database migrations for ui_runtime_settings"],
                )
        except Exception as exc:
            return None, postgres_storage_status(
                table="ui_runtime_settings",
                ready=False,
                reason="schema_check_failed",
                message=f"PostgreSQL runtime settings storage cannot verify ui_runtime_settings: {type(exc).__name__}",
                actions=["verify PostgreSQL schema permissions for UI runtime settings"],
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
        backend = _PostgresRuntimeVariableBackend(self._connection_factory)
        status = postgres_storage_status(
            table="ui_runtime_settings",
            ready=True,
        )
        self._backend_status_cache = (time.monotonic() + 5.0, backend, dict(status))
        return backend, status


class _PostgresRuntimeVariableBackend:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def read_values(self) -> dict[str, Any]:
        conn = self._connection_factory()
        try:
            rows = RuntimeSettingRepository(conn).list_settings()
            return {
                str(row.get("setting_key") or ""): row.get("value_json")
                for row in rows
                if str(row.get("setting_key") or "")
            }
        finally:
            conn.close()

    def write_value(self, key: str, value: Any) -> None:
        conn = self._connection_factory()
        try:
            RuntimeSettingRepository(conn).upsert(
                setting_key=key,
                value=value,
                updated_at=beijing_now_iso(),
                updated_by="settings_admin",
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def runtime_setting_bool_for_store(store: Any, key: str, *, default: bool = False) -> bool:
    try:
        return bool(SettingsRuntimeVariableStore.from_backend_store(store).value(key, default))
    except Exception:
        return _env_bool(key, default=default)


def runtime_setting_float_for_store(store: Any, key: str, *, default: float) -> float:
    try:
        return float(SettingsRuntimeVariableStore.from_backend_store(store).value(key, default))
    except Exception:
        return _env_float(key, default=default)


def runtime_setting_int_for_store(store: Any, key: str, *, default: int) -> int:
    try:
        return int(SettingsRuntimeVariableStore.from_backend_store(store).value(key, default))
    except Exception:
        return _env_int(key, default=default)


def _coerce_value(definition: RuntimeVariableDefinition, value: Any) -> bool | int | float | str:
    if definition.value_type == "boolean":
        return _coerce_bool(value)
    if definition.value_type == "integer":
        parsed = int(float(str(value).strip())) if not isinstance(value, bool) else int(value)
        return int(_bounded(parsed, definition))
    if definition.value_type == "number":
        parsed = float(value)
        return _bounded(parsed, definition)
    return str(value or "").strip()


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ValueError("expected a boolean value")


def _bounded(value: int | float, definition: RuntimeVariableDefinition) -> int | float:
    if definition.minimum is not None and value < definition.minimum:
        raise ValueError(f"{definition.key} must be >= {definition.minimum:g}")
    if definition.maximum is not None and value > definition.maximum:
        raise ValueError(f"{definition.key} must be <= {definition.maximum:g}")
    return value


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _updated_at_for(key: str, values: dict[str, Any]) -> str | None:
    updated_at = values.get("__updated_at__")
    if isinstance(updated_at, dict):
        text = str(updated_at.get(key) or "").strip()
        return text or None
    return None


def _settings_admin_payload(*, storage: dict[str, Any] | None = None) -> dict[str, Any]:
    enabled = _env_bool("SETTINGS_ADMIN_ENABLED", default=False)
    token_configured = bool(os.environ.get("SETTINGS_ADMIN_TOKEN"))
    storage_ready = _settings_storage_write_available(storage)
    write_blocked_reason = _settings_storage_blocked_reason(storage)
    return {
        "enabled": enabled,
        "token_configured": token_configured,
        "write_available": enabled and token_configured and storage_ready,
        "storage": storage or {},
        "write_blocked_reason": "" if storage_ready else write_blocked_reason,
    }


def _settings_storage_write_available(storage: dict[str, Any] | None) -> bool:
    if not storage:
        return True
    if "ready" in storage or "read_only" in storage:
        return storage_write_available(storage)
    states = [value for value in storage.values() if isinstance(value, dict)]
    return all(storage_write_available(state) for state in states)


def _settings_storage_blocked_reason(storage: dict[str, Any] | None) -> str:
    if not storage:
        return ""
    if "ready" in storage or "read_only" in storage:
        return str(storage.get("reason") or "storage_unavailable")
    for state in storage.values():
        if isinstance(state, dict) and not storage_write_available(state):
            return str(state.get("reason") or "storage_unavailable")
    return ""


def _admin_variables() -> list[dict[str, Any]]:
    admin = _settings_admin_payload()
    return [
        {
            "key": "SETTINGS_ADMIN_ENABLED",
            "label": "设置写权限",
            "value": "true" if admin["enabled"] else "false",
            "raw_value": admin["enabled"],
            "value_type": "boolean",
            "state": "requires_restart",
            "locked": True,
            "editable": False,
            "secret": False,
            "source": "environment",
            "description": "控制 settings 写接口是否可用。",
        },
        {
            "key": "SETTINGS_ADMIN_TOKEN",
            "label": "管理员令牌",
            "value": "已配置" if admin["token_configured"] else "未配置",
            "raw_value": admin["token_configured"],
            "value_type": "secret",
            "state": "requires_restart",
            "locked": True,
            "editable": False,
            "secret": True,
            "source": "environment",
            "description": "只通过环境变量配置，永不回显。",
        },
    ]


def _llm_env_lock_variable() -> dict[str, Any]:
    locked = any(_env_present(key) for key in _LLM_ENV_LOCK_KEYS)
    return {
        "key": "WEREWOLF_LLM_*",
        "label": "环境变量模型",
        "value": "锁定默认模型" if locked else "未锁定",
        "raw_value": locked,
        "value_type": "secret",
        "state": "env_locked" if locked else "editable_next_task",
        "locked": locked,
        "editable": False,
        "secret": True,
        "source": "environment" if locked else "default",
        "description": "WEREWOLF_LLM_MODEL/BASE_URL/API_KEY 优先级最高，不允许被本地 settings 覆盖。",
    }


def _env_present(name: str) -> bool:
    return bool(os.environ.get(name))


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return _coerce_bool(raw)
    except ValueError:
        return default


def _env_float(name: str, *, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, *, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


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
