"""Backend store and long-running task orchestration for the UI backend."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from app.config import PathConfig, load_llm_config, load_tts_config
from app.lib.version import VersionRegistryProtocol, version_registry_from_env
from app.run import run_evaluation, run_evolution
from app.services.llm import create_llm
from ui.backend.background_store import BackgroundTaskStoreMixin
from ui.backend.game_store import GameStoreMixin
from ui.backend.schemas import EvolutionStartRequest
from ui.backend.services import (
    BenchmarkService,
    EvolutionRunService,
    GameDeleteCoordinator,
    GameHistoryService,
    GamePersistenceService,
    GameReadGateway,
    GameSessionService,
    LangfuseTaskService,
    LiveGameLifecycleCoordinator,
    TaskService,
)
from ui.backend.settings_model_profiles import SettingsModelProfileStore
from ui.backend.services.task_worker import TaskWorkerLoop
from ui.backend.live_game import LiveGameSession
from ui.backend.task_events import TaskEventLog
from ui.backend.startup_checks import default_startup_checks, log_startup_checks, run_startup_checks

_log = logging.getLogger(__name__)

_ComponentT = TypeVar("_ComponentT")


class _FakeModel:
    async def ainvoke(self, messages: Any) -> Any:
        return type(
            "Result",
            (),
            {
                "content": (
                    '{"choice":null,"target":null,"public_text":"ok",'
                    '"private_reasoning":"ui backend fallback model",'
                    '"confidence":1,"alternatives":[],"rejected_reasons":[],'
                    '"selected_skills":[]}'
                )
            },
        )()


@dataclass
class BackendStore(BackgroundTaskStoreMixin, GameStoreMixin):
    paths: PathConfig
    model: Any | None = None
    games: dict[str, dict[str, Any]] = field(default_factory=dict)
    live_sessions: dict[str, LiveGameSession] = field(default_factory=dict)
    evolution_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    evolution_batches: dict[str, dict[str, Any]] = field(default_factory=dict)
    benchmark_leaderboard_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    benchmark_saved_views: dict[str, dict[str, Any]] = field(default_factory=dict)
    background_state_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _background_state_fingerprint: str | None = field(default=None, init=False, repr=False)
    _task_event_fingerprints: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _task_event_log: TaskEventLog | None = field(default=None, init=False, repr=False)
    _task_service_cache: TaskService | None = field(default=None, init=False, repr=False)
    _benchmark_service_cache: BenchmarkService | None = field(default=None, init=False, repr=False)
    _evolution_run_service_cache: EvolutionRunService | None = field(default=None, init=False, repr=False)
    _game_history_service_cache: GameHistoryService | None = field(default=None, init=False, repr=False)
    _game_read_gateway_cache: GameReadGateway | None = field(default=None, init=False, repr=False)
    _game_delete_coordinator_cache: GameDeleteCoordinator | None = field(default=None, init=False, repr=False)
    _game_persistence_service_cache: GamePersistenceService | None = field(default=None, init=False, repr=False)
    _game_session_service_cache: GameSessionService | None = field(default=None, init=False, repr=False)
    _langfuse_task_service_cache: LangfuseTaskService | None = field(default=None, init=False, repr=False)
    _live_game_lifecycle_cache: LiveGameLifecycleCoordinator | None = field(default=None, init=False, repr=False)
    _registry: VersionRegistryProtocol | None = field(default=None, init=False, repr=False)
    _role_overview_cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    startup_checks: dict[str, Any] = field(default_factory=default_startup_checks)

    def _cached_component(self, cache_attr: str, factory: Callable[[], _ComponentT]) -> _ComponentT:
        component = getattr(self, cache_attr, None)
        if component is None:
            component = factory()
            setattr(self, cache_attr, component)
        return component

    def _task_service(self) -> TaskService:
        return self._cached_component("_task_service_cache", lambda: TaskService(self))

    def _benchmark_service(self) -> BenchmarkService:
        return self._cached_component("_benchmark_service_cache", lambda: BenchmarkService(self))

    def _evolution_run_service(self) -> EvolutionRunService:
        return self._cached_component("_evolution_run_service_cache", lambda: EvolutionRunService(self))

    def _game_history_service(self) -> GameHistoryService:
        return self._cached_component("_game_history_service_cache", lambda: GameHistoryService(self))

    def _game_read_gateway(self) -> GameReadGateway:
        return self._cached_component("_game_read_gateway_cache", lambda: GameReadGateway(self))

    def _game_delete_coordinator(self) -> GameDeleteCoordinator:
        return self._cached_component("_game_delete_coordinator_cache", lambda: GameDeleteCoordinator(self))

    def _game_persistence_service(self) -> GamePersistenceService:
        return self._cached_component("_game_persistence_service_cache", lambda: GamePersistenceService(self))

    def _game_session_service(self) -> GameSessionService:
        return self._cached_component("_game_session_service_cache", lambda: GameSessionService(self))

    def _langfuse_task_service(self) -> LangfuseTaskService:
        return self._cached_component("_langfuse_task_service_cache", lambda: LangfuseTaskService(self))

    def _live_game_lifecycle(self) -> LiveGameLifecycleCoordinator:
        return self._cached_component("_live_game_lifecycle_cache", lambda: LiveGameLifecycleCoordinator(self))

    @property
    def registry(self) -> VersionRegistryProtocol:
        if self._registry is None:
            self._registry = version_registry_from_env(paths=self.paths)
        return self._registry

    def close(self) -> None:
        self._close_wolf_read_connection()
        if self._registry is not None:
            self._registry.close()
            self._registry = None

    def refresh_startup_checks(self) -> dict[str, Any]:
        self.startup_checks = run_startup_checks(self)
        log_startup_checks(self.startup_checks)
        return self.startup_checks

    def invalidate_role_overview_cache(self) -> None:
        self._role_overview_cache.clear()

    def _open_ui_task_connection(self) -> Any:
        return self.task_service.open_connection()

    @property
    def benchmark_service(self) -> BenchmarkService:
        return self._benchmark_service()

    def leaderboard_scores_for_role(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        return self.benchmark_service.leaderboard_scores_for_role(
            role,
            evaluation_set_id=evaluation_set_id,
        )

    def leaderboard_entries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.benchmark_service.leaderboard_entries(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            limit=limit,
        )

    def model_leaderboard_entries(
        self,
        *,
        evaluation_set_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.benchmark_service.model_leaderboard_entries(
            evaluation_set_id=evaluation_set_id,
            limit=limit,
        )

    def leaderboard_compare(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        baseline_subject_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.benchmark_service.leaderboard_compare(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            baseline_subject_id=baseline_subject_id,
            limit=limit,
        )

    def leaderboard_scores_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        return self.benchmark_service.leaderboard_scores_for_roles(
            roles,
            evaluation_set_id=evaluation_set_id,
        )

    def get_benchmark_spec_summary(self, benchmark_id: str) -> dict[str, Any]:
        return self.benchmark_service.get_benchmark_spec_summary(benchmark_id)

    def settings_model_runtime_for_scope(
        self,
        scope: str,
        *,
        model_profile_id: str | None = None,
    ) -> dict[str, Any] | None:
        return SettingsModelProfileStore.from_backend_store(self).model_runtime_payload(
            scope=scope,
            profile_id=model_profile_id,
        )

    def model_for_run(
        self,
        *,
        scope: str = "game_decision",
        model_profile_id: str | None = None,
    ) -> Any | None:
        normalized_profile_id = str(model_profile_id or "").strip() or None
        if normalized_profile_id is not None:
            return SettingsModelProfileStore.from_backend_store(self).create_llm_for_scope(
                scope=scope,
                profile_id=normalized_profile_id,
            )
        if self.model is not None:
            return self.model
        use_fake = os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").lower() in {"1", "true", "yes"}
        if use_fake:
            return _FakeModel()
        settings_model = SettingsModelProfileStore.from_backend_store(self).create_llm_for_scope(
            scope=scope,
            profile_id=normalized_profile_id,
        )
        if settings_model is not None:
            return settings_model
        try:
            return create_llm()
        except RuntimeError:
            _log.warning("LLM config missing; UI backend is using fallback model", exc_info=True)
            return _FakeModel()

    async def evaluate_benchmark_batch(
        self,
        *,
        batch_config: dict[str, Any],
        model: Any | None,
        paths: PathConfig,
    ) -> dict[str, Any]:
        return await run_evaluation(
            batch_config=batch_config,
            model=model,
            decision_judge_model=self.model_for_run(scope="judge"),
            paths=paths,
        )

    def evolution_runner(self) -> Any:
        return run_evolution

    def llm_status(self) -> str:
        if self.model is not None:
            return "configured"
        use_fake = os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").lower() in {"1", "true", "yes"}
        if use_fake:
            return "fallback"
        try:
            load_llm_config()
        except RuntimeError:
            return "fallback"
        return "configured"

    def tts_status(self) -> str:
        try:
            load_tts_config()
        except RuntimeError:
            return "fallback"
        return "configured"

    def tts_streaming_available(self) -> bool:
        try:
            load_tts_config()
        except RuntimeError:
            return False
        return True

    def queue_evolution(self, request: EvolutionStartRequest) -> dict[str, Any]:
        return self._evolution_run_service().queue_evolution(request)

    def queue_evolution_task(self, queued: dict[str, Any], request: EvolutionStartRequest) -> dict[str, Any]:
        return self._evolution_run_service().queue_evolution_task(queued, request)

    def _create_evolution_run(
        self,
        role: str,
        request: EvolutionStartRequest,
        *,
        batch_id: str | None = None,
        status: str = "running",
    ) -> dict[str, Any]:
        return self._evolution_run_service().create_evolution_run(
            role,
            request,
            batch_id=batch_id,
            status=status,
        )

    @staticmethod
    def _count_evolution_games(value: Any) -> int:
        return EvolutionRunService.count_evolution_games(value)

    def _evolution_overall_progress(self, run: dict[str, Any]) -> dict[str, Any]:
        return self._evolution_run_service().evolution_overall_progress(run)

    def _sync_evolution_progress(self, run_id: str, snapshot: dict[str, Any]) -> None:
        self._evolution_run_service().sync_evolution_progress(run_id, snapshot)

    def _evolution_cancel_check(self, run_id: str) -> bool:
        return self._evolution_run_service().evolution_cancel_check(run_id)

    def _run_summary_for_batch(self, run: dict[str, Any]) -> dict[str, Any]:
        return self._evolution_run_service().run_summary_for_batch(run)

    def _refresh_evolution_batch(self, batch_id: Any) -> None:
        self._evolution_run_service().refresh_evolution_batch(batch_id)

    def _mark_evolution_stopped(self, entity: dict[str, Any]) -> None:
        self._evolution_run_service().mark_evolution_stopped(entity)

    async def run_queued_evolution(self, run_id: str, request: EvolutionStartRequest) -> None:
        await self._evolution_run_service().run_queued_evolution(run_id, request)

    async def run_queued_evolution_batch(self, batch_id: str, request: EvolutionStartRequest) -> None:
        await self._evolution_run_service().run_queued_evolution_batch(batch_id, request)

    async def _run_single_evolution(self, role: str, request: EvolutionStartRequest) -> dict[str, Any]:
        return await self._evolution_run_service().run_single_evolution(role, request)

    def create_task_worker_loop(
        self,
        *,
        worker_id: str = "ui-task-worker",
        poll_interval_seconds: float = 1.0,
        lease_seconds: int = 300,
    ) -> TaskWorkerLoop:
        executors: dict[str, Any] = {}
        executors.update(self.benchmark_service.task_executors())
        executors.update(self._evolution_run_service().task_executors())
        executors.update(self._langfuse_task_service().task_executors())
        return TaskWorkerLoop(
            connection_factory=self.task_service.open_connection,
            executors=executors,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            poll_interval_seconds=poll_interval_seconds,
            event_publisher=self.task_service.publish_task_queue_event,
        )
