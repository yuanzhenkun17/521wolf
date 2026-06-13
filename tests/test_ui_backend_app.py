"""Focused contract tests for the app-native UI FastAPI backend."""

from __future__ import annotations

import json
import re
import asyncio
import ast
import sqlite3
import time
import threading
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import PathConfig
from app.util.time import beijing_now_iso
from storage.public_events import public_events_only
import ui.backend.app as ui_backend_app
from ui.backend.live_game import BroadcastEventSink, LiveGameSession
from ui.backend.schemas import BenchmarkLifecycleRequest, BenchmarkRequest, EvolutionStartRequest, GameStartRequest
import ui.backend.services.benchmark_leaderboard_service as benchmark_leaderboard_service_module
import ui.backend.services.benchmark_service as benchmark_service_module
from ui.backend.services.role_service import RoleService
from ui.backend.sse import stream_queue_sse
from ui.backend.game_serializers import _dead_players, _frontend_review, _player_view_snapshot, _sheriff_from_events, _vote_tally
import ui.backend.store as ui_backend_store
from ui.backend.task_events import TaskEventLog

LIVE_GAME_TIMEOUT_SECONDS = 30.0
LIVE_GAME_POLL_SECONDS = 0.1


def test_frontend_review_does_not_copy_overall_into_missing_dimensions() -> None:
    review = _frontend_review(
        {
            "agent_scores": {
                "1": {
                    "role": "seer",
                    "scores": {
                        "speech_quality": 8.0,
                        "vote_accuracy": 7.0,
                        "skill_accuracy": 9.0,
                        "team_contribution": 6.0,
                        "overall": 7.5,
                    },
                }
            }
        },
        events=[],
    )

    score = review["player_evaluations"][0]
    assert score["speech_score"] == 0.8
    assert score["role_score"] == 0.75
    assert score["logic_score"] is None
    assert score["information_score"] is None


@dataclass
class _FakeVersionSummary:
    version_id: str
    role: str
    source: str = ""
    created_at: str = "2026-01-01T00:00:00+08:00"
    is_baseline: bool = False
    status: str = "active"
    release_stage: str = "draft"
    provenance: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "version_id": self.version_id,
            "role": self.role,
            "source": self.source,
            "created_at": self.created_at,
            "is_baseline": self.is_baseline,
            "status": self.status,
            "release_stage": self.release_stage,
            "provenance": dict(self.provenance or {}),
        }
        if self.metrics is not None:
            payload["metrics"] = dict(self.metrics)
        return payload


class FakeVersionRegistry:
    def __init__(self, root: Path) -> None:
        self._registry_dir = root / "registry"
        self._registry_dir.mkdir(parents=True, exist_ok=True)
        self._versions: dict[str, dict[str, dict[str, Any]]] = {}
        self._baselines: dict[str, str] = {}
        self._rejected: dict[str, list[dict[str, Any]]] = {}
        self._scratch: list[Path] = []

    @property
    def registry_dir(self) -> Path:
        return self._registry_dir

    def close(self) -> None:
        return None

    def publish_skills(
        self,
        role: str,
        skill_contents: dict[str, str],
        *,
        parent_id: str | None = None,
        source: str = "manual",
        run_id: str | None = None,
        proposal_ids: list[str] | None = None,
        version_id: str | None = None,
        set_as_baseline: bool = False,
        expected_current: str | None = None,
        release_stage: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> str:
        del parent_id
        role_versions = self._versions.setdefault(role, {})
        version_id = version_id or f"{role}_v{len(role_versions) + 1}"
        stage = "baseline" if set_as_baseline else str(release_stage or "draft")
        status = "active" if stage == "draft" else stage
        role_versions[version_id] = {
            "summary": _FakeVersionSummary(
                version_id=version_id,
                role=role,
                source=source,
                is_baseline=False,
                status=status,
                release_stage=stage,
                provenance={
                    **dict(provenance or {}),
                    "source": source,
                    "run_id": run_id,
                    "proposal_ids": list(proposal_ids or []),
                    "release_stage": stage,
                },
            ),
            "contents": dict(skill_contents),
        }
        if set_as_baseline and not self.set_baseline(role, version_id, expected_current=expected_current):
            raise RuntimeError(f"Failed to set baseline for {role}")
        return version_id

    def get_baseline(self, role: str) -> str | None:
        return self._baselines.get(role)

    def set_baseline(
        self,
        role: str,
        version_id: str,
        expected_current: str | None = None,
    ) -> bool:
        if version_id not in self._versions.get(role, {}):
            return False
        if self._baselines.get(role) != expected_current:
            return False
        previous = self._baselines.get(role)
        if previous in self._versions.get(role, {}):
            self._versions[role][previous]["summary"].is_baseline = False
        self._baselines[role] = version_id
        summary = self._versions[role][version_id]["summary"]
        summary.is_baseline = True
        summary.status = "promoted"
        summary.release_stage = "baseline"
        summary.provenance = {**dict(summary.provenance or {}), "release_stage": "baseline"}
        return True

    def reject(self, role: str, version_id: str, reason: str = "") -> None:
        del reason
        if version_id not in self._versions.get(role, {}):
            raise FileNotFoundError(f"Version {role}/{version_id} not found")
        self._versions[role][version_id]["summary"].status = "rejected"

    def read_skill_contents(self, role: str, version_id: str) -> dict[str, str]:
        try:
            return dict(self._versions[role][version_id]["contents"])
        except KeyError as exc:
            raise FileNotFoundError(f"Version {role}/{version_id} not found") from exc

    def get_skill_dir(self, role: str, version_id: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="ui_backend_skills_"))
        self._scratch.append(root)
        for rel_path, content in self.read_skill_contents(role, version_id).items():
            output = root / rel_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
        return root

    def build_skill_dir(self, role_versions: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp(prefix="ui_backend_skillset_"))
        self._scratch.append(root)
        for role, version_id in role_versions.items():
            for rel_path, content in self.read_skill_contents(role, version_id).items():
                output = root / role / rel_path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(content, encoding="utf-8")
        return root

    def list_versions(self, role: str) -> list[_FakeVersionSummary]:
        return [item["summary"] for item in self._versions.get(role, {}).values()]

    def list_roles(self) -> list[str]:
        return sorted(self._versions)

    def save_rejected(
        self,
        role: str,
        proposals: list[dict[str, Any]],
        battle_result: dict[str, Any] | None = None,
    ) -> None:
        rows = self._rejected.setdefault(role, [])
        for proposal in proposals:
            row = dict(proposal)
            row["battle_result"] = battle_result
            row["rejected_at"] = "2026-01-01T00:00:00+08:00"
            rows.append(row)

    def load_rejected(self, role: str) -> list[dict[str, Any]]:
        return list(self._rejected.get(role, []))


class _RoleServiceContextFake:
    def __init__(
        self,
        registry: FakeVersionRegistry,
        scores: dict[str, dict[str, dict[str, Any]]],
    ) -> None:
        self._registry = registry
        self._scores = scores
        self._role_overview_cache: dict[str, dict[str, Any]] = {}
        self.score_calls: list[tuple[list[str], str | None]] = []
        self.invalidations = 0

    @property
    def registry(self) -> FakeVersionRegistry:
        return self._registry

    def leaderboard_scores_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        self.score_calls.append((list(roles), evaluation_set_id))
        return {role: self._scores.get(role, {}) for role in roles}

    def invalidate_role_overview_cache(self) -> None:
        self.invalidations += 1
        self._role_overview_cache.clear()


class FakeModel:
    _ACTION_RE = re.compile(r"本次行动:\s*([a-z_]+)")
    _CANDIDATES_RE = re.compile(r"可选目标 candidates:\s*(\[[^\n]*\])")

    async def ainvoke(self, messages: Any) -> Any:
        prompt = self._prompt_from_messages(messages)
        action_type = self._action_type(prompt)
        candidates = self._candidates(prompt)
        choice, target = self._decision(action_type, candidates)
        content = json.dumps(
            {
                "schema_version": "1.0",
                "choice": choice,
                "target": target,
                "public_text": "ok",
                "private_reasoning": "test fake model",
                "confidence": 1,
                "alternatives": candidates[:3],
                "rejected_reasons": [],
                "selected_skills": [],
            },
            ensure_ascii=False,
        )
        return type(
            "Result",
            (),
            {"content": content},
        )()

    def _prompt_from_messages(self, messages: Any) -> str:
        if hasattr(messages, "to_messages"):
            items = list(messages.to_messages())
        elif isinstance(messages, (list, tuple)):
            items = list(messages)
        else:
            items = [messages]
        return "\n".join(self._message_content(message) for message in items)

    def _message_content(self, message: Any) -> str:
        if isinstance(message, dict):
            return str(message.get("content", ""))
        if isinstance(message, tuple) and len(message) >= 2:
            return str(message[1])
        return str(getattr(message, "content", message))

    def _action_type(self, prompt: str) -> str:
        match = self._ACTION_RE.search(prompt)
        return match.group(1) if match else "speak"

    def _candidates(self, prompt: str) -> list[int]:
        match = self._CANDIDATES_RE.search(prompt)
        if not match:
            return []
        try:
            value = ast.literal_eval(match.group(1))
        except (SyntaxError, ValueError):
            return []
        if not isinstance(value, list):
            return []
        candidates: list[int] = []
        for item in value:
            try:
                candidates.append(int(item))
            except (TypeError, ValueError):
                continue
        return candidates

    def _decision(self, action_type: str, candidates: list[int]) -> tuple[str | None, int | None]:
        if action_type == "sheriff_run":
            return "pass", None
        if action_type == "sheriff_withdraw":
            return "stay", None
        if action_type == "sheriff_badge":
            return "destroy", None
        if action_type == "speech_order":
            return "forward", None
        if action_type == "witch_act":
            return "none", None
        if action_type == "white_wolf_explode":
            return "pass", None
        if action_type == "guard_protect":
            return None, max(candidates) if candidates else None
        if action_type == "werewolf_kill":
            return None, min(candidates) if candidates else None
        if action_type in {"seer_check", "hunter_shoot"}:
            return None, min(candidates) if candidates else None
        if action_type in {"exile_vote", "pk_vote", "sheriff_vote"}:
            return None, max(candidates) if candidates else None
        return None, None


class FailingModel(FakeModel):
    async def ainvoke(self, messages: Any) -> Any:
        del messages
        raise TimeoutError("model probe timed out with api_key=secret")


class _FakePersistenceSink:
    def __init__(self) -> None:
        self.records: list[Any] = []

    def record_event(self, entry: Any) -> None:
        self.records.append(entry)

    def record_decision(self, decision: Any) -> None:
        self.records.append(decision)


class _FakeGamePersistence:
    instances: list["_FakeGamePersistence"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.event_sink = _FakePersistenceSink()
        self.decision_sink = _FakePersistenceSink()
        self.saved_results: list[dict[str, Any]] = []
        self.closed = False
        self.close_calls = 0
        self.instances.append(self)

    def create_event_sink(self) -> _FakePersistenceSink:
        return self.event_sink

    def create_decision_sink(self) -> _FakePersistenceSink:
        return self.decision_sink

    def save_game_result(self, **kwargs: Any) -> None:
        self.saved_results.append(kwargs)

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _UiCursor:
    rowcount = 0

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = list(rows or [])
        self.rowcount = len(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _UiMemoryDatabase:
    def __init__(self) -> None:
        self.background_tasks: dict[str, dict[str, Any]] = {}
        self.task_events: dict[int, dict[str, Any]] = {}
        self.task_queue: dict[str, dict[str, Any]] = {}
        self.task_workers: dict[str, dict[str, Any]] = {}
        self.model_profiles: dict[str, dict[str, Any]] = {}
        self.model_profiles_enabled = False
        self.runtime_settings: dict[str, dict[str, Any]] = {}
        self.runtime_settings_enabled = False
        self.settings_audit: dict[str, dict[str, Any]] = {}
        self.settings_audit_enabled = False
        self.background_upserts = 0
        self.background_reads = 0
        self.event_upserts = 0
        self.deletes = 0
        self.begin_writes = 0
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0
        self.ddl_statements: list[str] = []
        self.game_deletes: list[tuple[str, str, str]] = []
        self.lock = threading.Lock()


class _UiMemoryConnection:
    def __init__(self, db: _UiMemoryDatabase) -> None:
        self._db = db
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.begin_writes = 0

    def execute(self, sql: str, parameters: Any = ()) -> _UiCursor:
        if self.closed:
            raise RuntimeError("connection closed")
        text = " ".join(sql.split())
        params = tuple(parameters)

        if text.startswith("CREATE TABLE") or text.startswith("CREATE INDEX"):
            with self._db.lock:
                self._db.ddl_statements.append(text)
            raise AssertionError(f"runtime DDL is not allowed in UI backend tests: {text}")

        if text == "SELECT 1 AS ok":
            return _UiCursor([{"ok": 1}])

        if text.startswith("SELECT version_num FROM public.alembic_version"):
            return _UiCursor([{"version_num": "20260611_0008"}])

        if text == "SELECT status, COUNT(*) AS count FROM ui_task_queue GROUP BY status":
            counts: dict[str, int] = {}
            with self._db.lock:
                for task in self._db.task_queue.values():
                    status = str(task.get("status") or "")
                    counts[status] = counts.get(status, 0) + 1
            return _UiCursor([
                {"status": status, "count": count}
                for status, count in sorted(counts.items())
            ])

        if text.startswith("SELECT COUNT(*) AS count FROM ui_task_queue WHERE status = 'running'"):
            now = str(params[0])
            with self._db.lock:
                if "lease_expires_at > ?" in text:
                    count = sum(
                        1
                        for task in self._db.task_queue.values()
                        if task.get("status") == "running"
                        and task.get("lease_expires_at") is not None
                        and str(task.get("lease_expires_at")) > now
                    )
                else:
                    count = sum(
                        1
                        for task in self._db.task_queue.values()
                        if task.get("status") == "running"
                        and task.get("lease_expires_at") is not None
                        and str(task.get("lease_expires_at")) <= now
                    )
            return _UiCursor([{"count": count}])

        if text.startswith("SELECT worker_id, status, last_heartbeat_at, lease_seconds, current_task_id, metadata FROM ui_task_workers"):
            limit = int(params[0])
            with self._db.lock:
                rows = sorted(
                    (dict(row) for row in self._db.task_workers.values()),
                    key=lambda row: (str(row.get("last_heartbeat_at") or ""), str(row.get("worker_id") or "")),
                    reverse=True,
                )[:limit]
            return _UiCursor(rows)

        if text.startswith("INSERT INTO ui_background_tasks"):
            entity_id, entity_kind, status, payload, updated_at = params
            with self._db.lock:
                self._db.background_tasks[str(entity_id)] = {
                    "entity_id": str(entity_id),
                    "entity_kind": entity_kind,
                    "status": status,
                    "payload": payload,
                    "updated_at": updated_at,
                }
                self._db.background_upserts += 1
            return _UiCursor()

        if text.startswith("SELECT entity_id, entity_kind, status, payload, updated_at FROM ui_background_tasks"):
            with self._db.lock:
                self._db.background_reads += 1
                rows = sorted(
                    (dict(row) for row in self._db.background_tasks.values()),
                    key=lambda row: (str(row.get("updated_at") or ""), str(row.get("entity_id") or "")),
                )
            return _UiCursor(rows)

        if text.startswith("SELECT profile_id, name, provider, base_url, model, api_key_ciphertext"):
            with self._db.lock:
                rows = sorted(
                    (dict(row) for row in self._db.model_profiles.values()),
                    key=lambda row: (str(row.get("created_at") or ""), str(row.get("profile_id") or "")),
                )
            if " WHERE profile_id = ?" in text:
                profile_id = str(params[0])
                rows = [row for row in rows if str(row.get("profile_id") or "") == profile_id]
            return _UiCursor(rows)

        if text.startswith("INSERT INTO ui_model_profiles"):
            (
                profile_id,
                name,
                provider,
                base_url,
                model,
                api_key_ciphertext,
                api_key_kid,
                api_key_masked,
                temperature,
                timeout_seconds,
                max_retries,
                enabled,
                default_scopes,
                capabilities,
                metadata,
                created_at,
                updated_at,
                last_tested_at,
                last_test_status,
                last_test_error,
            ) = params
            with self._db.lock:
                self._db.model_profiles[str(profile_id)] = {
                    "profile_id": str(profile_id),
                    "name": name,
                    "provider": provider,
                    "base_url": base_url,
                    "model": model,
                    "api_key_ciphertext": api_key_ciphertext,
                    "api_key_kid": api_key_kid,
                    "api_key_masked": api_key_masked,
                    "temperature": temperature,
                    "timeout_seconds": timeout_seconds,
                    "max_retries": max_retries,
                    "enabled": bool(enabled),
                    "default_scopes": json.loads(default_scopes) if isinstance(default_scopes, str) else default_scopes,
                    "capabilities": json.loads(capabilities) if isinstance(capabilities, str) else capabilities,
                    "metadata": json.loads(metadata) if isinstance(metadata, str) else metadata,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "last_tested_at": last_tested_at,
                    "last_test_status": last_test_status,
                    "last_test_error": last_test_error,
                }
            return _UiCursor()

        if text.startswith("UPDATE ui_model_profiles SET api_key_ciphertext = ?, api_key_kid = ?"):
            ciphertext, key_id, masked, updated_at, profile_id = params
            with self._db.lock:
                row = self._db.model_profiles[str(profile_id)]
                row["api_key_ciphertext"] = ciphertext
                row["api_key_kid"] = key_id
                row["api_key_masked"] = masked
                row["updated_at"] = updated_at
            return _UiCursor()

        if text.startswith("UPDATE ui_model_profiles SET api_key_ciphertext = NULL"):
            updated_at, profile_id = params
            with self._db.lock:
                row = self._db.model_profiles[str(profile_id)]
                row["api_key_ciphertext"] = None
                row["api_key_kid"] = None
                row["api_key_masked"] = ""
                row["updated_at"] = updated_at
            return _UiCursor()

        if text.startswith("DELETE FROM ui_model_profiles WHERE profile_id = ?"):
            with self._db.lock:
                self._db.model_profiles.pop(str(params[0]), None)
                self._db.deletes += 1
            return _UiCursor()

        if text.startswith("SELECT setting_key, value_json, updated_at, updated_by FROM ui_runtime_settings"):
            with self._db.lock:
                rows = sorted(
                    (dict(row) for row in self._db.runtime_settings.values()),
                    key=lambda row: str(row.get("setting_key") or ""),
                )
            if " WHERE setting_key = ?" in text:
                setting_key = str(params[0])
                rows = [row for row in rows if str(row.get("setting_key") or "") == setting_key]
            return _UiCursor(rows)

        if text.startswith("INSERT INTO ui_runtime_settings"):
            setting_key, value_json, updated_at, updated_by = params
            with self._db.lock:
                self._db.runtime_settings[str(setting_key)] = {
                    "setting_key": str(setting_key),
                    "value_json": json.loads(value_json) if isinstance(value_json, str) else value_json,
                    "updated_at": updated_at,
                    "updated_by": updated_by,
                }
            return _UiCursor()

        if text.startswith("INSERT INTO ui_settings_audit_log"):
            audit_id, action, entity_kind, entity_id, status, actor, message, details, created_at = params
            with self._db.lock:
                self._db.settings_audit[str(audit_id)] = {
                    "audit_id": str(audit_id),
                    "action": action,
                    "entity_kind": entity_kind,
                    "entity_id": str(entity_id),
                    "status": status,
                    "actor": actor,
                    "message": message,
                    "details": json.loads(details) if isinstance(details, str) else details,
                    "created_at": created_at,
                }
            return _UiCursor()

        if text.startswith("SELECT audit_id, action, entity_kind, entity_id, status, actor, message, details, created_at FROM ui_settings_audit_log"):
            limit = int(params[0])
            with self._db.lock:
                rows = sorted(
                    (dict(row) for row in self._db.settings_audit.values()),
                    key=lambda row: (str(row.get("created_at") or ""), str(row.get("audit_id") or "")),
                    reverse=True,
                )[:limit]
            return _UiCursor(rows)

        if text.startswith("INSERT INTO ui_task_events"):
            event_id, entity_id, entity_kind, event, status, payload, created_at = params
            with self._db.lock:
                self._db.task_events[int(event_id)] = {
                    "id": int(event_id),
                    "entity_id": str(entity_id),
                    "entity_kind": entity_kind,
                    "event": event,
                    "status": status,
                    "payload": payload,
                    "created_at": created_at,
                }
                self._db.event_upserts += 1
            return _UiCursor()

        if text.startswith("SELECT id, entity_id, entity_kind, event, status, payload, created_at FROM ui_task_events"):
            limit = int(params[0])
            with self._db.lock:
                rows = sorted(
                    (dict(row) for row in self._db.task_events.values()),
                    key=lambda row: int(row["id"]),
                    reverse=True,
                )[:limit]
            return _UiCursor(rows)

        if text.startswith("DELETE FROM ui_task_events WHERE id < ?"):
            cutoff = int(params[0])
            with self._db.lock:
                for event_id in [event_id for event_id in self._db.task_events if event_id < cutoff]:
                    self._db.task_events.pop(event_id, None)
                    self._db.deletes += 1
            return _UiCursor()

        match = re.match(r"DELETE FROM ([A-Za-z_][A-Za-z0-9_]*) WHERE (game_id|id) = \?", text)
        if match:
            table = match.group(1)
            column = match.group(2)
            game_id = str(params[0]) if params else ""
            with self._db.lock:
                self._db.game_deletes.append((table, column, game_id))
                self._db.deletes += 1
            return _UiCursor()

        if text.startswith("SELECT * FROM games WHERE id = ?"):
            return _UiCursor()

        if "FROM games g" in text and "LEFT JOIN" in text:
            return _UiCursor()

        if text.startswith("SELECT COUNT(*) AS total") and " FROM " in text:
            row: dict[str, Any] = {"total": 0}
            for alias in re.findall(r"\bAS\s+(max_[A-Za-z0-9_]+)", text):
                row[alias] = None
            return _UiCursor([row])

        if "FROM benchmark_leaderboard" in text:
            return _UiCursor()

        raise AssertionError(f"unexpected SQL: {text}")

    def begin_write(self) -> None:
        self.begin_writes += 1
        with self._db.lock:
            self._db.begin_writes += 1

    def commit(self) -> None:
        self.commits += 1
        with self._db.lock:
            self._db.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1
        with self._db.lock:
            self._db.rollbacks += 1

    def close(self) -> None:
        self.closed = True
        with self._db.lock:
            self._db.closes += 1

    def table_exists(self, table_name: str) -> bool:
        if table_name == "ui_model_profiles":
            return self._db.model_profiles_enabled
        if table_name == "ui_runtime_settings":
            return self._db.runtime_settings_enabled
        if table_name == "ui_settings_audit_log":
            return self._db.settings_audit_enabled
        return table_name in {
            "ui_background_tasks",
            "ui_task_events",
            "ui_task_queue",
            "ui_task_artifacts",
            "ui_task_workers",
        }

    def __enter__(self) -> "_UiMemoryConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


class _UiFakeStorageProvider:
    def __init__(self) -> None:
        self.db = _UiMemoryDatabase()

    def open_wolf_connection(self) -> _UiMemoryConnection:
        return _UiMemoryConnection(self.db)

    def open_registry_connection(self) -> _UiMemoryConnection:
        raise AssertionError("registry connection should not be used in UI backend tests")

    def open_evolution_connection(self) -> _UiMemoryConnection:
        raise AssertionError("evolution connection should not be used in UI backend tests")


@pytest.fixture(autouse=True)
def _fake_ui_pg_provider(monkeypatch: pytest.MonkeyPatch) -> _UiFakeStorageProvider:
    import storage.provider as provider_mod
    import ui.backend.game_store as ui_backend_game_store

    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    provider = _UiFakeStorageProvider()

    def provider_from_env(*, paths=None):
        return provider

    monkeypatch.setattr(provider_mod, "storage_provider_from_env", provider_from_env)
    monkeypatch.setattr(ui_backend_game_store, "storage_provider_from_env", provider_from_env)
    return provider


def _test_client(tmp_path: Path) -> TestClient:
    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=FakeModel())
    store = app.state.backend_store
    store._registry = FakeVersionRegistry(tmp_path)
    _FakeGamePersistence.instances.clear()
    import ui.backend.game_store as ui_backend_game_store

    ui_backend_game_store.GamePersistence = _FakeGamePersistence
    terminal_statuses = {"completed", "cancelled", "interrupted", "failed"}

    def pg_games() -> list[dict[str, Any]]:
        return [
            game
            for game in store.games.values()
            if str(game.get("status") or "").lower() in terminal_statuses
        ]

    store._postgres_history_fingerprint = lambda: {
        "games": [
            (
                game.get("game_id"),
                game.get("status"),
                game.get("log_time"),
                game.get("finished_at"),
                game.get("started_at"),
                game.get("last_heartbeat_at"),
            )
            for game in pg_games()
        ]
    }
    store._load_game_from_pg = lambda game_id: store.games.get(game_id)
    store._list_games_from_pg = lambda: [store._game_list_row(game) for game in pg_games()]
    return TestClient(app)


def _seed_fresh_task_worker(db: _UiMemoryDatabase, worker_id: str = "worker-health-test") -> None:
    db.task_workers[worker_id] = {
        "worker_id": worker_id,
        "status": "running",
        "last_heartbeat_at": beijing_now_iso(),
        "lease_seconds": 300,
        "current_task_id": None,
        "metadata": {},
    }


def _seer_skill(body: str = "body") -> dict[str, str]:
    return {
        "vote.md": (
            "---\n"
            "name: s\n"
            "role: seer\n"
            "applicable_actions:\n"
            "  - seer_check\n"
            "status: active\n"
            "evolution:\n"
            "  enabled: true\n"
            "  allowed_actions:\n"
            "    - append_rule\n"
            "---\n"
            f"{body}\n"
        )
    }


def _publish_seer_version(
    registry: FakeVersionRegistry,
    version_id: str,
    *,
    release_stage: str | None = None,
    baseline: bool = False,
    expected_current: str | None = None,
    body: str = "body",
) -> str:
    return registry.publish_skills(
        "seer",
        _seer_skill(body),
        source="test",
        version_id=version_id,
        release_stage=release_stage,
        set_as_baseline=baseline,
        expected_current=expected_current,
    )


def _assert_domain_exception(
    exc: HTTPException,
    *,
    code: str,
    release_stage: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    assert exc.status_code == 409
    assert isinstance(exc.detail, dict)
    assert exc.detail["code"] == code
    assert isinstance(exc.detail["detail"], str)
    diagnostics = exc.detail["diagnostics"]
    assert isinstance(diagnostics, list)
    assert diagnostics
    diagnostic = diagnostics[0]
    if release_stage is not None:
        assert f"release_stage={release_stage}" in exc.detail["detail"]
        assert diagnostic["release_stage"] == release_stage
    if kind is not None:
        assert diagnostic["kind"] == kind
    return exc.detail


def _assert_domain_response(
    response: Any,
    *,
    status_code: int = 409,
    code: str,
    release_stage: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    assert response.status_code == status_code
    payload = response.json()
    assert isinstance(payload["detail"], str)
    error = payload["error"]
    assert error["code"] == code
    diagnostics = error["diagnostics"]
    assert isinstance(diagnostics, list)
    assert diagnostics
    diagnostic = diagnostics[0]
    if release_stage is not None:
        assert f"release_stage={release_stage}" in payload["detail"]
        assert diagnostic["release_stage"] == release_stage
    if kind is not None:
        assert diagnostic["kind"] == kind
    return payload


def _write_benchmark_spec(root: Path, *, benchmark_id: str = "role-baseline-v1") -> None:
    spec_dir = root / "data" / "benchmarks"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{benchmark_id}.yaml").write_text(
        f"""
id: {benchmark_id}
version: 1
name: Role Baseline Benchmark
description: Fixed-seed role version evaluation benchmark
target_type: role_version
roles: [seer, witch]
game_count: 3
max_days: 5
paired_seed: true
seed_set_id: role-baseline-quick-202606
seed_start: 260600
metrics:
  primary: avg_role_score
  secondary: [target_side_win_rate, fallback_rate, llm_error_rate]
gates:
  min_completed_games: 1
  min_valid_game_rate: 0.5
  max_fallback_rate: 0.5
  max_llm_error_rate: 0.5
judge:
  enable_decision_judge: true
  judge_max_decisions: 10
  judge_concurrency: 2
  judge_timeout_seconds: 60
""",
        encoding="utf-8",
    )
    seed_dir = root / "data" / "benchmark_seed_sets"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "role-baseline-quick-202606.yaml").write_text(
        """
id: role-baseline-quick-202606
purpose: role_leaderboard_smoke
version: 1
target_type: role_version
seeds: [260600, 260607, 260619]
enabled: true
""",
        encoding="utf-8",
    )


def _write_model_benchmark_spec(root: Path, *, benchmark_id: str = "model-baseline-v1") -> None:
    spec_dir = root / "data" / "benchmarks"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{benchmark_id}.yaml").write_text(
        f"""
id: {benchmark_id}
version: 1
name: Model Baseline Benchmark
description: Fixed-seed model/runtime evaluation benchmark
target_type: model
roles: [seer, witch]
game_count: 3
max_days: 5
paired_seed: true
seed_set_id: model-baseline-quick-202606
seed_start: 270600
metrics:
  primary: strength_score
  secondary: [avg_role_score, fallback_rate, llm_error_rate]
gates:
  min_completed_games: 1
  min_valid_game_rate: 0.5
  max_fallback_rate: 0.5
  max_llm_error_rate: 0.5
judge:
  enable_decision_judge: true
  judge_max_decisions: 10
  judge_concurrency: 2
  judge_timeout_seconds: 60
""",
        encoding="utf-8",
    )
    seed_dir = root / "data" / "benchmark_seed_sets"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "model-baseline-quick-202606.yaml").write_text(
        """
id: model-baseline-quick-202606
purpose: model_leaderboard_smoke
version: 1
target_type: model
seeds: [270600, 270611, 270623]
enabled: true
""",
        encoding="utf-8",
    )


def _install_sqlite_benchmark_leaderboard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    import app.lib.score as score_lib

    db_path = tmp_path / "benchmark_leaderboard.sqlite3"

    def open_conn(paths: Any = None) -> sqlite3.Connection:
        del paths
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    conn = open_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmark_leaderboard (
                id text PRIMARY KEY,
                scope text NOT NULL,
                subject_id text NOT NULL,
                model_id text,
                model_config_hash text,
                target_role text,
                target_version_id text,
                comparison_group_id text,
                evaluation_set_id text,
                seed_set_id text,
                games_played integer DEFAULT 0,
                valid_game_rate real DEFAULT 0.0,
                strength_score real DEFAULT 0.0,
                avg_role_score real DEFAULT 0.0,
                by_role_category_scores text,
                avg_speech_score real DEFAULT 0.0,
                avg_vote_score real DEFAULT 0.0,
                avg_skill_score real DEFAULT 0.0,
                avg_logic_score real DEFAULT 0.0,
                avg_team_score real DEFAULT 0.0,
                risk_penalty real DEFAULT 0.0,
                fallback_rate real DEFAULT 0.0,
                llm_error_rate real DEFAULT 0.0,
                policy_adjusted_rate real DEFAULT 0.0,
                target_side_win_rate real DEFAULT 0.0,
                rankable integer DEFAULT 0,
                data_sufficient integer DEFAULT 0,
                summary text,
                updated_at text NOT NULL,
                optimistic_version integer NOT NULL DEFAULT 1
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(score_lib, "open_eval_connection", open_conn)
    return open_conn


def _persist_benchmark_leaderboard_entries(open_conn: Any, *entries: dict[str, Any]) -> None:
    from app.lib.score import persist_leaderboard_entry

    conn = open_conn()
    try:
        for entry in entries:
            warning = persist_leaderboard_entry(conn, entry)
            assert warning is None
    finally:
        conn.close()


def _assert_error_payload(payload: dict[str, Any], *, detail: Any, code: str, message: str) -> None:
    assert payload["detail"] == detail
    assert payload["error"]["code"] == code
    assert payload["error"]["message"] == message
    assert isinstance(payload["error"]["diagnostics"], list)


def _compact_game_snapshot(game: dict[str, Any] | None) -> dict[str, Any] | None:
    if game is None:
        return None
    logs = game.get("logs") if isinstance(game.get("logs"), list) else []
    events = game.get("events") if isinstance(game.get("events"), list) else []
    decisions = game.get("decisions") if isinstance(game.get("decisions"), list) else []
    return {
        "status": game.get("status"),
        "waiting_for": game.get("waiting_for"),
        "pending_human_action": game.get("pending_human_action"),
        "log_count": len(logs),
        "event_count": len(events),
        "decision_count": len(decisions),
        "last_logs": logs[-3:],
    }


def _history_snapshot(game_id: str, *, status: str, log_time: str) -> dict[str, Any]:
    return {
        "game_id": game_id,
        "log_name": game_id,
        "status": status,
        "log_time": log_time,
        "started_at": log_time,
        "finished_at": log_time,
        "players": [],
        "events": [],
        "logs": [],
        "decisions": [],
        "config": {"log_time": log_time},
    }

def _stop_game_for_timeout(client: TestClient, game_id: str) -> dict[str, Any]:
    response = client.post(f"/api/games/{game_id}/stop")
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text[-500:]
    return {"status_code": response.status_code, "body": body}


def _wait_for_game_terminal(
    client: TestClient,
    game_id: str,
    timeout: float = LIVE_GAME_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    start = time.monotonic()
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    polls = 0
    while time.monotonic() < deadline:
        polls += 1
        response = client.get(f"/api/games/{game_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("status") in {"completed", "failed", "cancelled"}:
            time.sleep(LIVE_GAME_POLL_SECONDS)
            refresh_response = client.get(f"/api/games/{game_id}")
            assert refresh_response.status_code == 200, refresh_response.text
            refreshed = refresh_response.json()
            if refreshed.get("status") in {"completed", "failed", "cancelled"}:
                return refreshed
            return last
        time.sleep(LIVE_GAME_POLL_SECONDS)
    elapsed = time.monotonic() - start
    try:
        stop_result = _stop_game_for_timeout(client, game_id)
    except Exception as exc:  # pragma: no cover - diagnostic best effort.
        stop_result = {"error": repr(exc)}
    diagnostics = {
        "elapsed_seconds": round(elapsed, 3),
        "timeout_seconds": timeout,
        "polls": polls,
        "last": _compact_game_snapshot(last),
        "stop": stop_result,
    }
    raise AssertionError(f"game {game_id} did not finish before timeout; diagnostics={diagnostics}")


def test_health_and_roles_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEREWOLF_TTS_API_KEY", "")
    import ui.backend.startup_checks as startup_checks_mod

    original_check_alembic = startup_checks_mod._check_alembic
    monkeypatch.setattr(
        startup_checks_mod,
        "_check_alembic",
        lambda store: {"status": "ok", "message": "mocked", "expected_heads": [], "current_versions": []},
    )
    with _test_client(tmp_path) as client:
        health_response = client.get("/api/health")
        roles_response = client.get("/api/roles")

    assert health_response.status_code == 200
    health = health_response.json()
    assert health["ok"] is True
    assert health["schema_version"] == 2
    assert health["ready"] is True
    assert health["status"] == "degraded"
    assert health["mode"] == "api"
    checks = health["checks"]
    assert checks["postgresql"]["status"] == "ok"
    assert checks["alembic"]["status"] == "ok"
    assert checks["registry_baseline"]["status"] == "degraded"
    assert "seer" in checks["registry_baseline"]["missing_roles"]
    assert checks["llm"]["status"] == "ok"
    assert checks["llm_config"]["status"] == "ok"
    assert checks["llm_config"]["source"] == "injected_model"
    assert checks["llm_connectivity"]["status"] == "unknown"
    assert checks["llm_connectivity"]["source"] == "injected_model"
    assert checks["langfuse_config"]["status"] == "ok"
    assert checks["langfuse_config"]["enabled"] is False
    assert checks["langfuse_config"]["source"] == "disabled"
    assert checks["tts_config"]["status"] == "degraded"
    assert checks["tts_config"]["source"] == "missing_config"
    assert checks["task_queue"]["status"] == "degraded"
    assert checks["task_queue"]["queue_status_counts"] == {}
    assert checks["task_queue"]["stale_running_count"] == 0
    assert checks["task_worker"]["status"] == "degraded"
    assert checks["task_worker"]["worker_fresh"] is False
    assert checks["task_worker"]["worker_count"] == 0
    assert "workers" not in checks["task_worker"]
    assert checks["artifact_root"]["status"] == "ok"
    assert checks["artifact_root"]["writable"] is True
    assert "path" not in checks["artifact_root"]
    assert health["gates"]["game_start"]["ready"] is True
    assert health["gates"]["game_start"]["blockers"] == []
    assert "llm_connectivity" in health["gates"]["game_start"]["warnings"]
    assert health["external"]["provider"] == "app-langgraph"
    assert health["external"]["supports_human"] is True
    assert health["external"]["supports_sse"] is True
    startup_checks = health["external"]["startup_checks"]
    assert startup_checks["status"] == "degraded"
    assert startup_checks["checks"]["postgresql"]["status"] == "ok"
    assert startup_checks["checks"]["alembic"]["status"] == "ok"
    assert startup_checks["checks"]["registry_baseline"]["status"] == "degraded"
    assert "seer" in startup_checks["checks"]["registry_baseline"]["missing_roles"]
    assert startup_checks["checks"]["llm"]["status"] == "ok"
    task_control = health["external"]["task_control"]
    assert task_control["status"] == "degraded"
    assert task_control["queue_status_counts"] == {}
    assert task_control["stale_running_count"] == 0
    assert task_control["worker_fresh"] is False
    assert task_control["worker_count"] == 0
    assert "workers" not in task_control
    assert task_control["artifact_root"]["status"] == "ok"
    assert task_control["artifact_root"]["writable"] is True
    assert "path" not in task_control["artifact_root"]

    assert roles_response.status_code == 200
    roles = roles_response.json()["roles"]
    assert "villager" in roles
    assert "werewolf" in roles
    assert "seer" in roles


def test_health_public_task_control_omits_artifact_paths_and_worker_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    monkeypatch.setenv("WOLF_USE_PG_TASK_QUEUE", "true")
    monkeypatch.delenv("WOLF_GIT_SHA", raising=False)
    monkeypatch.delenv("APP_GIT_SHA", raising=False)
    monkeypatch.delenv("WOLF_APP_ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    monkeypatch.setenv("WOLF_APP_RELEASE", "release-20260611")
    monkeypatch.setenv("GITHUB_SHA", "abcdef1234567890")
    monkeypatch.setenv("LANGFUSE_ENVIRONMENT", "production")
    worker_secret = "worker-secret-id"
    task_secret = "task-secret-id"
    metadata_secret = "sk-worker-health-secret"
    _fake_ui_pg_provider.db.task_workers[worker_secret] = {
        "worker_id": worker_secret,
        "status": "running",
        "last_heartbeat_at": beijing_now_iso(),
        "lease_seconds": 300,
        "current_task_id": task_secret,
        "metadata": {"api_key": metadata_secret},
    }

    with _test_client(tmp_path) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    checks = payload["checks"]
    task_control = payload["external"]["task_control"]

    assert checks["task_worker"]["status"] == "ok"
    assert checks["task_worker"]["worker_fresh"] is True
    assert checks["task_worker"]["worker_count"] == 1
    assert "workers" not in checks["task_worker"]
    assert "path" not in checks["artifact_root"]
    assert task_control["worker_fresh"] is True
    assert task_control["worker_count"] == 1
    assert "workers" not in task_control
    assert "path" not in task_control["artifact_root"]
    assert payload["release"] == {
        "release": "release-20260611",
        "git_sha": "abcdef1234567890",
        "git_sha_short": "abcdef123456",
        "environment": "production",
        "configured": True,
        "sources": {
            "release": "WOLF_APP_RELEASE",
            "git_sha": "GITHUB_SHA",
            "environment": "LANGFUSE_ENVIRONMENT",
        },
    }

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert worker_secret not in serialized
    assert task_secret not in serialized
    assert metadata_secret not in serialized
    assert str(tmp_path) not in serialized


def test_ops_metrics_reports_public_counts_without_sensitive_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    import ui.backend.startup_checks as startup_checks_mod

    monkeypatch.setattr(
        startup_checks_mod,
        "_check_alembic",
        lambda store: {"status": "ok", "message": "mocked", "expected_heads": [], "current_versions": []},
    )
    monkeypatch.setenv("WOLF_USE_PG_TASK_QUEUE", "true")
    monkeypatch.delenv("WOLF_APP_RELEASE", raising=False)
    monkeypatch.delenv("WOLF_GIT_SHA", raising=False)
    monkeypatch.setenv("APP_RELEASE", "ops-release")
    monkeypatch.setenv("APP_GIT_SHA", "1234567890abcdef")
    worker_secret = "worker-secret-id"
    task_secret = "task-secret-id"
    metadata_secret = "sk-worker-health-secret"
    _fake_ui_pg_provider.db.task_workers[worker_secret] = {
        "worker_id": worker_secret,
        "status": "running",
        "last_heartbeat_at": beijing_now_iso(),
        "lease_seconds": 300,
        "current_task_id": task_secret,
        "metadata": {"api_key": metadata_secret},
    }
    _fake_ui_pg_provider.db.task_queue["queued-secret-task"] = {
        "task_id": "queued-secret-task",
        "kind": "benchmark",
        "status": "queued",
        "payload": {"api_key": "sk-task-payload-secret"},
        "updated_at": beijing_now_iso(),
    }

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.live_sessions["live-secret-game"] = object()
        store.games["game-running"] = {"game_id": "game-running", "status": "running"}
        store.games["game-completed"] = {"game_id": "game-completed", "status": "completed"}
        store.evolution_runs["run-active"] = {"run_id": "run-active", "status": "running"}
        store.evolution_batches["batch-done"] = {"batch_id": "batch-done", "status": "completed"}
        response = client.get("/api/ops/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "ops_metrics"
    assert payload["schema_version"] == 1
    assert payload["ready"] is True
    assert payload["status"] in {"ok", "degraded"}
    metrics = payload["metrics"]
    assert metrics["health_ready"] == 1
    assert metrics["live_game_active_count"] == 1
    assert metrics["game_status_counts"]["running"] == 1
    assert metrics["game_status_counts"]["completed"] == 1
    assert metrics["background_active_count"] == 1
    assert metrics["background_status_counts"]["running"] == 1
    assert metrics["background_status_counts"]["completed"] == 1
    assert metrics["task_queue_status_counts"]["queued"] == 1
    assert metrics["task_worker_fresh"] == 1
    assert metrics["task_worker_count"] == 1
    assert payload["tasks"]["worker_fresh"] is True
    assert payload["tasks"]["worker_count"] == 1
    assert payload["checks"]["task_worker"]["status"] == "ok"
    assert payload["release"]["release"] == "ops-release"
    assert payload["release"]["git_sha"] == "1234567890abcdef"
    assert payload["release"]["git_sha_short"] == "1234567890ab"

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert worker_secret not in serialized
    assert task_secret not in serialized
    assert metadata_secret not in serialized
    assert "sk-task-payload-secret" not in serialized
    assert str(tmp_path) not in serialized


def test_ops_metrics_alerts_when_langfuse_input_output_capture_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example")
    monkeypatch.setenv("LANGFUSE_CAPTURE_INPUT_OUTPUT", "false")
    monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "1")

    with _test_client(tmp_path) as client:
        response = client.get("/api/ops/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["integrations"]["langfuse"]["enabled"] is True
    assert payload["integrations"]["langfuse"]["capture_input_output"] is False
    alert_codes = {alert["code"] for alert in payload["alerts"]}
    assert "langfuse.capture_input_output_disabled" in alert_codes
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "secret-test" not in serialized


def test_health_reports_optional_langfuse_and_tts_without_blocking_launch_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "")
    monkeypatch.setenv("WEREWOLF_TTS_API_KEY", "")

    with _test_client(tmp_path) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["ready"] is False
    checks = payload["checks"]
    assert checks["langfuse_config"]["status"] == "error"
    assert checks["langfuse_config"]["missing"] == [
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
    ]
    assert checks["tts_config"]["status"] == "degraded"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "LANGFUSE_SECRET_KEY" in serialized
    assert "secret-" not in serialized

    for scope in ("game_start", "benchmark_start", "evolution_start"):
        gate = payload["gates"][scope]
        assert "langfuse_config" not in gate["blockers"]
        assert "tts_config" not in gate["blockers"]


def test_health_probe_llm_updates_connectivity_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    headers = {"X-Settings-Admin-Token": "token-123"}
    with _test_client(tmp_path) as client:
        before_response = client.get("/api/health")
        forbidden_response = client.post("/api/health/probes/llm?scope=settings_model_test")
        probe_response = client.post("/api/health/probes/llm?scope=settings_model_test", headers=headers)
        after_response = client.get("/api/health")

    assert before_response.status_code == 200
    assert before_response.json()["checks"]["llm_connectivity"]["status"] == "unknown"

    assert forbidden_response.status_code == 403
    assert forbidden_response.json()["error"]["code"] == "settings_admin_required"

    assert probe_response.status_code == 200
    probe = probe_response.json()
    assert probe["status"] == "ok"
    assert probe["scope"] == "settings_model_test"
    assert probe["source"] == "injected_model"
    assert isinstance(probe["latency_ms"], int)
    assert probe["checked_at"]

    assert after_response.status_code == 200
    llm_connectivity = after_response.json()["checks"]["llm_connectivity"]
    assert llm_connectivity["status"] == "ok"
    assert llm_connectivity["scope"] == "settings_model_test"
    assert llm_connectivity["source"] == "injected_model"


def test_health_preflight_endpoint_returns_runtime_gate(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        response = client.post("/api/health/preflight?scope=benchmark_start&model_scope=benchmark")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "benchmark_start"
    assert payload["model_scope"] == "benchmark"
    assert payload["model_profile_id"] is None
    assert payload["ready"] is True
    assert payload["gate"]["ready"] is True
    assert payload["checks"]["llm_connectivity"]["status"] == "ok"
    assert "secret" not in json.dumps(payload, ensure_ascii=False)


def test_game_start_blocks_when_llm_probe_fails(tmp_path: Path) -> None:
    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=FailingModel())
    store = app.state.backend_store
    store._registry = FakeVersionRegistry(tmp_path)
    _FakeGamePersistence.instances.clear()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/games",
            json={"seed": 2, "max_days": 1, "player_count": 12},
        )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "runtime_not_ready"
    assert payload["error"]["message"] == "模型连接不可用，不能开始游戏。"
    detail = payload["detail"]
    assert detail["scope"] == "game_start"
    assert detail["blockers"] == ["llm_connectivity"]
    assert detail["checks"]["llm_connectivity"]["status"] == "error"
    assert detail["checks"]["llm_connectivity"]["error"]["type"] == "TimeoutError"
    assert "secret" not in json.dumps(detail, ensure_ascii=False)
    assert store.live_sessions == {}
    assert store.games == {}
    assert _FakeGamePersistence.instances == []


def test_http_launch_entrypoints_share_runtime_gate_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def failing_preflight(store: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"store": store, **kwargs})
        raise HTTPException(
            status_code=503,
            detail={
                "code": "runtime_not_ready",
                "message": "运行环境未就绪。",
                "scope": kwargs.get("scope"),
                "model_scope": kwargs.get("model_scope"),
                "model_profile_id": kwargs.get("model_profile_id"),
                "blockers": ["llm_connectivity"],
                "actions": ["Open Settings and test the model connection."],
            },
        )

    monkeypatch.setattr("ui.backend.services.live_game_lifecycle.require_runtime_ready", failing_preflight)
    monkeypatch.setattr("ui.backend.routes.benchmark.require_runtime_ready", failing_preflight)
    monkeypatch.setattr("ui.backend.routes.evolution.require_runtime_ready", failing_preflight)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        responses = [
            client.post("/api/games", json={"seed": 2, "max_days": 1, "player_count": 12}),
            client.post("/api/benchmark", json={"roles": ["seer"], "battle_games": 1, "max_days": 1}),
            client.post("/api/benchmark/batch", json={"roles": ["seer"], "battle_games": 1, "max_days": 1}),
            client.post("/api/evolution-runs", json={"roles": ["seer"], "training_games": 0, "battle_games": 0}),
        ]

    assert [response.status_code for response in responses] == [503, 503, 503, 503]
    for response in responses:
        payload = response.json()
        assert payload["error"]["code"] == "runtime_not_ready"
        assert payload["detail"]["blockers"] == ["llm_connectivity"]
        assert payload["detail"]["actions"] == ["Open Settings and test the model connection."]

    assert [
        (call["scope"], call["model_scope"], call["model_profile_id"])
        for call in calls
    ] == [
        ("game_start", "game_decision", None),
        ("benchmark_start", "benchmark", None),
        ("benchmark_start", "benchmark", None),
        ("evolution_start", "evolution", None),
    ]
    assert all(call["store"] is store for call in calls)
    assert store.live_sessions == {}
    assert store.games == {}
    assert store.evolution_runs == {}
    assert store.evolution_batches == {}


def test_settings_model_profiles_are_read_only_without_admin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SETTINGS_ADMIN_ENABLED", raising=False)
    monkeypatch.delenv("SETTINGS_ADMIN_TOKEN", raising=False)

    with _test_client(tmp_path) as client:
        list_response = client.get("/api/settings/model-profiles")
        create_response = client.post(
            "/api/settings/model-profiles",
            json={
                "name": "Qwen Prod",
                "provider": "openai_compatible",
                "base_url": "https://example.com/v1",
                "model": "qwen-plus",
                "api_key": "sk-secret-readonly",
            },
        )

    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["kind"] == "settings_model_profiles"
    assert payload["profiles"] == []
    assert payload["admin"]["enabled"] is False
    assert payload["admin"]["token_configured"] is False
    assert payload["admin"]["write_available"] is False
    assert payload["admin"]["storage"]["model_profiles"]["reason"] == "missing_table"
    assert payload["health"]["schema_version"] == 2
    assert payload["ops_metrics"]["kind"] == "ops_metrics"
    assert "alerts" in payload["ops_metrics"]

    assert create_response.status_code == 403
    assert create_response.json()["error"]["code"] == "settings_admin_disabled"


def test_settings_model_profiles_block_writes_when_postgres_storage_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    headers = {"X-Settings-Admin-Token": "token-123"}

    with _test_client(tmp_path) as client:
        list_response = client.get("/api/settings/model-profiles")
        create_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Qwen Prod",
                "provider": "openai_compatible",
                "base_url": "https://example.com/v1",
                "model": "qwen-plus",
                "api_key": "sk-secret-blocked",
            },
        )

    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["admin"]["enabled"] is True
    assert payload["admin"]["token_configured"] is True
    assert payload["admin"]["write_available"] is False
    assert payload["storage"]["model_profiles"]["backend"] == "postgres"
    assert payload["storage"]["model_profiles"]["reason"] == "missing_table"

    assert create_response.status_code == 503
    error_payload = create_response.json()
    assert error_payload["error"]["code"] == "settings_storage_unavailable"
    assert error_payload["error"]["diagnostics"][0]["reason"] == "missing_table"
    assert not (tmp_path / "data" / "settings" / "model-profiles.json").exists()
    assert not (tmp_path / "data" / "settings" / "model-profile-secrets.json").exists()


def test_settings_model_profiles_require_secret_encryption_for_postgres_writes(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    _fake_ui_pg_provider.db.model_profiles_enabled = True
    monkeypatch.delenv("SETTINGS_SECRET_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    headers = {"X-Settings-Admin-Token": "token-123"}

    with _test_client(tmp_path) as client:
        list_response = client.get("/api/settings/model-profiles")
        create_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Encrypted Required",
                "provider": "openai_compatible",
                "base_url": "https://example.com/v1",
                "model": "qwen-plus",
                "api_key": "sk-secret-blocked",
            },
        )

    assert list_response.status_code == 200
    assert list_response.json()["storage"]["model_profiles"]["reason"] == "secret_encryption_missing"
    assert create_response.status_code == 503
    payload = create_response.json()
    assert payload["error"]["code"] == "settings_storage_unavailable"
    assert payload["error"]["diagnostics"][0]["reason"] == "secret_encryption_missing"
    assert _fake_ui_pg_provider.db.model_profiles == {}
    assert not (tmp_path / "data" / "settings" / "model-profiles.json").exists()


def test_settings_model_profile_admin_crud_masks_secret_and_tests_connection(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    import ui.backend.settings_model_profiles as settings_model_profiles

    class ProbeModel:
        async def ainvoke(self, messages: Any) -> Any:
            assert messages == settings_model_profiles.MODEL_PROFILE_TEST_PROMPT
            return type("Result", (), {"content": "ok"})()

    create_calls: list[dict[str, Any]] = []

    def fake_create_llm(**kwargs: Any) -> ProbeModel:
        create_calls.append(dict(kwargs))
        return ProbeModel()

    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "settings-secret-test-key")
    _fake_ui_pg_provider.db.model_profiles_enabled = True
    monkeypatch.setattr(settings_model_profiles, "create_llm", fake_create_llm)
    headers = {"X-Settings-Admin-Token": "token-123"}

    with _test_client(tmp_path) as client:
        forbidden_response = client.post(
            "/api/settings/model-profiles",
            json={
                "name": "DeepSeek Dev",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "api_key": "sk-secret-denied",
            },
        )
        create_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "DeepSeek Dev",
                "provider": "openai_compatible",
                "base_url": "https://api.deepseek.com/v1?api_key=hidden-query&token=hidden-token",
                "model": "deepseek-chat",
                "api_key": "sk-secret-123456",
                "temperature": 0.3,
                "timeout_seconds": 45,
                "max_retries": 1,
                "default_scopes": {"benchmark": True, "prompt_test": True},
                "capabilities": {"chat": True, "json_mode": True},
                "metadata": {
                    "public_label": "dev",
                    "api_key": "metadata-api-key",
                    "secret_ref": "metadata-secret-ref",
                },
            },
        )
        profile = create_response.json()["profile"]
        profile_id = profile["profile_id"]
        patch_response = client.patch(
            f"/api/settings/model-profiles/{profile_id}",
            headers=headers,
            json={"model": "deepseek-chat-v2"},
        )
        test_response = client.post(f"/api/settings/model-profiles/{profile_id}/test", headers=headers)
        disable_response = client.post(f"/api/settings/model-profiles/{profile_id}/disable", headers=headers)
        list_response = client.get("/api/settings/model-profiles")
        delete_response = client.delete(f"/api/settings/model-profiles/{profile_id}", headers=headers)
        audit_response = client.get("/api/settings/audit-log?limit=10")
        final_response = client.get("/api/settings/model-profiles")

    assert forbidden_response.status_code == 403
    assert forbidden_response.json()["error"]["code"] == "settings_admin_required"

    assert create_response.status_code == 200
    assert profile["name"] == "DeepSeek Dev"
    assert profile["base_url"] == "https://api.deepseek.com/v1"
    assert profile["api_key_masked"] == "sk-****3456"
    assert profile["has_api_key"] is True
    assert profile["metadata"]["public_label"] == "dev"
    assert profile["metadata"]["api_key"] == "[REDACTED]"
    assert profile["metadata"]["secret_ref"] == "[REDACTED]"
    assert profile["default_scopes"]["benchmark"] is True
    assert profile["default_scopes"]["evolution"] is False
    serialized_create = json.dumps(create_response.json(), ensure_ascii=False)
    assert "sk-secret" not in serialized_create
    assert "hidden-query" not in serialized_create
    assert "hidden-token" not in serialized_create
    assert "metadata-api-key" not in serialized_create
    assert "metadata-secret-ref" not in serialized_create

    assert patch_response.status_code == 200
    patched = patch_response.json()["profile"]
    assert patched["model"] == "deepseek-chat-v2"
    assert patched["last_test_status"] == "stale"

    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True
    assert test_response.json()["model"] == "deepseek-chat-v2"
    assert create_calls[-1]["api_key"] == "sk-secret-123456"
    assert create_calls[-1]["model"] == "deepseek-chat-v2"
    assert create_calls[-1]["base_url"] == "https://api.deepseek.com/v1"

    assert disable_response.status_code == 200
    assert disable_response.json()["profile"]["enabled"] is False
    listed = list_response.json()["profiles"]
    assert [item["profile_id"] for item in listed] == [profile_id]
    assert listed[0]["last_test_status"] == "ok"
    assert listed[0]["api_key_masked"] == "sk-****3456"
    serialized_list = json.dumps(list_response.json(), ensure_ascii=False)
    assert "sk-secret" not in serialized_list
    assert "hidden-query" not in serialized_list
    assert "hidden-token" not in serialized_list
    assert "metadata-api-key" not in serialized_list
    assert "metadata-secret-ref" not in serialized_list

    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()
    assert audit_payload["kind"] == "settings_audit_log"
    audit_actions = {event["action"] for event in audit_payload["events"]}
    assert {
        "model_profile.deleted",
        "model_profile.disabled",
        "model_profile.tested",
        "model_profile.updated",
        "model_profile.created",
    }.issubset(audit_actions)
    assert all(event["actor"] == "settings_admin" for event in audit_payload["events"])
    assert "sk-secret" not in json.dumps(audit_payload, ensure_ascii=False)
    assert final_response.json()["profiles"] == []


def test_settings_model_profiles_store_api_keys_encrypted_in_postgres(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    import ui.backend.settings_model_profiles as settings_model_profiles

    class ProbeModel:
        async def ainvoke(self, messages: Any) -> Any:
            assert messages == settings_model_profiles.MODEL_PROFILE_TEST_PROMPT
            return type("Result", (), {"content": "ok"})()

    create_calls: list[dict[str, Any]] = []

    def fake_create_llm(**kwargs: Any) -> ProbeModel:
        create_calls.append(dict(kwargs))
        return ProbeModel()

    _fake_ui_pg_provider.db.model_profiles_enabled = True
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "settings-secret-test-key")
    monkeypatch.setattr(settings_model_profiles, "create_llm", fake_create_llm)
    headers = {"X-Settings-Admin-Token": "token-123"}

    with _test_client(tmp_path) as client:
        create_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Encrypted Qwen",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "qwen-encrypted",
                "api_key": "sk-postgres-secret-123456",
                "default_scopes": {"benchmark": True},
                "capabilities": {"chat": True, "json_mode": True},
            },
        )
        profile_id = create_response.json()["profile"]["profile_id"]
        list_response = client.get("/api/settings/model-profiles")
        test_response = client.post(f"/api/settings/model-profiles/{profile_id}/test", headers=headers)

    assert create_response.status_code == 200
    created_payload = create_response.json()
    assert created_payload["profile"]["api_key_masked"] == "sk-****3456"
    assert created_payload["profile"]["has_api_key"] is True
    assert "sk-postgres-secret" not in json.dumps(created_payload, ensure_ascii=False)

    db_row = _fake_ui_pg_provider.db.model_profiles[profile_id]
    assert db_row["api_key_ciphertext"]
    assert db_row["api_key_kid"] == "settings:v1"
    assert db_row["api_key_masked"] == "sk-****3456"
    assert "sk-postgres-secret" not in str(db_row["api_key_ciphertext"])
    assert not (tmp_path / "data" / "settings" / "model-profile-secrets.json").exists()

    assert list_response.status_code == 200
    listed_payload = list_response.json()
    assert listed_payload["profiles"][0]["has_api_key"] is True
    assert listed_payload["profiles"][0]["api_key_masked"] == "sk-****3456"
    assert "sk-postgres-secret" not in json.dumps(listed_payload, ensure_ascii=False)

    assert test_response.status_code == 200
    assert test_response.json()["ok"] is True
    assert create_calls[-1]["api_key"] == "sk-postgres-secret-123456"
    assert create_calls[-1]["model"] == "qwen-encrypted"

    with _test_client(tmp_path) as client:
        clear_response = client.patch(
            f"/api/settings/model-profiles/{profile_id}",
            headers=headers,
            json={"clear_api_key": True},
        )

    assert clear_response.status_code == 200
    assert clear_response.json()["profile"]["has_api_key"] is False
    cleared_row = _fake_ui_pg_provider.db.model_profiles[profile_id]
    assert cleared_row["api_key_ciphertext"] is None
    assert cleared_row["api_key_masked"] == ""


def test_settings_model_profile_delete_does_not_decrypt_rotated_postgres_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    _fake_ui_pg_provider.db.model_profiles_enabled = True
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "old-settings-secret")
    headers = {"X-Settings-Admin-Token": "token-123"}

    with _test_client(tmp_path) as client:
        create_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Rotated Secret Model",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "rotated-secret-model",
                "api_key": "sk-old-secret",
            },
        )
        profile_id = create_response.json()["profile"]["profile_id"]
        monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "new-settings-secret")
        delete_response = client.delete(f"/api/settings/model-profiles/{profile_id}", headers=headers)

    assert create_response.status_code == 200
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert profile_id not in _fake_ui_pg_provider.db.model_profiles


def test_settings_model_profile_default_update_does_not_decrypt_rotated_postgres_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    _fake_ui_pg_provider.db.model_profiles_enabled = True
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "old-settings-secret")
    headers = {"X-Settings-Admin-Token": "token-123"}

    with _test_client(tmp_path) as client:
        create_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Rotated Secret Model",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "rotated-secret-model",
                "api_key": "sk-old-secret",
            },
        )
        profile_id = create_response.json()["profile"]["profile_id"]
        original_ciphertext = _fake_ui_pg_provider.db.model_profiles[profile_id]["api_key_ciphertext"]
        monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "new-settings-secret")
        update_response = client.patch(
            f"/api/settings/model-profiles/{profile_id}",
            headers=headers,
            json={"default_scopes": {"game_decision": True, "benchmark": True, "evolution": True}},
        )

    assert create_response.status_code == 200
    assert update_response.status_code == 200
    profile = update_response.json()["profile"]
    assert profile["has_api_key"] is True
    assert profile["default_scopes"]["game_decision"] is True
    assert profile["default_scopes"]["benchmark"] is True
    assert profile["default_scopes"]["evolution"] is True
    assert _fake_ui_pg_provider.db.model_profiles[profile_id]["api_key_ciphertext"] == original_ciphertext


def test_settings_runtime_variables_update_health_gates_and_respect_env_locks(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    _fake_ui_pg_provider.db.runtime_settings_enabled = True
    _fake_ui_pg_provider.db.settings_audit_enabled = True
    monkeypatch.delenv("TASK_WORKER_REQUIRED", raising=False)
    monkeypatch.delenv("WOLF_USE_PG_TASK_QUEUE", raising=False)
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    headers = {"X-Settings-Admin-Token": "token-123"}

    with _test_client(tmp_path) as client:
        list_response = client.get("/api/settings/runtime-variables")
        update_response = client.patch(
            "/api/settings/runtime-variables/TASK_WORKER_REQUIRED",
            headers=headers,
            json={"value": True},
        )
        health_response = client.get("/api/health")
        settings_response = client.get("/api/settings/model-profiles")
        audit_response = client.get("/api/settings/audit-log?limit=5")

    assert list_response.status_code == 200
    listed = list_response.json()["variables"]
    worker_var = next(item for item in listed if item["key"] == "TASK_WORKER_REQUIRED")
    concurrency_var = next(item for item in listed if item["key"] == "WEREWOLF_GAME_CONCURRENCY")
    assert worker_var["editable"] is True
    assert worker_var["value"] == "false"
    assert worker_var["source"] == "default"
    assert concurrency_var["label"] == "多局并发数"
    assert concurrency_var["raw_value"] == 0
    assert concurrency_var["minimum"] == 0
    assert concurrency_var["maximum"] == 64

    assert update_response.status_code == 200
    updated = update_response.json()["variable"]
    assert updated["key"] == "TASK_WORKER_REQUIRED"
    assert updated["raw_value"] is True
    assert updated["source"] == "settings"
    assert _fake_ui_pg_provider.db.runtime_settings["TASK_WORKER_REQUIRED"]["value_json"] is True
    assert audit_response.status_code == 200
    audit_events = audit_response.json()["events"]
    assert audit_events[0]["action"] == "runtime_variable.updated"
    assert audit_events[0]["entity_id"] == "TASK_WORKER_REQUIRED"
    assert audit_events[0]["details"]["value_type"] == "boolean"
    assert _fake_ui_pg_provider.db.settings_audit

    health = health_response.json()
    assert health["ready"] is False
    assert health["status"] == "error"
    assert health["checks"]["task_worker"]["status"] == "error"
    assert health["gates"]["benchmark_start"]["ready"] is False
    assert "task_worker" in health["gates"]["benchmark_start"]["blockers"]

    payload_vars = settings_response.json()["variables"]
    payload_worker_var = next(item for item in payload_vars if item["key"] == "TASK_WORKER_REQUIRED")
    assert payload_worker_var["value"] == "true"
    assert payload_worker_var["source"] == "settings"
    ops_metrics = settings_response.json()["ops_metrics"]
    assert ops_metrics["kind"] == "ops_metrics"
    assert ops_metrics["metrics"]["health_gate_blocked_count"] >= 1
    assert any(alert["code"] == "health_not_ready" for alert in ops_metrics["alerts"])
    assert any(alert["code"] == "task_worker.not_fresh" for alert in ops_metrics["alerts"])

    monkeypatch.setenv("TASK_WORKER_REQUIRED", "false")
    with _test_client(tmp_path) as client:
        locked_list_response = client.get("/api/settings/runtime-variables")
        locked_update_response = client.patch(
            "/api/settings/runtime-variables/TASK_WORKER_REQUIRED",
            headers=headers,
            json={"value": True},
        )

    locked_worker_var = next(
        item for item in locked_list_response.json()["variables"]
        if item["key"] == "TASK_WORKER_REQUIRED"
    )
    assert locked_worker_var["locked"] is True
    assert locked_worker_var["editable"] is False
    assert locked_worker_var["value"] == "false"
    assert locked_worker_var["source"] == "environment"
    assert locked_update_response.status_code == 409
    assert locked_update_response.json()["error"]["code"] == "settings_runtime_variable_locked"


def test_settings_runtime_variables_block_writes_when_postgres_storage_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("TASK_WORKER_REQUIRED", raising=False)
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    headers = {"X-Settings-Admin-Token": "token-123"}

    with _test_client(tmp_path) as client:
        list_response = client.get("/api/settings/runtime-variables")
        update_response = client.patch(
            "/api/settings/runtime-variables/TASK_WORKER_REQUIRED",
            headers=headers,
            json={"value": True},
        )

    assert list_response.status_code == 200
    assert list_response.json()["admin"]["write_available"] is False
    assert list_response.json()["storage"]["runtime_variables"]["reason"] == "missing_table"
    assert update_response.status_code == 503
    payload = update_response.json()
    assert payload["error"]["code"] == "settings_storage_unavailable"
    assert payload["error"]["diagnostics"][0]["reason"] == "missing_table"
    assert not (tmp_path / "data" / "settings" / "runtime-variables.json").exists()


def test_settings_model_profile_runtime_resolver_feeds_launch_provenance(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    import ui.backend.settings_model_profiles as settings_model_profiles

    class ProfileModel(FakeModel):
        model_id = "settings-runtime-model"

    create_calls: list[dict[str, Any]] = []

    def fake_create_llm(**kwargs: Any) -> ProfileModel:
        create_calls.append(dict(kwargs))
        return ProfileModel()

    monkeypatch.delenv("UI_BACKEND_USE_FAKE_LLM", raising=False)
    for key in ("WEREWOLF_LLM_API_KEY", "WEREWOLF_LLM_BASE_URL", "WEREWOLF_LLM_MODEL"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "settings-secret-test-key")
    _fake_ui_pg_provider.db.model_profiles_enabled = True
    monkeypatch.setattr(settings_model_profiles, "create_llm", fake_create_llm)
    _write_model_benchmark_spec(tmp_path)

    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=None)
    store = app.state.backend_store
    headers = {"X-Settings-Admin-Token": "token-123"}

    with TestClient(app) as client:
        create_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Runtime Qwen",
                "provider": "openai_compatible",
                "base_url": "https://token.example.test/v1?api_key=hidden",
                "model": "qwen-runtime",
                "api_key": "sk-runtime-secret",
                "temperature": 0.25,
                "timeout_seconds": 33,
                "max_retries": 2,
                "default_scopes": {"game_decision": True, "benchmark": True, "evolution": True},
                "capabilities": {"chat": True, "json_mode": True},
            },
        )
        profile_id = create_response.json()["profile"]["profile_id"]
        preflight_response = client.post(
            f"/api/health/preflight?scope=benchmark_start&model_scope=benchmark&model_profile_id={profile_id}"
        )
        health_response = client.get("/api/health")

    assert create_response.status_code == 200
    created_profile = create_response.json()["profile"]
    assert created_profile["base_url"] == "https://token.example.test/v1"
    assert "api_key=hidden" not in json.dumps(create_response.json(), ensure_ascii=False)
    assert preflight_response.status_code == 200
    preflight = preflight_response.json()
    assert preflight["ready"] is True
    assert preflight["checks"]["llm_config"]["source"] == "settings_profile"
    assert preflight["checks"]["llm_config"]["model_profile_id"] == profile_id
    assert preflight["checks"]["llm_connectivity"]["model_profile_id"] == profile_id
    assert preflight["gate"]["ready"] is True
    health = health_response.json()
    assert health["checks"]["llm_config"]["source"] == "settings_profile"
    assert health["checks"]["llm_config"]["model"] == "qwen-runtime"
    assert health["checks"]["llm_config"]["model_profile_id"] == profile_id
    assert health["gates"]["game_start"]["ready"] is True

    profile_plan = store.benchmark_service.plan_benchmark(
        BenchmarkRequest(benchmark_id="model-baseline-v1", target_type="model", model_profile_id=profile_id)
    )
    plan_runtime = profile_plan["model_runtime"]
    assert profile_plan["model_id"] == "qwen-runtime"
    assert profile_plan["model_config_hash"] == plan_runtime["model_config_hash"]
    assert plan_runtime["source"] == "settings_profile"
    assert plan_runtime["model_profile_id"] == profile_id
    assert plan_runtime["scope"] == "benchmark"
    assert plan_runtime["base_url_host"] == "token.example.test"

    benchmark_request = BenchmarkRequest(benchmark_id="model-baseline-v1", target_type="model")
    batch = store.benchmark_service.queue_benchmark(benchmark_request)
    benchmark_runtime = batch["model_runtime"]
    assert benchmark_runtime["source"] == "settings_profile"
    assert benchmark_runtime["model_profile_id"] == profile_id
    assert benchmark_runtime["base_url_host"] == "token.example.test"
    assert benchmark_runtime["hash_input"]["base_url_host"] == "token.example.test"
    assert benchmark_runtime["model_id"] == "qwen-runtime"
    assert batch["config"]["model_runtime"] == benchmark_runtime

    model = store.model_for_run(scope="benchmark")
    assert isinstance(model, ProfileModel)
    assert create_calls[-1]["api_key"] == "sk-runtime-secret"
    assert create_calls[-1]["base_url"] == "https://token.example.test/v1"
    assert create_calls[-1]["model"] == "qwen-runtime"

    evolution = store.queue_evolution(EvolutionStartRequest(roles=["seer"], training_games=0, battle_games=0))
    evolution_runtime = evolution["model_runtime"]
    assert evolution_runtime["source"] == "settings_profile"
    assert evolution_runtime["model_profile_id"] == profile_id
    assert evolution["config"]["model_runtime"] == evolution_runtime

    public_payload = json.dumps({"batch": batch, "evolution": evolution, "health": health}, ensure_ascii=False)
    assert "sk-runtime-secret" not in public_payload
    assert "api_key=hidden" not in public_payload
    assert "api_key" not in public_payload
    assert "sk-runtime-secret" not in json.dumps(profile_plan, ensure_ascii=False)
    assert "api_key=hidden" not in json.dumps(profile_plan, ensure_ascii=False)

    monkeypatch.setenv("WEREWOLF_LLM_API_KEY", "env-secret")
    with pytest.raises(HTTPException) as exc_info:
        store.benchmark_service.benchmark_model_runtime(
            BenchmarkRequest(benchmark_id="model-baseline-v1", target_type="model", model_profile_id=profile_id)
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "benchmark_model_profile_invalid"
    assert "override is not allowed" in exc_info.value.detail["detail"]


def test_env_locked_model_runtime_skips_unreadable_settings_profile_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ui.backend.settings_model_profiles import SettingsModelProfileStore
    from ui.backend.settings_secret_crypto import SettingsSecretEncryptionError

    monkeypatch.setenv("WEREWOLF_LLM_API_KEY", "env-secret")
    monkeypatch.setenv("WEREWOLF_LLM_BASE_URL", "https://env.example.test/v1")
    monkeypatch.setenv("WEREWOLF_LLM_MODEL", "env-model")

    store = SettingsModelProfileStore(tmp_path)

    def fail_read_profiles() -> list[dict[str, Any]]:
        raise AssertionError("env-locked runtime should not read Settings profiles")

    def fail_read_secrets() -> dict[str, str]:
        raise SettingsSecretEncryptionError("settings secret cannot be decrypted")

    monkeypatch.setattr(store, "_read_profiles", fail_read_profiles)
    monkeypatch.setattr(store, "_read_secrets", fail_read_secrets)

    assert store.model_runtime_payload(scope="game_decision") is None
    assert store.create_llm_for_scope(scope="game_decision") is None
    with pytest.raises(ValueError, match="environment LLM config is locked"):
        store.create_llm_for_scope(scope="game_decision", profile_id="model_1")


def test_benchmark_start_probes_selected_model_profile_before_queueing(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    import ui.backend.settings_model_profiles as settings_model_profiles

    class ProfileProbeModel:
        def __init__(self, *, fail: bool = False) -> None:
            self._fail = fail

        async def ainvoke(self, messages: Any) -> Any:
            assert messages in {
                "Return exactly: ok",
                settings_model_profiles.MODEL_PROFILE_TEST_PROMPT,
            }
            if self._fail:
                raise TimeoutError("selected profile timed out with sk-bad-profile-secret")
            return type("Result", (), {"content": "ok"})()

    create_calls: list[dict[str, Any]] = []

    def fake_create_llm(**kwargs: Any) -> ProfileProbeModel:
        create_calls.append(dict(kwargs))
        return ProfileProbeModel(fail=kwargs.get("model") == "bad-benchmark-model")

    monkeypatch.delenv("UI_BACKEND_USE_FAKE_LLM", raising=False)
    for key in ("WEREWOLF_LLM_API_KEY", "WEREWOLF_LLM_BASE_URL", "WEREWOLF_LLM_MODEL"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "settings-secret-test-key")
    _fake_ui_pg_provider.db.model_profiles_enabled = True
    monkeypatch.setattr(settings_model_profiles, "create_llm", fake_create_llm)

    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=None)
    store = app.state.backend_store
    headers = {"X-Settings-Admin-Token": "token-123"}

    with TestClient(app, raise_server_exceptions=False) as client:
        good_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Good Game Model",
                "provider": "openai_compatible",
                "base_url": "https://good.example.test/v1",
                "model": "good-game-model",
                "api_key": "sk-good-profile-secret",
                "default_scopes": {"game_decision": True},
            },
        )
        bad_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Bad Benchmark Model",
                "provider": "openai_compatible",
                "base_url": "https://bad.example.test/v1",
                "model": "bad-benchmark-model",
                "api_key": "sk-bad-profile-secret",
                "default_scopes": {"benchmark": True},
            },
        )
        bad_profile_id = bad_response.json()["profile"]["profile_id"]
        start_response = client.post(
            "/api/benchmark",
            json={
                "target_type": "model",
                "battle_games": 1,
                "max_days": 1,
                "model_profile_id": bad_profile_id,
            },
        )

    assert good_response.status_code == 200
    assert bad_response.status_code == 200
    assert start_response.status_code == 503
    payload = start_response.json()
    assert payload["error"]["code"] == "runtime_not_ready"
    detail = payload["detail"]
    assert detail["scope"] == "benchmark_start"
    assert detail["model_scope"] == "benchmark"
    assert detail["model_profile_id"] == bad_profile_id
    assert detail["blockers"] == ["llm_connectivity"]
    llm_check = detail["checks"]["llm_connectivity"]
    assert llm_check["status"] == "error"
    assert llm_check["source"] == "settings_profile"
    assert llm_check["model"] == "bad-benchmark-model"
    assert llm_check["model_profile_id"] == bad_profile_id
    assert llm_check["error"]["type"] == "TimeoutError"
    assert store.evolution_batches == {}
    assert create_calls[-1]["model"] == "bad-benchmark-model"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-bad-profile-secret" not in serialized
    assert "sk-good-profile-secret" not in serialized


def test_game_start_probes_selected_model_profile_before_starting(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    import ui.backend.settings_model_profiles as settings_model_profiles

    class ProfileProbeModel(FakeModel):
        def __init__(self, *, fail: bool = False) -> None:
            self._fail = fail

        async def ainvoke(self, messages: Any) -> Any:
            if messages == "Return exactly: ok":
                if self._fail:
                    raise TimeoutError("selected game profile timed out with sk-bad-game-profile-secret")
                return type("Result", (), {"content": "ok"})()
            return await super().ainvoke(messages)

    create_calls: list[dict[str, Any]] = []

    def fake_create_llm(**kwargs: Any) -> ProfileProbeModel:
        create_calls.append(dict(kwargs))
        return ProfileProbeModel(fail=kwargs.get("model") == "bad-game-model")

    _FakeGamePersistence.instances.clear()
    monkeypatch.delenv("UI_BACKEND_USE_FAKE_LLM", raising=False)
    for key in ("WEREWOLF_LLM_API_KEY", "WEREWOLF_LLM_BASE_URL", "WEREWOLF_LLM_MODEL"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "settings-secret-test-key")
    _fake_ui_pg_provider.db.model_profiles_enabled = True
    monkeypatch.setattr(settings_model_profiles, "create_llm", fake_create_llm)

    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=None)
    store = app.state.backend_store
    store._registry = FakeVersionRegistry(tmp_path)
    headers = {"X-Settings-Admin-Token": "token-123"}

    with TestClient(app, raise_server_exceptions=False) as client:
        good_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Good Game Model",
                "provider": "openai_compatible",
                "base_url": "https://good-game.example.test/v1",
                "model": "good-game-model",
                "api_key": "sk-good-game-profile-secret",
                "default_scopes": {"game_decision": True},
            },
        )
        bad_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Bad Game Model",
                "provider": "openai_compatible",
                "base_url": "https://bad-game.example.test/v1",
                "model": "bad-game-model",
                "api_key": "sk-bad-game-profile-secret",
                "default_scopes": {"game_decision": True},
            },
        )
        bad_profile_id = bad_response.json()["profile"]["profile_id"]
        start_response = client.post(
            "/api/games",
            json={
                "seed": 2,
                "max_days": 1,
                "player_count": 12,
                "model_profile_id": bad_profile_id,
            },
        )

    assert good_response.status_code == 200
    assert bad_response.status_code == 200
    assert start_response.status_code == 503
    payload = start_response.json()
    assert payload["error"]["code"] == "runtime_not_ready"
    detail = payload["detail"]
    assert detail["scope"] == "game_start"
    assert detail["model_scope"] == "game_decision"
    assert detail["model_profile_id"] == bad_profile_id
    assert detail["blockers"] == ["llm_connectivity"]
    llm_check = detail["checks"]["llm_connectivity"]
    assert llm_check["status"] == "error"
    assert llm_check["source"] == "settings_profile"
    assert llm_check["model"] == "bad-game-model"
    assert llm_check["model_profile_id"] == bad_profile_id
    assert llm_check["error"]["type"] == "TimeoutError"
    assert store.live_sessions == {}
    assert store.games == {}
    assert _FakeGamePersistence.instances == []
    assert create_calls[-1]["model"] == "bad-game-model"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-bad-game-profile-secret" not in serialized
    assert "sk-good-game-profile-secret" not in serialized


def test_evolution_start_probes_selected_model_profile_before_queueing(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    import ui.backend.settings_model_profiles as settings_model_profiles

    class ProfileProbeModel(FakeModel):
        def __init__(self, *, fail: bool = False) -> None:
            self._fail = fail

        async def ainvoke(self, messages: Any) -> Any:
            if messages == "Return exactly: ok":
                if self._fail:
                    raise TimeoutError("selected evolution profile timed out with sk-bad-evo-profile-secret")
                return type("Result", (), {"content": "ok"})()
            return await super().ainvoke(messages)

    create_calls: list[dict[str, Any]] = []

    def fake_create_llm(**kwargs: Any) -> ProfileProbeModel:
        create_calls.append(dict(kwargs))
        return ProfileProbeModel(fail=kwargs.get("model") == "bad-evolution-model")

    monkeypatch.delenv("UI_BACKEND_USE_FAKE_LLM", raising=False)
    for key in ("WEREWOLF_LLM_API_KEY", "WEREWOLF_LLM_BASE_URL", "WEREWOLF_LLM_MODEL"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    monkeypatch.setenv("SETTINGS_SECRET_ENCRYPTION_KEY", "settings-secret-test-key")
    _fake_ui_pg_provider.db.model_profiles_enabled = True
    monkeypatch.setattr(settings_model_profiles, "create_llm", fake_create_llm)

    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=None)
    store = app.state.backend_store
    headers = {"X-Settings-Admin-Token": "token-123"}

    with TestClient(app, raise_server_exceptions=False) as client:
        good_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Good Evolution Model",
                "provider": "openai_compatible",
                "base_url": "https://good-evo.example.test/v1",
                "model": "good-evolution-model",
                "api_key": "sk-good-evo-profile-secret",
                "default_scopes": {"evolution": True},
            },
        )
        bad_response = client.post(
            "/api/settings/model-profiles",
            headers=headers,
            json={
                "name": "Bad Evolution Model",
                "provider": "openai_compatible",
                "base_url": "https://bad-evo.example.test/v1",
                "model": "bad-evolution-model",
                "api_key": "sk-bad-evo-profile-secret",
                "default_scopes": {"evolution": True},
            },
        )
        bad_profile_id = bad_response.json()["profile"]["profile_id"]
        start_response = client.post(
            "/api/evolution-runs",
            json={
                "roles": ["seer"],
                "training_games": 0,
                "battle_games": 0,
                "model_profile_id": bad_profile_id,
            },
        )

    assert good_response.status_code == 200
    assert bad_response.status_code == 200
    assert start_response.status_code == 503
    payload = start_response.json()
    assert payload["error"]["code"] == "runtime_not_ready"
    detail = payload["detail"]
    assert detail["scope"] == "evolution_start"
    assert detail["model_scope"] == "evolution"
    assert detail["model_profile_id"] == bad_profile_id
    assert detail["blockers"] == ["llm_connectivity"]
    llm_check = detail["checks"]["llm_connectivity"]
    assert llm_check["status"] == "error"
    assert llm_check["source"] == "settings_profile"
    assert llm_check["model"] == "bad-evolution-model"
    assert llm_check["model_profile_id"] == bad_profile_id
    assert llm_check["error"]["type"] == "TimeoutError"
    assert store.evolution_runs == {}
    assert store.evolution_batches == {}
    assert create_calls[-1]["model"] == "bad-evolution-model"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-bad-evo-profile-secret" not in serialized
    assert "sk-good-evo-profile-secret" not in serialized


def test_error_handlers_keep_detail_and_add_error_shape(tmp_path: Path) -> None:
    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=FakeModel())

    @app.get("/api/_test/unhandled-error")
    def unhandled_error() -> None:
        raise RuntimeError("internal diagnostic should not leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        missing_response = client.get("/api/games/missing_error_shape_game")
        validation_response = client.post("/api/games", json={"max_days": 0})
        internal_response = client.get("/api/_test/unhandled-error")

    assert missing_response.status_code == 404
    _assert_error_payload(
        missing_response.json(),
        detail="game not found",
        code="not_found",
        message="game not found",
    )

    assert validation_response.status_code == 422
    validation_payload = validation_response.json()
    assert validation_payload["detail"][0]["loc"] == ["body", "max_days"]
    assert validation_payload["error"]["code"] == "validation_error"
    assert validation_payload["error"]["message"] == "Request validation failed"
    assert validation_payload["error"]["diagnostics"] == validation_payload["detail"]

    assert internal_response.status_code == 500
    _assert_error_payload(
        internal_response.json(),
        detail="Internal Server Error",
        code="internal_error",
        message="Internal Server Error",
    )
    assert "diagnostic should not leak" not in internal_response.text


def test_game_review_route_uses_light_review_loader(tmp_path: Path) -> None:
    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=FakeModel())
    store = app.state.backend_store
    calls: list[str] = []

    def get_game_review(game_id: str) -> dict[str, Any]:
        calls.append(game_id)
        return {"game_id": game_id, "review_status": "ok", "notes": []}

    def get_game(_game_id: str) -> None:
        raise AssertionError("review route must not load full game detail")

    store.get_game_review = get_game_review
    store.get_game = get_game

    with TestClient(app) as client:
        response = client.get("/api/games/review_light_game/review")

    assert response.status_code == 200
    assert response.json() == {"game_id": "review_light_game", "review_status": "ok", "notes": []}
    assert calls == ["review_light_game"]


def test_games_create_list_read_archive_and_review_contract(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        create_response = client.post(
            "/api/games",
            json={"seed": 2, "max_days": 5, "player_count": 12},
        )

        assert create_response.status_code == 200
        created = create_response.json()
        game_id = created["game_id"]

        completed = _wait_for_game_terminal(client, game_id)
        list_response = client.get("/api/games")
        read_response = client.get(f"/api/games/{game_id}")
        history_detail_response = client.get(f"/api/games/{game_id}?view=history")
        history_shell_response = client.get(f"/api/games/{game_id}?view=history-shell")
        phase_response = client.get(
            f"/api/games/{game_id}/phase?day=1&phase=setup&log_limit=1&decision_limit=1"
        )
        flow_data_response = client.get(f"/api/games/{game_id}/flow-data")
        replay_response = client.get(f"/api/games/{game_id}/replay?cursor=0&limit=1")
        events_response = client.get(f"/api/games/{game_id}/events")
        archive_response = client.get(f"/api/games/{game_id}/archive")
        review_response = client.get(f"/api/games/{game_id}/review")

    assert game_id.startswith("ui_")
    assert created["status"] == "running"
    assert created["mode"] == "watch"
    assert created["seed"] == 2
    assert created["max_days"] == 5
    assert created["player_count"] == 12
    assert len(created["players"]) == 12
    assert created["waiting_for"] == "none"
    assert created["pending_human_action"] is None

    assert completed["status"] == "completed"
    assert completed["mode"] == "watch"
    assert len(completed["players"]) == 12
    assert len(completed["logs"]) > 0
    assert len(completed["events"]) == len(completed["logs"])
    assert len(completed["decisions"]) > 0
    assert completed["waiting_for"] == "none"
    assert completed["pending_human_action"] is None

    assert list_response.status_code == 200
    listed_games = list_response.json()["games"]
    listed = next(item for item in listed_games if item["game_id"] == game_id)
    assert listed["event_count"] == len(completed["events"])
    assert listed["player_count"] == 12

    assert read_response.status_code == 200
    read_back = read_response.json()
    assert read_back["game_id"] == game_id
    assert len(read_back["players"]) == 12
    assert len(read_back["events"]) == len(read_back["logs"])
    assert len(read_back["decisions"]) == len(completed["decisions"])

    assert history_detail_response.status_code == 200
    history_detail = history_detail_response.json()
    assert history_detail["game_id"] == game_id
    assert history_detail["detail_view"] == "history"
    assert "events" not in history_detail
    assert len(history_detail["logs"]) == len(completed["logs"])
    assert history_detail["event_count"] == len(completed["logs"])
    assert history_detail["decision_count"] == len(completed["decisions"])

    assert history_shell_response.status_code == 200
    history_shell = history_shell_response.json()
    assert history_shell["game_id"] == game_id
    assert history_shell["detail_view"] == "history-shell"
    assert "logs" not in history_shell
    assert "events" not in history_shell
    assert "decisions" not in history_shell

    assert phase_response.status_code == 200
    phase_detail = phase_response.json()
    assert phase_detail["game_id"] == game_id
    assert phase_detail["detail_view"] == "phase-detail"
    assert "pagination" in phase_detail
    assert "logs" in phase_detail["pagination"]
    assert "decisions" in phase_detail["pagination"]

    assert flow_data_response.status_code == 200
    flow_data = flow_data_response.json()
    assert flow_data["game_id"] == game_id
    assert flow_data["detail_view"] == "flow-data"
    assert "logs" not in flow_data
    assert "events" not in flow_data

    assert replay_response.status_code == 200
    replay = replay_response.json()
    assert replay["game_id"] == game_id
    assert replay["detail_view"] == "replay"
    assert replay["cursor"] == 0
    assert replay["limit"] == 1
    assert "next_cursor" in replay
    assert "has_more" in replay
    assert len(replay["events"]) <= 1

    assert events_response.status_code == 200
    assert "event: log" in events_response.text
    assert "event: done" in events_response.text

    assert archive_response.status_code == 200
    archive = archive_response.json()
    assert archive["kind"] == "game_trace_archive"
    assert archive["game_id"] == game_id
    assert archive["title"]
    assert archive["summary"]
    assert isinstance(archive["highlights"], list)
    assert archive["decision_count"] == len(completed["decisions"])
    assert archive["events"] == public_events_only(completed["events"])

    assert review_response.status_code == 200
    review = review_response.json()
    assert review["game_id"] == game_id


def test_human_player_id_starts_live_play_contract(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        response = client.post(
            "/api/games",
            json={"seed": 2, "max_days": 5, "player_count": 12, "human_player_id": 1},
        )
        assert response.status_code == 200
        created = response.json()
        stop_response = client.post(f"/api/games/{created['game_id']}/stop")

    assert created["mode"] == "play"
    assert created["status"] == "running"
    assert created["human_player_id"] == 1
    assert created["players"][0]["is_human"] is True
    assert created["waiting_for"] in {"none", "speech", "vote", "action"}
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "cancelled"


def test_vote_tally_scopes_to_current_vote_round() -> None:
    decisions = [
        {"day": 1, "phase": "exile_vote", "action_type": "exile_vote", "actor_id": 1, "target_id": 4},
        {"day": 1, "phase": "exile_vote", "action_type": "exile_vote", "actor_id": 2, "target_id": 4},
        {"day": 2, "phase": "exile_vote", "action_type": "exile_vote", "actor_id": 3, "target_id": 5},
        {"day": 2, "phase": "exile_vote", "action_type": "exile_vote", "actor_id": 4, "target_id": 5},
        {"day": 2, "phase": "exile_vote", "action_type": "pk_vote", "actor_id": 6, "target_id": 3},
    ]

    current_exile = _vote_tally(
        decisions,
        current_day=2,
        current_phase="exile_vote",
        pending_action={"action_type": "exile_vote"},
    )
    current_pk = _vote_tally(
        decisions,
        current_day=2,
        current_phase="exile_vote",
        pending_action={"action_type": "pk_vote"},
    )

    assert [(row["target_id"], row["count"], row["voter_ids"]) for row in current_exile] == [(5, 2, [3, 4])]
    assert [(row["target_id"], row["count"], row["voter_ids"]) for row in current_pk] == [(3, 1, [6])]

    player_view = _player_view_snapshot(
        {
            "game_id": "player_vote_scope",
            "mode": "play",
            "status": "running",
            "human_player_id": 1,
            "day": 2,
            "phase": "exile_vote",
            "players": [
                {"id": player_id, "role": "villager", "role_hint": "村民", "team": "villagers", "alive": True}
                for player_id in range(1, 7)
            ],
            "events": [],
            "decisions": decisions,
            "pending_human_action": {
                "player_id": 1,
                "action_type": "pk_vote",
                "phase": "exile_vote",
                "day": 2,
                "candidates": [3, 5],
            },
        }
    )

    assert [(row["target_id"], row["count"], row["voter_ids"]) for row in player_view["vote_tally"]] == [
        (3, 1, [6])
    ]


def test_archive_rebuild_helpers_accept_target_id_only_events() -> None:
    events = [
        {"event_type": "death", "target_id": "2", "message": "2 died"},
        {"event_type": "death", "payload": {"target_id": "3"}, "message": "3 died"},
        {"event_type": "sheriff_election_end", "target_id": "1", "payload": {}},
        {"event_type": "sheriff_badge_transfer", "target_id": "4", "payload": {}},
    ]

    assert _dead_players(events) == {2, 3}
    assert _sheriff_from_events(events) == 4


def test_player_view_redacts_abnormal_terminal_play_snapshots() -> None:
    for status in ("cancelled", "interrupted", "failed"):
        snapshot = _player_view_snapshot(
            {
                "game_id": f"player_view_{status}",
                "mode": "play",
                "status": status,
                "human_player_id": 1,
                "day": 1,
                "phase": "night",
                "players": [
                    {
                        "id": 1,
                        "role": "seer",
                        "role_hint": "预言家",
                        "team": "villagers",
                        "role_state": {"checks": {"2": "werewolves"}},
                    },
                    {
                        "id": 2,
                        "role": "werewolf",
                        "role_hint": "狼人",
                        "team": "werewolves",
                        "role_state": {"wolf_chat": ["kill 1"]},
                    },
                ],
                "events": [
                    {
                        "event_type": "game_init",
                        "visibility": "public",
                        "payload": {"roles": {"1": "seer", "2": "werewolf"}, "seat_count": 12},
                    },
                    {
                        "event_type": "seer_result",
                        "actor_id": 2,
                        "visibility": "private",
                        "payload": {"target": 1, "role": "seer"},
                    },
                    {
                        "event_type": "god_debug",
                        "visibility": "god",
                        "payload": {"roles": {"1": "seer", "2": "werewolf"}},
                    },
                    {
                        "event_type": "hunter_shot",
                        "actor_id": 2,
                        "target_id": 1,
                        "visibility": "public",
                        "payload": {"target": 1},
                    },
                ],
                "decisions": [],
            }
        )

        assert snapshot["players"][0]["role"] == "seer"
        assert snapshot["players"][0]["role_state"] == {"checks": {"2": "werewolves"}}
        assert snapshot["players"][1]["role"] == "unknown"
        assert snapshot["players"][1]["role_state"] == {}

        event_types = [event["event_type"] for event in snapshot["events"]]
        assert event_types == ["game_init", "hunter_shot"]
        assert snapshot["events"][0]["payload"] == {"seat_count": 12}
        assert snapshot["events"][1]["target_id"] == 1


def test_player_view_hides_other_white_wolf_pass_decisions() -> None:
    base_snapshot = {
        "game_id": "white_wolf_pass_player_view",
        "mode": "play",
        "status": "running",
        "day": 1,
        "phase": "day_speech",
        "players": [
            {"id": 1, "role": "villager", "role_hint": "村民", "team": "villagers", "alive": True},
            {"id": 2, "role": "white_wolf_king", "role_hint": "白狼王", "team": "werewolves", "alive": True},
        ],
        "events": [],
        "decisions": [
            {
                "decision_id": "d_pass",
                "player_id": 2,
                "actor_id": 2,
                "role": "white_wolf_king",
                "day": 1,
                "phase": "day_speech",
                "action_type": "white_wolf_explode",
                "choice": "pass",
                "target_id": None,
            }
        ],
    }

    villager_view = _player_view_snapshot({**base_snapshot, "human_player_id": 1})
    white_wolf_view = _player_view_snapshot({**base_snapshot, "human_player_id": 2})

    assert villager_view["decisions"] == []
    assert [decision["action"] for decision in white_wolf_view["decisions"]] == ["white_wolf_explode"]


def test_role_versions_flow_to_app_skill_dir(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {
                "main.md": (
                    "---\n"
                    "name: seer_test_skill\n"
                    "role: seer\n"
                    "applicable_actions:\n"
                    "  - seer_check\n"
                    "status: active\n"
                    "evolution:\n"
                    "  enabled: true\n"
                    "  allowed_actions:\n"
                    "    - append_rule\n"
                    "---\n"
                    "## Runtime\n"
                    "prefer checking suspicious players\n"
                )
            },
            version_id="seer_test",
        )
        response = client.post(
            "/api/games",
            json={
                "seed": 2,
                "max_days": 5,
                "enable_sheriff": False,
                "player_count": 12,
                "role_versions": {"seer": "seer_test"},
            },
        )
        payload = response.json()
        completed = _wait_for_game_terminal(client, payload["game_id"])

    assert response.status_code == 200
    skill_dir = Path(payload["config"]["skill_dir"])
    assert skill_dir.exists()
    assert (skill_dir / "seer" / "main.md").read_text(encoding="utf-8").startswith("---\nname: seer_test_skill")
    assert payload["config"]["enable_sheriff"] is False
    assert payload["config"]["role_versions"] == {"seer": "seer_test"}
    assert payload["role_skill_dirs"] == {"seer": "seer_test"}
    assert completed["status"] == "completed"
    assert completed["config"]["enable_sheriff"] is False
    assert completed["config"]["role_versions"] == {"seer": "seer_test"}


def test_normal_game_role_versions_reject_shadow_and_canary(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        baseline = _publish_seer_version(store.registry, "seer_base_v1", baseline=True, body="baseline")
        shadow = _publish_seer_version(store.registry, "seer_shadow_v1", release_stage="shadow", body="shadow")
        canary = _publish_seer_version(store.registry, "seer_canary_v1", release_stage="canary", body="canary")

        baseline_dir = store.skill_dir_for_request(GameStartRequest(role_versions={"seer": baseline}))
        with pytest.raises(HTTPException) as shadow_error:
            store.skill_dir_for_request(GameStartRequest(role_versions={"seer": shadow}))
        with pytest.raises(HTTPException) as canary_error:
            store.skill_dir_for_request(GameStartRequest(role_versions={"seer": canary}))

    assert baseline_dir is not None
    assert (Path(baseline_dir) / "seer" / "vote.md").exists()
    _assert_domain_exception(
        shadow_error.value,
        code="role_version_release_stage_not_allowed",
        release_stage="shadow",
        kind="role_version_release_stage_not_allowed",
    )
    _assert_domain_exception(
        canary_error.value,
        code="role_version_release_stage_not_allowed",
        release_stage="canary",
        kind="role_version_release_stage_not_allowed",
    )


def test_normal_game_rejects_experimental_version_even_when_id_matches_fallback(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        fallback_id = "seer_baseline"
        _publish_seer_version(store.registry, fallback_id, release_stage="shadow", body="shadow fallback collision")

        with pytest.raises(HTTPException) as exc_info:
            store.skill_dir_for_request(GameStartRequest(role_versions={"seer": fallback_id}))

    _assert_domain_exception(
        exc_info.value,
        code="role_version_release_stage_not_allowed",
        release_stage="shadow",
        kind="role_version_release_stage_not_allowed",
    )


@pytest.mark.parametrize("release_stage", ["shadow", "canary"])
def test_start_game_api_rejects_experimental_role_versions(tmp_path: Path, release_stage: str) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        version_id = _publish_seer_version(
            store.registry,
            f"seer_{release_stage}_v1",
            release_stage=release_stage,
            body=release_stage,
        )
        response = client.post(
            "/api/games",
            json={
                "max_days": 1,
                "player_count": 12,
                "role_versions": {"seer": version_id},
            },
        )

    _assert_domain_response(
        response,
        code="role_version_release_stage_not_allowed",
        release_stage=release_stage,
        kind="role_version_release_stage_not_allowed",
    )


def test_role_versions_fallback_contract(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        versions_response = client.get("/api/roles/seer/versions")
        version_response = client.get("/api/roles/seer/versions/seer_baseline")

    assert versions_response.status_code == 200
    payload = versions_response.json()
    assert payload["role"] == "seer"
    assert payload["versions"][0]["version_id"] == "seer_baseline"
    assert payload["versions"][0]["role"] == "seer"
    assert payload["versions"][0]["source"] == "app-fallback"
    assert payload["versions"][0]["is_baseline"] is True
    assert payload["versions"][0]["status"] == "missing_registry"
    assert payload["versions"][0]["metrics"] == {"score": 0.0, "win_rate": 0.0, "games_played": 0}

    assert version_response.status_code == 200
    version = version_response.json()
    assert version["kind"] == "knowledge_package"
    assert version["role"] == "seer"
    assert version["version_id"] == "seer_baseline"
    assert version["files"] == []
    assert version["skills"] == []
    assert version["patterns"] == []
    assert version["metrics"] == {"score": 0.0, "win_rate": 0.0, "games_played": 0}
    assert version["provenance"]["source"] == "app-fallback"
    assert version["status"] == "missing_registry"


def test_role_version_detail_includes_registry_summary_metadata(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        version_id = store.registry.publish_skills(
            "seer",
            _seer_skill("metadata detail"),
            version_id="seer_metadata_v1",
            source="evolution",
            run_id="evolve_metadata",
            proposal_ids=["p1"],
            release_stage="canary",
            provenance={
                "manual_action": "promote",
                "trust_bundle_id": "trust_bundle_metadata",
                "gate_report_id": "gate_metadata",
                "attribution_report_id": "attribution_metadata",
                "source_run_id": "source_run_metadata",
                "bundle_hash": "bundle_hash_metadata",
            },
        )
        summary = store.registry._versions["seer"][version_id]["summary"]
        summary.created_at = "2026-06-09T12:00:00+08:00"
        summary.metrics = {"score": 0.72, "win_rate": 0.64, "games_played": 11}

        versions_response = client.get("/api/roles/seer/versions")
        detail_response = client.get(f"/api/roles/seer/versions/{version_id}")

    assert versions_response.status_code == 200
    assert detail_response.status_code == 200

    listed = next(item for item in versions_response.json()["versions"] if item["version_id"] == version_id)
    detail = detail_response.json()
    for key in ("source", "created_at", "is_baseline", "status", "release_stage", "metrics", "provenance"):
        assert detail[key] == listed[key]
    assert detail["trust_bundle_id"] == "trust_bundle_metadata"
    assert detail["gate_report_id"] == "gate_metadata"
    assert detail["attribution_report_id"] == "attribution_metadata"
    assert detail["source_run_id"] == "source_run_metadata"
    assert detail["bundle_hash"] == "bundle_hash_metadata"
    assert detail["files"][0]["path"] == "vote.md"


def test_fallback_role_version_selection_does_not_break_game_start(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        response = client.post(
            "/api/games",
            json={
                "seed": 2,
                "max_days": 5,
                "player_count": 12,
                "role_versions": {"seer": "seer_baseline"},
            },
        )
        payload = response.json()
        completed = _wait_for_game_terminal(client, payload["game_id"])

    assert response.status_code == 200
    assert payload["config"]["skill_dir"] is None
    assert payload["config"]["role_versions"] == {"seer": "seer_baseline"}
    assert completed["status"] == "completed"
    assert completed["config"]["skill_dir"] is None


def test_roles_include_builtin_roles_when_registry_has_partial_versions(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {
                "main.md": (
                    "---\n"
                    "name: seer_test\n"
                    "role: seer\n"
                    "applicable_actions:\n"
                    "  - seer_check\n"
                    "status: active\n"
                    "evolution:\n"
                    "  enabled: true\n"
                    "  allowed_actions:\n"
                    "    - append_rule\n"
                    "---\n"
                    "seer notes\n"
                )
            },
            version_id="seer_only",
        )
        response = client.get("/api/roles")

    assert response.status_code == 200
    roles = response.json()["roles"]
    assert roles[:7] == list(ui_backend_app.ROLE_ORDER)
    assert "seer" in roles
    assert "villager" in roles
    assert "werewolf" in roles
    assert "guard" in roles


def test_evolution_and_benchmark_create_and_list_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def fake_run_evolution(
        *,
        role: str,
        training_games: int,
        battle_games: int,
        run_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        assert training_games == 0
        assert battle_games == 0
        assert kwargs["max_days"] == 1
        assert kwargs["auto_promote"] is True
        assert "role_concurrency" not in kwargs
        assert "game_concurrency" not in kwargs
        assert "llm_concurrency" not in kwargs
        assert "llm_rpm" not in kwargs
        return {
            "run_id": run_id,
            "role": role,
            "status": "reviewing",
            "training_games": [],
            "battle_games": [],
            "battle_result": {"completed": 0},
            "proposals": [],
            "diff": [],
            "errors": [],
        }

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        # One batch per requested role, grouped under the parent batch id.
        assert batch_config["comparison_group_id"].startswith("bench_")
        assert batch_config["game_count"] == 0
        assert batch_config["max_days"] == 1
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": 0,
            "completed": 0,
            "errored": 0,
            "games": [
                {
                    "game_id": "bench_heavy_game",
                    "events": [{"event_type": "game_init", "message": "heavy"}],
                    "decisions": [{"decision_id": "d1"}],
                }
            ],
            "score_summary": {"game_count": 0},
            "fairness": {"is_fair": False, "reason": "No games in batch"},
            "rankable": False,
            "rankable_reason": "No games in batch",
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:00:00+08:00",
        }

    monkeypatch.setattr(ui_backend_store, "run_evolution", fake_run_evolution)
    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        evolution_response = client.post(
            "/api/evolution-runs",
            json={
                "roles": ["seer"],
                "training_games": 0,
                "battle_games": 0,
                "max_days": 1,
                "auto_promote": True,
                "role_concurrency": 2,
                "game_concurrency": 4,
                "llm_concurrency": 6,
                "llm_rpm": 120,
            },
        )
        benchmark_response = client.post(
            "/api/benchmark",
            json={"roles": ["seer"], "battle_games": 0, "max_days": 1},
        )
        list_response = client.get("/api/evolution-runs")

    assert evolution_response.status_code == 200
    evolution = evolution_response.json()
    assert evolution["run_id"].startswith("evolve_seer_")
    assert evolution["role"] == "seer"
    assert evolution["status"] == "running"
    assert evolution["training_games"] == []
    assert evolution["battle_games"] == []

    assert benchmark_response.status_code == 200
    benchmark = benchmark_response.json()
    assert benchmark["batch_id"].startswith("bench_")
    assert benchmark["roles"] == ["seer"]
    assert benchmark["status"] == "running"
    assert benchmark["current_stage"] == "queued"
    assert benchmark["progress"] == {
        "stage": "queued",
        "percent": 0.0,
        "completed_roles": 0,
        "role_count": 1,
        "total_roles": 1,
        "updated_at": benchmark["last_heartbeat_at"],
    }
    assert benchmark["diagnostics"] == []
    assert benchmark["last_heartbeat_at"]
    assert benchmark["result"] is None

    assert list_response.status_code == 200
    listed = list_response.json()
    listed_evolution = next(item for item in listed["runs"] if item["run_id"] == evolution["run_id"])
    listed_benchmark = next(item for item in listed["batches"] if item["batch_id"] == benchmark["batch_id"])
    assert listed_evolution["status"] == "reviewing"
    assert listed_evolution["config"] == {
        "roles": ["seer"],
        "training_games": 0,
        "battle_games": 0,
        "max_days": 1,
        "auto_promote": True,
        "convergence_rounds": 3,
        "min_improvement_ratio": 0.01,
        "regression_threshold": 0.05,
    }
    assert listed_benchmark["status"] == "completed"
    assert listed_benchmark["current_stage"] == "completed"
    assert listed_benchmark["progress"]["stage"] == "completed"
    assert listed_benchmark["progress"]["percent"] == 1.0
    assert listed_benchmark["progress"]["completed_roles"] == 1
    assert listed_benchmark["progress"]["role_count"] == 1
    assert listed_benchmark["diagnostics"] == []
    assert listed_benchmark["result"]["completed"] == 0
    assert "games" not in listed_benchmark["result"]


def test_benchmark_start_uses_pg_task_queue_when_enabled(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    async def fail_run_evaluation(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("benchmark should not run through FastAPI BackgroundTasks when PG queue is enabled")

    monkeypatch.setenv("WOLF_USE_PG_TASK_QUEUE", "true")
    monkeypatch.setattr(ui_backend_store, "run_evaluation", fail_run_evaluation)
    _seed_fresh_task_worker(_fake_ui_pg_provider.db)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        calls: list[tuple[str, dict[str, Any]]] = []

        def fake_queue_benchmark_task(batch: dict[str, Any], request: Any) -> dict[str, Any]:
            calls.append((batch["batch_id"], request.model_dump(mode="json", exclude_none=True)))
            batch["task_id"] = batch["batch_id"]
            batch["task_queue_status"] = "queued"
            return {"task_id": batch["batch_id"], "status": "queued"}

        store.benchmark_service.queue_benchmark_task = fake_queue_benchmark_task  # type: ignore[method-assign]
        response = client.post(
            "/api/benchmark",
            json={"roles": ["seer"], "battle_games": 0, "max_days": 1},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch_id"].startswith("bench_")
    assert payload["task_id"] == payload["batch_id"]
    assert payload["task_queue_status"] == "queued"
    assert calls == [
        (
            payload["batch_id"],
            {
                "target_type": "role_version",
                "roles": ["seer"],
                "battle_games": 0,
                "max_days": 1,
                "target_versions": {},
            },
        )
    ]


def test_benchmark_start_requires_fresh_worker_when_pg_task_queue_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WOLF_USE_PG_TASK_QUEUE", "true")

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store

        def fail_queue_benchmark(_request: Any) -> dict[str, Any]:
            raise AssertionError("benchmark should be blocked before batch creation when worker is missing")

        store.benchmark_service.queue_benchmark = fail_queue_benchmark  # type: ignore[method-assign]
        response = client.post(
            "/api/benchmark",
            json={"roles": ["seer"], "battle_games": 0, "max_days": 1},
        )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["code"] == "runtime_not_ready"
    assert payload["error"]["message"] == "任务 worker 不可用，不能启动长任务。"
    assert payload["detail"]["scope"] == "benchmark_start"
    assert payload["detail"]["blockers"] == ["task_worker"]
    assert payload["detail"]["checks"]["task_worker"]["status"] == "error"


def test_evolution_start_uses_pg_task_queue_when_enabled(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    async def fail_run_evolution(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("evolution should not run through FastAPI BackgroundTasks when PG queue is enabled")

    monkeypatch.setenv("WOLF_USE_PG_TASK_QUEUE", "true")
    monkeypatch.setattr(ui_backend_store, "run_evolution", fail_run_evolution)
    _seed_fresh_task_worker(_fake_ui_pg_provider.db)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        calls: list[tuple[str, dict[str, Any]]] = []

        def fake_queue_evolution_task(queued: dict[str, Any], request: Any) -> dict[str, Any]:
            entity_id = queued.get("batch_id") or queued["run_id"]
            calls.append((entity_id, request.model_dump(mode="json", exclude_none=True)))
            queued["task_id"] = entity_id
            queued["task_queue_status"] = "queued"
            return {"task_id": entity_id, "status": "queued"}

        store.queue_evolution_task = fake_queue_evolution_task  # type: ignore[method-assign]
        response = client.post(
            "/api/evolution-runs",
            json={
                "roles": ["seer"],
                "training_games": 0,
                "battle_games": 0,
                "max_days": 1,
                "auto_promote": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"].startswith("evolve_seer_")
    assert payload["task_id"] == payload["run_id"]
    assert payload["task_queue_status"] == "queued"
    assert calls == [
        (
            payload["run_id"],
            {
                "roles": ["seer"],
                "training_games": 0,
                "battle_games": 0,
                "max_days": 1,
                "auto_promote": True,
                "convergence_rounds": 3,
                "min_improvement_ratio": 0.01,
                "regression_threshold": 0.05,
            },
        )
    ]


def test_evolution_reads_overlay_pg_task_queue_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    active_run_id = "evolve_seer_pg_active"
    done_run_id = "evolve_witch_pg_done"

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_runs[active_run_id] = {
            "kind": "role_evolution_run",
            "run_id": active_run_id,
            "role": "seer",
            "status": "queued",
            "task_id": active_run_id,
            "task_queue_status": "queued",
            "current_stage": "queued",
            "progress": {"stage": "queued", "percent": 0.0},
            "overall_progress": {"stage": "queued", "percent": 0.0},
            "diagnostics": [],
            "training_game_count": 2,
            "battle_game_count": 1,
        }
        store.evolution_runs[done_run_id] = {
            "kind": "role_evolution_run",
            "run_id": done_run_id,
            "role": "witch",
            "status": "reviewing",
            "task_id": done_run_id,
            "task_queue_status": "succeeded",
            "current_stage": "reviewing",
            "progress": {"stage": "reviewing", "percent": 1.0},
            "overall_progress": {"stage": "reviewing", "percent": 1.0},
            "diagnostics": [],
        }
        task_rows = {
            active_run_id: {
                "task_id": active_run_id,
                "kind": "evolution_run",
                "status": "running",
                "progress": {"stage": "training", "percent": 0.5, "completed_games": 1},
                "updated_at": "2026-01-01T00:02:00+08:00",
                "started_at": "2026-01-01T00:01:00+08:00",
                "finished_at": None,
                "cancel_requested": False,
                "result": None,
                "error": None,
            },
            done_run_id: {
                "task_id": done_run_id,
                "kind": "evolution_run",
                "status": "succeeded",
                "progress": {"stage": "completed", "percent": 1.0},
                "updated_at": "2026-01-01T00:04:00+08:00",
                "started_at": "2026-01-01T00:03:00+08:00",
                "finished_at": "2026-01-01T00:04:00+08:00",
                "cancel_requested": False,
                "result": {"status": "reviewing", "artifact_ids": ["artifact-result"]},
                "error": None,
            },
        }

        monkeypatch.setattr(store.task_service, "get_task_queue_row", lambda task_id: task_rows.get(str(task_id)))
        monkeypatch.setattr(store.task_service, "get_task_queue_rows", lambda task_ids: {tid: task_rows[tid] for tid in task_ids if tid in task_rows})

        active_detail = client.get(f"/api/evolution-runs/{active_run_id}").json()
        done_detail = client.get(f"/api/evolution-runs/{done_run_id}").json()
        running_list = client.get("/api/evolution-runs?status=running").json()
        reviewing_list = client.get("/api/evolution-runs?status=reviewing").json()

    assert active_detail["status"] == "running"
    assert active_detail["task_queue_status"] == "running"
    assert active_detail["current_stage"] == "training"
    assert active_detail["progress"]["percent"] == 0.5
    assert active_detail["progress"]["task_status"] == "running"
    assert active_detail["last_heartbeat_at"] == "2026-01-01T00:02:00+08:00"
    assert [run["run_id"] for run in running_list["runs"]] == [active_run_id]

    assert done_detail["status"] == "reviewing"
    assert done_detail["task_queue_status"] == "succeeded"
    assert done_detail["task_artifact_ids"] == ["artifact-result"]
    assert [run["run_id"] for run in reviewing_list["runs"]] == [done_run_id]


def test_langfuse_task_routes_enqueue_pg_tasks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        calls: list[dict[str, Any]] = []

        def fake_enqueue_task(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {
                "task_id": kwargs["task_id"],
                "kind": kwargs["kind"],
                "status": "queued",
            }

        monkeypatch.setattr(store.task_service, "enqueue_task", fake_enqueue_task)
        verification = client.post(
            "/api/langfuse/verification-tasks",
            json={
                "task_id": "verify-langfuse",
                "payload_files": ["runs/benchmark-report.json"],
                "verify_remote": False,
                "env": {"LANGFUSE_TRACING_ENABLED": "false"},
            },
        )
        annotation = client.post(
            "/api/langfuse/annotation-export-tasks",
            json={
                "task_id": "annotation-langfuse",
                "input_paths": ["runs/benchmark-report.json"],
                "max_items": 10,
            },
        )
        manifest = client.post(
            "/api/langfuse/link-manifest-tasks",
            json={
                "task_id": "manifest-langfuse",
                "input_paths": ["runs/annotation-queue.json"],
                "ui_base_url": "http://localhost:5173",
            },
        )

    assert verification.status_code == 200
    assert annotation.status_code == 200
    assert manifest.status_code == 200
    assert [call["kind"] for call in calls] == [
        "langfuse_verification",
        "langfuse_annotation_export",
        "langfuse_link_manifest",
    ]
    assert calls[0]["payload"]["payload_files"] == ["runs/benchmark-report.json"]
    assert calls[1]["payload"]["max_items"] == 10
    assert calls[2]["payload"]["ui_base_url"] == "http://localhost:5173"
    assert verification.json()["task_id"] == "verify-langfuse"
    assert verification.json()["task_queue_status"] == "queued"


def test_evolution_start_preserves_requested_counts_when_enabling_auto_promote(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_evolution(
        *,
        role: str,
        training_games: int,
        battle_games: int,
        run_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        captured.update(
            {
                "role": role,
                "training_games": training_games,
                "battle_games": battle_games,
                "auto_promote": kwargs["auto_promote"],
            }
        )
        return {
            "run_id": run_id,
            "role": role,
            "status": "rejected",
            "training_games": [],
            "battle_games": [],
            "battle_result": {"completed": 0},
            "proposals": [],
            "diff": [],
            "errors": [],
        }

    monkeypatch.setattr(ui_backend_store, "run_evolution", fake_run_evolution)

    with _test_client(tmp_path) as client:
        response = client.post(
            "/api/evolution-runs",
            json={
                "roles": ["seer"],
                "training_games": 20,
                "battle_games": 10,
                "max_days": 5,
                "auto_promote": False,
            },
        )
        run_id = response.json()["run_id"]
        detail_response = client.get(f"/api/evolution-runs/{run_id}")

    assert response.status_code == 200
    assert captured == {
        "role": "seer",
        "training_games": 20,
        "battle_games": 10,
        "auto_promote": True,
    }
    assert detail_response.status_code == 200
    assert detail_response.json()["config"] == {
        "roles": ["seer"],
        "training_games": 20,
        "battle_games": 10,
        "max_days": 5,
        "auto_promote": True,
        "convergence_rounds": 3,
        "min_improvement_ratio": 0.01,
        "regression_threshold": 0.05,
    }


def test_evolution_start_request_defaults_to_twenty_games_and_days() -> None:
    request = EvolutionStartRequest()

    assert request.training_games == 20
    assert request.battle_games == 20
    assert request.max_days == 20


def test_benchmark_evaluation_resolves_default_judge_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path), model=FakeModel())
    game_model = object()
    judge_model = object()
    resolved_scopes: list[str] = []
    captured: dict[str, Any] = {}

    def model_for_run(*, scope: str = "game_decision", model_profile_id: str | None = None) -> Any:
        assert model_profile_id is None
        resolved_scopes.append(scope)
        return judge_model

    async def fake_run_evaluation(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"status": "completed"}

    monkeypatch.setattr(store, "model_for_run", model_for_run)
    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    result = asyncio.run(
        store.evaluate_benchmark_batch(
            batch_config={"batch_id": "judge-model-scope"},
            model=game_model,
            paths=store.paths,
        )
    )

    assert result["status"] == "completed"
    assert resolved_scopes == ["judge"]
    assert captured["model"] is game_model
    assert captured["decision_judge_model"] is judge_model


def test_fake_model_game_review_evolution_benchmark_smoke(tmp_path: Path, monkeypatch) -> None:
    smoke_game: dict[str, Any] = {}
    evolution_call: dict[str, Any] = {}
    benchmark_call: dict[str, Any] = {}

    async def fake_run_evolution(
        *,
        role: str,
        training_games: int,
        battle_games: int,
        run_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        evolution_call.update(
            {
                "role": role,
                "training_games": training_games,
                "battle_games": battle_games,
                "run_id": run_id,
                "max_days": kwargs["max_days"],
                "has_model": kwargs["model"] is not None,
                "paths_root": kwargs["paths"].root,
            }
        )
        return {
            "run_id": run_id,
            "role": role,
            "status": "reviewing",
            "candidate_hash": "candidate_smoke_seer",
            "training_games": [
                {
                    "game_id": smoke_game["game_id"],
                    "status": smoke_game["status"],
                    "seed": smoke_game["seed"],
                    "winner": smoke_game.get("winner"),
                    "phase": "training",
                    "events": smoke_game["events"][:2],
                    "decisions": smoke_game["decisions"][:1],
                }
            ],
            "battle_games": [],
            "battle_result": {"completed": 0},
            "proposals": [
                {
                    "proposal_id": "smoke_p1",
                    "target_file": "seer.md",
                    "content": "Prefer checks that clarify vote conflicts.",
                }
            ],
            "diff": [{"target_file": "seer.md", "action": "append_rule"}],
            "errors": [],
            "warnings": [],
        }

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        benchmark_call.update(
            {
                "batch_config": dict(batch_config),
                "has_model": kwargs["model"] is not None,
                "paths_root": kwargs["paths"].root,
            }
        )
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [
                {
                    "game_id": smoke_game["game_id"],
                    "status": smoke_game["status"],
                    "events": smoke_game["events"][:1],
                    "decisions": smoke_game["decisions"][:1],
                }
            ],
            "score_summary": {"game_count": batch_config["game_count"]},
            "fairness": {"is_fair": True},
            "rankable": batch_config["game_count"] > 0,
            "rankable_reason": "smoke fake evaluation",
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:00:00+08:00",
        }

    monkeypatch.setattr(ui_backend_store, "run_evolution", fake_run_evolution)
    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        game_response = client.post(
            "/api/games",
            json={"seed": 2, "max_days": 5, "player_count": 12},
        )
        assert game_response.status_code == 200, game_response.text
        game_id = game_response.json()["game_id"]
        smoke_game.update(_wait_for_game_terminal(client, game_id))

        archive_response = client.get(f"/api/games/{game_id}/archive")
        review_response = client.get(f"/api/games/{game_id}/review")

        evolution_response = client.post(
            "/api/evolution-runs",
            json={"roles": ["seer"], "training_games": 0, "battle_games": 0, "max_days": 1},
        )
        assert evolution_response.status_code == 200, evolution_response.text
        evolution_run_id = evolution_response.json()["run_id"]
        evolution_detail_response = client.get(f"/api/evolution-runs/{evolution_run_id}")
        evolution_games_response = client.get(f"/api/evolution-runs/{evolution_run_id}/games?phase=training")

        benchmark_response = client.post(
            "/api/benchmark",
            json={"roles": ["seer"], "battle_games": 0, "max_days": 1},
        )
        assert benchmark_response.status_code == 200, benchmark_response.text
        benchmark_id = benchmark_response.json()["batch_id"]
        benchmark_detail_response = client.get(f"/api/evolution-runs/{benchmark_id}")
        history_response = client.get("/api/evolution-runs?limit=20&offset=0")

    assert smoke_game["status"] == "completed"
    assert smoke_game["game_id"] == game_id
    assert len(smoke_game["events"]) > 0
    assert len(smoke_game["decisions"]) > 0

    assert archive_response.status_code == 200
    archive = archive_response.json()
    assert archive["kind"] == "game_trace_archive"
    assert archive["game_id"] == game_id

    assert review_response.status_code == 200
    review = review_response.json()
    assert review["game_id"] == game_id

    assert evolution_call == {
        "role": "seer",
        "training_games": 0,
        "battle_games": 0,
        "run_id": evolution_run_id,
        "max_days": 1,
        "has_model": True,
        "paths_root": tmp_path,
    }
    assert evolution_detail_response.status_code == 200
    evolution_detail = evolution_detail_response.json()
    assert evolution_detail["status"] == "reviewing"
    assert evolution_detail["candidate_hash"] == "candidate_smoke_seer"
    assert evolution_detail["training_games"][0]["game_id"] == game_id

    assert evolution_games_response.status_code == 200
    evolution_games = evolution_games_response.json()["games"]
    assert evolution_games[0]["game_id"] == game_id
    assert "events" not in evolution_games[0]

    assert benchmark_call["batch_config"]["comparison_group_id"] == benchmark_id
    assert benchmark_call["batch_config"]["game_count"] == 0
    assert benchmark_call["batch_config"]["max_days"] == 1
    assert benchmark_call["has_model"] is True
    assert benchmark_call["paths_root"] == tmp_path

    assert benchmark_detail_response.status_code == 200
    benchmark_detail = benchmark_detail_response.json()
    assert benchmark_detail["status"] == "completed"
    assert benchmark_detail["current_stage"] == "completed"
    assert benchmark_detail["result"]["completed"] == 0

    assert history_response.status_code == 200
    history = history_response.json()
    assert any(item["run_id"] == evolution_run_id for item in history["runs"])
    assert any(item["batch_id"] == benchmark_id for item in history["batches"])


def test_benchmark_uses_battle_games_for_game_count(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        captured.update(batch_config)
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {"game_count": batch_config["game_count"]},
            "fairness": {"is_fair": True},
            "rankable": True,
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:00:00+08:00",
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        response = client.post(
            "/api/benchmark",
            json={
                "roles": ["seer"],
                "training_games": 2,
                "battle_games": 3,
                "role_concurrency": 2,
                "game_concurrency": 4,
                "llm_concurrency": 6,
                "llm_rpm": 120,
                "max_days": 1,
            },
        )
        batch_id = response.json()["batch_id"]
        listed_response = client.get("/api/evolution-runs")

    assert response.status_code == 200
    assert captured["game_count"] == 3
    assert captured["max_days"] == 1
    # New contract: one batch per role, grouped, with the parent batch id.
    assert captured["comparison_group_id"] == batch_id
    assert set(captured) >= {"batch_id", "game_count", "max_days", "comparison_group_id", "model_id"}
    listed = next(item for item in listed_response.json()["batches"] if item["batch_id"] == batch_id)
    assert listed["config"] == {
        "roles": ["seer"],
        "battle_games": 3,
        "max_days": 1,
        "game_concurrency": 3,
    }
    assert listed["result"]["game_count"] == 3


def test_workflow_game_concurrency_setting_feeds_benchmark_and_evolution(
    tmp_path: Path,
    monkeypatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    benchmark_config: dict[str, Any] = {}
    evolution_config: dict[str, Any] = {}

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        benchmark_config.update(batch_config)
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {"game_count": batch_config["game_count"]},
            "fairness": {"is_fair": True},
            "rankable": True,
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:00:00+08:00",
        }

    async def fake_run_evolution(
        *,
        role: str,
        training_games: int,
        battle_games: int,
        run_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        evolution_config.update(kwargs.get("config") or {})
        return {
            "run_id": run_id,
            "role": role,
            "status": "reviewing",
            "training_games": [{"game_id": "train-1"}] if training_games else [],
            "battle_games": [{"game_id": "battle-1"}] if battle_games else [],
            "battle_result": {"completed": battle_games},
            "proposals": [],
            "diff": [],
            "errors": [],
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)
    monkeypatch.setattr(ui_backend_store, "run_evolution", fake_run_evolution)
    monkeypatch.delenv("WEREWOLF_GAME_CONCURRENCY", raising=False)
    monkeypatch.setenv("SETTINGS_ADMIN_ENABLED", "true")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "token-123")
    _fake_ui_pg_provider.db.runtime_settings_enabled = True
    headers = {"X-Settings-Admin-Token": "token-123"}

    with _test_client(tmp_path) as client:
        update_response = client.patch(
            "/api/settings/runtime-variables/WEREWOLF_GAME_CONCURRENCY",
            headers=headers,
            json={"value": 4},
        )
        plan_response = client.post(
            "/api/benchmark/plan",
            json={"roles": ["seer"], "battle_games": 8, "max_days": 1},
        )
        benchmark_response = client.post(
            "/api/benchmark",
            json={"roles": ["seer"], "battle_games": 8, "max_days": 1},
        )
        evolution_response = client.post(
            "/api/evolution-runs",
            json={"roles": ["seer"], "training_games": 1, "battle_games": 1, "max_days": 1},
        )

    assert update_response.status_code == 200
    assert update_response.json()["variable"]["raw_value"] == 4
    assert plan_response.status_code == 200
    assert plan_response.json()["concurrency_policy"]["game_concurrency"] == 4
    assert benchmark_response.status_code == 200
    assert benchmark_config["game_concurrency"] == 4
    assert evolution_response.status_code == 200
    assert evolution_config["game_concurrency"] == 4


def test_benchmark_queue_freezes_default_planned_game_concurrency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("WEREWOLF_GAME_CONCURRENCY", raising=False)
    paths = PathConfig(root=tmp_path)
    store = ui_backend_store.BackendStore(paths=paths, model=FakeModel())
    request = BenchmarkRequest(
        target_type="model",
        roles=["seer"],
        battle_games=10,
        max_days=1,
    )

    batch = store.benchmark_service.queue_benchmark(request)
    eval_config = store.benchmark_service.benchmark_batch_config(
        batch["batch_id"],
        "seer",
        request,
        0,
    )

    assert batch["run_plan"]["concurrency_policy"]["game_concurrency"] == 4
    assert batch["config"]["game_concurrency"] == 4
    assert eval_config["game_concurrency"] == 4


def test_benchmark_request_accepts_suite_and_target_versions() -> None:
    request = BenchmarkRequest(
        benchmark_id="role-baseline-v1",
        roles=["seer", "seer", "witch"],
        target_versions={"seer": "seer_candidate_v2"},
        budget_limit_units=500,
        budget_limit_cost=0.5,
        stop_after_budget_units=400,
    )

    assert request.benchmark_id == "role-baseline-v1"
    assert request.roles == ["seer", "witch"]
    assert request.target_versions == {"seer": "seer_candidate_v2"}
    assert request.target_type == "role_version"
    assert request.battle_games is None
    assert request.max_days is None
    assert request.budget_limit_units == 500
    assert request.budget_limit_cost == 0.5
    assert request.stop_after_budget_units == 400


def test_benchmark_request_normalizes_blank_langfuse_fields() -> None:
    request = BenchmarkRequest(
        roles=["seer"],
        langfuse_dataset_name="  ",
        langfuse_experiment_name="\t",
        langfuse_run_name="",
    )

    assert request.langfuse_dataset_name is None
    assert request.langfuse_experiment_name is None
    assert request.langfuse_run_name is None


def test_spec_benchmark_queue_saves_snapshot_and_eval_config(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, Any] = {}
    _write_benchmark_spec(tmp_path)

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        captured.update(batch_config)
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {"game_count": batch_config["game_count"]},
            "fairness": {"is_fair": True},
            "rankable": True,
            "rankable_reason": "ok",
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:00:00+08:00",
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {"vote.md": "# Seer baseline"},
            version_id="seer_base_v1",
        )
        store.registry.set_baseline("seer", "seer_base_v1")
        _publish_seer_version(store.registry, "seer_candidate_v2", release_stage="canary", body="canary candidate")

        response = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "battle_games": 1,
                "max_days": 1,
                "target_versions": {"seer": "seer_candidate_v2"},
            },
        )
        batch = response.json()
        listed_response = client.get("/api/evolution-runs")
        stored_batch = store.evolution_batches[batch["batch_id"]]

    assert response.status_code == 200
    benchmark = batch["benchmark"]
    assert benchmark["id"] == "role-baseline-v1"
    assert benchmark["version"] == 1
    assert benchmark["config_hash"].startswith("sha256:")
    assert benchmark["evaluation_set_id"] == "role-baseline-v1@v1"
    assert benchmark["seed_set_id"] == "role-baseline-quick-202606"
    assert benchmark["seed_count"] == 3
    assert benchmark["seed_preview"] == [260600, 260607, 260619]
    assert benchmark["seed_set"]["purpose"] == "role_leaderboard_smoke"
    assert benchmark["seed_set_config_hash"].startswith("sha256:")
    assert benchmark["spec_snapshot"]["id"] == "role-baseline-v1"
    assert benchmark["spec_snapshot"]["seeds"] == [260600, 260607, 260619]
    assert benchmark["spec_snapshot"]["gates"]["min_completed_games"] >= 1
    assert batch["target_type"] == "role_version"
    assert batch["config"]["benchmark_id"] == "role-baseline-v1"
    assert batch["config"]["target_versions"] == {"seer": "seer_candidate_v2"}

    assert captured["comparison_group_id"] == batch["batch_id"]
    assert captured["comparison_type"] == "role_version"
    assert captured["target_role"] == "seer"
    assert captured["target_version_id"] == "seer_candidate_v2"
    assert captured["evaluation_set_id"] == benchmark["evaluation_set_id"]
    assert captured["seed_set_id"] == benchmark["seed_set_id"]
    assert captured["seed_start"] == 260600
    assert captured["seeds"] == [260600, 260607, 260619]
    assert captured["paired_seed"] is True
    assert captured["benchmark_id"] == "role-baseline-v1"
    assert captured["benchmark_version"] == 1
    assert captured["benchmark_config_hash"] == benchmark["config_hash"]
    assert captured["langfuse_dataset_name"] == benchmark["evaluation_set_id"]
    assert captured["langfuse_experiment_name"] == "role-baseline-v1"
    assert captured["langfuse_run_name"] == f"{batch['batch_id']}_seer"
    assert set(captured) >= {
        "data_sufficient_min_games",
        "leaderboard_min_games",
        "data_sufficient_min_valid_game_rate",
        "leaderboard_min_valid_game_rate",
        "max_fallback_rate",
        "max_llm_error_rate",
        "leaderboard_fallback_rate_ceiling",
        "leaderboard_llm_error_rate_ceiling",
        "eval_decision_judge",
        "eval_judge_max_decisions",
        "eval_judge_concurrency",
        "eval_judge_timeout_seconds",
    }
    assert captured["game_count"] == benchmark["spec_snapshot"]["game_count"]
    assert captured["max_days"] == benchmark["spec_snapshot"]["max_days"]

    assert stored_batch["benchmark"] == benchmark
    listed = next(item for item in listed_response.json()["batches"] if item["batch_id"] == batch["batch_id"])
    assert listed["config"]["benchmark_id"] == "role-baseline-v1"


def test_run_queued_benchmark_uses_queued_spec_snapshot_after_spec_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}
    _write_benchmark_spec(tmp_path)

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        captured.update(batch_config)
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {"game_count": batch_config["game_count"]},
            "fairness": {"is_fair": True},
            "rankable": True,
            "rankable_reason": "ok",
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:00:00+08:00",
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        _publish_seer_version(store.registry, "seer_candidate_v2", release_stage="canary", body="canary candidate")
        request = BenchmarkRequest(
            benchmark_id="role-baseline-v1",
            roles=["seer"],
            target_versions={"seer": "seer_candidate_v2"},
        )
        batch = store.benchmark_service.queue_benchmark(request)
        queued_benchmark = dict(batch["benchmark"])
        queued_snapshot = dict(queued_benchmark["spec_snapshot"])

        _write_benchmark_spec(tmp_path)
        spec_path = tmp_path / "data" / "benchmarks" / "role-baseline-v1.yaml"
        spec_path.write_text(
            spec_path.read_text(encoding="utf-8")
            .replace("game_count: 3", "game_count: 9")
            .replace("max_days: 5", "max_days: 7")
            .replace("seed_start: 260600", "seed_start: 999000")
            .replace("min_completed_games: 1", "min_completed_games: 8"),
            encoding="utf-8",
        )

        asyncio.run(store.benchmark_service.run_queued_benchmark(batch["batch_id"], request))

    assert queued_snapshot["game_count"] == 3
    assert queued_snapshot["max_days"] == 5
    assert queued_snapshot["seed_start"] == 260600
    assert queued_snapshot["gates"]["min_completed_games"] == 1
    assert captured["game_count"] == 3
    assert captured["max_days"] == 5
    assert captured["seed_start"] == 260600
    assert captured["seeds"] == [260600, 260607, 260619]
    assert captured["data_sufficient_min_games"] == 1
    assert captured["benchmark_config_hash"] == queued_benchmark["config_hash"]
    assert store.evolution_batches[batch["batch_id"]]["benchmark"] == queued_benchmark


def test_benchmark_allows_canary_but_rejects_shadow_target_versions(tmp_path: Path, monkeypatch) -> None:
    _write_benchmark_spec(tmp_path)
    captured: dict[str, Any] = {}

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        captured.update(batch_config)
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {"game_count": batch_config["game_count"]},
            "fairness": {"is_fair": True},
            "rankable": True,
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        _publish_seer_version(store.registry, "seer_shadow_v1", release_stage="shadow", body="shadow")
        _publish_seer_version(store.registry, "seer_canary_v1", release_stage="canary", body="canary")

        shadow_plan = client.post(
            "/api/benchmark/plan",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "target_versions": {"seer": "seer_shadow_v1"},
            },
        )
        shadow_launch = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "target_versions": {"seer": "seer_shadow_v1"},
            },
        )
        canary_launch = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "target_versions": {"seer": "seer_canary_v1"},
            },
        )

    _assert_domain_response(
        shadow_plan,
        code="benchmark_target_version_not_allowed",
        release_stage="shadow",
        kind="benchmark_target_version_not_allowed",
    )
    _assert_domain_response(
        shadow_launch,
        code="benchmark_target_version_not_allowed",
        release_stage="shadow",
        kind="benchmark_target_version_not_allowed",
    )
    assert canary_launch.status_code == 200
    assert captured["target_role"] == "seer"
    assert captured["target_version_id"] == "seer_canary_v1"


def test_benchmark_batch_detail_games_and_diagnostics_after_launch(tmp_path: Path, monkeypatch) -> None:
    _write_benchmark_spec(tmp_path)

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": 2,
            "attempted_game_count": 3,
            "completed": 2,
            "errored": 1,
            "games": [
                {
                    "game_id": f"{batch_config['batch_id']}_game_001",
                    "status": "completed",
                    "seed": batch_config["seeds"][0],
                    "winner": "good",
                    "events": [{"event_type": "game_init", "message": "started"}],
                    "decisions": [{"decision_id": "d1", "action_type": "seer_check"}],
                },
                {
                    "game_id": f"{batch_config['batch_id']}_game_002",
                    "status": "completed",
                    "seed": batch_config["seeds"][1],
                    "winner": "evil",
                    "langfuse_trace_id": "trace-game-002",
                    "langfuse_trace_url": "http://langfuse.local/project/p/traces/trace-game-002",
                    "langfuse_dataset_run_id": "dataset-run-002",
                    "langfuse_dataset_run_item_id": "dataset-run-item-002",
                    "langfuse_experiment_url": "http://langfuse.local/project/p/datasets/dataset/runs/dataset-run-002",
                    "events": [{"event_type": "night_action", "message": "fallback"}],
                    "decisions": [{"decision_id": "d2", "action_type": "seer_check"}],
                    "errors": ["transient LLM timeout"],
                    "fallback_count": 1,
                    "diagnostics": [
                        {
                            "kind": "llm_error",
                            "stage": "llm.call",
                            "level": "warning",
                            "message": "transient LLM timeout",
                        }
                    ],
                },
                {
                    "game_id": f"{batch_config['batch_id']}_game_003",
                    "status": "failed",
                    "seed": batch_config["seeds"][2],
                    "error": "engine aborted",
                    "events": [],
                    "decisions": [],
                    "diagnostics": [
                        {
                            "kind": "game_error",
                            "stage": "game.run",
                            "level": "error",
                            "message": "engine aborted",
                        }
                    ],
                },
            ],
            "score_summary": {
                "game_count": 1,
                "decision_judge_aggregate": {
                    "status": "degraded",
                    "reason": "judge skipped",
                    "metrics": {"judged": 1},
                },
            },
            "fairness": {"is_fair": False, "reason": "missing sibling batch"},
            "rankable": False,
            "rankable_reason": "completed_games 1 < required 3",
            "leaderboard_gate": {
                "accepted": False,
                "reason": "quality_gate_failed",
                "metrics": {"valid_game_rate": 0.5},
            },
            "warnings": ["judge skipped one decision"],
            "diagnostics": [
                {
                    "kind": "fairness_failed",
                    "stage": "fairness.validate",
                    "level": "warning",
                    "message": "missing sibling batch",
                }
            ],
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:00:02+08:00",
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        _publish_seer_version(store.registry, "seer_candidate_v2", release_stage="canary", body="canary candidate")
        response = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "target_versions": {"seer": "seer_candidate_v2"},
            },
        )
        batch_id = response.json()["batch_id"]
        problem_seed = 260607
        detail_response = client.get(f"/api/benchmark/batch/{batch_id}")
        games_response = client.get(f"/api/benchmark/batch/{batch_id}/games?status=failed&limit=10&offset=0")
        problem_games_response = client.get(f"/api/benchmark/batch/{batch_id}/games?status=problem&limit=10&offset=0")
        seed_games_response = client.get(f"/api/benchmark/batch/{batch_id}/games?seed={problem_seed}&limit=10&offset=0")
        problem_seed_games_response = client.get(
            f"/api/benchmark/batch/{batch_id}/games?status=problem&seed={problem_seed}&limit=10&offset=0"
        )
        diagnostics_response = client.get(f"/api/benchmark/batch/{batch_id}/diagnostics")
        diagnostics_seed_response = client.get(
            f"/api/benchmark/batch/{batch_id}/diagnostics?kind=llm_error&seed={problem_seed}"
        )
        diagnostics_status_response = client.get(
            f"/api/benchmark/batch/{batch_id}/diagnostics?status=completed&seed={problem_seed}"
        )

    assert response.status_code == 200

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["kind"] == "benchmark_batch_detail"
    assert detail["batch_id"] == batch_id
    assert detail["benchmark"]["id"] == "role-baseline-v1"
    assert detail["target_type"] == "role_version"
    assert detail["result_count"] == 1
    assert detail["results"][0]["target_role"] == "seer"
    assert detail["results"][0]["result_batch_id"] == f"{batch_id}_seer"
    assert detail["game_summary"]["total"] == 3
    assert detail["game_summary"]["by_status"] == {"completed": 2, "failed": 1}
    assert detail["diagnostic_summary"]["by_kind"]["rankable_failed"] == 1
    assert detail["langfuse"]["dataset_names"] == ["role-baseline-v1@v1"]
    assert detail["langfuse"]["experiment_names"] == ["role-baseline-v1"]
    assert detail["langfuse"]["run_names"] == [f"{batch_id}_seer"]
    assert detail["langfuse"]["trace_count"] == 1
    assert detail["langfuse"]["dataset_run_count"] == 1
    assert detail["langfuse"]["dataset_run_item_count"] == 1
    assert detail["langfuse"]["links"]["trace_urls"] == ["http://langfuse.local/project/p/traces/trace-game-002"]
    assert detail["langfuse"]["links"]["experiment_urls"] == [
        "http://langfuse.local/project/p/datasets/dataset/runs/dataset-run-002"
    ]

    assert games_response.status_code == 200
    games = games_response.json()
    assert games["kind"] == "benchmark_batch_games"
    assert games["pagination"]["total"] == 1
    assert games["games"][0]["game_id"] == f"{batch_id}_seer_game_003"
    assert games["games"][0]["target_role"] == "seer"
    assert games["games"][0]["status"] == "failed"
    assert "events" not in games["games"][0]
    assert "decisions" not in games["games"][0]

    assert problem_games_response.status_code == 200
    problem_games = problem_games_response.json()
    assert problem_games["pagination"]["total"] == 2
    assert [game["game_id"] for game in problem_games["games"]] == [
        f"{batch_id}_seer_game_002",
        f"{batch_id}_seer_game_003",
    ]
    assert problem_games["games"][0]["status"] == "completed"
    assert problem_games["games"][0]["diagnostic_count"] == 1
    assert problem_games["games"][0]["error_count"] == 1
    assert problem_games["games"][0]["fallback_count"] == 1
    assert problem_games["games"][0]["langfuse"] == {
        "trace_id": "trace-game-002",
        "trace_url": "http://langfuse.local/project/p/traces/trace-game-002",
        "dataset_name": "role-baseline-v1@v1",
        "dataset_item_id": "role-baseline-v1@v1:role-baseline-quick-202606:260607",
        "dataset_run_id": "dataset-run-002",
        "dataset_run_item_id": "dataset-run-item-002",
        "dataset_run_url": "http://langfuse.local/project/p/datasets/dataset/runs/dataset-run-002",
        "experiment_name": "role-baseline-v1",
        "run_name": f"{batch_id}_seer",
        "experiment_url": "http://langfuse.local/project/p/datasets/dataset/runs/dataset-run-002",
    }
    assert problem_games["games"][0]["observability"]["langfuse"] == problem_games["games"][0]["langfuse"]

    assert seed_games_response.status_code == 200
    seed_games = seed_games_response.json()
    assert seed_games["pagination"]["total"] == 1
    assert seed_games["games"][0]["game_id"] == f"{batch_id}_seer_game_002"

    assert problem_seed_games_response.status_code == 200
    problem_seed_games = problem_seed_games_response.json()
    assert problem_seed_games["pagination"]["total"] == 1
    assert problem_seed_games["games"][0]["status"] == "completed"

    assert diagnostics_response.status_code == 200
    diagnostics = diagnostics_response.json()
    assert diagnostics["kind"] == "benchmark_batch_diagnostics"
    assert diagnostics["summary"]["by_kind"]["decision_judge_degraded"] == 1
    assert diagnostics["summary"]["by_kind"]["game_failure"] == 1
    assert diagnostics["summary"]["by_kind"]["llm_error"] == 1
    assert diagnostics["summary"]["by_kind"]["leaderboard_gate_failed"] == 1
    assert diagnostics["summary"]["by_origin"]["result"] >= 1

    assert diagnostics_seed_response.status_code == 200
    diagnostics_seed = diagnostics_seed_response.json()
    assert diagnostics_seed["filters"]["kind"] == "llm_error"
    assert diagnostics_seed["filters"]["seed"] == str(problem_seed)
    assert diagnostics_seed["summary"]["total"] == 1
    assert diagnostics_seed["diagnostics"][0]["game_id"] == f"{batch_id}_seer_game_002"
    assert diagnostics_seed["diagnostics"][0]["seed"] == problem_seed
    assert diagnostics_seed["diagnostics"][0]["status"] == "completed"

    assert diagnostics_status_response.status_code == 200
    diagnostics_status = diagnostics_status_response.json()
    assert diagnostics_status["filters"]["status"] == "completed"
    assert diagnostics_status["summary"]["total"] == 1


def test_benchmark_service_no_longer_requires_store_callable_map(tmp_path: Path) -> None:
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path))

    service = store.benchmark_service

    assert store.benchmark_service is service
    assert isinstance(service, benchmark_service_module.BenchmarkService)
    assert not hasattr(ui_backend_store, "BENCHMARK_PUBLIC_METHODS")
    assert not hasattr(benchmark_service_module, "BENCHMARK_PUBLIC_METHODS")
    assert not hasattr(store, "_create_benchmark_snapshot")


def test_benchmark_service_facade_preserves_public_monkeypatch_compatibility(tmp_path: Path) -> None:
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path))
    _ = store.benchmark_service
    captured: list[dict[str, Any]] = []

    def fake_leaderboard_entries(
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        captured.append(
            {
                "scope": scope,
                "evaluation_set_id": evaluation_set_id,
                "target_role": target_role,
                "limit": limit,
            }
        )
        return []

    store.leaderboard_entries = fake_leaderboard_entries  # type: ignore[method-assign]

    payload = store.leaderboard_compare(
        scope="role_version",
        evaluation_set_id="role-baseline-v1@v1",
        target_role="seer",
        limit=25,
    )

    assert captured == [
        {
            "scope": "role_version",
            "evaluation_set_id": "role-baseline-v1@v1",
            "target_role": "seer",
            "limit": 25,
        }
    ]
    assert payload["kind"] == "benchmark_leaderboard_compare"
    assert payload["rows"] == []


def test_benchmark_service_uses_minimal_context_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(paths=PathConfig(root=tmp_path))
    opened_paths: list[Any] = []
    repository_calls: list[dict[str, Any]] = []

    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    connections: list[FakeConnection] = []

    def fake_open_eval_connection(paths: Any) -> FakeConnection:
        opened_paths.append(paths)
        connection = FakeConnection()
        connections.append(connection)
        return connection

    class FakeLeaderboardRepository:
        def __init__(self, conn: FakeConnection) -> None:
            assert conn is connections[-1]

        def list(
            self,
            *,
            scope: str | None = None,
            evaluation_set_id: str | None = None,
            target_role: str | None = None,
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            repository_calls.append(
                {
                    "scope": scope,
                    "evaluation_set_id": evaluation_set_id,
                    "target_role": target_role,
                    "limit": limit,
                }
            )
            return [{"id": "row-1"}]

    monkeypatch.setattr("app.lib.score.open_eval_connection", fake_open_eval_connection)
    monkeypatch.setattr(
        benchmark_leaderboard_service_module,
        "BenchmarkLeaderboardRepository",
        FakeLeaderboardRepository,
    )

    service = benchmark_service_module.BenchmarkService(context)
    rows = service.load_leaderboard_rows(
        scope="role_version",
        evaluation_set_id="suite@v1",
        target_role="seer",
        limit=3,
    )

    assert rows == [{"id": "row-1"}]
    assert opened_paths == [context.paths]
    assert repository_calls == [
        {
            "scope": "role_version",
            "evaluation_set_id": "suite@v1",
            "target_role": "seer",
            "limit": 3,
        }
    ]
    assert connections and connections[0].closed is True


def test_benchmark_service_catalog_does_not_require_store_callables(tmp_path: Path) -> None:
    _write_benchmark_spec(tmp_path)
    context = SimpleNamespace(paths=PathConfig(root=tmp_path), evolution_batches={})
    service = benchmark_service_module.BenchmarkService(context)

    specs_payload = service.benchmark_specs_payload()
    spec_ids = {item["id"] for item in specs_payload["items"]}
    assert specs_payload["kind"] == "benchmark_specs"
    assert "role-baseline-v1" in spec_ids

    summary = service.get_benchmark_spec_summary("role-baseline-v1")
    assert summary["id"] == "role-baseline-v1"
    assert summary["seed_set_id"] == "role-baseline-quick-202606"
    assert summary["last_run"] is None
    assert summary["latest_snapshot"] is None

    seed_sets = service.list_benchmark_seed_sets()
    seed_set = next(item for item in seed_sets["items"] if item["id"] == "role-baseline-quick-202606")
    assert seed_set["enabled"] is True

    seed_set_detail = service.get_benchmark_seed_set("role-baseline-quick-202606")
    assert seed_set_detail["item"]["seeds"] == [260600, 260607, 260619]

    lifecycle = service.update_benchmark_lifecycle(
        "role-baseline-v1",
        BenchmarkLifecycleRequest(status="disabled", reason="service catalog test"),
    )
    assert lifecycle["kind"] == "benchmark_suite_lifecycle"
    assert lifecycle["benchmark_id"] == "role-baseline-v1"
    assert lifecycle["status"] == "disabled"
    assert lifecycle["launchable"] is False


def test_leaderboard_real_store_isolates_scope_evaluation_role_and_formal_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    open_conn = _install_sqlite_benchmark_leaderboard(monkeypatch, tmp_path)
    _persist_benchmark_leaderboard_entries(
        open_conn,
        {
            "id": "role-seer-baseline",
            "scope": "role_version",
            "subject_id": "seer_base_v1",
            "target_role": "seer",
            "target_version_id": "seer_base_v1",
            "comparison_group_id": "bench_role_release_20260609",
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "game_count": 30,
            "valid_game_rate": 1.0,
            "strength_score": 7.0,
            "avg_role_score": 7.0,
            "target_side_win_rate": 0.58,
            "rankable": True,
            "summary": {"is_baseline": True},
            "updated_at": "2026-06-09T10:00:00+08:00",
        },
        {
            "id": "role-seer-candidate",
            "scope": "role_version",
            "subject_id": "seer_candidate_v2",
            "target_role": "seer",
            "target_version_id": "seer_candidate_v2",
            "comparison_group_id": "bench_role_release_20260609",
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "game_count": 30,
            "valid_game_rate": 1.0,
            "strength_score": 7.4,
            "avg_role_score": 7.4,
            "target_side_win_rate": 0.63,
            "rankable": True,
            "updated_at": "2026-06-09T10:01:00+08:00",
        },
        {
            "id": "role-seer-gate-failed",
            "scope": "role_version",
            "subject_id": "seer_gate_failed_v1",
            "target_role": "seer",
            "target_version_id": "seer_gate_failed_v1",
            "comparison_group_id": "bench_role_release_20260609",
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "game_count": 30,
            "valid_game_rate": 0.2,
            "strength_score": 9.9,
            "avg_role_score": 9.9,
            "target_side_win_rate": 0.9,
            "rankable": False,
            "summary": {
                "rankable_reason": "completed_games 30 < required 40",
                "completed_games": 30,
                "total_games": 30,
            },
            "updated_at": "2026-06-09T10:02:00+08:00",
        },
        {
            "id": "role-seer-other-eval",
            "scope": "role_version",
            "subject_id": "seer_other_eval_v1",
            "target_role": "seer",
            "target_version_id": "seer_other_eval_v1",
            "comparison_group_id": "bench_role_other",
            "evaluation_set_id": "role-baseline-v2@v1",
            "seed_set_id": "role-baseline-other-202606",
            "game_count": 30,
            "valid_game_rate": 1.0,
            "strength_score": 8.8,
            "avg_role_score": 8.8,
            "rankable": True,
            "updated_at": "2026-06-09T10:03:00+08:00",
        },
        {
            "id": "role-witch-same-eval",
            "scope": "role_version",
            "subject_id": "witch_candidate_v1",
            "target_role": "witch",
            "target_version_id": "witch_candidate_v1",
            "comparison_group_id": "bench_role_release_20260609",
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "game_count": 30,
            "valid_game_rate": 1.0,
            "strength_score": 8.1,
            "avg_role_score": 8.1,
            "rankable": True,
            "updated_at": "2026-06-09T10:04:00+08:00",
        },
        {
            "id": "model-same-release",
            "scope": "model",
            "subject_id": "runtime_hash_v1",
            "model_id": "qwen-max",
            "model_config_hash": "runtime_hash_v1",
            "comparison_group_id": "bench_model_release_20260609",
            "evaluation_set_id": "model-baseline-v1@v1",
            "seed_set_id": "model-baseline-quick-202606",
            "game_count": 30,
            "valid_game_rate": 1.0,
            "strength_score": 7.8,
            "avg_role_score": 7.2,
            "rankable": True,
            "updated_at": "2026-06-09T10:05:00+08:00",
        },
    )

    with _test_client(tmp_path) as client:
        leaderboard_response = client.get(
            "/api/leaderboards?"
            "scope=role_version&evaluation_set_id=role-baseline-v1%40v1&target_role=seer&limit=20"
        )
        compare_response = client.get(
            "/api/leaderboards/compare?"
            "scope=role_version&evaluation_set_id=role-baseline-v1%40v1&"
            "target_role=seer&baseline_subject_id=seer_base_v1&limit=20"
        )
        model_response = client.get("/api/models/leaderboard?evaluation_set_id=model-baseline-v1%40v1&limit=20")

    assert leaderboard_response.status_code == 200
    leaderboard = leaderboard_response.json()
    entries = leaderboard["entries"]
    assert {entry["scope"] for entry in entries} == {"role_version"}
    assert {entry["evaluation_set_id"] for entry in entries} == {"role-baseline-v1@v1"}
    assert {entry["target_role"] for entry in entries} == {"seer"}
    assert {entry["subject_id"] for entry in entries} == {
        "seer_base_v1",
        "seer_candidate_v2",
        "seer_gate_failed_v1",
    }
    candidate_entry = next(entry for entry in entries if entry["subject_id"] == "seer_candidate_v2")
    assert candidate_entry["sample_size"] == 30
    assert candidate_entry["paired_sample_size"] == 0
    assert candidate_entry["win_rate_ci"]["level"] == 0.95
    assert candidate_entry["ci_low"] == candidate_entry["win_rate_ci"]["low"]
    assert candidate_entry["ci_high"] == candidate_entry["win_rate_ci"]["high"]
    assert candidate_entry["standard_error"] > 0
    assert candidate_entry["significant"] is False
    assert candidate_entry["significance_label"] == "待比较"
    assert candidate_entry["warnings"] == []

    assert compare_response.status_code == 200
    compare = compare_response.json()
    formal_subjects = {row["subject_id"] for row in compare["rows"]}
    assert formal_subjects == {"seer_base_v1", "seer_candidate_v2"}
    assert all(row["rankable"] is True for row in compare["rows"])
    assert compare["baseline_subject_id"] == "seer_base_v1"
    compare_candidate = next(row for row in compare["rows"] if row["subject_id"] == "seer_candidate_v2")
    assert compare_candidate["sample_size"] == 30
    assert compare_candidate["paired_sample_size"] == 0
    assert compare_candidate["paired_delta"] is None
    assert compare_candidate["significant"] is False
    assert compare_candidate["significance_label"] == "差异不显著"
    assert "unpaired_seeds" in compare_candidate["warnings"]
    assert compare["summary"]["not_significant_count"] == 1
    assert compare["summary"]["unpaired_seed_count"] >= 1
    assert compare["summary"]["unrankable_evidence_count"] == 1
    assert compare["summary"]["unrankable_count"] == 1
    assert len(compare["unrankable_evidence"]) == 1
    evidence = compare["unrankable_evidence"][0]
    assert evidence["subject_id"] == "seer_gate_failed_v1"
    assert evidence["target_role"] == "seer"
    assert evidence["evaluation_set_id"] == "role-baseline-v1@v1"
    assert evidence["reason"] == "completed_games 30 < required 40"
    assert evidence["completed_games"] == 30
    assert evidence["total_games"] == 30

    assert model_response.status_code == 200
    model_entries = model_response.json()["entries"]
    assert [entry["subject_id"] for entry in model_entries] == ["runtime_hash_v1"]
    assert model_entries[0]["scope"] == "model"
    assert model_entries[0]["target_role"] is None
    assert model_entries[0]["sample_size"] == 30
    assert model_entries[0]["win_rate_ci"]["level"] == 0.95


def test_model_benchmark_queue_uses_model_scope_and_seed_registry(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    _write_model_benchmark_spec(tmp_path)
    open_conn = _install_sqlite_benchmark_leaderboard(monkeypatch, tmp_path)

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append(dict(batch_config))
        _persist_benchmark_leaderboard_entries(
            open_conn,
            {
                "id": "model-runtime-hash-v1",
                "scope": "model",
                "subject_id": batch_config["model_config_hash"],
                "model_id": batch_config["model_id"],
                "model_config_hash": batch_config["model_config_hash"],
                "comparison_group_id": batch_config["comparison_group_id"],
                "evaluation_set_id": batch_config["evaluation_set_id"],
                "seed_set_id": batch_config["seed_set_id"],
                "game_count": batch_config["game_count"],
                "valid_game_rate": 1.0,
                "strength_score": 6.8,
                "avg_role_score": 6.5,
                "by_role_category_scores": {"seer": 6.4, "witch": 6.6},
                "fallback_rate": 0.02,
                "llm_error_rate": 0.01,
                "policy_adjusted_rate": 0.0,
                "rankable": True,
                "model_runtime": batch_config["model_runtime"],
                "summary": {"source_run_id": batch_config["comparison_group_id"]},
                "updated_at": "2026-06-09T10:00:00+08:00",
            },
        )
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {
                "strength_score": 6.8,
                "avg_role_score": 6.5,
                "game_count": batch_config["game_count"],
                "by_role_category": {"seer": 6.4, "witch": 6.6},
                "fallback_rate": 0.02,
                "llm_error_rate": 0.01,
                "policy_adjusted_rate": 0.0,
            },
            "fairness": {"is_fair": True},
            "rankable": True,
            "rankable_reason": "ok",
            "model_id": batch_config["model_id"],
            "model_config_hash": batch_config["model_config_hash"],
            "model_runtime": batch_config["model_runtime"],
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:00:00+08:00",
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        response = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "model-baseline-v1",
                "target_type": "model",
                "model_id": "qwen-max",
                "model_config_hash": "runtime_hash_v1",
            },
        )
        batch = response.json()
        batch_id = batch["batch_id"]
        detail_response = client.get(f"/api/benchmark/batch/{batch_id}")
        report_response = client.get(f"/api/benchmark/batch/{batch_id}/report")
        markdown_response = client.get(f"/api/benchmark/batch/{batch_id}/report?format=markdown")
        csv_response = client.get(f"/api/benchmark/batch/{batch_id}/report?format=csv")
        leaderboard_response = client.get("/api/models/leaderboard?evaluation_set_id=model-baseline-v1%40v1&limit=10")

    assert response.status_code == 200
    assert batch["target_type"] == "model"
    assert batch["roles"] == ["seer", "witch"]
    benchmark = batch["benchmark"]
    assert benchmark["id"] == "model-baseline-v1"
    assert benchmark["seed_preview"] == [270600, 270611, 270623]
    assert benchmark["spec_snapshot"]["target_type"] == "model"
    assert benchmark["spec_snapshot"]["seeds"] == [270600, 270611, 270623]
    queued_runtime = batch["config"]["model_runtime"]
    assert queued_runtime["source"] == "request"
    assert queued_runtime["hash_source"] == "request"
    assert queued_runtime["hash_algorithm"] == "sha256"
    assert queued_runtime["hash_input_schema_version"] == 1
    assert queued_runtime["externally_provided"] is True
    assert queued_runtime["hash_provided"] is True
    assert queued_runtime["hash_input"] == {}
    assert queued_runtime["model_id"] == "qwen-max"
    assert queued_runtime["model_config_hash"] == "runtime_hash_v1"

    assert len(calls) == 1
    config = calls[0]
    assert config["comparison_type"] == "model"
    assert config["model_id"] == "qwen-max"
    assert config["model_config_hash"] == "runtime_hash_v1"
    assert config["model_runtime"] == queued_runtime
    assert config["evaluation_set_id"] == "model-baseline-v1@v1"
    assert config["seed_set_id"] == "model-baseline-quick-202606"
    assert config["seeds"] == [270600, 270611, 270623]
    assert "target_role" not in config
    assert "target_version_id" not in config

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["kind"] == "benchmark_batch_detail"
    assert detail["batch_id"] == batch_id
    assert detail["target_type"] == "model"
    assert detail["model_runtime"] == queued_runtime
    assert detail["result_count"] == 1
    assert detail["results"][0]["config"]["comparison_type"] == "model"
    assert detail["results"][0]["config"]["model_id"] == "qwen-max"
    assert detail["results"][0]["config"]["model_config_hash"] == "runtime_hash_v1"
    assert detail["results"][0]["config"]["model_runtime"] == queued_runtime
    assert detail["results"][0]["target_role"] is None

    assert report_response.status_code == 200
    report = report_response.json()
    assert report["kind"] == "benchmark_run_report"
    assert report["report_id"] == f"benchmark_report:{batch_id}"
    assert report["content_hash"].startswith("sha256:")
    assert report["artifacts"]["content_hash"] == report["content_hash"]
    assert report["leaderboard"]["scope"] == "model"
    assert report["leaderboard"]["evaluation_set_id"] == "model-baseline-v1@v1"
    assert report["leaderboard"]["target_role"] is None
    assert report["subject"]["model_id"] == "qwen-max"
    assert report["subject"]["model_config_hash"] == "runtime_hash_v1"
    assert report["model_runtime"] == queued_runtime
    assert report["summary"]["rankable_count"] == 1

    assert markdown_response.status_code == 200
    markdown = markdown_response.json()
    assert markdown["report_id"] == report["report_id"]
    assert markdown["content_hash"] == report["content_hash"]
    assert markdown["export_content_hash"].startswith("sha256:")
    assert markdown["artifact_hash"] == markdown["export_content_hash"]
    assert "## 模型运行配置" in markdown["content"]

    assert csv_response.status_code == 200
    csv = csv_response.json()
    assert csv["report_id"] == report["report_id"]
    assert csv["content_hash"] == report["content_hash"]
    assert csv["export_content_hash"].startswith("sha256:")
    assert "模型运行配置,来源,request" in csv["content"]

    assert leaderboard_response.status_code == 200
    leaderboard = leaderboard_response.json()
    assert leaderboard["kind"] == "model_leaderboard"
    assert leaderboard["scope"] == "model"
    assert leaderboard["evaluation_set_id"] == "model-baseline-v1@v1"
    assert len(leaderboard["entries"]) == 1
    entry = leaderboard["entries"][0]
    assert entry["scope"] == "model"
    assert entry["subject_id"] == "runtime_hash_v1"
    assert entry["model_id"] == "qwen-max"
    assert entry["model_config_hash"] == "runtime_hash_v1"
    assert entry["model_runtime"] == queued_runtime
    assert entry["evaluation_set_id"] == "model-baseline-v1@v1"
    assert entry["seed_set_id"] == "model-baseline-quick-202606"
    assert entry["rankable"] is True
    assert entry["target_role"] is None
    assert entry["target_version_id"] is None
    assert entry["strength_score"] == 6.8


def test_benchmark_reports_sanitize_stored_model_runtime(tmp_path: Path, monkeypatch) -> None:
    _write_model_benchmark_spec(tmp_path)

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "batch_id": batch_config["batch_id"],
            "config": dict(batch_config),
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {
                "strength_score": 6.8,
                "avg_role_score": 6.5,
                "game_count": batch_config["game_count"],
                "by_role_category": {"seer": 6.4, "witch": 6.6},
                "fallback_rate": 0.02,
                "llm_error_rate": 0.01,
                "policy_adjusted_rate": 0.0,
            },
            "fairness": {"is_fair": True},
            "rankable": True,
            "rankable_reason": "ok",
            "model_id": batch_config["model_id"],
            "model_config_hash": batch_config["model_config_hash"],
            "model_runtime": dict(batch_config["model_runtime"]),
            "started_at": "2026-01-01T00:00:00+08:00",
            "finished_at": "2026-01-01T00:00:00+08:00",
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    leaky_runtime = {
        "source": "settings_profile",
        "model_id": "leaky-model",
        "model_config_hash": "leaky_hash",
        "base_url": "https://leak.example/v1?token=hidden-token#fragment-secret",
        "api_key": "sk-report-secret",
        "secret_ref": "secret-ref-value",
        "endpoint_url": "https://inner.example/v1?api_key=inner-hidden",
        "hash_input": {
            "base_url": "https://hash.example/v1?token=hash-hidden",
            "metadata": {
                "token": "nested-hidden-token",
                "visible": "kept",
            },
        },
    }

    with _test_client(tmp_path) as client:
        response = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "model-baseline-v1",
                "target_type": "model",
                "model_id": "qwen-max",
                "model_config_hash": "runtime_hash_v1",
            },
        )
        assert response.status_code == 200
        batch_id = response.json()["batch_id"]
        store = client.app.state.backend_store
        stored_batch = store.evolution_batches[batch_id]
        runtime_payload = json.loads(json.dumps(leaky_runtime))
        stored_batch["model_runtime"] = runtime_payload
        stored_batch["config"]["model_runtime"] = json.loads(json.dumps(leaky_runtime))
        stored_batch["run_plan"]["model_runtime"] = json.loads(json.dumps(leaky_runtime))
        stored_batch["results"][0]["model_runtime"] = json.loads(json.dumps(leaky_runtime))
        stored_batch["results"][0]["config"]["model_runtime"] = json.loads(json.dumps(leaky_runtime))

        detail_response = client.get(f"/api/benchmark/batch/{batch_id}")
        report_response = client.get(f"/api/benchmark/batch/{batch_id}/report")
        markdown_response = client.get(f"/api/benchmark/batch/{batch_id}/report?format=markdown")
        csv_response = client.get(f"/api/benchmark/batch/{batch_id}/report?format=csv")

    assert detail_response.status_code == 200
    assert report_response.status_code == 200
    assert markdown_response.status_code == 200
    assert csv_response.status_code == 200

    detail = detail_response.json()
    report = report_response.json()
    markdown = markdown_response.json()
    csv = csv_response.json()
    assert detail["model_runtime"]["base_url"] == "https://leak.example/v1"
    assert detail["batch"]["config"]["model_runtime"]["endpoint_url"] == "https://inner.example/v1"
    assert detail["batch"]["run_plan"]["model_runtime"]["base_url"] == "https://leak.example/v1"
    assert detail["results"][0]["config"]["model_runtime"]["hash_input"]["base_url"] == "https://hash.example/v1"
    assert report["model_runtime"]["base_url"] == "https://leak.example/v1"
    assert report["results"][0]["config"]["model_runtime"]["endpoint_url"] == "https://inner.example/v1"
    assert report["reproducibility_manifest"]["request"]["model_runtime"]["base_url"] == "https://leak.example/v1"
    assert report["reproducibility_manifest"]["planner"]["model_runtime"]["endpoint_url"] == "https://inner.example/v1"

    serialized = json.dumps(
        {"detail": detail, "report": report, "markdown": markdown, "csv": csv},
        ensure_ascii=False,
        sort_keys=True,
    )
    for forbidden in (
        "sk-report-secret",
        "secret-ref-value",
        "hidden-token",
        "fragment-secret",
        "inner-hidden",
        "hash-hidden",
        "nested-hidden-token",
    ):
        assert forbidden not in serialized


def test_model_benchmark_queue_freezes_auto_runtime_provenance(tmp_path: Path, monkeypatch) -> None:
    class RuntimeModel(FakeModel):
        model_id = "runtime-model"

        def __init__(self) -> None:
            self.temperature = 0.2
            self.timeout = 11.0
            self.model_kwargs = {
                "top_p": 0.7,
                "public_label": "queued",
                "api_key": "secret-value",
                "nested": {"token": "hidden-token", "visible": "kept"},
            }

    _write_model_benchmark_spec(tmp_path)
    model = RuntimeModel()
    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=model)
    store = app.state.backend_store
    captured: dict[str, Any] = {}

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        captured.update(batch_config)
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {"strength_score": 1.0, "avg_role_score": 1.0},
            "fairness": {"is_fair": True},
            "rankable": True,
            "rankable_reason": "ok",
            "model_id": batch_config["model_id"],
            "model_config_hash": batch_config["model_config_hash"],
            "model_runtime": batch_config["model_runtime"],
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    request = BenchmarkRequest(benchmark_id="model-baseline-v1", target_type="model")
    batch = store.benchmark_service.queue_benchmark(request)
    queued_runtime = batch["model_runtime"]
    queued_hash = queued_runtime["model_config_hash"]
    model.temperature = 0.9
    model.model_kwargs["public_label"] = "mutated"
    model.model_kwargs["new_public"] = "after-queue"

    asyncio.run(store.benchmark_service.run_queued_benchmark(batch["batch_id"], request))

    assert queued_runtime["source"] == "injected_model"
    assert queued_runtime["hash_source"] == "injected_model"
    assert queued_runtime["externally_provided"] is False
    assert queued_runtime["hash_input"]["temperature"] == 0.2
    assert queued_runtime["hash_input"]["timeout"] == 11.0
    assert queued_runtime["hash_input"]["model_kwargs"]["public_label"] == "queued"
    assert queued_runtime["hash_input"]["model_kwargs"]["nested"] == {"visible": "kept"}
    runtime_text = json.dumps(queued_runtime, ensure_ascii=False)
    assert "secret-value" not in runtime_text
    assert "hidden-token" not in runtime_text
    assert "api_key" not in runtime_text
    assert "token" not in runtime_text
    assert captured["model_runtime"] == queued_runtime
    assert captured["model_config_hash"] == queued_hash
    assert "new_public" not in captured["model_runtime"]["hash_input"]["model_kwargs"]
    result_runtime = store.evolution_batches[batch["batch_id"]]["results"][0]["config"]["model_runtime"]
    assert result_runtime == queued_runtime


def test_model_runtime_hash_uses_public_config_and_ignores_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("UI_BACKEND_USE_FAKE_LLM", raising=False)
    monkeypatch.setenv("WEREWOLF_LLM_API_KEY", "secret-a")
    monkeypatch.setenv("WEREWOLF_LLM_BASE_URL", "https://example.test/v1?token=hidden-runtime-token")
    monkeypatch.setenv("WEREWOLF_LLM_MODEL", "qwen-runtime-a")
    monkeypatch.setenv("WEREWOLF_LLM_TEMPERATURE", "0.2")
    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=None)
    store = app.state.backend_store
    request = BenchmarkRequest(benchmark_id="model-baseline-v1", target_type="model")

    first = store.benchmark_service.benchmark_model_runtime(request)["model_runtime"]
    monkeypatch.setenv("WEREWOLF_LLM_API_KEY", "secret-b")
    same_public_config = store.benchmark_service.benchmark_model_runtime(request)["model_runtime"]
    monkeypatch.setenv("WEREWOLF_LLM_TEMPERATURE", "0.9")
    changed_public_config = store.benchmark_service.benchmark_model_runtime(request)["model_runtime"]

    assert first["source"] == "configured_llm"
    assert first["hash_input"]["model"] == "qwen-runtime-a"
    assert first["hash_input"]["base_url_host"] == "example.test"
    assert "base_url" not in first["hash_input"]
    assert first["hash_input"]["temperature"] == 0.2
    assert first["model_config_hash"] == same_public_config["model_config_hash"]
    assert first["model_config_hash"] != changed_public_config["model_config_hash"]
    plan = store.benchmark_service.plan_benchmark(BenchmarkRequest(target_type="model", battle_games=0, max_days=1))
    assert plan["model_runtime"]["hash_input"]["base_url_host"] == "example.test"
    runtime_text = json.dumps(first, ensure_ascii=False)
    assert "secret-a" not in runtime_text
    assert "secret-b" not in runtime_text
    assert "api_key" not in runtime_text
    assert "hidden-runtime-token" not in runtime_text
    assert "hidden-runtime-token" not in json.dumps(plan, ensure_ascii=False)


def test_benchmark_product_ci_smoke_covers_release_chain(tmp_path: Path, monkeypatch) -> None:
    """Low-cost CI smoke for the benchmark product contract without touching UI."""
    _write_benchmark_spec(tmp_path)
    open_conn = _install_sqlite_benchmark_leaderboard(monkeypatch, tmp_path)
    captured_configs: list[dict[str, Any]] = []

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        captured_configs.append(dict(batch_config))
        _persist_benchmark_leaderboard_entries(
            open_conn,
            {
                "id": f"{batch_config['comparison_group_id']}:seer_candidate_v2",
                "scope": "role_version",
                "subject_id": batch_config["target_version_id"],
                "hash": batch_config["target_version_id"],
                "target_role": batch_config["target_role"],
                "target_version_id": batch_config["target_version_id"],
                "comparison_group_id": batch_config["comparison_group_id"],
                "evaluation_set_id": batch_config["evaluation_set_id"],
                "seed_set_id": batch_config["seed_set_id"],
                "benchmark_id": batch_config["benchmark_id"],
                "benchmark_version": batch_config["benchmark_version"],
                "benchmark_config_hash": batch_config["benchmark_config_hash"],
                "game_count": batch_config["game_count"],
                "games_played": batch_config["game_count"],
                "valid_game_rate": 1.0,
                "strength_score": 0.74,
                "avg_role_score": 0.74,
                "target_role_role_weighted_score": 0.74,
                "target_side_win_rate": 0.62,
                "rankable": True,
                "data_sufficient": True,
                "batch_id": batch_config["comparison_group_id"],
                "source_run_id": batch_config["comparison_group_id"],
                "result_batch_id": batch_config["batch_id"],
                "report_id": f"benchmark_report:{batch_config['comparison_group_id']}",
                "summary": {"ci_smoke": True},
                "updated_at": "2026-06-09T11:00:00+08:00",
            },
            {
                "id": "other-eval-seer",
                "scope": "role_version",
                "subject_id": "seer_other_suite",
                "target_role": "seer",
                "target_version_id": "seer_other_suite",
                "evaluation_set_id": "role-baseline-other@v1",
                "seed_set_id": batch_config["seed_set_id"],
                "benchmark_config_hash": batch_config["benchmark_config_hash"],
                "game_count": batch_config["game_count"],
                "games_played": batch_config["game_count"],
                "valid_game_rate": 1.0,
                "strength_score": 0.95,
                "avg_role_score": 0.95,
                "target_side_win_rate": 0.9,
                "rankable": True,
                "updated_at": "2026-06-09T11:01:00+08:00",
            },
        )
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {
                "game_count": batch_config["game_count"],
                "avg_role_score": 0.74,
                "target_side_win_rate": 0.62,
            },
            "fairness": {"is_fair": True},
            "rankable": True,
            "rankable_reason": "ok",
            "started_at": "2026-06-09T11:00:00+08:00",
            "finished_at": "2026-06-09T11:01:00+08:00",
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        _publish_seer_version(store.registry, "seer_base_v1", baseline=True, body="baseline")
        _publish_seer_version(store.registry, "seer_candidate_v2", release_stage="canary", body="candidate")

        suites_response = client.get("/api/benchmarks")
        seed_sets_response = client.get("/api/benchmark/seed-sets")
        plan_response = client.post(
            "/api/benchmark/plan",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "target_versions": {"seer": "seer_candidate_v2"},
                "budget_limit_units": 100000,
                "budget_limit_cost": 100.0,
            },
        )
        start_response = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "target_versions": {"seer": "seer_candidate_v2"},
            },
        )
        batch_id = start_response.json()["batch_id"]
        detail_response = client.get(f"/api/benchmark/batch/{batch_id}")
        events_response = client.get(f"/api/benchmark/batch/{batch_id}/events")
        leaderboard_response = client.get(
            "/api/leaderboards?scope=role_version&evaluation_set_id=role-baseline-v1%40v1&target_role=seer&limit=10"
        )
        snapshot_response = client.post(
            "/api/benchmark/snapshots",
            json={
                "title": "CI smoke release",
                "scope": "role_version",
                "benchmark_id": "role-baseline-v1",
                "benchmark_version": 1,
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": captured_configs[0]["benchmark_config_hash"],
                "target_role": "seer",
                "limit": 10,
            },
        )
        snapshot_id = snapshot_response.json()["snapshot_id"]
        export_response = client.get(f"/api/benchmark/snapshots/{snapshot_id}/export?format=markdown")

    assert suites_response.status_code == 200
    assert any(item["id"] == "role-baseline-v1" for item in suites_response.json()["items"])

    assert seed_sets_response.status_code == 200
    seed_set = next(item for item in seed_sets_response.json()["items"] if item["id"] == "role-baseline-quick-202606")
    assert seed_set["immutable"] is True
    assert seed_set["config_hash"].startswith("sha256:")

    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["benchmark"]["id"] == "role-baseline-v1"
    assert plan["budget"]["exceeded"]["value"] is False
    assert plan["dry_run"] is True

    assert start_response.status_code == 200
    assert len(captured_configs) == 1
    config = captured_configs[0]
    assert config["evaluation_set_id"] == "role-baseline-v1@v1"
    assert config["seed_set_id"] == "role-baseline-quick-202606"
    assert config["seeds"] == [260600, 260607, 260619]
    assert config["benchmark_config_hash"].startswith("sha256:")

    batch = start_response.json()
    assert batch["benchmark"]["spec_snapshot"]["id"] == "role-baseline-v1"
    assert batch["benchmark"]["seed_set_config_hash"].startswith("sha256:")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "completed"
    assert detail["benchmark"]["evaluation_set_id"] == "role-baseline-v1@v1"
    assert detail["result_count"] == 1

    assert events_response.status_code == 200
    assert "event: completed" in events_response.text
    assert f'"batch_id": "{batch_id}"' in events_response.text

    assert leaderboard_response.status_code == 200
    entries = leaderboard_response.json()["entries"]
    assert [entry["subject_id"] for entry in entries] == ["seer_candidate_v2"]
    assert entries[0]["evaluation_set_id"] == "role-baseline-v1@v1"
    assert entries[0]["sample_size"] == 3
    assert "seer_other_suite" not in json.dumps(entries, ensure_ascii=False)

    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["row_count"] == 1
    assert snapshot["linked_run_ids"] == [batch_id]
    assert snapshot["linked_report_ids"] == [f"benchmark_report:{batch_id}"]
    assert snapshot["linked_result_batch_ids"] == [f"{batch_id}_seer"]

    assert export_response.status_code == 200
    exported = export_response.json()
    assert exported["kind"] == "benchmark_leaderboard_snapshot_export"
    assert exported["format"] == "markdown"
    assert "CI smoke release" in exported["content"]
    assert "seer_candidate_v2" in exported["content"]


def test_benchmark_plan_estimates_cost_and_blocks_over_budget_launch(tmp_path: Path) -> None:
    _write_benchmark_spec(tmp_path)
    _write_model_benchmark_spec(tmp_path)

    with _test_client(tmp_path) as client:
        role_plan_response = client.post(
            "/api/benchmark/plan",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "budget_limit_units": 1000,
                "budget_limit_cost": 1.0,
                "stop_after_budget_units": 500,
            },
        )
        model_plan_response = client.post(
            "/api/benchmark/plan",
            json={
                "benchmark_id": "model-baseline-v1",
                "target_type": "model",
                "budget_limit_units": 1000,
                "budget_limit_cost": 1.0,
            },
        )
        blocked_response = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "budget_limit_units": 100,
                "budget_limit_cost": 0.1,
                "stop_after_budget_units": 120,
            },
        )

    assert role_plan_response.status_code == 200
    role_plan = role_plan_response.json()
    assert role_plan["target_type"] == "role_version"
    assert role_plan["roles"] == ["seer"]
    assert role_plan["model_id"] == "FakeModel"
    assert role_plan["model_config_hash"]
    assert role_plan["model_runtime"]["source"] == "injected_model"
    assert role_plan["model_runtime"]["model_id"] == role_plan["model_id"]
    assert role_plan["model_runtime"]["model_config_hash"] == role_plan["model_config_hash"]
    assert role_plan["eval_batch_count"] == 1
    assert role_plan["total_games"] == 3
    assert role_plan["judge"]["estimated_decisions"] == 30
    assert role_plan["estimates"]["game_decision_units"] == 180
    assert role_plan["estimates"]["estimated_llm_call_units"] == 210
    assert role_plan["dry_run"] is True
    assert role_plan["estimated_tokens"] == 225900
    assert role_plan["estimated_cost"] == 0.4518
    assert role_plan["currency"] == "USD"
    assert role_plan["expected_duration_seconds"] == 97
    assert role_plan["concurrency_policy"]["policy"] == "bounded_sequential_eval_batches"
    assert role_plan["concurrency_policy"]["game_concurrency"] == 3
    assert role_plan["concurrency_policy"]["judge_concurrency"] == 2
    assert role_plan["concurrency_policy"]["expected_duration_seconds"] == 97
    assert role_plan["assumptions"] == [
        "game_decision_units = total_games * max_days * 12 players",
        "judge_decision_units = total_games * judge_max_decisions when decision judge is enabled",
        "estimated_tokens = game units and judge units multiplied by planner token assumptions",
        "estimated_cost uses planner token cost assumptions and is reported before launch",
    ]
    assert role_plan["budget"] == {
        "limit_units": 1000,
        "estimated_units": 210,
        "limit_cost": 1.0,
        "estimated_cost": 0.4518,
        "estimated_tokens": 225900,
        "currency": "USD",
        "stop_after_budget_units": 500,
        "stop_after_predicted": False,
        "exceeded": {"value": False, "reasons": [], "evidence": []},
    }
    assert role_plan["launchable"] is True

    assert model_plan_response.status_code == 200
    model_plan = model_plan_response.json()
    assert model_plan["target_type"] == "model"
    assert model_plan["roles"] == ["seer", "witch"]
    assert model_plan["model_id"] == "FakeModel"
    assert model_plan["model_config_hash"]
    assert model_plan["model_runtime"]["source"] == "injected_model"
    assert model_plan["model_runtime"]["model_id"] == model_plan["model_id"]
    assert model_plan["model_runtime"]["model_config_hash"] == model_plan["model_config_hash"]
    assert model_plan["eval_batch_count"] == 1
    assert model_plan["total_games"] == 3
    assert model_plan["judge"]["estimated_decisions"] == 30
    assert model_plan["dry_run"] is True
    assert model_plan["estimated_tokens"] == 225900
    assert model_plan["estimated_cost"] == 0.4518
    assert model_plan["currency"] == "USD"
    assert model_plan["budget"]["exceeded"] == {"value": False, "reasons": [], "evidence": []}

    assert blocked_response.status_code == 422
    blocked_payload = blocked_response.json()
    assert blocked_payload["detail"]["message"] == "benchmark budget exceeded"
    assert blocked_payload["detail"]["estimated"] == {
        "units": 210,
        "tokens": 225900,
        "cost": 0.4518,
        "currency": "USD",
    }
    assert blocked_payload["detail"]["limit"] == {"units": 100, "cost": 0.1, "currency": "USD"}
    blocked_budget = blocked_payload["detail"]["budget"]
    assert blocked_budget["stop_after_budget_units"] == 120
    assert blocked_budget["stop_after_predicted"] is True
    assert blocked_budget["exceeded"]["value"] is True
    assert blocked_budget["exceeded"]["reasons"] == [
        "estimated_units_exceed_limit_units",
        "estimated_cost_exceed_limit_cost",
    ]
    assert blocked_budget["exceeded"]["evidence"] == [
        {"metric": "estimated_units", "estimated": 210, "limit": 100, "delta": 110, "unit": "llm_call_unit"},
        {"metric": "estimated_cost", "estimated": 0.4518, "limit": 0.1, "delta": 0.3518, "unit": "USD"},
    ]
    assert blocked_payload["error"]["code"] == "benchmark_budget_exceeded"
    assert blocked_payload["error"]["diagnostics"][0]["kind"] == "budget_exceeded"
    assert blocked_payload["error"]["diagnostics"][0]["estimated_units"] == 210
    assert blocked_payload["error"]["diagnostics"][0]["limit_units"] == 100
    assert blocked_payload["error"]["diagnostics"][0]["estimated_cost"] == 0.4518
    assert blocked_payload["error"]["diagnostics"][0]["limit_cost"] == 0.1
    assert blocked_payload["error"]["diagnostics"][0]["evidence"] == blocked_budget["exceeded"]["evidence"]


def test_legacy_benchmark_queue_stays_ad_hoc_compatible(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        captured.update(batch_config)
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {"game_count": batch_config["game_count"]},
            "fairness": {"is_fair": True},
            "rankable": True,
            "rankable_reason": "ok",
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        response = client.post("/api/benchmark", json={"roles": ["seer"], "battle_games": 0, "max_days": 1})
        batch = response.json()
        listed_response = client.get("/api/evolution-runs")
        stored_batch = store.evolution_batches[batch["batch_id"]]

    assert response.status_code == 200
    assert batch["benchmark"] is None
    assert batch["target_type"] == "role_version"
    assert batch["config"] == {
        "roles": ["seer"],
        "battle_games": 0,
        "max_days": 1,
        "game_concurrency": 1,
    }
    assert captured["game_count"] == 0
    assert captured["max_days"] == 1
    assert "evaluation_set_id" not in captured
    assert "seed_set_id" not in captured
    assert "benchmark_id" not in captured
    assert stored_batch["benchmark"] is None
    listed = next(item for item in listed_response.json()["batches"] if item["batch_id"] == batch["batch_id"])
    assert listed["config"] == {
        "roles": ["seer"],
        "battle_games": 0,
        "max_days": 1,
        "game_concurrency": 1,
    }


def test_benchmark_queue_passes_langfuse_config_to_eval_launcher(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        captured.update(batch_config)
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {"game_count": batch_config["game_count"]},
            "fairness": {"is_fair": True},
            "rankable": True,
            "rankable_reason": "ok",
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        response = client.post(
            "/api/benchmark",
            json={
                "roles": ["seer"],
                "battle_games": 0,
                "max_days": 1,
                "langfuse_dataset_name": "dataset-a",
                "langfuse_experiment_name": "experiment-a",
                "langfuse_run_name": "run-a",
            },
        )
        batch = response.json()

    assert response.status_code == 200
    assert batch["config"]["langfuse_dataset_name"] == "dataset-a"
    assert batch["config"]["langfuse_experiment_name"] == "experiment-a"
    assert batch["config"]["langfuse_run_name"] == "run-a"
    assert captured["langfuse_dataset_name"] == "dataset-a"
    assert captured["langfuse_experiment_name"] == "experiment-a"
    assert captured["langfuse_run_name"] == "run-a"


def test_stopped_benchmark_is_not_overwritten_by_background_result(tmp_path: Path, monkeypatch) -> None:
    called = False

    async def fake_run_evaluation(*, batch_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {
            "batch_id": batch_config["batch_id"],
            "config": batch_config,
            "game_count": batch_config["game_count"],
            "completed": batch_config["game_count"],
            "errored": 0,
            "games": [],
            "score_summary": {"game_count": batch_config["game_count"]},
            "fairness": {"is_fair": True},
            "rankable": True,
        }

    monkeypatch.setattr(ui_backend_store, "run_evaluation", fake_run_evaluation)

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        request = BenchmarkRequest(
            roles=["seer"],
            battle_games=2,
            max_days=1,
        )
        batch = store.benchmark_service.queue_benchmark(request)
        batch["status"] = "failed"
        batch["stop_requested"] = True
        asyncio.run(store.benchmark_service.run_queued_benchmark(batch["batch_id"], request))

    assert called is False
    assert batch["status"] == "failed"
    assert batch["current_stage"] == "stopped"
    assert batch["progress"]["stage"] == "stopped"
    assert batch["diagnostics"][0]["kind"] == "benchmark_stopped"
    assert batch["error"] == "stopped"
    assert batch["result"] is None


def test_benchmark_stop_surfaces_progress_in_summary(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        batch = store.benchmark_service.queue_benchmark(
            BenchmarkRequest(
                roles=["seer"],
                battle_games=2,
                max_days=1,
            )
        )
        stop_response = client.post(f"/api/benchmark/batch/{batch['batch_id']}/stop")
        list_response = client.get("/api/evolution-runs")

    assert stop_response.status_code == 200
    stopped = stop_response.json()
    assert stopped["status"] == "failed"
    assert stopped["stop_requested"] is True
    assert stopped["cancelled"] is True
    assert stopped["failed"] is False
    assert stopped["current_stage"] == "stopped"
    assert stopped["progress"]["stage"] == "stopped"
    assert stopped["progress"]["percent"] == 0.0
    assert stopped["progress"]["completed_roles"] == 0
    assert stopped["progress"]["role_count"] == 1
    assert stopped["diagnostics"][0]["kind"] == "benchmark_stopped"

    listed = next(item for item in list_response.json()["batches"] if item["batch_id"] == batch["batch_id"])
    assert listed["status"] == "failed"
    assert listed["stop_requested"] is True
    assert listed["cancelled"] is True
    assert listed["failed"] is False
    assert listed["current_stage"] == "stopped"
    assert listed["progress"]["stage"] == "stopped"
    assert listed["diagnostics"][0]["kind"] == "benchmark_stopped"


def test_background_tasks_persist_skips_unchanged_state(
    tmp_path: Path,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    paths = PathConfig(root=tmp_path)
    store = ui_backend_store.BackendStore(paths=paths, model=FakeModel())

    batch = store.benchmark_service.queue_benchmark(
        BenchmarkRequest(
            roles=["seer"],
            battle_games=1,
            max_days=1,
        )
    )
    assert _fake_ui_pg_provider.db.background_upserts == 1
    assert _fake_ui_pg_provider.db.begin_writes == 2
    assert _fake_ui_pg_provider.db.commits == 2
    initial_closes = _fake_ui_pg_provider.db.closes
    assert batch["batch_id"] in _fake_ui_pg_provider.db.background_tasks

    store._persist_background_tasks()
    store._persist_background_tasks()
    assert _fake_ui_pg_provider.db.background_upserts == 1
    assert _fake_ui_pg_provider.db.begin_writes == 2
    assert _fake_ui_pg_provider.db.commits == 2
    assert _fake_ui_pg_provider.db.closes == initial_closes

    store._mark_benchmark_stage(
        batch,
        "evaluating",
        status="running",
        percent=0.5,
        role="seer",
        role_index=1,
        role_count=1,
        completed_roles=0,
    )
    store._persist_background_tasks()
    store._persist_background_tasks()
    assert _fake_ui_pg_provider.db.background_upserts == 2
    assert _fake_ui_pg_provider.db.begin_writes == 4
    assert _fake_ui_pg_provider.db.commits == 4
    assert _fake_ui_pg_provider.db.rollbacks == 0
    assert _fake_ui_pg_provider.db.closes == initial_closes + 2
    row = _fake_ui_pg_provider.db.background_tasks[batch["batch_id"]]
    payload = json.loads(row["payload"])
    assert payload["batch_id"] == batch["batch_id"]
    assert payload["progress"]["stage"] == "evaluating"


def test_background_task_loads_are_coalesced_with_force_refresh(
    tmp_path: Path,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UI_BACKGROUND_REFRESH_INTERVAL_SECONDS", "60")
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path), model=FakeModel())

    store.task_service.load_background_tasks()
    store.task_service.load_background_tasks()

    assert _fake_ui_pg_provider.db.background_reads == 1

    store.task_service._persistence.load_background_tasks(force=True)

    assert _fake_ui_pg_provider.db.background_reads == 2


def test_expired_background_task_refresh_does_not_block_requests(
    tmp_path: Path,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UI_BACKGROUND_REFRESH_INTERVAL_SECONDS", "60")
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path), model=FakeModel())
    persistence = store.task_service._persistence
    persistence.load_background_tasks()

    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_refresh() -> None:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)

    monkeypatch.setenv("UI_BACKGROUND_REFRESH_INTERVAL_SECONDS", "0")
    monkeypatch.setattr(persistence, "_refresh_background_tasks", slow_refresh)

    before = time.monotonic()
    persistence.load_background_tasks()
    elapsed = time.monotonic() - before

    assert elapsed < 0.2
    assert started.wait(timeout=1)
    persistence.load_background_tasks()
    assert calls == 1

    release.set()


def test_background_tasks_persist_is_thread_safe(
    tmp_path: Path,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    paths = PathConfig(root=tmp_path)
    store = ui_backend_store.BackendStore(paths=paths, model=FakeModel())
    store.evolution_batches["bench_concurrent"] = {
        "kind": "benchmark_batch",
        "batch_id": "bench_concurrent",
        "roles": ["seer"],
        "status": "running",
        "started_at": "2026-01-01T00:00:00+08:00",
    }
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(20):
                store._persist_background_tasks()
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert _fake_ui_pg_provider.db.background_upserts == 1
    row = _fake_ui_pg_provider.db.background_tasks["bench_concurrent"]
    assert json.loads(row["payload"])["batch_id"] == "bench_concurrent"


def test_background_tasks_restore_active_runs_as_interrupted(tmp_path: Path) -> None:
    paths = PathConfig(root=tmp_path)
    first_app = ui_backend_app.create_app(paths=paths, model=FakeModel())
    store = first_app.state.backend_store

    request = EvolutionStartRequest(
        roles=["seer", "witch"],
        training_games=0,
        battle_games=0,
        max_days=1,
    )
    active_batch = store.queue_evolution(request)
    active_run_id = active_batch["runs"][0]
    benchmark = store.benchmark_service.queue_benchmark(
        BenchmarkRequest(
            roles=["seer"],
            battle_games=0,
            max_days=1,
        )
    )
    completed_run_id = "evolve_seer_reviewing"
    store.evolution_runs[completed_run_id] = {
        "kind": "role_evolution_run",
        "run_id": completed_run_id,
        "role": "seer",
        "status": "reviewing",
        "last_heartbeat_at": "2026-01-01T00:00:00+08:00",
    }
    store._persist_background_tasks()

    restarted_app = ui_backend_app.create_app(paths=paths, model=FakeModel())
    restarted_store = restarted_app.state.backend_store
    active_run = restarted_store.evolution_runs[active_run_id]
    restarted_batch = restarted_store.evolution_batches[active_batch["batch_id"]]
    restarted_benchmark = restarted_store.evolution_batches[benchmark["batch_id"]]
    completed_run = restarted_store.evolution_runs[completed_run_id]

    assert active_run["status"] == "interrupted"
    assert active_run["interrupted_at"]
    assert active_run["last_heartbeat_at"]
    assert active_run["error"] == "interrupted by backend restart"
    assert restarted_batch["status"] == "interrupted"
    assert restarted_batch["interrupted_at"]
    assert restarted_benchmark["status"] == "interrupted"
    assert restarted_benchmark["interrupted"] is True
    assert restarted_benchmark["cancelled"] is False
    assert restarted_benchmark["failed"] is False
    assert restarted_benchmark["interrupted_at"]
    assert restarted_benchmark["current_stage"] == "interrupted"
    assert restarted_benchmark["progress"]["stage"] == "interrupted"
    assert restarted_benchmark["diagnostics"][0]["kind"] == "benchmark_interrupted"
    assert completed_run["status"] == "reviewing"
    assert "interrupted_at" not in completed_run

    with TestClient(restarted_app) as client:
        listed_response = client.get("/api/evolution-runs")

    assert listed_response.status_code == 200
    listed = listed_response.json()
    listed_run = next(item for item in listed["runs"] if item["run_id"] == active_run_id)
    listed_batch = next(item for item in listed["batches"] if item["batch_id"] == active_batch["batch_id"])
    listed_benchmark = next(item for item in listed["batches"] if item["batch_id"] == benchmark["batch_id"])
    assert listed_run["status"] == "interrupted"
    assert listed_run["last_heartbeat_at"]
    assert listed_run["interrupted_at"]
    assert listed_batch["status"] == "interrupted"
    assert listed_batch["last_heartbeat_at"]
    assert listed_batch["interrupted_at"]
    assert listed_benchmark["status"] == "interrupted"
    assert listed_benchmark["interrupted"] is True
    assert listed_benchmark["cancelled"] is False
    assert listed_benchmark["failed"] is False
    assert listed_benchmark["current_stage"] == "interrupted"
    assert listed_benchmark["progress"]["stage"] == "interrupted"
    assert listed_benchmark["diagnostics"][0]["kind"] == "benchmark_interrupted"


def test_background_tasks_restore_pg_task_rows(tmp_path: Path, _fake_ui_pg_provider: _UiFakeStorageProvider) -> None:
    paths = PathConfig(root=tmp_path)
    active_run_id = "evolve_seer_state_active"
    reviewing_run_id = "evolve_witch_state_reviewing"
    promoted_run_id = "evolve_guard_state_promoted"
    failed_run_id = "evolve_hunter_state_failed"

    def seed_task(entity_id: str, payload: dict[str, Any], updated_at: str) -> None:
        _fake_ui_pg_provider.db.background_tasks[entity_id] = {
            "entity_id": entity_id,
            "entity_kind": payload["kind"],
            "status": payload["status"],
            "payload": json.dumps(payload, ensure_ascii=False),
            "updated_at": updated_at,
        }

    seed_task(
        active_run_id,
        {
            "kind": "role_evolution_run",
            "run_id": active_run_id,
            "role": "seer",
            "parent_hash": "baseline_seer",
            "status": "training",
            "training_game_count": 3,
            "battle_game_count": 2,
            "training_games": [],
            "battle_games": [],
            "candidate_hash": "candidate_seer_state",
            "current_stage": "training",
            "last_heartbeat_at": "2026-01-01T01:00:00+08:00",
            "progress": {"stage": "training", "percent": 0.25, "completed_games": 1},
            "diagnostics": [
                {
                    "kind": "training_error",
                    "stage": "training.run_games",
                    "message": "scheduler down",
                }
            ],
            "proposals": [{"proposal_id": "p1", "target_file": "seer.md", "content": "Prefer hard claims."}],
            "diff": [{"filename": "seer.md", "action": "update"}],
            "errors": [],
        },
        "2026-01-01T01:00:00+08:00",
    )
    seed_task(
        reviewing_run_id,
        {
            "kind": "role_evolution_run",
            "run_id": reviewing_run_id,
            "role": "witch",
            "parent_hash": "baseline_witch",
            "status": "reviewing",
            "training_game_count": 1,
            "battle_game_count": 0,
            "candidate_hash": "candidate_witch_state",
            "battle_result": {"completed": 0},
            "last_heartbeat_at": "2026-01-01T02:00:00+08:00",
        },
        "2026-01-01T02:00:00+08:00",
    )
    seed_task(
        promoted_run_id,
        {
            "kind": "role_evolution_run",
            "run_id": promoted_run_id,
            "role": "guard",
            "parent_hash": "baseline_guard",
            "status": "promoted",
            "training_game_count": 0,
            "battle_game_count": 1,
            "candidate_hash": "candidate_guard_state",
            "last_heartbeat_at": "2026-01-01T03:00:00+08:00",
        },
        "2026-01-01T03:00:00+08:00",
    )
    seed_task(
        failed_run_id,
        {
            "kind": "role_evolution_run",
            "run_id": failed_run_id,
            "role": "hunter",
            "parent_hash": "baseline_hunter",
            "status": "failed",
            "training_game_count": 0,
            "battle_game_count": 0,
            "errors": ["boom"],
            "last_heartbeat_at": "2026-01-01T04:00:00+08:00",
        },
        "2026-01-01T04:00:00+08:00",
    )

    app = ui_backend_app.create_app(paths=paths, model=FakeModel())
    store = app.state.backend_store

    active_run = store.evolution_runs[active_run_id]
    reviewing_run = store.evolution_runs[reviewing_run_id]
    promoted_run = store.evolution_runs[promoted_run_id]
    failed_run = store.evolution_runs[failed_run_id]

    assert active_run["status"] == "interrupted"
    assert active_run["interrupted_at"]
    assert active_run["last_heartbeat_at"] == "2026-01-01T01:00:00+08:00"
    assert active_run["training_game_count"] == 3
    assert active_run["battle_game_count"] == 2
    assert active_run["training_games"] == []
    assert active_run["battle_games"] == []
    assert active_run["proposals"][0]["proposal_id"] == "p1"
    assert active_run["diff"][0]["filename"] == "seer.md"
    assert active_run["current_stage"] == "interrupted"
    assert active_run["progress"]["stage"] == "interrupted"
    assert active_run["progress"]["previous_stage"] == "training"
    assert active_run["progress"]["percent"] == 0.25
    assert active_run["progress"]["completed_games"] == 1
    assert active_run["diagnostics"][0]["kind"] == "training_error"
    assert active_run["diagnostics"][1]["kind"] == "evolution_interrupted"
    assert active_run["diagnostics"][1]["previous_stage"] == "training"

    assert reviewing_run["status"] == "reviewing"
    assert "interrupted_at" not in reviewing_run
    assert reviewing_run["last_heartbeat_at"] == "2026-01-01T02:00:00+08:00"
    assert reviewing_run["candidate_hash"] == "candidate_witch_state"
    assert promoted_run["status"] == "promoted"
    assert "interrupted_at" not in promoted_run
    assert failed_run["status"] == "failed"
    assert "interrupted_at" not in failed_run

    with TestClient(app) as client:
        listed_response = client.get("/api/evolution-runs")

    assert listed_response.status_code == 200
    listed = listed_response.json()["runs"]
    listed_active = next(item for item in listed if item["run_id"] == active_run_id)
    listed_reviewing = next(item for item in listed if item["run_id"] == reviewing_run_id)
    assert listed_active["status"] == "interrupted"
    assert listed_active["training_game_count"] == 3
    assert listed_active["battle_game_count"] == 2
    assert listed_active["proposal_count"] == 1
    assert listed_active["diff_count"] == 1
    assert listed_active["last_heartbeat_at"] == "2026-01-01T01:00:00+08:00"
    assert listed_active["interrupted_at"]
    assert listed_active["current_stage"] == "interrupted"
    assert listed_active["progress"]["stage"] == "interrupted"
    assert listed_active["progress"]["previous_stage"] == "training"
    assert listed_active["progress"]["percent"] == 0.25
    assert listed_active["diagnostics"][0]["stage"] == "training.run_games"
    assert listed_active["diagnostics"][1]["kind"] == "evolution_interrupted"
    assert listed_reviewing["status"] == "reviewing"
    assert listed_reviewing["candidate_hash"] == "candidate_witch_state"
    assert "interrupted_at" not in listed_reviewing


def test_background_tasks_restore_uses_pg_task_payload_only(
    tmp_path: Path,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    paths = PathConfig(root=tmp_path)
    run_id = "evolve_seer_index_merge"
    first_app = ui_backend_app.create_app(paths=paths, model=FakeModel())
    store = first_app.state.backend_store
    store.evolution_runs[run_id] = {
        "kind": "role_evolution_run",
        "run_id": run_id,
        "role": "seer",
        "status": "training",
        "started_at": "2026-01-01T00:00:00+08:00",
        "last_heartbeat_at": "2026-01-01T00:05:00+08:00",
        "config": {"roles": ["seer"], "training_games": 9, "battle_games": 9, "max_days": 1},
        "training_games": [],
        "battle_games": [],
    }
    store._persist_background_tasks()

    restarted_app = ui_backend_app.create_app(paths=paths, model=FakeModel())
    restarted_run = restarted_app.state.backend_store.evolution_runs[run_id]

    assert restarted_run["status"] == "interrupted"
    assert restarted_run["interrupted_at"]
    assert restarted_run["config"] == {
        "roles": ["seer"],
        "training_games": 9,
        "battle_games": 9,
        "max_days": 1,
    }
    assert restarted_run["last_heartbeat_at"] == "2026-01-01T00:05:00+08:00"
    assert "candidate_hash" not in restarted_run
    assert "battle_result" not in restarted_run


def test_evolution_sample_game_details_match_frontend_contract(tmp_path: Path) -> None:
    run_id = "evolve_seer_contract"
    game_id = "evolve_seer_contract_battle_001"
    game = {
        "game_id": game_id,
        "seed": 42,
        "winner": "villagers",
        "days": 1,
        "events": [
            {
                "index": 1,
                "event_type": "game_init",
                "day": 0,
                "phase": "setup",
                "message": "样本局开始",
            }
        ],
        "decisions": [
            {
                "decision_id": "d1",
                "action_type": "seer_check",
                "player_id": 3,
                "selected_target": 7,
                "public_text": "查验 7 号",
                "private_reasoning": "测试样本局详情",
            }
        ],
    }

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_runs[run_id] = {
            "kind": "role_evolution_run",
            "run_id": run_id,
            "role": "seer",
            "status": "reviewing",
            "training_games": [],
            "battle_games": [game],
        }
        baseline_response = client.get(f"/api/evolution-runs/{run_id}/games?phase=battle&side=baseline")
        candidate_response = client.get(f"/api/evolution-runs/{run_id}/games?phase=battle&side=candidate")
        archive_response = client.get(
            f"/api/evolution-runs/{run_id}/games/{game_id}/archive?phase=battle&side=candidate"
        )
        decisions_response = client.get(
            f"/api/evolution-runs/{run_id}/games/{game_id}/decisions?phase=battle&side=candidate"
        )
        events_response = client.get(
            f"/api/evolution-runs/{run_id}/games/{game_id}/events?phase=battle&side=candidate"
        )

    assert baseline_response.status_code == 200
    assert candidate_response.status_code == 200
    assert baseline_response.json()["games"][0]["game_id"] == game_id
    assert candidate_response.json()["games"][0]["game_id"] == game_id
    assert "events" not in baseline_response.json()["games"][0]
    assert "decisions" not in baseline_response.json()["games"][0]

    assert archive_response.status_code == 200
    archive = archive_response.json()
    assert archive["kind"] == "role_evolution_game_archive"
    assert archive["run_id"] == run_id
    assert archive["game_id"] == game_id
    assert archive["title"]
    assert archive["summary"]
    assert archive["highlights"] == ["样本局开始"]
    assert archive["decision_count"] == 1

    assert decisions_response.status_code == 200
    decision = decisions_response.json()["decisions"][0]
    assert decision["id"] == "d1"
    assert decision["action_type"] == "seer_check"
    assert decision["target_id"] == 7

    assert events_response.status_code == 200
    event = events_response.json()["events"][0]
    assert event["type"] == "game_init"
    assert event["sequence"] == 1


def test_evolution_sse_event_names_match_frontend_contract(tmp_path: Path) -> None:
    run_id = "evolve_seer_sse"
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_runs[run_id] = {
            "kind": "role_evolution_run",
            "run_id": run_id,
            "role": "seer",
            "status": "training",
        }
        progress_response = client.get(f"/api/evolution-runs/{run_id}/events")
        store.evolution_runs[run_id]["status"] = "completed"
        completed_response = client.get(f"/api/evolution-runs/{run_id}/events")

    assert progress_response.status_code == 200
    assert "event: progress" in progress_response.text
    assert "id: 1" in progress_response.text
    assert completed_response.status_code == 200
    assert "event: completed" in completed_response.text


async def test_sse_queue_helper_emits_ping_and_stops_on_terminal() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    frames = stream_queue_sse(
        queue,
        ping_payload=lambda: {"status": "running"},
        event_name=lambda item: str(item.get("event") or "message"),
        terminal=lambda _item, event_name: event_name == "done",
        timeout_seconds=0.001,
    )

    ping = await anext(frames)
    assert "event: ping" in ping
    assert '"status": "running"' in ping

    await queue.put({"id": 7, "event": "done", "payload": {"status": "completed"}})
    done = await anext(frames)
    assert "id: 7" in done
    assert "event: done" in done
    assert '"status": "completed"' in done

    try:
        await anext(frames)
    except StopAsyncIteration:
        pass
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("SSE queue helper did not stop after terminal event")


async def test_sse_queue_helper_skips_none_payloads_when_requested() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    frames = stream_queue_sse(
        queue,
        ping_payload=lambda: {"status": "running"},
        event_name=lambda item: str(item.get("event") or "message"),
        payload=lambda item: item.get("payload"),
        terminal=lambda _item, event_name: event_name == "done",
        timeout_seconds=0.001,
        skip_none_payload=True,
    )

    await queue.put({"id": 1, "event": "log", "payload": None})
    await queue.put({"id": 2, "event": "decision", "payload": {"ok": True}})
    frame = await anext(frames)
    assert "id: 2" in frame
    assert "event: decision" in frame
    assert '"ok": true' in frame
    assert "data: null" not in frame

    await queue.put({"id": 3, "event": "done", "payload": None})
    try:
        await anext(frames)
    except StopAsyncIteration:
        pass
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("SSE queue helper did not stop after skipped terminal event")


def test_game_live_sse_resumes_until_terminal_and_unsubscribes(tmp_path: Path) -> None:
    game_id = "live_sse_resume"
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        sink = BroadcastEventSink()
        sink.record_event({"sequence": 1, "event_type": "game_init", "message": "one"})
        sink.record_event({"sequence": 2, "event_type": "phase", "message": "two"})
        sink.close({"game_id": game_id, "status": "completed"})
        store.live_sessions[game_id] = SimpleNamespace(
            event_sink=sink,
            status="running",
            snapshot=lambda: {"game_id": game_id, "status": "completed"},
        )

        response = client.get(f"/api/games/{game_id}/events", headers={"Last-Event-ID": "1"})

    assert response.status_code == 200
    assert "id: 1" not in response.text
    assert "id: 2" in response.text
    assert "event: log" in response.text
    assert "id: 3" in response.text
    assert "event: done" in response.text
    assert not sink.subscribers


def _live_session_for_persistence_test(
    game_id: str,
    *,
    status: str = "running",
    event_sink: BroadcastEventSink | None = None,
) -> LiveGameSession:
    engine = SimpleNamespace(
        logger=SimpleNamespace(entries=[]),
        state=SimpleNamespace(
            players={},
            phase="night",
            day=1,
            sheriff_id=None,
            winner=None,
        ),
    )
    session = LiveGameSession(
        game_id=game_id,
        request=GameStartRequest(max_days=1),
        engine=engine,
        recorder=SimpleNamespace(records=[]),
        human=None,
        event_sink=event_sink or BroadcastEventSink(),
    )
    session.status = status
    if status in {"completed", "cancelled", "interrupted", "failed"}:
        session.finished_at = "2026-01-01T00:00:00+08:00"
    return session


def test_live_terminal_persistence_closes_once_and_skips_duplicate_write(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        session = _live_session_for_persistence_test("live_terminal_once", status="completed")
        persistence = _FakeGamePersistence()
        setattr(session, "persistence", persistence)
        snapshot = session.snapshot()

        store.persist_live_session(session, snapshot)
        store.persist_live_session(session, snapshot)

    assert session.files_written is True
    assert len(persistence.saved_results) == 1
    assert persistence.closed is True
    assert persistence.close_calls == 1


def test_live_terminal_persistence_failure_rolls_back_files_written_for_retry(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        session = _live_session_for_persistence_test("live_terminal_retry", status="completed")
        persistence = _FakeGamePersistence()
        setattr(session, "persistence", persistence)
        snapshot = session.snapshot()

        def fail_save(**_kwargs: Any) -> None:
            raise RuntimeError("pg unavailable")

        persistence.save_game_result = fail_save
        with pytest.raises(RuntimeError, match="pg unavailable"):
            store.persist_live_session(session, snapshot)

        assert session.files_written is False
        assert persistence.closed is False
        assert persistence.close_calls == 0

        def record_save(**kwargs: Any) -> None:
            persistence.saved_results.append(kwargs)

        persistence.save_game_result = record_save
        store.persist_live_session(session, snapshot)

    assert session.files_written is True
    assert len(persistence.saved_results) == 1
    assert persistence.closed is True
    assert persistence.close_calls == 1


def test_stop_live_game_cancels_closes_and_persists_terminal_session_without_task(tmp_path: Path) -> None:
    game_id = "live_stop_persist"
    sink = BroadcastEventSink()
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        session = _live_session_for_persistence_test(game_id, event_sink=sink)
        persistence = _FakeGamePersistence()
        setattr(session, "persistence", persistence)
        store.live_sessions[game_id] = session

        stopped = store.stop_game(game_id)

    assert stopped["status"] == "cancelled"
    assert stopped["stop_requested"] is True
    assert stopped["cancelled"] is True
    assert stopped["error"] == "cancelled"
    assert sink.closed is True
    assert session.files_written is True
    assert len(persistence.saved_results) == 1
    assert persistence.saved_results[0]["final_state"]["status"] == "cancelled"
    assert persistence.closed is True
    assert persistence.close_calls == 1


def test_live_watchdog_persistence_failure_rolls_back_and_cleans_session(tmp_path: Path) -> None:
    game_id = "live_watchdog_persist_failure"
    sink = BroadcastEventSink()
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        session = _live_session_for_persistence_test(game_id, event_sink=sink)
        session.last_heartbeat_at = "2026-01-01T00:00:00+08:00"
        persistence = _FakeGamePersistence()

        def fail_save(**_kwargs: Any) -> None:
            raise RuntimeError("pg down")

        persistence.save_game_result = fail_save
        setattr(session, "persistence", persistence)
        store.live_sessions[game_id] = session

        interrupted = store.check_live_game_watchdog(timeout_seconds=0.001)

    assert len(interrupted) == 1
    assert interrupted[0]["status"] == "interrupted"
    assert store.games[game_id]["status"] == "interrupted"
    assert game_id not in store.live_sessions
    assert sink.closed is True
    assert session.files_written is False
    assert persistence.closed is False
    assert persistence.close_calls == 0


def test_live_game_watchdog_marks_stale_sessions_interrupted(tmp_path: Path) -> None:
    class FakeEngine:
        def __init__(self) -> None:
            self.logger = SimpleNamespace(entries=[])
            self.state = SimpleNamespace(
                players={},
                phase="night",
                day=1,
                sheriff_id=None,
                winner=None,
            )

    game_id = "live_watchdog_stale"
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        sink = BroadcastEventSink()
        session = LiveGameSession(
            game_id=game_id,
            request=GameStartRequest(max_days=1),
            engine=FakeEngine(),
            recorder=SimpleNamespace(records=[]),
            human=None,
            event_sink=sink,
        )
        session.last_heartbeat_at = "2026-01-01T00:00:00+08:00"
        store.live_sessions[game_id] = session

        interrupted = store.check_live_game_watchdog(timeout_seconds=0.001)
        response = client.get(f"/api/games/{game_id}")
        history_response = client.get("/api/games?limit=10")
        events_response = client.get(f"/api/games/{game_id}/events")

    assert len(interrupted) == 1
    payload = response.json()
    assert payload["status"] == "interrupted"
    assert payload["interrupted"] is True
    assert payload["interrupted_at"]
    assert payload["last_heartbeat_at"] == "2026-01-01T00:00:00+08:00"
    assert payload["diagnostics"][0]["kind"] == "live_game_interrupted"
    assert payload["diagnostics"][0]["last_heartbeat_at"] == "2026-01-01T00:00:00+08:00"

    history = history_response.json()
    assert history["counts"]["normal"] == 1
    assert history["games"][0]["game_id"] == game_id
    assert history["games"][0]["status"] == "interrupted"

    assert "event: done" in events_response.text
    assert '"status": "interrupted"' in events_response.text


def test_live_game_watchdog_waits_for_pending_human_timeout(tmp_path: Path) -> None:
    from datetime import timedelta

    from app.util.time import beijing_now

    class FakeEngine:
        def __init__(self) -> None:
            self.logger = SimpleNamespace(entries=[])
            self.state = SimpleNamespace(
                players={},
                phase="exile_vote",
                day=1,
                sheriff_id=None,
                winner=None,
            )

    game_id = "live_watchdog_human_pending"
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        session = LiveGameSession(
            game_id=game_id,
            request=GameStartRequest(max_days=1, human_player_id=1),
            engine=FakeEngine(),
            recorder=SimpleNamespace(records=[]),
            human=SimpleNamespace(is_waiting=True, timeout_seconds=300.0, current_request=None),
            event_sink=BroadcastEventSink(),
        )
        session.last_heartbeat_at = (beijing_now() - timedelta(seconds=10)).isoformat()
        store.live_sessions[game_id] = session

        interrupted = store.check_live_game_watchdog(timeout_seconds=0.001)

    assert interrupted == []
    assert store.live_sessions[game_id] is session
    assert session.status == "running"
    assert session.interrupted is False


async def test_human_player_submit_from_thread_wakes_waiting_loop() -> None:
    from engine.models import ActionRequest, ActionResponse, ActionType, Observation, Phase, Role
    from engine.players import HumanPlayer

    human = HumanPlayer(1, timeout_seconds=2)
    request = ActionRequest(
        player_id=1,
        action_type=ActionType.EXILE_VOTE,
        phase=Phase.EXILE_VOTE,
        observation=Observation(
            player_id=1,
            self_role=Role.VILLAGER,
            phase=Phase.EXILE_VOTE,
            day=1,
            alive_players=(1, 2),
            dead_players=(),
            sheriff_id=None,
            visible_events=(),
        ),
        candidates=(2,),
    )
    task = asyncio.create_task(human.act(request))
    for _ in range(100):
        if human.is_waiting:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("human player did not enter waiting state")

    submitted: list[bool] = []
    submitter = threading.Thread(
        target=lambda: submitted.append(
            human.submit(ActionResponse(ActionType.EXILE_VOTE, target=2, text="thread submit"))
        )
    )
    submitter.start()
    submitter.join(timeout=1)

    response = await asyncio.wait_for(task, timeout=1)

    assert submitted == [True]
    assert response.target == 2
    assert response.text == "thread submit"


async def test_live_human_invalid_submission_is_not_recorded_until_engine_accepts() -> None:
    from app.lib.store import AgentDecisionRecorder
    from engine.config import GameConfig
    from engine.engine import GameEngine
    from engine.models import ActionResponse, ActionType, Phase, Role
    from engine.players import HumanPlayer, ScriptedAgent
    from ui.backend.schemas import HumanActionRequest

    roles = {1: Role.VILLAGER, 2: Role.WEREWOLF, 3: Role.SEER}
    human = HumanPlayer(1, timeout_seconds=2)
    recorder = AgentDecisionRecorder()
    engine = GameEngine(
        roles,
        {1: human, 2: ScriptedAgent(), 3: ScriptedAgent()},
        config=GameConfig(name="human_recording_test", role_counts=Counter(roles.values())),
    )
    engine.state.day = 1
    engine.state.phase = Phase.EXILE_VOTE
    session = LiveGameSession(
        game_id="human_recording_test",
        request=GameStartRequest(max_days=1, human_player_id=1),
        engine=engine,
        recorder=recorder,
        human=human,
        event_sink=BroadcastEventSink(),
    )

    async def _wait_for_retry(retry_count: int) -> None:
        for _ in range(100):
            current = human.current_request
            if human.is_waiting and current is not None and current.retry_count == retry_count:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"human request retry {retry_count} was not reached")

    ask_task = asyncio.create_task(
        engine._ask(
            1,
            ActionType.EXILE_VOTE,
            candidates=(2, 3),
            validator=lambda res: res.target in (2, 3),
            default=ActionResponse(ActionType.EXILE_VOTE),
        )
    )
    await _wait_for_retry(0)

    assert session.submit(HumanActionRequest(action_type="exile_vote", target=99, text="bad")) is True
    await _wait_for_retry(1)
    assert recorder.records == []

    assert session.submit(HumanActionRequest(action_type="exile_vote", target=2, text="good")) is True
    response = await asyncio.wait_for(ask_task, timeout=2)

    assert response.target == 2
    assert [record.selected_target for record in recorder.records] == [2]
    assert recorder.records[0].public_text == "good"
    assert [event.target for event in engine.logger.entries if event.type == "invalid_response"] == [99]


def test_evolution_sse_replays_task_event_log(tmp_path: Path) -> None:
    run_id = "evolve_seer_replay"
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_runs[run_id] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": run_id,
            "role": "seer",
            "status": "queued",
            "progress": {"stage": "queued", "percent": 0.0, "updated_at": "2026-01-01T00:00:00+08:00"},
            "diagnostics": [],
        }
        store._persist_background_tasks()

        store.evolution_runs[run_id]["status"] = "training"
        store.evolution_runs[run_id]["progress"] = {
            "stage": "training",
            "percent": 0.25,
            "updated_at": "2026-01-01T00:00:01+08:00",
        }
        store._touch_background_task(store.evolution_runs[run_id])
        store._persist_background_tasks()

        store.evolution_runs[run_id]["status"] = "completed"
        store.evolution_runs[run_id]["progress"] = {
            "stage": "completed",
            "percent": 1.0,
            "updated_at": "2026-01-01T00:00:02+08:00",
        }
        store._touch_background_task(store.evolution_runs[run_id])
        store._persist_background_tasks()

        full_response = client.get(f"/api/evolution-runs/{run_id}/events")
        resumed_response = client.get(f"/api/evolution-runs/{run_id}/events", headers={"Last-Event-ID": "2"})

    assert full_response.status_code == 200
    assert "id: 1" in full_response.text
    assert "id: 2" in full_response.text
    assert "id: 3" in full_response.text
    assert "event: progress" in full_response.text
    assert "event: completed" in full_response.text

    assert resumed_response.status_code == 200
    assert "id: 1" not in resumed_response.text
    assert "id: 2" not in resumed_response.text
    assert "id: 3" in resumed_response.text
    assert "event: completed" in resumed_response.text


def test_evolution_sse_streams_task_events_until_terminal(tmp_path: Path) -> None:
    run_id = "evolve_seer_live_sse"
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_runs[run_id] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": run_id,
            "role": "seer",
            "status": "training",
            "progress": {"stage": "training", "percent": 0.25, "updated_at": "2026-01-01T00:00:01+08:00"},
            "diagnostics": [],
        }
        store._persist_background_tasks()

        def publish_terminal() -> None:
            time.sleep(0.05)
            run = store.evolution_runs[run_id]
            run["status"] = "completed"
            run["progress"] = {"stage": "completed", "percent": 1.0, "updated_at": "2026-01-01T00:00:02+08:00"}
            store._touch_background_task(run)
            store._persist_background_tasks()

        publisher = threading.Thread(target=publish_terminal)
        publisher.start()
        with client.stream("GET", f"/api/evolution-runs/{run_id}/events", headers={"Last-Event-ID": "1"}) as response:
            text = response.read().decode("utf-8")
        publisher.join(timeout=2)

    assert response.status_code == 200
    assert "id: 1" not in text
    assert "id: 2" in text
    assert "event: completed" in text
    assert '"status": "completed"' in text
    assert not publisher.is_alive()
    assert store.task_event_log.subscriber_count(run_id) == 0


def test_benchmark_sse_replays_task_event_log(tmp_path: Path) -> None:
    batch_id = "bench_replay"
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_batches[batch_id] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": batch_id,
            "roles": ["seer"],
            "status": "running",
            "progress": {
                "stage": "queued",
                "percent": 0.0,
                "updated_at": "2026-01-01T00:00:00+08:00",
            },
            "diagnostics": [],
        }
        store._persist_background_tasks()

        batch = store.evolution_batches[batch_id]
        store._mark_benchmark_stage(
            batch,
            "evaluating",
            status="running",
            percent=0.5,
            role="seer",
            role_index=1,
            role_count=1,
            completed_roles=0,
        )
        store._persist_background_tasks()

        batch["status"] = "completed"
        store._mark_benchmark_stage(
            batch,
            "completed",
            status="completed",
            percent=1.0,
            role_count=1,
            completed_roles=1,
        )
        store._persist_background_tasks()

        full_response = client.get(f"/api/benchmark/batch/{batch_id}/events")
        resumed_response = client.get(f"/api/benchmark/batch/{batch_id}/events?lastEventId=2")
        missing_response = client.get("/api/benchmark/batch/missing_bench/events")

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "batch not found"

    assert full_response.status_code == 200
    assert "id: 1" in full_response.text
    assert "id: 2" in full_response.text
    assert "id: 3" in full_response.text
    assert "event: progress" in full_response.text
    assert "event: completed" in full_response.text
    assert '"batch_id": "bench_replay"' in full_response.text

    assert resumed_response.status_code == 200
    assert "id: 1" not in resumed_response.text
    assert "id: 2" not in resumed_response.text
    assert "id: 3" in resumed_response.text
    assert "event: completed" in resumed_response.text


def test_benchmark_sse_streams_task_events_until_terminal(tmp_path: Path) -> None:
    batch_id = "bench_live_sse"
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_batches[batch_id] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": batch_id,
            "roles": ["seer"],
            "status": "running",
            "progress": {
                "stage": "evaluating",
                "percent": 0.25,
                "updated_at": "2026-01-01T00:00:01+08:00",
            },
            "diagnostics": [],
        }
        store._persist_background_tasks()

        def publish_terminal() -> None:
            time.sleep(0.05)
            batch = store.evolution_batches[batch_id]
            batch["status"] = "completed"
            store._mark_benchmark_stage(
                batch,
                "completed",
                status="completed",
                percent=1.0,
                role_count=1,
                completed_roles=1,
            )
            store._persist_background_tasks()

        publisher = threading.Thread(target=publish_terminal)
        publisher.start()
        with client.stream("GET", f"/api/benchmark/batch/{batch_id}/events", headers={"Last-Event-ID": "1"}) as response:
            text = response.read().decode("utf-8")
        publisher.join(timeout=2)

    assert response.status_code == 200
    assert "id: 1" not in text
    assert "id: 2" in text
    assert "event: completed" in text
    assert '"status": "completed"' in text
    assert not publisher.is_alive()
    assert store.task_event_log.subscriber_count(batch_id) == 0


def test_task_event_log_appends_and_compacts_pg_backlog() -> None:
    db = _UiMemoryDatabase()
    log = TaskEventLog(
        connection_factory=lambda: _UiMemoryConnection(db),
        max_backlog=3,
        compact_every=0,
    )

    for index in range(5):
        log.publish(
            {
                "kind": "role_evolution_run",
                "run_id": "append_compact_run",
                "status": f"stage_{index}",
                "progress": {"step": index},
            }
        )

    assert len(db.task_events) == 5
    assert db.begin_writes == 5
    assert db.commits == 5
    assert db.closes == 5
    assert [item["id"] for item in log.replay("append_compact_run")] == [3, 4, 5]

    log.compact()
    assert sorted(db.task_events) == [3, 4, 5]
    assert db.begin_writes == 6
    assert db.commits == 6
    assert db.rollbacks == 0
    assert db.closes == 6

    loaded = TaskEventLog(
        connection_factory=lambda: _UiMemoryConnection(db),
        max_backlog=3,
        compact_every=0,
    )
    loaded.load()
    assert [item["id"] for item in loaded.replay("append_compact_run")] == [3, 4, 5]


def test_task_event_log_loads_pg_rows_and_continues_ids() -> None:
    db = _UiMemoryDatabase()
    db.task_events[1] = {
        "id": 1,
        "entity_id": "pg_replay",
        "entity_kind": "role_evolution_run",
        "event": "progress",
        "status": "training",
        "payload": json.dumps({"run_id": "pg_replay", "status": "training"}),
        "created_at": "2026-01-01T00:00:00+08:00",
    }
    db.task_events[3] = {
        "id": 3,
        "entity_id": "pg_replay",
        "entity_kind": "role_evolution_run",
        "event": "completed",
        "status": "completed",
        "payload": {"run_id": "pg_replay", "status": "completed"},
        "created_at": "2026-01-01T00:00:02+08:00",
    }

    log = TaskEventLog(
        connection_factory=lambda: _UiMemoryConnection(db),
        max_backlog=10,
        compact_every=0,
    )
    log.load()

    assert [item["id"] for item in log.replay("pg_replay")] == [1, 3]
    log.publish({"kind": "role_evolution_run", "run_id": "pg_replay", "status": "reviewing"})
    assert [item["id"] for item in log.replay("pg_replay")] == [1, 3, 4]
    assert 4 in db.task_events


def test_game_history_pagination_filters_and_sse_resume(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.games.update(
            {
                "ui_a": {
                    "game_id": "ui_a",
                    "status": "completed",
                    "log_time": "2026-01-01T00:00:01+08:00",
                    "players": [],
                    "events": [],
                    "decisions": [],
                },
                "ui_b": {
                    "game_id": "ui_b",
                    "status": "completed",
                    "log_time": "2026-01-01T00:00:02+08:00",
                    "players": [],
                    "events": [],
                    "decisions": [],
                },
                "ui_c": {
                    "game_id": "ui_c",
                    "status": "cancelled",
                    "log_time": "2026-01-01T00:00:03+08:00",
                    "players": [],
                    "events": [],
                    "decisions": [],
                },
                "ui_sse": {
                    "game_id": "ui_sse",
                    "status": "completed",
                    "players": [],
                    "events": [
                        {"event_type": "game_init", "message": "one"},
                        {"event_type": "phase", "message": "two"},
                    ],
                    "decisions": [{"decision_id": "d1", "action_type": "speak"}],
                },
            }
        )

        legacy_response = client.get("/api/games")
        page_response = client.get("/api/games?source=normal&status=completed&limit=1&offset=1")
        full_events_response = client.get("/api/games/ui_sse/events")
        resumed_response = client.get("/api/games/ui_sse/events", headers={"Last-Event-ID": "2"})

    assert legacy_response.status_code == 200
    legacy_payload = legacy_response.json()
    assert "pagination" not in legacy_payload
    assert "counts" not in legacy_payload
    assert "facets" not in legacy_payload

    assert page_response.status_code == 200
    payload = page_response.json()
    assert payload["pagination"] == {"total": 3, "offset": 1, "limit": 1, "returned": 1, "has_more": True}
    assert payload["counts"] == {"all": 4, "normal": 4, "benchmark": 0, "evolution": 0}
    assert payload["facets"]["source"] == payload["counts"]
    assert payload["facets"]["status"] == {"cancelled": 1, "completed": 3}
    assert len(payload["games"]) == 1
    assert payload["games"][0]["status"] == "completed"

    assert full_events_response.status_code == 200
    assert "id: 1" in full_events_response.text
    assert "id: 4" in full_events_response.text
    assert "event: done" in full_events_response.text

    assert resumed_response.status_code == 200
    assert "id: 1" not in resumed_response.text
    assert "id: 2" not in resumed_response.text
    assert "id: 3" in resumed_response.text
    assert "id: 4" in resumed_response.text
    assert "event: decision" in resumed_response.text
    assert "event: done" in resumed_response.text


def test_game_history_counts_facets_and_index_cache(tmp_path: Path, monkeypatch) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.games.update(
            {
                "ui_normal_a": _history_snapshot(
                    "ui_normal_a",
                    status="completed",
                    log_time="2026-01-01T00:00:01+08:00",
                ),
                "ui_normal_b": _history_snapshot(
                    "ui_normal_b",
                    status="cancelled",
                    log_time="2026-01-01T00:00:02+08:00",
                ),
                "bench_game_a": {
                    **_history_snapshot(
                        "bench_game_a",
                        status="completed",
                        log_time="2026-01-01T00:00:03+08:00",
                    ),
                    "log_source": "benchmark",
                    "source_run_id": "bench_counts",
                },
                "evo_game_a": {
                    **_history_snapshot(
                        "evo_game_a",
                        status="completed",
                        log_time="2026-01-01T00:00:04+08:00",
                    ),
                    "log_source": "evolution",
                    "source_run_id": "evolve_counts",
                    "source_phase": "training",
                },
                "evo_game_b": {
                    **_history_snapshot(
                        "evo_game_b",
                        status="failed",
                        log_time="2026-01-01T00:00:05+08:00",
                    ),
                    "log_source": "evolution",
                    "source_run_id": "evolve_counts",
                    "source_phase": "battle",
                },
            }
        )

        calls = 0
        original_build = store._build_game_history_rows

        def counted_build() -> list[dict[str, Any]]:
            nonlocal calls
            calls += 1
            return original_build()

        monkeypatch.setattr(store, "_build_game_history_rows", counted_build)

        normal_response = client.get("/api/games?source=normal&limit=1&offset=0")
        second_page_response = client.get("/api/games?source=evolution&status=completed&limit=1&offset=0")
        calls_after_cached_page = calls
        store.games["ui_normal_c"] = _history_snapshot(
            "ui_normal_c",
            status="completed",
            log_time="2026-01-01T00:00:06+08:00",
        )
        rebuilt_response = client.get("/api/games?source=normal&limit=10&offset=0")

    assert normal_response.status_code == 200
    normal_payload = normal_response.json()
    assert normal_payload["pagination"] == {"total": 2, "offset": 0, "limit": 1, "returned": 1, "has_more": True}
    assert normal_payload["counts"] == {"all": 5, "normal": 2, "benchmark": 1, "evolution": 2}
    assert normal_payload["facets"]["source"] == normal_payload["counts"]
    assert normal_payload["facets"]["status"] == {"cancelled": 1, "completed": 3, "failed": 1}
    assert {game["log_source"] for game in normal_payload["games"]} == {"normal"}

    assert second_page_response.status_code == 200
    second_page = second_page_response.json()
    assert second_page["pagination"] == {"total": 1, "offset": 0, "limit": 1, "returned": 1, "has_more": False}
    assert second_page["counts"] == {"all": 5, "normal": 2, "benchmark": 1, "evolution": 2}
    assert calls_after_cached_page == 1

    assert rebuilt_response.status_code == 200
    rebuilt = rebuilt_response.json()
    assert rebuilt["pagination"] == {"total": 3, "offset": 0, "limit": 10, "returned": 3, "has_more": False}
    assert rebuilt["counts"] == {"all": 6, "normal": 3, "benchmark": 1, "evolution": 2}
    assert calls == 2


def test_delete_normal_game_removes_history_detail_and_invalidates_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.games.update(
            {
                "ui_delete_a": _history_snapshot(
                    "ui_delete_a",
                    status="completed",
                    log_time="2026-01-01T00:00:01+08:00",
                ),
                "ui_delete_b": _history_snapshot(
                    "ui_delete_b",
                    status="completed",
                    log_time="2026-01-01T00:00:02+08:00",
                ),
                "bench_delete_a": {
                    **_history_snapshot(
                        "bench_delete_a",
                        status="completed",
                        log_time="2026-01-01T00:00:03+08:00",
                    ),
                    "log_source": "benchmark",
                },
            }
        )

        calls = 0
        original_build = store._build_game_history_rows

        def counted_build() -> list[dict[str, Any]]:
            nonlocal calls
            calls += 1
            return original_build()

        monkeypatch.setattr(store, "_build_game_history_rows", counted_build)

        before_response = client.get("/api/games?source=normal&limit=1&offset=0")
        delete_response = client.delete("/api/games/ui_delete_a")
        detail_response = client.get("/api/games/ui_delete_a")
        after_response = client.get("/api/games?source=normal&limit=10&offset=0")

    assert before_response.status_code == 200
    assert before_response.json()["pagination"] == {
        "total": 2,
        "offset": 0,
        "limit": 1,
        "returned": 1,
        "has_more": True,
    }

    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "game_id": "ui_delete_a",
        "deleted": True,
        "log_source": "normal",
        "force": False,
    }
    assert detail_response.status_code == 404

    after_payload = after_response.json()
    assert after_payload["pagination"] == {
        "total": 1,
        "offset": 0,
        "limit": 10,
        "returned": 1,
        "has_more": False,
    }
    assert after_payload["counts"] == {"all": 2, "normal": 1, "benchmark": 1, "evolution": 0}
    assert [game["game_id"] for game in after_payload["games"]] == ["ui_delete_b"]
    assert calls == 2
    assert _fake_ui_pg_provider.db.game_deletes == [
        ("decision_reviews", "game_id", "ui_delete_a"),
        ("counterfactuals", "game_id", "ui_delete_a"),
        ("llm_judgments", "game_id", "ui_delete_a"),
        ("evaluations", "game_id", "ui_delete_a"),
        ("reports", "game_id", "ui_delete_a"),
        ("decisions", "game_id", "ui_delete_a"),
        ("game_events", "game_id", "ui_delete_a"),
        ("players", "game_id", "ui_delete_a"),
        ("games", "id", "ui_delete_a"),
    ]
    assert _fake_ui_pg_provider.db.deletes == 9


def test_delete_game_missing_and_non_normal_force_policy(
    tmp_path: Path,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.games["bench_delete_policy"] = {
            **_history_snapshot(
                "bench_delete_policy",
                status="completed",
                log_time="2026-01-01T00:00:01+08:00",
            ),
            "log_source": "benchmark",
        }

        missing_response = client.delete("/api/games/missing_delete_game")
        conflict_response = client.delete("/api/games/bench_delete_policy")
        force_response = client.delete("/api/games/bench_delete_policy?force=true")
        detail_response = client.get("/api/games/bench_delete_policy")

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "game not found"

    assert conflict_response.status_code == 409
    assert conflict_response.json()["detail"] == "benchmark game requires force delete"

    assert force_response.status_code == 200
    assert force_response.json() == {
        "game_id": "bench_delete_policy",
        "deleted": True,
        "log_source": "benchmark",
        "force": True,
    }
    assert detail_response.status_code == 404
    assert [entry[2] for entry in _fake_ui_pg_provider.db.game_deletes] == ["bench_delete_policy"] * 9


def test_delete_active_live_game_cancels_and_removes_session(
    tmp_path: Path,
    _fake_ui_pg_provider: _UiFakeStorageProvider,
) -> None:
    class _LiveForDelete:
        status = "running"
        task = None

        def __init__(self) -> None:
            self.cancelled = False
            self.persistence = SimpleNamespace(closed=False, close=lambda: setattr(self.persistence, "closed", True))

        def snapshot(self) -> dict[str, Any]:
            return {
                "game_id": "ui_live_delete",
                "status": "running",
                "log_source": "normal",
                "players": [],
                "events": [],
                "decisions": [],
            }

        def cancel(self) -> None:
            self.cancelled = True
            self.status = "cancelled"

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        live = _LiveForDelete()
        store.live_sessions["ui_live_delete"] = live
        store.games["ui_live_delete"] = live.snapshot()

        response = client.delete("/api/games/ui_live_delete")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert live.cancelled is True
    assert live.persistence.closed is True
    assert "ui_live_delete" not in store.live_sessions
    assert "ui_live_delete" not in store.games
    assert [entry[2] for entry in _fake_ui_pg_provider.db.game_deletes] == ["ui_live_delete"] * 9


def test_evolution_history_and_games_pagination_filters(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_runs["evolve_done"] = {
            "kind": "role_evolution_run",
            "run_id": "evolve_done",
            "role": "seer",
            "status": "reviewing",
            "last_heartbeat_at": "2026-01-01T00:00:02+08:00",
            "training_games": [
                {"game_id": "g1", "status": "completed"},
                {"game_id": "g2", "status": "failed"},
                {"game_id": "g3", "status": "completed"},
            ],
            "battle_games": [],
        }
        store.evolution_batches["bench_done"] = {
            "kind": "benchmark_batch",
            "batch_id": "bench_done",
            "roles": ["seer"],
            "status": "completed",
            "last_heartbeat_at": "2026-01-01T00:00:03+08:00",
        }
        store.evolution_batches["evo_batch_done"] = {
            "kind": "role_evolution_batch",
            "batch_id": "evo_batch_done",
            "roles": ["seer"],
            "status": "completed",
            "last_heartbeat_at": "2026-01-01T00:00:04+08:00",
        }

        legacy_response = client.get("/api/evolution-runs")
        benchmark_response = client.get("/api/evolution-runs?source=benchmark&status=completed&limit=1")
        evolution_response = client.get("/api/evolution-runs?source=evolution&status=completed&limit=10")
        games_response = client.get("/api/evolution-runs/evolve_done/games?limit=1&offset=1&status=completed")
        sse_resume_response = client.get("/api/evolution-runs/evolve_done/events", headers={"Last-Event-ID": "1"})

    assert legacy_response.status_code == 200
    assert "pagination" not in legacy_response.json()

    benchmark = benchmark_response.json()
    assert benchmark["pagination"]["total"] == 1
    assert benchmark["runs"] == []
    assert benchmark["batches"][0]["batch_id"] == "bench_done"
    assert benchmark["batches"][0]["source"] == "benchmark"

    evolution = evolution_response.json()
    assert evolution["pagination"]["total"] == 1
    assert evolution["runs"] == []
    assert evolution["batches"][0]["batch_id"] == "evo_batch_done"
    assert evolution["batches"][0]["source"] == "evolution"

    games = games_response.json()
    assert games["pagination"] == {"total": 2, "offset": 1, "limit": 1, "returned": 1, "has_more": False}
    assert games["games"][0]["game_id"] == "g3"

    assert sse_resume_response.status_code == 200
    assert sse_resume_response.text == ""


def test_evolution_stop_action_uses_cancellation_contract(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_runs["evolve_stop"] = {
            "kind": "role_evolution_run",
            "run_id": "evolve_stop",
            "role": "seer",
            "status": "training",
            "started_at": "2026-01-01T00:00:00+08:00",
        }
        response = client.post("/api/evolution-runs/evolve_stop/actions", json={"action": "stop"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["stop_requested"] is True
    assert payload["cancelled"] is True
    assert payload["failed"] is False
    assert payload["error"] == "stopped"


def test_evolution_actions_persist_promote_and_reject_to_registry(tmp_path: Path) -> None:
    promote_run_id = "evolve_seer_promote"
    reject_run_id = "evolve_seer_reject"
    proposal = {
        "proposal_id": "p1",
        "target_file": "seer.md",
        "section": "Strategy",
        "content": "Prefer checking players who drive split votes.",
        "rationale": "Observed in training games.",
        "status": "accepted",
    }

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {"baseline.md": "# Seer baseline"},
            version_id="baseline_seer",
            source="fixture",
            set_as_baseline=True,
            expected_current=None,
        )
        store.evolution_runs[promote_run_id] = {
            "kind": "role_evolution_run",
            "run_id": promote_run_id,
            "role": "seer",
            "status": "reviewing",
            "parent_hash": "baseline_seer",
            "candidate_hash": "candidate_seer_promote",
            "proposals": [proposal],
            "diff": [],
            "battle_result": {"completed": 1},
        }
        promote_response = client.post(f"/api/evolution-runs/{promote_run_id}/actions", json={"action": "promote"})
        versions_response = client.get("/api/roles/seer/versions")
        detail_response = client.get("/api/roles/seer/versions/candidate_seer_promote")

        store.evolution_runs[reject_run_id] = {
            "kind": "role_evolution_run",
            "run_id": reject_run_id,
            "role": "seer",
            "status": "reviewing",
            "proposals": [{**proposal, "status": "proposed"}],
            "battle_result": {"completed": 1},
        }
        reject_response = client.post(f"/api/evolution-runs/{reject_run_id}/actions", json={"action": "reject"})
        rejected = store.registry.load_rejected("seer")

    assert promote_response.status_code == 200
    promoted = promote_response.json()
    assert promoted["status"] == "promoted"
    assert promoted["published_version_id"] == "candidate_seer_promote"
    assert promoted["published_release_stage"] == "shadow"
    assert promoted["release_stage"] == "shadow"
    assert promoted["promoted_version_id"] is None
    versions = versions_response.json()["versions"]
    published = next(item for item in versions if item["version_id"] == "candidate_seer_promote")
    assert published["is_baseline"] is False
    assert published["status"] == "shadow"
    assert published["release_stage"] == "shadow"
    assert published["source"] == "evolution"
    assert published["provenance"]["manual_action"] == "promote"
    assert published["provenance"]["release_stage"] == "shadow"
    detail = detail_response.json()
    assert detail["files"][0]["path"] == "evolution.md"
    assert "Prefer checking players" in detail["files"][0]["content"]

    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert rejected[-1]["proposal_id"] == "p1"


def test_evolution_action_promote_requires_explicit_proposal_review(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_runs["evolve_unreviewed_promote"] = {
            "kind": "role_evolution_run",
            "run_id": "evolve_unreviewed_promote",
            "role": "seer",
            "status": "reviewing",
            "candidate_hash": "candidate_unreviewed_promote",
            "proposals": [
                {
                    "proposal_id": "p1",
                    "target_file": "seer.md",
                    "section": "Strategy",
                    "content": "Prefer checking players who drive split votes.",
                    "rationale": "Observed in training games.",
                }
            ],
            "diff": [],
            "battle_result": {"completed": 1},
        }

        response = client.post(
            "/api/evolution-runs/evolve_unreviewed_promote/actions",
            json={"action": "promote"},
        )

    payload = _assert_domain_response(
        response,
        code="evolution_proposal_review_required",
        kind="evolution_proposal_review_required",
    )
    assert "accepted or applied proposal" in payload["detail"]


def test_evolution_action_promote_rejects_untrusted_parent_versions(tmp_path: Path) -> None:
    proposal = {
        "proposal_id": "p1",
        "target_file": "seer.md",
        "section": "Strategy",
        "content": "Prefer checking players who drive split votes.",
        "rationale": "Observed in training games.",
        "status": "accepted",
    }

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        _publish_seer_version(store.registry, "seer_shadow_parent", release_stage="shadow", body="shadow parent")
        store.evolution_runs["evolve_shadow_parent"] = {
            "kind": "role_evolution_run",
            "run_id": "evolve_shadow_parent",
            "role": "seer",
            "status": "reviewing",
            "parent_hash": "seer_shadow_parent",
            "candidate_hash": "candidate_shadow_parent",
            "proposals": [proposal],
            "diff": [],
            "battle_result": {"completed": 1},
        }
        shadow_response = client.post(
            "/api/evolution-runs/evolve_shadow_parent/actions",
            json={"action": "promote"},
        )

        store.evolution_runs["evolve_missing_parent"] = {
            "kind": "role_evolution_run",
            "run_id": "evolve_missing_parent",
            "role": "seer",
            "status": "reviewing",
            "parent_hash": "missing_parent",
            "candidate_hash": "candidate_missing_parent",
            "proposals": [proposal],
            "diff": [],
            "battle_result": {"completed": 1},
        }
        missing_response = client.post(
            "/api/evolution-runs/evolve_missing_parent/actions",
            json={"action": "promote"},
        )

    _assert_domain_response(
        shadow_response,
        code="evolution_parent_release_stage_not_allowed",
        release_stage="shadow",
        kind="evolution_parent_release_stage_not_allowed",
    )
    _assert_domain_response(
        missing_response,
        code="evolution_parent_version_not_found",
        kind="evolution_parent_version_not_found",
    )


def test_evolution_actions_baseline_promote_gate_sets_registry_baseline(tmp_path: Path) -> None:
    proposal = {
        "proposal_id": "p1",
        "target_file": "seer.md",
        "section": "Strategy",
        "content": "Prefer checking players who drive split votes.",
        "rationale": "Observed in training games.",
    }
    release_gate = {
        "schema_version": "promotion_gate_v2",
        "decision": "baseline_promote",
        "reasons": ["all gates passed"],
    }
    trust_completeness = {
        "schema_version": "trust_bundle_completeness_v1",
        "complete": True,
        "score": 1.0,
        "missing": [],
    }
    trust_bundle = {
        "schema_version": "trust_bundle_v1",
        "trust_bundle_id": "trust_bundle_evolve_seer_baseline_promote",
        "bundle_hash": "a" * 64,
        "run_id": "evolve_seer_baseline_promote",
        "role": "seer",
        "baseline_version": "baseline_seer",
        "candidate_version": "candidate_seer_baseline_promote",
        "gate_report_id": "gate_evolve_seer_baseline_promote",
        "training_game_ids": ["train_1"],
        "proposal_ids": ["p1"],
        "completeness": trust_completeness,
    }

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {"baseline.md": "# Seer baseline"},
            version_id="baseline_seer",
            source="fixture",
            set_as_baseline=True,
            expected_current=None,
        )
        store.evolution_runs["evolve_seer_baseline_promote"] = {
            "kind": "role_evolution_run",
            "run_id": "evolve_seer_baseline_promote",
            "role": "seer",
            "status": "reviewing",
            "parent_hash": "baseline_seer",
            "candidate_hash": "candidate_seer_baseline_promote",
            "proposals": [proposal],
            "diff": [],
            "applied_proposal_ids": ["p1"],
            "proposal_review": {"applied_proposal_ids": ["p1"]},
            "release_decision": "baseline_promote",
            "release_gate": release_gate,
            "gate_report": {
                "gate_report_id": "gate_evolve_seer_baseline_promote",
                "release_gate": release_gate,
                "trust_bundle_completeness": trust_completeness,
            },
            "trust_bundle": trust_bundle,
            "battle_result": {
                "completed": 3,
                "candidate_win_rate": 1.0,
                "release_decision": "baseline_promote",
                "release_gate": release_gate,
            },
        }

        promote_response = client.post(
            "/api/evolution-runs/evolve_seer_baseline_promote/actions",
            json={"action": "promote"},
        )
        versions_response = client.get("/api/roles/seer/versions")
        baseline_version = store.registry.get_baseline("seer")

    assert promote_response.status_code == 200
    promoted = promote_response.json()
    assert promoted["status"] == "promoted"
    assert promoted["published_version_id"] == "candidate_seer_baseline_promote"
    assert promoted["published_release_stage"] == "baseline"
    assert promoted["promoted_version_id"] == "candidate_seer_baseline_promote"
    assert baseline_version == "candidate_seer_baseline_promote"

    versions = {item["version_id"]: item for item in versions_response.json()["versions"]}
    assert versions["baseline_seer"]["is_baseline"] is False
    published = versions["candidate_seer_baseline_promote"]
    assert published["is_baseline"] is True
    assert published["release_stage"] == "baseline"
    assert published["provenance"]["release_stage"] == "baseline"
    assert published["provenance"]["release_decision"] == "baseline_promote"
    assert published["provenance"]["trust_bundle_id"] == "trust_bundle_evolve_seer_baseline_promote"
    assert published["provenance"]["gate_report_id"] == "gate_evolve_seer_baseline_promote"


def test_evolution_actions_baseline_promote_requires_complete_trust_bundle(tmp_path: Path) -> None:
    proposal = {
        "proposal_id": "p1",
        "target_file": "seer.md",
        "section": "Strategy",
        "content": "Prefer checking players who drive split votes.",
        "rationale": "Observed in training games.",
    }
    release_gate = {
        "schema_version": "promotion_gate_v2",
        "decision": "baseline_promote",
        "reasons": ["all gates passed"],
    }

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {"baseline.md": "# Seer baseline"},
            version_id="baseline_seer",
            source="fixture",
            set_as_baseline=True,
            expected_current=None,
        )
        store.evolution_runs["evolve_baseline_missing_trust"] = {
            "kind": "role_evolution_run",
            "run_id": "evolve_baseline_missing_trust",
            "role": "seer",
            "status": "reviewing",
            "parent_hash": "baseline_seer",
            "candidate_hash": "candidate_missing_trust",
            "proposals": [proposal],
            "applied_proposal_ids": ["p1"],
            "proposal_review": {"applied_proposal_ids": ["p1"]},
            "release_decision": "baseline_promote",
            "release_gate": release_gate,
            "gate_report": {"release_gate": release_gate},
            "battle_result": {"release_decision": "baseline_promote", "release_gate": release_gate},
        }
        missing_response = client.post(
            "/api/evolution-runs/evolve_baseline_missing_trust/actions",
            json={"action": "promote"},
        )

        store.evolution_runs["evolve_baseline_incomplete_trust"] = {
            "kind": "role_evolution_run",
            "run_id": "evolve_baseline_incomplete_trust",
            "role": "seer",
            "status": "reviewing",
            "parent_hash": "baseline_seer",
            "candidate_hash": "candidate_incomplete_trust",
            "proposals": [proposal],
            "applied_proposal_ids": ["p1"],
            "proposal_review": {"applied_proposal_ids": ["p1"]},
            "release_decision": "baseline_promote",
            "trust_bundle": {
                "schema_version": "trust_bundle_v1",
                "trust_bundle_id": "trust_bundle_incomplete",
                "run_id": "evolve_baseline_incomplete_trust",
                "role": "seer",
                "baseline_version": "baseline_seer",
                "candidate_version": "candidate_incomplete_trust",
                "completeness": {
                    "schema_version": "trust_bundle_completeness_v1",
                    "complete": False,
                    "score": 0.8,
                    "missing": ["evidence", "accepted_proposal_ids", "bundle_hash", "release_gate"],
                },
            },
            "battle_result": {"release_decision": "baseline_promote"},
        }
        incomplete_response = client.post(
            "/api/evolution-runs/evolve_baseline_incomplete_trust/actions",
            json={"action": "promote"},
        )
        baseline_version = store.registry.get_baseline("seer")

    _assert_domain_response(
        missing_response,
        code="evolution_trust_bundle_required",
        release_stage="baseline",
        kind="evolution_trust_bundle_required",
    )
    incomplete_payload = _assert_domain_response(
        incomplete_response,
        code="evolution_trust_bundle_incomplete",
        release_stage="baseline",
        kind="evolution_trust_bundle_incomplete",
    )
    missing_items = set(incomplete_payload["error"]["diagnostics"][0]["missing"])
    assert missing_items == {"training_evidence", "proposals", "trust_bundle", "gate_report"}
    assert "training_evidence" in incomplete_payload["detail"]
    assert "proposals" in incomplete_payload["detail"]
    assert "evidence" not in missing_items
    assert "accepted_proposal_ids" not in missing_items
    assert baseline_version == "baseline_seer"


def test_ui_backend_does_not_import_agent_package() -> None:
    backend_dir = Path(__file__).resolve().parents[1] / "ui" / "backend"
    pattern = re.compile(r"^\s*(?:from\s+agent(?:\.|\s+import)|import\s+agent(?:\.|\s|$))", re.MULTILINE)

    offenders = []
    for path in backend_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(str(path.relative_to(backend_dir.parents[1])))

    assert offenders == []


def test_role_leaderboard_reads_persisted_scores(tmp_path: Path) -> None:
    """The leaderboard endpoint surfaces benchmark_leaderboard scores, not zeros."""
    paths = PathConfig(root=tmp_path)
    registry = FakeVersionRegistry(tmp_path)
    vid = registry.publish_skills(
        "seer",
        {
            "vote.md": (
                "---\n"
                "name: s\n"
                "role: seer\n"
                "applicable_actions:\n"
                "  - seer_check\n"
                "status: active\n"
                "evolution:\n"
                "  enabled: true\n"
                "  allowed_actions:\n"
                "    - append_rule\n"
                "---\n"
                "body\n"
            )
        },
        source="test",
        set_as_baseline=True,
        expected_current=None,
    )

    app = ui_backend_app.create_app(paths=paths, model=FakeModel())
    store = app.state.backend_store
    store._registry = registry
    def fake_leaderboard_scores_for_role(role: str, *, evaluation_set_id: str | None = None) -> dict[str, dict[str, Any]]:
        assert evaluation_set_id is None
        return {
            vid: {
                "target_version_id": vid,
                "avg_role_score": 7.3,
                "target_side_win_rate": 0.6,
                "fallback_rate": 0.0,
                "rankable": True,
                "games_played": 5,
            }
        } if role == "seer" else {}

    store.leaderboard_scores_for_role = fake_leaderboard_scores_for_role
    with TestClient(app) as client:
        resp = client.get("/api/roles/seer/leaderboard")

    assert resp.status_code == 200
    entries = resp.json()["entries"]
    entry = next(e for e in entries if e["target_version_id"] == vid)
    assert entry["target_role_role_weighted_score"] == 7.3
    assert entry["target_side_win_rate"] == 0.6
    assert entry["rankable"] is True
    assert entry["game_count"] == 5
    assert entry["is_baseline"] is True
    assert entry["sample_size"] == 5
    assert entry["paired_sample_size"] == 0
    assert entry["win_rate_ci"]["level"] == 0.95
    assert entry["ci_low"] == entry["win_rate_ci"]["low"]
    assert entry["ci_high"] == entry["win_rate_ci"]["high"]
    assert entry["standard_error"] > 0
    assert entry["paired_delta"] is None
    assert entry["significant"] is False
    assert entry["significance_label"] == "待比较"
    assert entry["warnings"] == ["low_sample"]


def test_role_leaderboard_excludes_shadow_and_canary_versions(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        baseline = _publish_seer_version(store.registry, "seer_base_v1", baseline=True, body="baseline")
        shadow = _publish_seer_version(store.registry, "seer_shadow_v1", release_stage="shadow", body="shadow")
        canary = _publish_seer_version(store.registry, "seer_canary_v1", release_stage="canary", body="canary")

        def fake_leaderboard_scores_for_role(
            role: str,
            *,
            evaluation_set_id: str | None = None,
        ) -> dict[str, dict[str, Any]]:
            del evaluation_set_id
            assert role == "seer"
            return {
                baseline: {"avg_role_score": 7.0, "target_side_win_rate": 0.6, "rankable": True, "games_played": 8},
                shadow: {"avg_role_score": 9.9, "target_side_win_rate": 1.0, "rankable": True, "games_played": 8},
                canary: {"avg_role_score": 9.8, "target_side_win_rate": 1.0, "rankable": True, "games_played": 8},
            }

        store.leaderboard_scores_for_role = fake_leaderboard_scores_for_role
        response = client.get("/api/roles/seer/leaderboard")

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [entry["target_version_id"] for entry in entries] == [baseline]
    assert entries[0]["release_stage"] == "baseline"


def test_role_leaderboard_excludes_experimental_stage_from_provenance(tmp_path: Path) -> None:
    paths = PathConfig(root=tmp_path)
    registry = FakeVersionRegistry(tmp_path)
    baseline = _publish_seer_version(registry, "seer_base_v1", baseline=True, body="baseline")
    shadow = _publish_seer_version(registry, "seer_shadow_v1", release_stage="draft", body="shadow")
    registry._versions["seer"][shadow]["summary"].release_stage = ""
    registry._versions["seer"][shadow]["summary"].provenance = {"release_stage": "shadow"}

    app = ui_backend_app.create_app(paths=paths, model=FakeModel())
    store = app.state.backend_store
    store._registry = registry
    store.leaderboard_scores_for_role = lambda role, evaluation_set_id=None: {
        baseline: {"avg_role_score": 6.0, "rankable": True, "games_played": 4},
        shadow: {"avg_role_score": 9.9, "rankable": True, "games_played": 4},
    }

    with TestClient(app) as client:
        response = client.get("/api/roles/seer/leaderboard")

    assert response.status_code == 200
    assert [entry["target_version_id"] for entry in response.json()["entries"]] == [baseline]


def test_roles_overview_batches_versions_and_leaderboards(tmp_path: Path) -> None:
    paths = PathConfig(root=tmp_path)
    registry = FakeVersionRegistry(tmp_path)
    vid = registry.publish_skills(
        "seer",
        {
            "vote.md": (
                "---\n"
                "name: s\n"
                "role: seer\n"
                "applicable_actions:\n"
                "  - seer_check\n"
                "status: active\n"
                "evolution:\n"
                "  enabled: true\n"
                "  allowed_actions:\n"
                "    - append_rule\n"
                "---\n"
                "body\n"
            )
        },
        source="test",
        set_as_baseline=True,
        expected_current=None,
    )

    app = ui_backend_app.create_app(paths=paths, model=FakeModel())
    store = app.state.backend_store
    store._registry = registry
    calls: list[tuple[list[str], str | None]] = []

    def fake_leaderboard_scores_for_roles(
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        calls.append((list(roles), evaluation_set_id))
        return {
            "seer": {
                vid: {
                    "target_version_id": vid,
                    "avg_role_score": 8.1,
                    "target_side_win_rate": 0.7,
                    "fallback_rate": 0.1,
                    "rankable": True,
                    "games_played": 9,
                }
            }
        }

    store.leaderboard_scores_for_roles = fake_leaderboard_scores_for_roles
    with TestClient(app) as client:
        resp = client.get("/api/roles/overview?evaluation_set_id=suite@v1")
        cached_resp = client.get("/api/roles/overview?evaluation_set_id=suite@v1")

    assert resp.status_code == 200
    assert cached_resp.status_code == 200
    payload = resp.json()
    assert payload["kind"] == "role_overview"
    assert "seer" in payload["roles"]
    assert payload["versions"]["seer"][0]["version_id"] == vid
    entry = next(item for item in payload["leaderboards"]["seer"]["entries"] if item["target_version_id"] == vid)
    assert entry["target_role_role_weighted_score"] == 8.1
    assert entry["target_side_win_rate"] == 0.7
    assert entry["game_count"] == 9
    assert entry["sample_size"] == 9
    assert entry["paired_sample_size"] == 0
    assert entry["win_rate_ci"]["level"] == 0.95
    assert entry["standard_error"] > 0
    assert entry["significance_label"] == "待比较"
    assert entry["warnings"] == ["low_sample"]
    assert calls and calls[0][1] == "suite@v1"
    assert "seer" in calls[0][0]
    assert len(calls) == 1


def test_role_service_uses_minimal_context_protocol(tmp_path: Path) -> None:
    registry = FakeVersionRegistry(tmp_path)
    vid = registry.publish_skills(
        "seer",
        {"vote.md": "# Seer baseline"},
        source="test",
        set_as_baseline=True,
        expected_current=None,
    )
    context = _RoleServiceContextFake(
        registry,
        {
            "seer": {
                vid: {
                    "target_version_id": vid,
                    "avg_role_score": 8.1,
                    "target_side_win_rate": 0.7,
                    "fallback_rate": 0.1,
                    "rankable": True,
                    "games_played": 9,
                }
            }
        },
    )

    service = RoleService(context)
    payload = service.overview_payload(evaluation_set_id="suite@v1")
    cached_payload = service.overview_payload(evaluation_set_id="suite@v1")

    assert cached_payload is payload
    assert payload["kind"] == "role_overview"
    assert "seer" in payload["roles"]
    assert payload["versions"]["seer"][0]["version_id"] == vid
    entry = next(item for item in payload["leaderboards"]["seer"]["entries"] if item["target_version_id"] == vid)
    assert entry["target_role_role_weighted_score"] == 8.1
    assert entry["target_side_win_rate"] == 0.7
    assert context.score_calls and context.score_calls[0][1] == "suite@v1"
    assert "seer" in context.score_calls[0][0]
    assert len(context.score_calls) == 1

    service.clear_overview_cache()

    assert context.invalidations == 1
    assert context._role_overview_cache == {}


def test_roles_overview_cache_invalidates_after_rollback(tmp_path: Path) -> None:
    paths = PathConfig(root=tmp_path)
    registry = FakeVersionRegistry(tmp_path)
    first_vid = registry.publish_skills(
        "seer",
        {"vote.md": "# First seer baseline"},
        source="test",
        set_as_baseline=True,
        expected_current=None,
    )
    second_vid = registry.publish_skills(
        "seer",
        {"vote.md": "# Second seer baseline"},
        source="test",
        set_as_baseline=False,
    )

    app = ui_backend_app.create_app(paths=paths, model=FakeModel())
    store = app.state.backend_store
    store._registry = registry
    calls: list[list[str]] = []

    def fake_leaderboard_scores_for_roles(
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        del evaluation_set_id
        calls.append(list(roles))
        return {}

    store.leaderboard_scores_for_roles = fake_leaderboard_scores_for_roles
    with TestClient(app) as client:
        initial = client.get("/api/roles/overview")
        rollback = client.post(f"/api/roles/seer/rollback/{second_vid}")
        refreshed = client.get("/api/roles/overview")

    assert initial.status_code == 200
    assert rollback.status_code == 200
    assert refreshed.status_code == 200
    assert len(calls) == 2
    initial_versions = {item["version_id"]: item for item in initial.json()["versions"]["seer"]}
    refreshed_versions = {item["version_id"]: item for item in refreshed.json()["versions"]["seer"]}
    assert initial_versions[first_vid]["is_baseline"] is True
    assert initial_versions[second_vid]["is_baseline"] is False
    assert refreshed_versions[first_vid]["is_baseline"] is False
    assert refreshed_versions[second_vid]["is_baseline"] is True


def test_role_rollback_rejects_shadow_and_canary_versions(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        baseline = _publish_seer_version(store.registry, "seer_base_v1", baseline=True, body="baseline")
        shadow = _publish_seer_version(store.registry, "seer_shadow_v1", release_stage="shadow", body="shadow")
        canary = _publish_seer_version(store.registry, "seer_canary_v1", release_stage="canary", body="canary")

        shadow_response = client.post(f"/api/roles/seer/rollback/{shadow}")
        canary_response = client.post(f"/api/roles/seer/rollback/{canary}")
        baseline_after_rejects = store.registry.get_baseline("seer")

    _assert_domain_response(
        shadow_response,
        code="role_version_release_stage_not_allowed",
        release_stage="shadow",
        kind="role_rollback_version_not_allowed",
    )
    _assert_domain_response(
        canary_response,
        code="role_version_release_stage_not_allowed",
        release_stage="canary",
        kind="role_rollback_version_not_allowed",
    )
    assert baseline_after_rejects == baseline


def test_role_rollback_drill_restores_previous_baseline_after_staged_candidates(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
        first = _publish_seer_version(store.registry, "seer_base_a", baseline=True, body="baseline a")
        _publish_seer_version(store.registry, "seer_shadow_v1", release_stage="shadow", body="shadow")
        _publish_seer_version(store.registry, "seer_canary_v1", release_stage="canary", body="canary")
        second = _publish_seer_version(
            store.registry,
            "seer_base_b",
            baseline=True,
            expected_current=first,
            body="baseline b",
        )

        before = client.get("/api/roles/overview")
        rollback = client.post(f"/api/roles/seer/rollback/{first}")
        after = client.get("/api/roles/overview")
        baseline_after_rollback = store.registry.get_baseline("seer")

    assert before.status_code == 200
    assert rollback.status_code == 200
    assert rollback.json()["new_baseline"] == first
    assert after.status_code == 200
    assert baseline_after_rollback == first
    before_versions = {item["version_id"]: item for item in before.json()["versions"]["seer"]}
    after_versions = {item["version_id"]: item for item in after.json()["versions"]["seer"]}
    assert before_versions[first]["is_baseline"] is False
    assert before_versions[second]["is_baseline"] is True
    assert after_versions[first]["is_baseline"] is True
    assert after_versions[second]["is_baseline"] is False
