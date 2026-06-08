"""Focused contract tests for the app-native UI FastAPI backend."""

from __future__ import annotations

import json
import re
import asyncio
import ast
import time
import threading
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import PathConfig
from storage.public_events import public_events_only
import ui.backend.app as ui_backend_app
from ui.backend.live_game import BroadcastEventSink, LiveGameSession
from ui.backend.schemas import BenchmarkRequest, EvolutionStartRequest, GameStartRequest
from ui.backend.sse import stream_queue_sse
from ui.backend.game_serializers import _dead_players, _player_view_snapshot, _sheriff_from_events, _vote_tally
import ui.backend.store as ui_backend_store
from ui.backend.task_events import TaskEventLog

LIVE_GAME_TIMEOUT_SECONDS = 30.0
LIVE_GAME_POLL_SECONDS = 0.1


@dataclass
class _FakeVersionSummary:
    version_id: str
    role: str
    source: str = ""
    created_at: str = "2026-01-01T00:00:00+08:00"
    is_baseline: bool = False
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "role": self.role,
            "source": self.source,
            "created_at": self.created_at,
            "is_baseline": self.is_baseline,
            "status": self.status,
        }


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
    ) -> str:
        del parent_id, run_id, proposal_ids
        role_versions = self._versions.setdefault(role, {})
        version_id = version_id or f"{role}_v{len(role_versions) + 1}"
        role_versions[version_id] = {
            "summary": _FakeVersionSummary(
                version_id=version_id,
                role=role,
                source=source,
                is_baseline=False,
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
        self._versions[role][version_id]["summary"].is_baseline = True
        self._versions[role][version_id]["summary"].status = "promoted"
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
        self.instances.append(self)

    def create_event_sink(self) -> _FakePersistenceSink:
        return self.event_sink

    def create_decision_sink(self) -> _FakePersistenceSink:
        return self.decision_sink

    def save_game_result(self, **kwargs: Any) -> None:
        self.saved_results.append(kwargs)

    def close(self) -> None:
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
        self.background_upserts = 0
        self.event_upserts = 0
        self.deletes = 0
        self.lock = threading.Lock()


class _UiMemoryConnection:
    def __init__(self, db: _UiMemoryDatabase) -> None:
        self._db = db
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql: str, parameters: Any = ()) -> _UiCursor:
        if self.closed:
            raise RuntimeError("connection closed")
        text = " ".join(sql.split())
        params = tuple(parameters)

        if text.startswith("CREATE TABLE") or text.startswith("CREATE INDEX"):
            return _UiCursor()

        if text == "SELECT 1 AS ok":
            return _UiCursor([{"ok": 1}])

        if text.startswith("SELECT version_num FROM public.alembic_version"):
            return _UiCursor([{"version_num": "20260608_0001"}])

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
                rows = sorted(
                    (dict(row) for row in self._db.background_tasks.values()),
                    key=lambda row: (str(row.get("updated_at") or ""), str(row.get("entity_id") or "")),
                )
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

        if text.startswith("SELECT * FROM games WHERE id = ?"):
            return _UiCursor()

        if "FROM games g LEFT JOIN" in text:
            return _UiCursor()

        if text.startswith("SELECT COUNT(*) AS total") and " FROM " in text:
            row: dict[str, Any] = {"total": 0}
            for alias in re.findall(r"\bAS\s+(max_[A-Za-z0-9_]+)", text):
                row[alias] = None
            return _UiCursor([row])

        if "FROM benchmark_leaderboard" in text:
            return _UiCursor()

        raise AssertionError(f"unexpected SQL: {text}")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True

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

    provider = _UiFakeStorageProvider()
    provider_from_env = lambda *, paths=None: provider
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


def test_health_and_roles_contract(tmp_path: Path) -> None:
    with _test_client(tmp_path) as client:
        health_response = client.get("/api/health")
        roles_response = client.get("/api/roles")

    assert health_response.status_code == 200
    health = health_response.json()
    assert health["ok"] is True
    assert health["mode"] == "api"
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

    assert roles_response.status_code == 200
    roles = roles_response.json()["roles"]
    assert "villager" in roles
    assert "werewolf" in roles
    assert "seer" in roles


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
    assert len(read_back["decisions"]) == len(completed["decisions"])

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


def test_evolution_start_normalizes_legacy_manual_defaults(
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
        "training_games": 5,
        "battle_games": 4,
        "auto_promote": True,
    }
    assert detail_response.status_code == 200
    assert detail_response.json()["config"] == {
        "roles": ["seer"],
        "training_games": 5,
        "battle_games": 4,
        "max_days": 5,
        "auto_promote": True,
    }


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
    assert listed["config"] == {"roles": ["seer"], "battle_games": 3, "max_days": 1}
    assert listed["result"]["game_count"] == 3


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
        batch = store.queue_benchmark(request)
        batch["status"] = "failed"
        batch["stop_requested"] = True
        asyncio.run(store.run_queued_benchmark(batch["batch_id"], request))

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
        batch = store.queue_benchmark(
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

    batch = store.queue_benchmark(
        BenchmarkRequest(
            roles=["seer"],
            battle_games=1,
            max_days=1,
        )
    )
    assert _fake_ui_pg_provider.db.background_upserts == 1
    assert batch["batch_id"] in _fake_ui_pg_provider.db.background_tasks

    store._persist_background_tasks()
    store._persist_background_tasks()
    assert _fake_ui_pg_provider.db.background_upserts == 1

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
    row = _fake_ui_pg_provider.db.background_tasks[batch["batch_id"]]
    payload = json.loads(row["payload"])
    assert payload["batch_id"] == batch["batch_id"]
    assert payload["progress"]["stage"] == "evaluating"


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
    benchmark = store.queue_benchmark(
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
    assert [item["id"] for item in log.replay("append_compact_run")] == [3, 4, 5]

    log.compact()
    assert sorted(db.task_events) == [3, 4, 5]

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
    }

    with _test_client(tmp_path) as client:
        store = client.app.state.backend_store
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
            "proposals": [proposal],
            "battle_result": {"completed": 1},
        }
        reject_response = client.post(f"/api/evolution-runs/{reject_run_id}/actions", json={"action": "reject"})
        rejected = store.registry.load_rejected("seer")

    assert promote_response.status_code == 200
    promoted = promote_response.json()
    assert promoted["status"] == "promoted"
    assert promoted["published_version_id"] == "candidate_seer_promote"
    versions = versions_response.json()["versions"]
    published = next(item for item in versions if item["version_id"] == "candidate_seer_promote")
    assert published["is_baseline"] is True
    assert published["source"] == "evolution"
    detail = detail_response.json()
    assert detail["files"][0]["path"] == "evolution.md"
    assert "Prefer checking players" in detail["files"][0]["content"]

    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert rejected[-1]["proposal_id"] == "p1"


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
    store.leaderboard_scores_for_role = lambda role: {
        vid: {
            "target_version_id": vid,
            "avg_role_score": 7.3,
            "target_side_win_rate": 0.6,
            "fallback_rate": 0.0,
            "rankable": True,
            "games_played": 5,
        }
    } if role == "seer" else {}
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
