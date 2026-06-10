from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import PathConfig
import ui.backend.store as ui_backend_store
from ui.backend.schemas import EvolutionStartRequest
from ui.backend.services.benchmark_service import BenchmarkService
from ui.backend.services.benchmark_snapshot_service import BenchmarkSnapshotService
from ui.backend.services.evolution_read_service import EvolutionReadService
from ui.backend.services.evolution_run_service import EvolutionRunService
from ui.backend.services.evolution_service import EvolutionService
from ui.backend.services.task_persistence_service import TaskPersistenceService


def test_game_read_gateway_facades_delegate_to_cached_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[Any] = []

    class FakeGameReadGateway:
        def __init__(self, store: Any) -> None:
            self.store = store
            self.lock = object()
            self.calls: list[tuple[Any, ...]] = []
            instances.append(self)

        def open_connection(self) -> str:
            self.calls.append(("open_connection",))
            return "wolf-connection"

        def read_repository(self, read: Any) -> Any:
            self.calls.append(("read_repository", read))
            return read("wolf-repository")

        def load_game_detail(self, game_id: str) -> dict[str, Any]:
            self.calls.append(("load_game_detail", game_id))
            return {"method": "load_game_detail", "game_id": game_id}

        def load_game_history_shell(self, game_id: str) -> dict[str, Any]:
            self.calls.append(("load_game_history_shell", game_id))
            return {"method": "load_game_history_shell", "game_id": game_id}

        def load_game_phase_detail(self, game_id: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("load_game_phase_detail", game_id, kwargs))
            return {"method": "load_game_phase_detail", "game_id": game_id, "kwargs": kwargs}

        def load_game_flow_data(self, game_id: str) -> dict[str, Any]:
            self.calls.append(("load_game_flow_data", game_id))
            return {"method": "load_game_flow_data", "game_id": game_id}

        def load_game_replay(self, game_id: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("load_game_replay", game_id, kwargs))
            return {"method": "load_game_replay", "game_id": game_id, "kwargs": kwargs}

        def load_game_review(self, game_id: str) -> dict[str, Any]:
            self.calls.append(("load_game_review", game_id))
            return {"method": "load_game_review", "game_id": game_id}

        def list_history_rows(self) -> list[dict[str, Any]]:
            self.calls.append(("list_history_rows",))
            return [{"game_id": "from-pg"}]

        def close(self) -> None:
            self.calls.append(("close",))

    monkeypatch.setattr(ui_backend_store, "GameReadGateway", FakeGameReadGateway)
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path))

    gateway = store._game_read_gateway()

    assert store._game_read_gateway() is gateway
    assert instances == [gateway]
    assert gateway.store is store
    assert store._wolf_read_lock() is gateway.lock
    assert store._open_wolf_read_connection() == "wolf-connection"

    def read(repository: str) -> str:
        return f"read:{repository}"

    assert store._read_wolf_repository(read) == "read:wolf-repository"
    assert store._load_game_from_pg("game-1") == {"method": "load_game_detail", "game_id": "game-1"}
    assert store._load_game_history_shell_from_pg("game-2") == {
        "method": "load_game_history_shell",
        "game_id": "game-2",
    }
    assert store._load_game_phase_detail_from_pg(
        "game-3",
        day=2,
        phase="night",
        log_offset=3,
        log_limit=4,
        decision_offset=5,
        decision_limit=6,
    ) == {
        "method": "load_game_phase_detail",
        "game_id": "game-3",
        "kwargs": {
            "day": 2,
            "phase": "night",
            "log_offset": 3,
            "log_limit": 4,
            "decision_offset": 5,
            "decision_limit": 6,
        },
    }
    assert store._load_game_flow_data_from_pg("game-4") == {"method": "load_game_flow_data", "game_id": "game-4"}
    assert store._load_game_replay_from_pg("game-5", cursor=7, limit=8) == {
        "method": "load_game_replay",
        "game_id": "game-5",
        "kwargs": {"cursor": 7, "limit": 8},
    }
    assert store._load_game_review_from_pg("game-6") == {"method": "load_game_review", "game_id": "game-6"}
    assert store._list_games_from_pg() == [{"game_id": "from-pg"}]

    store._close_wolf_read_connection()

    assert gateway.calls == [
        ("open_connection",),
        ("read_repository", read),
        ("load_game_detail", "game-1"),
        ("load_game_history_shell", "game-2"),
        (
            "load_game_phase_detail",
            "game-3",
            {
                "day": 2,
                "phase": "night",
                "log_offset": 3,
                "log_limit": 4,
                "decision_offset": 5,
                "decision_limit": 6,
            },
        ),
        ("load_game_flow_data", "game-4"),
        ("load_game_replay", "game-5", {"cursor": 7, "limit": 8}),
        ("load_game_review", "game-6"),
        ("list_history_rows",),
        ("close",),
    ]


def test_game_history_facades_delegate_to_cached_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[Any] = []

    class FakeGameHistoryService:
        def __init__(self, store: Any) -> None:
            self.store = store
            self.calls: list[tuple[Any, ...]] = []
            instances.append(self)

        def history_fingerprint(self) -> dict[str, Any]:
            self.calls.append(("history_fingerprint",))
            return {"method": "history_fingerprint"}

        def memory_fingerprint(self) -> list[dict[str, Any]]:
            self.calls.append(("memory_fingerprint",))
            return [{"method": "memory_fingerprint"}]

        def memory_item(self, game_id: str, game: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(("memory_item", game_id, game))
            return {"method": "memory_item", "game_id": game_id}

        def postgres_fingerprint(self) -> dict[str, Any]:
            self.calls.append(("postgres_fingerprint",))
            return {"method": "postgres_fingerprint"}

        def snapshot_log_time(self, snapshot: dict[str, Any], fallback: str | None = None) -> str:
            self.calls.append(("snapshot_log_time", snapshot, fallback))
            return "snapshot-time"

        def game_list_row(self, game: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(("game_list_row", game))
            return {"method": "game_list_row", "game_id": game["game_id"]}

        def get_game_history_shell(self, game_id: str) -> dict[str, Any]:
            self.calls.append(("get_game_history_shell", game_id))
            return {"method": "get_game_history_shell", "game_id": game_id}

        def get_game_phase_detail(self, game_id: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("get_game_phase_detail", game_id, kwargs))
            return {"method": "get_game_phase_detail", "game_id": game_id, "kwargs": kwargs}

        def get_game_replay(self, game_id: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("get_game_replay", game_id, kwargs))
            return {"method": "get_game_replay", "game_id": game_id, "kwargs": kwargs}

        def history_shell_from_snapshot(self, game_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(("history_shell_from_snapshot", game_id, snapshot))
            return {"method": "history_shell_from_snapshot", "game_id": game_id}

        def history_phase_summaries_from_snapshot(
            self,
            snapshot: dict[str, Any],
            logs: list[dict[str, Any]],
            decisions: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            self.calls.append(("history_phase_summaries_from_snapshot", snapshot, logs, decisions))
            return [{"method": "history_phase_summaries_from_snapshot"}]

        def attach_history_state_to_phase_summaries(self, *args: Any) -> None:
            self.calls.append(("attach_history_state_to_phase_summaries", *args))

        def phase_detail_from_snapshot(self, game_id: str, snapshot: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("phase_detail_from_snapshot", game_id, snapshot, kwargs))
            return {"method": "phase_detail_from_snapshot", "game_id": game_id, "kwargs": kwargs}

        def replay_from_snapshot(self, game_id: str, snapshot: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("replay_from_snapshot", game_id, snapshot, kwargs))
            return {"method": "replay_from_snapshot", "game_id": game_id, "kwargs": kwargs}

        def build_game_history_rows(self) -> list[dict[str, Any]]:
            self.calls.append(("build_game_history_rows",))
            return [{"game_id": "from-history-service"}]

    monkeypatch.setattr(ui_backend_store, "GameHistoryService", FakeGameHistoryService)
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path))

    service = store._game_history_service()

    assert store._game_history_service() is service
    assert instances == [service]
    assert service.store is store
    assert store._game_history_fingerprint() == {"method": "history_fingerprint"}
    assert store._game_history_memory_fingerprint() == [{"method": "memory_fingerprint"}]
    assert store._game_history_memory_item("game-1", {"game_id": "game-1"}) == {
        "method": "memory_item",
        "game_id": "game-1",
    }
    assert store._postgres_history_fingerprint() == {"method": "postgres_fingerprint"}
    assert store._snapshot_log_time({"game_id": "game-2"}, fallback="fallback") == "snapshot-time"
    assert store._game_list_row({"game_id": "game-3"}) == {
        "method": "game_list_row",
        "game_id": "game-3",
    }
    assert store.get_game_history_shell("game-4") == {"method": "get_game_history_shell", "game_id": "game-4"}
    assert store.get_game_phase_detail(
        "game-5",
        day=2,
        phase="night",
        log_offset=3,
        log_limit=4,
        decision_offset=5,
        decision_limit=6,
    ) == {
        "method": "get_game_phase_detail",
        "game_id": "game-5",
        "kwargs": {
            "day": 2,
            "phase": "night",
            "log_offset": 3,
            "log_limit": 4,
            "decision_offset": 5,
            "decision_limit": 6,
        },
    }
    assert store.get_game_replay("game-6", cursor=7, limit=8) == {
        "method": "get_game_replay",
        "game_id": "game-6",
        "kwargs": {"cursor": 7, "limit": 8},
    }
    assert store._history_shell_from_snapshot("game-7", {"game_id": "game-7"}) == {
        "method": "history_shell_from_snapshot",
        "game_id": "game-7",
    }
    assert store._history_phase_summaries_from_snapshot({"game_id": "game-8"}, [], []) == [
        {"method": "history_phase_summaries_from_snapshot"}
    ]
    store._attach_history_state_to_phase_summaries([], {"game_id": "game-9"}, [], False, object())
    assert store._phase_detail_from_snapshot("game-10", {"game_id": "game-10"}, day=1, phase="setup") == {
        "method": "phase_detail_from_snapshot",
        "game_id": "game-10",
        "kwargs": {
            "day": 1,
            "phase": "setup",
            "log_offset": 0,
            "log_limit": 300,
            "decision_offset": 0,
            "decision_limit": 200,
        },
    }
    assert store._replay_from_snapshot("game-11", {"game_id": "game-11"}, cursor=12, limit=13) == {
        "method": "replay_from_snapshot",
        "game_id": "game-11",
        "kwargs": {"cursor": 12, "limit": 13},
    }
    assert store._build_game_history_rows() == [{"game_id": "from-history-service"}]


def test_live_game_lifecycle_facades_delegate_to_cached_coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[Any] = []

    class FakeLiveGameLifecycleCoordinator:
        def __init__(self, store: Any) -> None:
            self.store = store
            self.calls: list[tuple[Any, ...]] = []
            instances.append(self)

        async def start_game(self, request: Any) -> dict[str, Any]:
            self.calls.append(("start_game", request))
            return {"method": "start_game", "request": request}

        async def start_live_game(self, *, game_id: str, request: Any, skill_dir: str | None) -> dict[str, Any]:
            self.calls.append(("start_live_game", game_id, request, skill_dir))
            return {
                "method": "start_live_game",
                "game_id": game_id,
                "request": request,
                "skill_dir": skill_dir,
            }

        async def run_live_session(self, game_id: str) -> None:
            self.calls.append(("run_live_session", game_id))

        def check_watchdog(self, *, timeout_seconds: float | None = None) -> list[dict[str, Any]]:
            self.calls.append(("check_watchdog", timeout_seconds))
            return [{"timeout_seconds": timeout_seconds}]

        def live_session_waiting_for_human_within_timeout(self, session: Any) -> bool:
            self.calls.append(("live_session_waiting_for_human_within_timeout", session))
            return bool(session.waiting)

        def stop_game(self, game_id: str) -> dict[str, Any]:
            self.calls.append(("stop_game", game_id))
            return {"method": "stop_game", "game_id": game_id}

        def persist_start(self, session: Any) -> None:
            self.calls.append(("persist_start", session))

        def persist_session(self, session: Any, snapshot: dict[str, Any] | None) -> None:
            self.calls.append(("persist_session", session, snapshot))

    monkeypatch.setattr(ui_backend_store, "LiveGameLifecycleCoordinator", FakeLiveGameLifecycleCoordinator)
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path))
    request = SimpleNamespace(kind="request")
    session = SimpleNamespace(waiting=True)
    snapshot = {"game_id": "game-live"}

    coordinator = store._live_game_lifecycle()

    assert store._live_game_lifecycle() is coordinator
    assert instances == [coordinator]
    assert coordinator.store is store
    assert asyncio.run(store.start_game(request)) == {"method": "start_game", "request": request}
    assert asyncio.run(store.start_live_game(game_id="game-live", request=request, skill_dir="skills")) == {
        "method": "start_live_game",
        "game_id": "game-live",
        "request": request,
        "skill_dir": "skills",
    }
    asyncio.run(store.run_live_session("game-live"))
    assert store.check_live_game_watchdog(timeout_seconds=7.5) == [{"timeout_seconds": 7.5}]
    assert store._live_session_waiting_for_human_within_timeout(session) is True
    assert store.stop_game("game-live") == {"method": "stop_game", "game_id": "game-live"}
    store._persist_live_session_start(session)
    store.persist_live_session(session, snapshot)

    assert coordinator.calls == [
        ("start_game", request),
        ("start_live_game", "game-live", request, "skills"),
        ("run_live_session", "game-live"),
        ("check_watchdog", 7.5),
        ("live_session_waiting_for_human_within_timeout", session),
        ("stop_game", "game-live"),
        ("persist_start", session),
        ("persist_session", session, snapshot),
    ]


def test_game_delete_facade_delegates_to_cached_coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[Any] = []

    class FakeGameDeleteCoordinator:
        def __init__(self, store: Any) -> None:
            self.store = store
            self.calls: list[tuple[str, bool]] = []
            instances.append(self)

        def delete_game(self, game_id: str, *, force: bool = False) -> dict[str, Any]:
            self.calls.append((game_id, force))
            return {"game_id": game_id, "force": force}

    monkeypatch.setattr(ui_backend_store, "GameDeleteCoordinator", FakeGameDeleteCoordinator)
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path))

    coordinator = store._game_delete_coordinator()

    assert store._game_delete_coordinator() is coordinator
    assert instances == [coordinator]
    assert coordinator.store is store
    assert store.delete_game("game-a") == {"game_id": "game-a", "force": False}
    assert store.delete_game("game-b", force=True) == {"game_id": "game-b", "force": True}
    assert coordinator.calls == [("game-a", False), ("game-b", True)]


def test_task_service_facades_delegate_to_cached_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[Any] = []

    class FakeTaskService:
        def __init__(self, store: Any) -> None:
            self.store = store
            self.task_event_log = "task-events"
            self.calls: list[tuple[Any, ...]] = []
            instances.append(self)

        def open_connection(self) -> str:
            self.calls.append(("open_connection",))
            return "task-connection"

        def touch_background_task(self, entity: dict[str, Any], *, timestamp: str | None = None) -> str:
            self.calls.append(("touch_background_task", entity, timestamp))
            return "touched"

    monkeypatch.setattr(ui_backend_store, "TaskService", FakeTaskService)
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path))
    entity = {"run_id": "run-1"}

    service = store.task_service

    assert store.task_service is service
    assert instances == [service]
    assert service.store is store
    assert store._open_ui_task_connection() == "task-connection"
    assert store.task_event_log == "task-events"
    assert store._touch_background_task(entity, timestamp="now") == "touched"
    assert service.calls == [
        ("open_connection",),
        ("touch_background_task", entity, "now"),
    ]


def test_backend_store_creates_task_worker_loop_with_registered_executors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTaskService:
        def __init__(self, store: Any) -> None:
            self.store = store

        def open_connection(self) -> str:
            return "task-connection"

        def publish_task_queue_event(self, task: dict[str, Any], event: str | None = None) -> dict[str, Any]:
            return {"task": task, "event": event}

    class FakeBenchmarkService:
        def __init__(self, store: Any) -> None:
            self.store = store

        def task_executors(self) -> dict[str, Any]:
            return {"benchmark_batch": lambda _task, _context: {"ok": True}}

    monkeypatch.setattr(ui_backend_store, "TaskService", FakeTaskService)
    monkeypatch.setattr(ui_backend_store, "BenchmarkService", FakeBenchmarkService)
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path))

    loop = store.create_task_worker_loop(worker_id="worker-test", poll_interval_seconds=0, lease_seconds=30)

    assert loop.registry.kinds() == ("benchmark_batch", "evolution_batch", "evolution_run")


class _FakeEvolutionTaskService:
    def __init__(self) -> None:
        self.enqueued_payload: dict[str, Any] | None = None
        self.artifacts: list[dict[str, Any]] = []

    def enqueue_task(self, **kwargs: Any) -> dict[str, Any]:
        self.enqueued_payload = dict(kwargs["payload"])
        return {"task_id": kwargs["task_id"], "status": "queued"}

    def put_task_json_artifact(
        self,
        *,
        task_id: str,
        name: str,
        payload: Any,
        artifact_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact = {
            "artifact_id": f"{task_id}:{name}",
            "task_id": task_id,
            "name": name,
            "payload": payload,
            "artifact_type": artifact_type,
            "metadata": metadata or {},
        }
        self.artifacts.append(artifact)
        return artifact


class _FakeEvolutionRunContext:
    def __init__(self, tmp_path: Path, runner: Any) -> None:
        self.evolution_runs: dict[str, dict[str, Any]] = {}
        self.evolution_batches: dict[str, dict[str, Any]] = {}
        self.task_service = _FakeEvolutionTaskService()
        self.paths = PathConfig(root=tmp_path)
        self.runner = runner
        self.persist_count = 0

    def _persist_background_tasks(self) -> None:
        self.persist_count += 1

    def _touch_background_task(self, entity: dict[str, Any], *, timestamp: str | None = None) -> str:
        heartbeat = timestamp or "2026-01-01T00:00:00+08:00"
        entity["last_heartbeat_at"] = heartbeat
        return heartbeat

    def _task_progress_percent(self, entity: dict[str, Any]) -> float:
        progress = entity.get("progress")
        if isinstance(progress, dict):
            return float(progress.get("percent") or 0.0)
        return 0.0

    def evolution_runner(self) -> Any:
        return self.runner

    def model_for_run(self) -> str:
        return "test-model"


def test_evolution_task_executor_restores_snapshot_before_running(tmp_path: Path) -> None:
    async def runner(**kwargs: Any) -> dict[str, Any]:
        return {
            "run_id": kwargs["run_id"],
            "role": kwargs["role"],
            "status": "reviewing",
            "training_games": [],
            "battle_games": [],
            "diagnostics": [{"kind": "worker_restore_checked"}],
        }

    request = EvolutionStartRequest(roles=["seer"], training_games=0, battle_games=0, max_days=1)
    api_context = _FakeEvolutionRunContext(tmp_path, runner)
    api_service = EvolutionRunService(api_context)
    queued = api_service.queue_evolution(request)
    run_id = queued["run_id"]
    api_service.queue_evolution_task(queued, request)

    assert queued["status"] == "queued"
    assert api_context.task_service.enqueued_payload is not None

    worker_context = _FakeEvolutionRunContext(tmp_path, runner)
    worker_service = EvolutionRunService(worker_context)
    worker_task_context = SimpleNamespace(
        heartbeat=lambda progress=None: True,
        cancel_requested=lambda: False,
    )

    result = worker_service.execute_evolution_task(
        {
            "task_id": run_id,
            "kind": "evolution_run",
            "payload": api_context.task_service.enqueued_payload,
        },
        worker_task_context,
    )

    assert worker_context.evolution_runs[run_id]["status"] == "reviewing"
    assert result["artifact_ids"] == [
        f"{run_id}:evolution-result.json",
        f"{run_id}:diagnostics.json",
    ]
    assert [artifact["name"] for artifact in worker_context.task_service.artifacts] == [
        "evolution-result.json",
        "diagnostics.json",
    ]


def test_evolution_task_executor_passes_queue_cancel_check(tmp_path: Path) -> None:
    runner_called = False

    async def runner(**kwargs: Any) -> dict[str, Any]:
        nonlocal runner_called
        runner_called = True
        assert kwargs["cancel_check"]() is True
        raise RuntimeError("stopped")

    request = EvolutionStartRequest(roles=["seer"], training_games=1, battle_games=0, max_days=1)
    api_context = _FakeEvolutionRunContext(tmp_path, runner)
    api_service = EvolutionRunService(api_context)
    queued = api_service.queue_evolution(request)
    run_id = queued["run_id"]
    api_service.queue_evolution_task(queued, request)

    cancel_calls = 0

    def cancel_requested() -> bool:
        nonlocal cancel_calls
        cancel_calls += 1
        return cancel_calls >= 2

    worker_context = _FakeEvolutionRunContext(tmp_path, runner)
    worker_service = EvolutionRunService(worker_context)
    worker_service.execute_evolution_task(
        {
            "task_id": run_id,
            "kind": "evolution_run",
            "payload": api_context.task_service.enqueued_payload,
        },
        SimpleNamespace(heartbeat=lambda progress=None: True, cancel_requested=cancel_requested),
    )

    run = worker_context.evolution_runs[run_id]
    assert runner_called is True
    assert run["status"] == "failed"
    assert run["cancelled"] is True
    assert run["current_stage"] == "stopped"


def test_evolution_batch_task_artifacts_include_child_diagnostics(tmp_path: Path) -> None:
    async def runner(**_kwargs: Any) -> dict[str, Any]:
        return {}

    context = _FakeEvolutionRunContext(tmp_path, runner)
    service = EvolutionRunService(context)
    context.evolution_runs["evolve_seer_child"] = {
        "kind": "role_evolution_run",
        "run_id": "evolve_seer_child",
        "role": "seer",
        "diagnostics": [{"kind": "child_warning"}],
    }
    batch = {
        "kind": "role_evolution_batch",
        "batch_id": "evo_batch_child_diag",
        "status": "completed",
        "runs": ["evolve_seer_child"],
        "diagnostics": [],
    }

    service.persist_evolution_task_artifacts("evo_batch_child_diag", batch)

    diagnostics_artifact = next(
        artifact for artifact in context.task_service.artifacts if artifact["name"] == "diagnostics.json"
    )
    assert diagnostics_artifact["payload"] == [
        {
            "kind": "child_warning",
            "run_id": "evolve_seer_child",
            "role": "seer",
        }
    ]


def test_evolution_task_artifacts_include_trust_loop_json_files(tmp_path: Path) -> None:
    async def runner(**_kwargs: Any) -> dict[str, Any]:
        return {}

    context = _FakeEvolutionRunContext(tmp_path, runner)
    service = EvolutionRunService(context)
    run = {
        "kind": "role_evolution_run",
        "run_id": "evolve_seer_artifacts",
        "role": "seer",
        "status": "reviewing",
        "gate_report": {"schema_version": "trust_loop_gate_v1", "decision": "review_required"},
        "trust_bundle": {"schema_version": "trust_bundle_v1", "trust_bundle_id": "tb-artifacts"},
        "paired_seed_battle_table": [{"seed": 7, "winner_side": "candidate"}],
        "scenario_replay_report": {"schema_version": "scenario_replay_report_v1", "scenario_count": 1},
    }

    service.persist_evolution_task_artifacts("evolve_seer_artifacts", run)

    artifacts = {artifact["name"]: artifact for artifact in context.task_service.artifacts}
    assert artifacts["gate-report.json"]["artifact_type"] == "evolution_gate_report"
    assert artifacts["gate-report.json"]["payload"] == run["gate_report"]
    assert artifacts["trust-bundle.json"]["artifact_type"] == "evolution_trust_bundle"
    assert artifacts["trust-bundle.json"]["payload"] == run["trust_bundle"]
    assert artifacts["paired-seed-battle-table.json"]["artifact_type"] == "evolution_paired_seed_battle_table"
    assert artifacts["paired-seed-battle-table.json"]["payload"] == run["paired_seed_battle_table"]
    assert artifacts["scenario-replay-report.json"]["artifact_type"] == "evolution_scenario_replay_report"
    assert artifacts["scenario-replay-report.json"]["payload"] == run["scenario_replay_report"]


def test_queue_backed_background_tasks_are_not_recovered_as_interrupted() -> None:
    run = {
        "kind": "role_evolution_run",
        "run_id": "evolve_pg",
        "status": "queued",
        "task_id": "evolve_pg",
        "task_queue_status": "queued",
        "progress": {"stage": "queued", "percent": 0.0},
    }
    store = SimpleNamespace(
        evolution_runs={"evolve_pg": run},
        evolution_batches={},
        _task_event_fingerprints={},
    )
    service = TaskPersistenceService(
        store,
        open_connection=lambda: None,
        task_event_log=lambda: None,
    )

    assert service.recover_background_tasks() == 0
    assert run["status"] == "queued"
    assert run["progress"]["stage"] == "queued"


def test_evolution_service_persists_actions_through_task_service() -> None:
    class FakeTaskService:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, ...]] = []

        def touch_background_task(self, entity: dict[str, Any], *, timestamp: str | None = None) -> str:
            self.calls.append(("touch_background_task", entity, timestamp))
            return "heartbeat"

        def persist_background_tasks(self) -> None:
            self.calls.append(("persist_background_tasks",))

    task_service = FakeTaskService()
    run = {"kind": "role_evolution_run", "run_id": "run-1", "status": "failed"}
    store = SimpleNamespace(
        evolution_runs={"run-1": run},
        evolution_batches={},
        task_service=task_service,
    )

    result = EvolutionService(store).resume_run("run-1")

    assert result is run
    assert run["status"] == "reviewing"
    assert run["stop_requested"] is False
    assert task_service.calls == [
        ("touch_background_task", run, None),
        ("persist_background_tasks",),
    ]


def test_evolution_read_service_handles_run_detail_drilldown_without_task_service() -> None:
    run = {
        "kind": "role_evolution_run",
        "run_id": "run-1",
        "role": "seer",
        "status": "reviewing",
        "last_heartbeat_at": "2026-01-01T00:00:02+08:00",
        "diff": [{"target_file": "seer.md", "action": "append_rule"}],
        "training_games": [
            {
                "game_id": "game-1",
                "status": "completed",
                "seed": 7,
                "events": [{"index": 1, "event_type": "game_init", "message": "started"}],
                "decisions": [{"decision_id": "d1", "action_type": "seer_check", "selected_target": 3}],
            },
            {"game_id": "game-2", "status": "failed"},
        ],
        "battle_games": [],
    }
    batch = {
        "kind": "role_evolution_batch",
        "batch_id": "batch-1",
        "status": "completed",
        "last_heartbeat_at": "2026-01-01T00:00:01+08:00",
    }
    service = EvolutionReadService(SimpleNamespace(evolution_runs={"run-1": run}, evolution_batches={"batch-1": batch}))

    listed = service.list_runs(history_requested=True, limit=1, source="evolution", status="reviewing")
    games = service.games("run-1", status="completed", limit=1, offset=0, paginate=True)
    decisions = service.game_detail("run-1", "game-1", "decisions")
    events = service.game_detail("run-1", "game-1", "events")

    assert listed["pagination"] == {"total": 1, "offset": 0, "limit": 1, "returned": 1, "has_more": False}
    assert listed["runs"][0]["run_id"] == "run-1"
    assert service.get_run("run-1") is run
    assert service.get_run("batch-1")["batch_id"] == "batch-1"
    assert service.diff("run-1")["diffs"] == [{"target_file": "seer.md", "action": "append_rule"}]
    assert games["pagination"] == {"total": 1, "offset": 0, "limit": 1, "returned": 1, "has_more": False}
    assert games["games"][0]["game_id"] == "game-1"
    assert "events" not in games["games"][0]
    assert decisions["decisions"][0]["id"] == "d1"
    assert decisions["decisions"][0]["target_id"] == 3
    assert events["events"][0]["type"] == "game_init"


def test_evolution_read_service_task_overlay_fails_open() -> None:
    class BrokenTaskService:
        def get_task_queue_row(self, task_id: str) -> dict[str, Any]:
            raise RuntimeError(f"offline: {task_id}")

    run = {
        "kind": "role_evolution_run",
        "run_id": "run-task-offline",
        "status": "reviewing",
        "task_id": "run-task-offline",
        "task_queue_status": "running",
    }
    service = EvolutionReadService(
        SimpleNamespace(
            evolution_runs={"run-task-offline": run},
            evolution_batches={},
            task_service=BrokenTaskService(),
        )
    )

    assert service.get_run("run-task-offline") is run
    assert service.get_run("run-task-offline")["status"] == "reviewing"


def test_evolution_read_service_parent_batch_task_does_not_override_child_status() -> None:
    class FakeTaskService:
        def get_task_queue_row(self, task_id: str) -> dict[str, Any] | None:
            if task_id != "batch-task":
                return None
            return {
                "task_id": "batch-task",
                "kind": "evolution_batch",
                "status": "succeeded",
                "progress": {"stage": "completed", "percent": 1.0},
                "updated_at": "2026-01-01T00:00:02+08:00",
                "finished_at": "2026-01-01T00:00:03+08:00",
                "cancel_requested": False,
                "result": {"status": "completed", "artifact_ids": ["batch-artifact"]},
            }

    child = {
        "kind": "role_evolution_run",
        "run_id": "child-run",
        "batch_id": "batch-task",
        "status": "reviewing",
        "task_id": "batch-task",
        "task_queue_status": "succeeded",
    }
    batch = {
        "kind": "role_evolution_batch",
        "batch_id": "batch-task",
        "runs": ["child-run"],
        "status": "completed",
        "task_id": "batch-task",
        "task_queue_status": "succeeded",
    }
    service = EvolutionReadService(
        SimpleNamespace(
            evolution_runs={"child-run": child},
            evolution_batches={"batch-task": batch},
            task_service=FakeTaskService(),
        )
    )

    listed = service.list_runs(history_requested=False)
    child_summary = listed["runs"][0]
    batch_detail = service.get_run("batch-task")

    assert child_summary["status"] == "reviewing"
    assert child_summary["task_queue_status"] == "succeeded"
    assert "task_artifact_ids" not in child_summary
    assert batch_detail["status"] == "completed"
    assert batch_detail["task_artifact_ids"] == ["batch-artifact"]


def test_evolution_read_service_trust_bundle_falls_back_to_run_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    import storage.evolution.state_gateway as state_gateway

    class FakeEvolutionStateGateway:
        def __init__(self, *, paths: Any | None = None) -> None:
            self.paths = paths

        def get_trust_bundle(self, run_id: str) -> None:
            raise RuntimeError(f"offline: {run_id}")

    monkeypatch.setattr(state_gateway, "EvolutionStateGateway", FakeEvolutionStateGateway)
    run = {
        "run_id": "run-1",
        "role": "seer",
        "started_at": "2026-01-01T00:00:00+08:00",
        "finished_at": "2026-01-01T00:01:00+08:00",
        "result": {
            "trust_bundle": {
                "schema_version": "trust_bundle_v1",
                "trust_bundle_id": "trust-bundle-1",
                "run_id": "run-1",
                "role": "seer",
                "bundle_hash": "abc123",
            },
        },
    }
    service = EvolutionReadService(SimpleNamespace(evolution_runs={"run-1": run}, evolution_batches={}, paths="pg"))

    payload = service.trust_bundle_payload("run-1")

    assert payload["kind"] == "evolution_trust_bundle"
    assert payload["trust_bundle_id"] == "trust-bundle-1"
    assert payload["bundle_hash"] == "abc123"
    assert payload["trust_bundle"]["schema_version"] == "trust_bundle_v1"


def test_benchmark_service_stops_batches_through_task_service(tmp_path: Path) -> None:
    class FakeTaskService:
        def __init__(self) -> None:
            self.calls: list[tuple[Any, ...]] = []

        def task_progress_percent(self, entity: dict[str, Any], default: float = 0.0) -> float:
            self.calls.append(("task_progress_percent", entity, default))
            return 0.35

        def mark_benchmark_stage(
            self,
            batch: dict[str, Any],
            stage: str,
            **kwargs: Any,
        ) -> None:
            self.calls.append(("mark_benchmark_stage", batch, stage, kwargs))

        def persist_background_tasks(self) -> None:
            self.calls.append(("persist_background_tasks",))

    task_service = FakeTaskService()
    batch = {
        "kind": "benchmark_batch",
        "batch_id": "batch-1",
        "status": "running",
        "roles": ["seer", "villager"],
        "progress": {"completed_roles": 1},
    }
    context = SimpleNamespace(
        paths=PathConfig(root=tmp_path),
        evolution_batches={"batch-1": batch},
        task_service=task_service,
    )

    result = BenchmarkService(context).stop_benchmark("batch-1")

    assert result is batch
    assert batch["status"] == "failed"
    assert batch["stop_requested"] is True
    assert batch["cancelled"] is True
    assert [call[0] for call in task_service.calls] == [
        "task_progress_percent",
        "mark_benchmark_stage",
        "persist_background_tasks",
    ]
    mark_call = task_service.calls[1]
    assert mark_call[1:3] == (batch, "stopped")
    assert mark_call[3] == {
        "status": "failed",
        "percent": 0.35,
        "completed_roles": 1,
        "role_count": 2,
        "diagnostic": {"kind": "benchmark_stopped", "message": batch["error"]},
    }


def test_benchmark_facades_delegate_to_cached_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[Any] = []

    class FakeBenchmarkService:
        def __init__(self, store: Any) -> None:
            self.store = store
            self.calls: list[tuple[Any, ...]] = []
            instances.append(self)

        def leaderboard_entries(
            self,
            *,
            scope: str | None = None,
            evaluation_set_id: str | None = None,
            target_role: str | None = None,
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            self.calls.append(("leaderboard_entries", scope, evaluation_set_id, target_role, limit))
            return [
                {
                    "scope": scope,
                    "evaluation_set_id": evaluation_set_id,
                    "target_role": target_role,
                    "limit": limit,
                }
            ]

    monkeypatch.setattr(ui_backend_store, "BenchmarkService", FakeBenchmarkService)
    store = ui_backend_store.BackendStore(paths=PathConfig(root=tmp_path))

    service = store.benchmark_service

    assert store.benchmark_service is service
    assert instances == [service]
    assert service.store is store
    assert store.leaderboard_entries(
        scope="role_version",
        evaluation_set_id="eval-1",
        target_role="seer",
        limit=3,
    ) == [
        {
            "scope": "role_version",
            "evaluation_set_id": "eval-1",
            "target_role": "seer",
            "limit": 3,
        }
    ]
    assert service.calls == [
        ("leaderboard_entries", "role_version", "eval-1", "seer", 3),
    ]


def test_benchmark_snapshot_facades_delegate_to_snapshot_service(tmp_path: Path) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def recorder(name: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append((name, args, kwargs))
            return {"method": name, "args": list(args), "kwargs": kwargs}

        return call

    class FakeSnapshotService:
        create_benchmark_snapshot = staticmethod(recorder("create_benchmark_snapshot"))
        list_benchmark_snapshots = staticmethod(recorder("list_benchmark_snapshots"))
        get_benchmark_snapshot = staticmethod(recorder("get_benchmark_snapshot"))
        benchmark_snapshot_export = staticmethod(recorder("benchmark_snapshot_export"))
        benchmark_snapshot_compare = staticmethod(recorder("benchmark_snapshot_compare"))
        save_benchmark_view = staticmethod(recorder("save_benchmark_view"))
        list_benchmark_views = staticmethod(recorder("list_benchmark_views"))
        get_benchmark_view = staticmethod(recorder("get_benchmark_view"))
        delete_benchmark_view = staticmethod(recorder("delete_benchmark_view"))

    batch = {
        "kind": "benchmark_batch",
        "batch_id": "batch-1",
        "status": "completed",
        "target_type": "model",
        "benchmark": {
            "id": "bench-1",
            "version": "v1",
            "evaluation_set_id": "eval-1",
            "seed_set_id": "seed-1",
        },
        "results": [
            {
                "batch_id": "result-1",
                "config": {
                    "batch_id": "result-1",
                    "comparison_type": "model",
                    "benchmark_id": "bench-1",
                    "evaluation_set_id": "eval-1",
                    "seed_set_id": "seed-1",
                    "model_id": "model-a",
                    "model_config_hash": "hash-a",
                },
                "model_id": "model-a",
                "model_config_hash": "hash-a",
                "game_count": 1,
                "completed": 1,
                "rankable": True,
                "games": [{"game_id": "game-1", "status": "completed", "seed": 1}],
            }
        ],
    }
    context = SimpleNamespace(paths=PathConfig(root=tmp_path), evolution_batches={"batch-1": batch})
    service = BenchmarkService(context)
    service._snapshots = FakeSnapshotService()  # type: ignore[attr-defined]
    snapshot_request = object()
    view_request = object()

    assert service.benchmark_batch_report("batch-1")["kind"] == "benchmark_run_report"
    assert service.benchmark_reports(scope="model", status="completed", offset=3)["kind"] == "benchmark_run_reports"
    assert service.create_benchmark_snapshot(snapshot_request)["method"] == "create_benchmark_snapshot"
    assert service.list_benchmark_snapshots(benchmark_id="bench-1", target_role="seer")["method"] == "list_benchmark_snapshots"
    assert service.get_benchmark_snapshot("snap-1")["method"] == "get_benchmark_snapshot"
    assert service.benchmark_snapshot_export("snap-1", format="csv")["method"] == "benchmark_snapshot_export"
    assert service.benchmark_snapshot_compare("snap-1", against_snapshot_id="snap-0", limit=7)["method"] == (
        "benchmark_snapshot_compare"
    )
    assert service.save_benchmark_view(view_request)["method"] == "save_benchmark_view"
    assert service.list_benchmark_views(view_key="default", limit=2)["method"] == "list_benchmark_views"
    assert service.get_benchmark_view("default")["method"] == "get_benchmark_view"
    assert service.delete_benchmark_view("default")["method"] == "delete_benchmark_view"

    assert calls == [
        ("create_benchmark_snapshot", (snapshot_request,), {}),
        (
            "list_benchmark_snapshots",
            (),
            {
                "scope": None,
                "evaluation_set_id": None,
                "benchmark_id": "bench-1",
                "target_role": "seer",
                "limit": 50,
            },
        ),
        ("get_benchmark_snapshot", ("snap-1",), {}),
        ("benchmark_snapshot_export", ("snap-1",), {"format": "csv"}),
        ("benchmark_snapshot_compare", ("snap-1",), {"against_snapshot_id": "snap-0", "limit": 7}),
        ("save_benchmark_view", (view_request,), {}),
        (
            "list_benchmark_views",
            (),
            {
                "scope": None,
                "evaluation_set_id": None,
                "benchmark_id": None,
                "target_role": None,
                "view_key": "default",
                "limit": 2,
            },
        ),
        ("get_benchmark_view", ("default",), {}),
        ("delete_benchmark_view", ("default",), {}),
    ]


def test_benchmark_snapshot_service_uses_minimal_context_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    class FakeSnapshotRepository:
        def __init__(self, conn: FakeConnection) -> None:
            assert conn is connections[-1]

        def list(
            self,
            *,
            scope: str | None = None,
            evaluation_set_id: str | None = None,
            benchmark_id: str | None = None,
            target_role: str | None = None,
            limit: int = 50,
        ) -> list[dict[str, Any]]:
            repository_calls.append(
                {
                    "scope": scope,
                    "evaluation_set_id": evaluation_set_id,
                    "benchmark_id": benchmark_id,
                    "target_role": target_role,
                    "limit": limit,
                }
            )
            return [{"snapshot_id": "snap-1"}]

    monkeypatch.setattr("app.lib.score.open_eval_connection", fake_open_eval_connection)
    monkeypatch.setattr(
        "ui.backend.services.benchmark_snapshot_service.BenchmarkSnapshotRepository",
        FakeSnapshotRepository,
    )

    context = SimpleNamespace(paths=PathConfig(root=tmp_path))
    service = BenchmarkSnapshotService(context)
    rows = service.load_benchmark_snapshot_summaries(
        scope="role_version",
        evaluation_set_id="suite@v1",
        benchmark_id="bench-1",
        target_role="seer",
        limit=3,
    )

    assert rows == [{"snapshot_id": "snap-1"}]
    assert opened_paths == [context.paths]
    assert repository_calls == [
        {
            "scope": "role_version",
            "evaluation_set_id": "suite@v1",
            "benchmark_id": "bench-1",
            "target_role": "seer",
            "limit": 3,
        }
    ]
    assert connections and connections[0].closed is True
