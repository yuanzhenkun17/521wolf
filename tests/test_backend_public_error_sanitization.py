"""Public backend error payload sanitization contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.config import PathConfig
import ui.backend.app as ui_backend_app
from ui.backend.health import _task_control_health
from ui.backend.services.task_service import TaskService


def _assert_not_serialized(value: Any, *forbidden: str) -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for text in forbidden:
        assert text not in serialized


def test_validation_error_does_not_echo_settings_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "settings-token")
    secret = "sk-" + ("validation-secret" * 260)
    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=None, restore_background=False)

    with TestClient(app) as client:
        response = client.post(
            "/api/settings/model-profiles",
            headers={"X-Settings-Admin-Token": "settings-token"},
            json={
                "name": "Leaky profile",
                "provider": "openai_compatible",
                "base_url": "https://llm.example/v1",
                "model": "qwen-max",
                "api_key": secret,
            },
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    _assert_not_serialized(payload, secret, "validation-secretvalidation-secret")


def test_task_control_health_redacts_storage_exception_message(tmp_path: Path) -> None:
    service = TaskService(SimpleNamespace(paths=PathConfig(root=tmp_path), _task_event_log=None))

    def failing_connection() -> Any:
        raise RuntimeError("postgres://user:password@db.local/app?token=health-hidden sk-health-secret123")

    service.open_connection = failing_connection  # type: ignore[method-assign]

    payload = service.task_control_health()

    assert payload["status"] == "error"
    assert payload["error"]["type"] == "RuntimeError"
    _assert_not_serialized(payload, "password@db.local", "health-hidden", "sk-health-secret123")


def test_health_task_control_fallback_redacts_exception_message() -> None:
    class RaisingTaskService:
        def task_control_health(self) -> dict[str, Any]:
            raise RuntimeError("postgres://user:password@db.local/app?token=health-hidden sk-health-secret123")

    payload = _task_control_health(SimpleNamespace(task_service=RaisingTaskService()))

    assert payload["status"] == "error"
    assert payload["error"]["type"] == "RuntimeError"
    _assert_not_serialized(payload, "password@db.local", "health-hidden", "sk-health-secret123")
