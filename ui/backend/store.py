"""Backend store and long-running task orchestration for the UI backend."""

from __future__ import annotations
import hashlib
import json
import logging
import math
import os
import uuid
import asyncio
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from app.config import PathConfig, load_llm_config, load_tts_config
from app.lib.benchmark_release_gate import evaluate_benchmark_release_gate
from app.lib.benchmark_reproducibility import build_benchmark_reproducibility_manifest
from app.lib.benchmark_spec import (
    BenchmarkSeedSet,
    BenchmarkSpec,
    BenchmarkSpecError,
    LAUNCHABLE_BENCHMARK_STATUSES,
    VALID_BENCHMARK_STATUSES,
    benchmark_seed_registry_summary,
    benchmark_seed_set_summary,
    benchmark_config_hash,
    benchmark_spec_summary,
    list_benchmark_seed_sets,
    load_benchmark_seed_set,
    materialize_benchmark_spec,
    load_benchmark_spec,
    seed_set_config_hash,
)
from app.lib.version import VersionRegistryProtocol, registry_version_release_stage, version_registry_from_env
from app.run import LANGFUSE_EVAL_CONFIG_KEYS, run_evaluation, run_evolution
from app.services.llm import create_llm
from app.util.time import beijing_now_iso
from storage.benchmark.saved_view_repo import BenchmarkSavedViewRepository
from storage.benchmark.snapshot_repo import BenchmarkSnapshotRepository
from ui.backend.background_store import BackgroundTaskStoreMixin
from ui.backend.constants import (
    MANUAL_STOP_REASON,
    ROLE_ORDER,
)
from ui.backend.errors import domain_error_detail, release_stage_diagnostic
from ui.backend.game_store import GameStoreMixin
from ui.backend.schemas import (
    BenchmarkLifecycleRequest,
    BenchmarkRequest,
    BenchmarkSnapshotRequest,
    BenchmarkViewRequest,
    EvolutionStartRequest,
    automatic_evolution_request,
)
from ui.backend.services import BENCHMARK_PUBLIC_METHODS, BenchmarkService
from ui.backend.live_game import BroadcastEventSink, LiveGameSession
from ui.backend.task_events import TaskEventLog
from ui.backend.task_state import (
    _filter_values,
    _match_filter,
    _pagination,
    _set_task_contract,
)
from ui.backend.startup_checks import default_startup_checks, log_startup_checks, run_startup_checks

_log = logging.getLogger(__name__)

_BENCHMARK_PLAYER_COUNT = 12
_BENCHMARK_DEFAULT_GAME_CONCURRENCY = 3
_BENCHMARK_DEFAULT_JUDGE_CONCURRENCY = 1
_BENCHMARK_GAME_UNIT_TOKENS = 1120
_BENCHMARK_JUDGE_DECISION_TOKENS = 810
_BENCHMARK_COST_PER_1K_TOKENS = 0.002
_BENCHMARK_CURRENCY = "USD"
_BENCHMARK_GAME_UNIT_SECONDS = 1.2
_BENCHMARK_JUDGE_DECISION_SECONDS = 1.0
_BENCHMARK_EVAL_BATCH_SETUP_SECONDS = 10.0


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


def _ceil_div(numerator: int, denominator: int) -> int:
    if numerator <= 0:
        return 0
    safe_denominator = max(1, int(denominator or 1))
    return (int(numerator) + safe_denominator - 1) // safe_denominator


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _rounded_cost(value: Any) -> float:
    try:
        return round(float(value or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def _benchmark_estimated_tokens(*, game_decision_units: int, judge_decision_units: int) -> int:
    return (
        int(game_decision_units or 0) * _BENCHMARK_GAME_UNIT_TOKENS
        + int(judge_decision_units or 0) * _BENCHMARK_JUDGE_DECISION_TOKENS
    )


def _benchmark_estimated_cost(estimated_tokens: int) -> float:
    return _rounded_cost((int(estimated_tokens or 0) / 1000.0) * _BENCHMARK_COST_PER_1K_TOKENS)


def _benchmark_concurrency_policy(
    *,
    eval_batch_count: int,
    game_count: int,
    max_days: int,
    player_count: int,
    judge_enabled: bool,
    judge_decision_units: int,
    judge_concurrency: Any,
) -> dict[str, Any]:
    game_concurrency = max(1, min(_BENCHMARK_DEFAULT_GAME_CONCURRENCY, max(1, int(game_count or 1))))
    effective_judge_concurrency = (
        _positive_int(judge_concurrency) or _BENCHMARK_DEFAULT_JUDGE_CONCURRENCY
        if judge_enabled
        else 0
    )
    game_units_per_eval_batch = int(game_count or 0) * int(max_days or 0) * int(player_count or 0)
    game_waves_per_eval_batch = _ceil_div(game_units_per_eval_batch, game_concurrency)
    judge_waves = _ceil_div(int(judge_decision_units or 0), effective_judge_concurrency) if judge_enabled else 0
    expected_duration_seconds = round(
        int(eval_batch_count or 0) * _BENCHMARK_EVAL_BATCH_SETUP_SECONDS
        + game_waves_per_eval_batch * int(eval_batch_count or 0) * _BENCHMARK_GAME_UNIT_SECONDS
        + judge_waves * _BENCHMARK_JUDGE_DECISION_SECONDS
    )
    return {
        "policy": "bounded_sequential_eval_batches",
        "role_batch_concurrency": 1,
        "eval_batch_count": int(eval_batch_count or 0),
        "game_concurrency": game_concurrency,
        "judge_concurrency": effective_judge_concurrency,
        "judge_enabled": bool(judge_enabled),
        "game_waves_per_eval_batch": game_waves_per_eval_batch,
        "judge_waves": judge_waves,
        "expected_duration_seconds": max(0, int(expected_duration_seconds)),
        "notes": [
            "role-version benchmarks run one evaluation batch per role",
            "model benchmarks run one full-role evaluation batch",
            "games inside each evaluation batch use bounded game concurrency",
        ],
    }


def _benchmark_budget_payload(
    request: BenchmarkRequest,
    *,
    estimated_units: int,
    estimated_tokens: int,
    estimated_cost: float,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    reasons: list[str] = []
    if request.budget_limit_units is not None and int(estimated_units) > int(request.budget_limit_units):
        reasons.append("estimated_units_exceed_limit_units")
        evidence.append(
            {
                "metric": "estimated_units",
                "estimated": int(estimated_units),
                "limit": int(request.budget_limit_units),
                "delta": int(estimated_units) - int(request.budget_limit_units),
                "unit": "llm_call_unit",
            }
        )
    if request.budget_limit_cost is not None and float(estimated_cost) > float(request.budget_limit_cost):
        reasons.append("estimated_cost_exceed_limit_cost")
        evidence.append(
            {
                "metric": "estimated_cost",
                "estimated": _rounded_cost(estimated_cost),
                "limit": _rounded_cost(request.budget_limit_cost),
                "delta": _rounded_cost(float(estimated_cost) - float(request.budget_limit_cost)),
                "unit": _BENCHMARK_CURRENCY,
            }
        )
    return {
        "limit_units": request.budget_limit_units,
        "estimated_units": int(estimated_units),
        "limit_cost": _rounded_cost(request.budget_limit_cost) if request.budget_limit_cost is not None else None,
        "estimated_cost": _rounded_cost(estimated_cost),
        "estimated_tokens": int(estimated_tokens),
        "currency": _BENCHMARK_CURRENCY,
        "stop_after_budget_units": request.stop_after_budget_units,
        "stop_after_predicted": (
            request.stop_after_budget_units is not None
            and int(estimated_units) > int(request.stop_after_budget_units)
        ),
        "exceeded": {
            "value": bool(evidence),
            "reasons": reasons,
            "evidence": evidence,
        },
    }


def _benchmark_budget_exceeded(budget: dict[str, Any]) -> bool:
    exceeded = budget.get("exceeded")
    if isinstance(exceeded, dict):
        return bool(exceeded.get("value"))
    return bool(exceeded)


def _benchmark_budget_error_detail(run_plan: dict[str, Any]) -> dict[str, Any]:
    budget = run_plan.get("budget") if isinstance(run_plan.get("budget"), dict) else {}
    exceeded = budget.get("exceeded") if isinstance(budget.get("exceeded"), dict) else {}
    return domain_error_detail(
        code="benchmark_budget_exceeded",
        message="Benchmark budget exceeded.",
        detail={
            "message": "benchmark budget exceeded",
            "estimated": {
                "units": budget.get("estimated_units"),
                "tokens": budget.get("estimated_tokens"),
                "cost": budget.get("estimated_cost"),
                "currency": budget.get("currency"),
            },
            "limit": {
                "units": budget.get("limit_units"),
                "cost": budget.get("limit_cost"),
                "currency": budget.get("currency"),
            },
            "budget": budget,
        },
        diagnostics=[
            {
                "kind": "budget_exceeded",
                "estimated_units": budget.get("estimated_units"),
                "limit_units": budget.get("limit_units"),
                "estimated_tokens": budget.get("estimated_tokens"),
                "estimated_cost": budget.get("estimated_cost"),
                "limit_cost": budget.get("limit_cost"),
                "currency": budget.get("currency"),
                "reasons": exceeded.get("reasons", []) if isinstance(exceeded, dict) else [],
                "evidence": exceeded.get("evidence", []) if isinstance(exceeded, dict) else [],
            }
        ],
    )


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
    _benchmark_service: BenchmarkService | None = field(default=None, init=False, repr=False)
    _registry: VersionRegistryProtocol | None = field(default=None, init=False, repr=False)
    _role_overview_cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    startup_checks: dict[str, Any] = field(default_factory=default_startup_checks)

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
        from storage.provider import storage_provider_from_env

        return storage_provider_from_env(paths=self.paths).open_wolf_connection()

    @property
    def benchmark_service(self) -> BenchmarkService:
        if self._benchmark_service is None:
            missing = [
                method_name
                for method_name in BENCHMARK_PUBLIC_METHODS
                if not hasattr(self, f"_{method_name}")
            ]
            if missing:
                raise RuntimeError(f"BenchmarkService missing BackendStore implementations: {', '.join(missing)}")
            self._benchmark_service = BenchmarkService(
                self,
                callables={
                    method_name: getattr(self, f"_{method_name}")
                    for method_name in BENCHMARK_PUBLIC_METHODS
                },
            )
        return self._benchmark_service

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

    def leaderboard_unrankable_evidence(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return self.benchmark_service.leaderboard_unrankable_evidence(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            limit=limit,
            rows=rows,
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

    def create_benchmark_snapshot(self, request: BenchmarkSnapshotRequest) -> dict[str, Any]:
        return self.benchmark_service.create_benchmark_snapshot(request)

    def list_benchmark_snapshots(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self.benchmark_service.list_benchmark_snapshots(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            limit=limit,
        )

    def get_benchmark_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        return self.benchmark_service.get_benchmark_snapshot(snapshot_id)

    def benchmark_snapshot_export(self, snapshot_id: str, *, format: str = "json") -> dict[str, Any]:
        return self.benchmark_service.benchmark_snapshot_export(snapshot_id, format=format)

    def benchmark_snapshot_compare(
        self,
        snapshot_id: str,
        *,
        against_snapshot_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.benchmark_service.benchmark_snapshot_compare(
            snapshot_id,
            against_snapshot_id=against_snapshot_id,
            limit=limit,
        )

    def save_benchmark_view(self, request: BenchmarkViewRequest) -> dict[str, Any]:
        return self.benchmark_service.save_benchmark_view(request)

    def list_benchmark_views(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        view_key: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self.benchmark_service.list_benchmark_views(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            view_key=view_key,
            limit=limit,
        )

    def get_benchmark_view(self, view_key: str) -> dict[str, Any]:
        return self.benchmark_service.get_benchmark_view(view_key)

    def delete_benchmark_view(self, view_key: str) -> dict[str, Any]:
        return self.benchmark_service.delete_benchmark_view(view_key)

    def list_benchmark_specs(self) -> list[dict[str, Any]]:
        return self.benchmark_service.list_benchmark_specs()

    def get_benchmark_spec_summary(self, benchmark_id: str) -> dict[str, Any]:
        return self.benchmark_service.get_benchmark_spec_summary(benchmark_id)

    def update_benchmark_lifecycle(self, benchmark_id: str, request: BenchmarkLifecycleRequest) -> dict[str, Any]:
        return self.benchmark_service.update_benchmark_lifecycle(benchmark_id, request)

    def list_benchmark_seed_sets(self) -> dict[str, Any]:
        return self.benchmark_service.list_benchmark_seed_sets()

    def get_benchmark_seed_set(self, seed_set_id: str) -> dict[str, Any]:
        return self.benchmark_service.get_benchmark_seed_set(seed_set_id)

    def plan_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        return self.benchmark_service.plan_benchmark(request)

    def benchmark_batch_detail(self, batch_id: str) -> dict[str, Any]:
        return self.benchmark_service.benchmark_batch_detail(batch_id)

    def benchmark_batch_games(
        self,
        batch_id: str,
        *,
        result_batch_id: str | None = None,
        target_role: str | None = None,
        status: str | None = None,
        seed: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.benchmark_service.benchmark_batch_games(
            batch_id,
            result_batch_id=result_batch_id,
            target_role=target_role,
            status=status,
            seed=seed,
            limit=limit,
            offset=offset,
        )

    def benchmark_batch_diagnostics(
        self,
        batch_id: str,
        *,
        target_role: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
    ) -> dict[str, Any]:
        return self.benchmark_service.benchmark_batch_diagnostics(
            batch_id,
            target_role=target_role,
            kind=kind,
            level=level,
            status=status,
            stage=stage,
            seed=seed,
        )

    def benchmark_batch_report(self, batch_id: str, *, format: str = "json") -> dict[str, Any]:
        return self.benchmark_service.benchmark_batch_report(batch_id, format=format)

    def benchmark_reports(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.benchmark_service.benchmark_reports(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            model_id=model_id,
            model_config_hash=model_config_hash,
            status=status,
            limit=limit,
            offset=offset,
        )

    def benchmark_diagnostics(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.benchmark_service.benchmark_diagnostics(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            model_id=model_id,
            model_config_hash=model_config_hash,
            kind=kind,
            level=level,
            status=status,
            stage=stage,
            seed=seed,
            limit=limit,
            offset=offset,
        )

    def benchmark_model_runtime(self, request: BenchmarkRequest | None = None) -> dict[str, Any]:
        return self.benchmark_service.benchmark_model_runtime(request)

    def queue_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        return self.benchmark_service.queue_benchmark(request)

    async def run_queued_benchmark(self, batch_id: str, request: BenchmarkRequest) -> None:
        await self.benchmark_service.run_queued_benchmark(batch_id, request)

    def _leaderboard_scores_for_role(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Load persisted benchmark scores for a role, keyed by version id.

        Reads the benchmark_leaderboard table populated by the eval pipeline.
        Returns {} on any failure so the leaderboard endpoint still renders.
        """
        from app.lib.score import open_eval_connection

        scores: dict[str, dict[str, Any]] = {}
        conn = None
        try:
            conn = open_eval_connection(self.paths)
            where = "WHERE scope = 'role_version' AND target_role = ? "
            params: list[Any] = [role]
            if evaluation_set_id:
                where += "AND evaluation_set_id = ? "
                params.append(evaluation_set_id)
            rows = conn.execute(
                "SELECT scope, subject_id, model_id, model_config_hash, target_role, target_version_id, "
                "comparison_group_id, evaluation_set_id, seed_set_id, games_played, valid_game_rate, "
                "strength_score, avg_role_score, by_role_category_scores, avg_speech_score, avg_vote_score, "
                "avg_skill_score, avg_logic_score, avg_team_score, risk_penalty, fallback_rate, llm_error_rate, "
                "policy_adjusted_rate, target_side_win_rate, rankable, data_sufficient, summary, updated_at "
                "FROM benchmark_leaderboard "
                f"{where}"
                "ORDER BY updated_at DESC",
                tuple(params),
            ).fetchall()
            for row in rows:
                vid = row["target_version_id"]
                if vid and vid not in scores:  # newest row per version wins
                    scores[vid] = self._leaderboard_row_payload(row)
        except Exception:  # noqa: BLE001 — leaderboard read is best-effort
            _log.warning("leaderboard_scores_for_role failed for %s", role, exc_info=True)
        finally:
            if conn is not None:
                conn.close()
        return scores

    def _leaderboard_entries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Load benchmark leaderboard rows with explicit scope isolation."""
        from app.lib.score import open_eval_connection

        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope not in {"", "role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported leaderboard scope")
        rows_out: list[dict[str, Any]] = []
        conn = None
        try:
            conn = open_eval_connection(self.paths)
            where = "WHERE 1 = 1 "
            params: list[Any] = []
            if normalized_scope:
                where += "AND scope = ? "
                params.append(normalized_scope)
            if evaluation_set_id:
                where += "AND evaluation_set_id = ? "
                params.append(evaluation_set_id)
            if target_role:
                where += "AND target_role = ? "
                params.append(target_role)
            capped_limit = max(1, min(int(limit or 100), 500))
            params.append(capped_limit)
            rows = conn.execute(
                "SELECT scope, subject_id, model_id, model_config_hash, target_role, target_version_id, "
                "comparison_group_id, evaluation_set_id, seed_set_id, games_played, valid_game_rate, "
                "strength_score, avg_role_score, by_role_category_scores, avg_speech_score, avg_vote_score, "
                "avg_skill_score, avg_logic_score, avg_team_score, risk_penalty, fallback_rate, llm_error_rate, "
                "policy_adjusted_rate, target_side_win_rate, rankable, data_sufficient, summary, updated_at "
                "FROM benchmark_leaderboard "
                f"{where}"
                "ORDER BY rankable DESC, strength_score DESC, avg_role_score DESC, updated_at DESC "
                "LIMIT ?",
                tuple(params),
            ).fetchall()
            rows_out = [self._leaderboard_row_payload(row) for row in rows]
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - leaderboard read is best-effort
            _log.warning("leaderboard_entries failed", exc_info=True)
        finally:
            if conn is not None:
                conn.close()
        return rows_out

    def _model_leaderboard_entries(
        self,
        *,
        evaluation_set_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Load model-scope benchmark leaderboard rows."""
        return self.leaderboard_entries(scope="model", evaluation_set_id=evaluation_set_id, limit=limit)

    def _leaderboard_unrankable_evidence(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return non-ranking evidence rows for subjects excluded by leaderboard gates."""
        normalized_scope = str(scope or "").strip().lower() or None
        source_rows = rows if rows is not None else self.leaderboard_entries(
            scope=normalized_scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role if normalized_scope != "model" else None,
            limit=limit,
        )
        evidence = _filter_unrankable_evidence_for_compare(
            source_rows,
            scope=normalized_scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role if normalized_scope != "model" else None,
        )
        evidence.extend(
            self._benchmark_batch_unrankable_evidence(
                scope=normalized_scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role if normalized_scope != "model" else None,
                limit=limit,
            )
        )
        return _dedupe_unrankable_evidence(evidence)[: max(1, min(int(limit or 100), 500))]

    def _benchmark_batch_unrankable_evidence(
        self,
        *,
        scope: str | None,
        evaluation_set_id: str | None,
        target_role: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Recover gate-failed benchmark results that never reached leaderboard rows."""
        normalized_scope = str(scope or "").strip().lower() or None
        requested_eval = str(evaluation_set_id or "").strip()
        requested_role = str(target_role or "").strip().lower()
        evidence: list[dict[str, Any]] = []
        capped_limit = max(1, min(int(limit or 100), 500))
        for batch in self.evolution_batches.values():
            if not isinstance(batch, dict):
                continue
            meta = _benchmark_batch_boundary(batch)
            batch_scope = str(meta.get("target_type") or "").strip().lower()
            if normalized_scope and batch_scope and batch_scope != normalized_scope:
                continue
            batch_eval = str(meta.get("evaluation_set_id") or "").strip()
            if requested_eval and batch_eval != requested_eval:
                continue
            for index, result in enumerate(_benchmark_results(batch), start=1):
                if not _benchmark_result_has_unrankable_evidence(result):
                    continue
                result_role = _benchmark_result_role(result)
                if requested_role and str(result_role or "").strip().lower() != requested_role:
                    continue
                result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
                summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
                gate = result.get("leaderboard_gate") if isinstance(result.get("leaderboard_gate"), dict) else {}
                gate_metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
                result_batch_id = _benchmark_result_batch_id(result)
                model_id = _first_text(result.get("model_id"), result_config.get("model_id"), meta.get("model_id"))
                model_config_hash = _first_text(
                    result.get("model_config_hash"),
                    result_config.get("model_config_hash"),
                    meta.get("model_config_hash"),
                )
                target_version_id = _first_text(result.get("target_version_id"), result_config.get("target_version_id"))
                subject_id = (
                    model_config_hash or model_id or result_batch_id
                    if batch_scope == "model"
                    else target_version_id or result_batch_id
                )
                total_games = _first_int(
                    result.get("total_games"),
                    result.get("game_count"),
                    result.get("attempted_game_count"),
                    result_config.get("game_count"),
                    summary.get("total_games"),
                    summary.get("game_count"),
                    default=_benchmark_result_game_count(result),
                )
                completed_games = _first_int(
                    result.get("completed_games"),
                    result.get("completed"),
                    result.get("games_played"),
                    summary.get("completed_games"),
                    summary.get("games_played"),
                    gate_metrics.get("completed_games"),
                    default=_benchmark_result_game_count(result),
                )
                reason = _first_text(
                    result.get("rankable_reason"),
                    result.get("leaderboard_skipped_reason"),
                    gate.get("reason"),
                    summary.get("rankable_reason"),
                    "rankable gate failed",
                )
                row_summary = dict(summary)
                row_summary.update(
                    {
                        "batch_id": meta.get("batch_id"),
                        "result_batch_id": result_batch_id,
                        "rankable_reason": reason,
                        "leaderboard_skipped_reason": result.get("leaderboard_skipped_reason") or gate.get("reason"),
                        "completed_games": completed_games,
                        "total_games": total_games,
                    }
                )
                row = {
                    "scope": batch_scope or normalized_scope,
                    "hash": subject_id,
                    "subject_id": subject_id,
                    "model_id": model_id or None,
                    "model_config_hash": model_config_hash or None,
                    "target_role": result_role,
                    "target_version_id": target_version_id or None,
                    "comparison_group_id": meta.get("batch_id"),
                    "evaluation_set_id": batch_eval or requested_eval,
                    "seed_set_id": meta.get("seed_set_id"),
                    "game_count": total_games,
                    "games_played": completed_games,
                    "completed_games": completed_games,
                    "total_games": total_games,
                    "valid_game_rate": _first_float(
                        result.get("valid_game_rate"),
                        summary.get("valid_game_rate"),
                        gate_metrics.get("valid_game_rate"),
                    ),
                    "rankable": False,
                    "rankable_reason": reason,
                    "leaderboard_skipped_reason": result.get("leaderboard_skipped_reason") or gate.get("reason"),
                    "summary": row_summary,
                    "batch_id": meta.get("batch_id"),
                    "result_batch_id": result_batch_id,
                    "updated_at": batch.get("finished_at") or batch.get("updated_at") or batch.get("started_at"),
                    "source": "benchmark_batch",
                }
                evidence.append(_leaderboard_unrankable_evidence_row(row, index=index))
                if len(evidence) >= capped_limit:
                    return evidence
        return evidence

    def _leaderboard_compare(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        baseline_subject_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return canonical leaderboard deltas against a pinned baseline row."""
        normalized_scope = str(scope or "").strip().lower() or None
        rows = self.leaderboard_entries(
            scope=normalized_scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role if normalized_scope != "model" else None,
            limit=limit,
        )
        rankable_rows = [row for row in rows if row.get("rankable") is not False]
        unrankable_evidence = self.leaderboard_unrankable_evidence(
            scope=normalized_scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role if normalized_scope != "model" else None,
            limit=limit,
            rows=rows,
        )
        baseline = _select_leaderboard_baseline(rankable_rows, baseline_subject_id=baseline_subject_id)
        compare_rows = [
            _leaderboard_compare_row(row, baseline, scope=normalized_scope, target_role=target_role)
            for row in rankable_rows
        ]
        summary = _leaderboard_compare_summary(compare_rows)
        summary["unrankable_count"] = len(unrankable_evidence)
        summary["unrankable_evidence_count"] = len(unrankable_evidence)
        return {
            "kind": "benchmark_leaderboard_compare",
            "schema_version": 1,
            "scope": normalized_scope,
            "evaluation_set_id": evaluation_set_id,
            "target_role": target_role,
            "baseline_subject_id": _leaderboard_subject_key(baseline) if baseline else None,
            "baseline": baseline,
            "rows": compare_rows,
            "unrankable_evidence": unrankable_evidence,
            "summary": summary,
        }

    def _create_benchmark_snapshot(self, request: BenchmarkSnapshotRequest) -> dict[str, Any]:
        """Freeze the current leaderboard rows into an immutable release snapshot."""
        scope = str(request.scope or "").strip().lower()
        if scope not in {"role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported benchmark snapshot scope")
        evaluation_set_id = str(request.evaluation_set_id or "").strip()
        if not evaluation_set_id:
            raise HTTPException(status_code=422, detail="evaluation_set_id is required")
        target_role = str(request.target_role or "").strip().lower() or None
        if scope == "role_version" and not target_role:
            raise HTTPException(status_code=422, detail="target_role is required for role_version snapshots")

        rows = self.leaderboard_entries(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role if scope == "role_version" else None,
            limit=request.limit,
        )
        rows = _filter_benchmark_snapshot_rows(rows, request.source_filter)
        if not rows:
            raise HTTPException(status_code=422, detail="cannot snapshot empty leaderboard")

        now = beijing_now_iso()
        frozen_rows = [_json_clone(row) for row in rows]
        release_gate = _benchmark_snapshot_release_gate(
            frozen_rows,
            request=request,
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            seed_set_id=request.seed_set_id,
            benchmark_config_hash=request.benchmark_config_hash,
            target_role=target_role,
            config=self._benchmark_snapshot_release_gate_config(request),
        )
        if not release_gate.get("ok"):
            raise HTTPException(status_code=422, detail=_benchmark_snapshot_release_gate_error_detail(release_gate))
        rankable_count = sum(1 for row in frozen_rows if row.get("rankable") is not False)
        summary = {
            "row_count": len(frozen_rows),
            "rankable_count": rankable_count,
            "unrankable_count": len(frozen_rows) - rankable_count,
            "scope": scope,
            "evaluation_set_id": evaluation_set_id,
            "target_role": target_role,
            "source_filter_applied": _benchmark_snapshot_source_filter_summary(request.source_filter),
            "release_gate_ok": bool(release_gate.get("ok")),
            "release_gate_blocker_count": len(release_gate.get("blockers") or []),
            "release_gate_warning_count": len(release_gate.get("warnings") or []),
            "release_gate": _json_clone(release_gate),
        }
        source_summary = _benchmark_snapshot_source_summary(frozen_rows)
        summary.update(source_summary)
        content_payload = {
            "scope": scope,
            "benchmark_id": request.benchmark_id,
            "benchmark_version": request.benchmark_version,
            "evaluation_set_id": evaluation_set_id,
            "seed_set_id": request.seed_set_id,
            "benchmark_config_hash": request.benchmark_config_hash,
            "target_role": target_role,
            "source_filter": request.source_filter,
            "view_config": request.view_config,
            "rows": frozen_rows,
            "summary": summary,
            "release_gate": release_gate,
            **source_summary,
        }
        content_hash = _stable_payload_hash(content_payload)
        snapshot_id = f"bench_snap_{uuid.uuid4().hex[:10]}"
        snapshot = {
            "kind": "benchmark_leaderboard_snapshot",
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "title": str(request.title or "").strip() or _default_benchmark_snapshot_title(scope, evaluation_set_id, target_role),
            "release_notes": str(request.release_notes or ""),
            "scope": scope,
            "benchmark_id": request.benchmark_id,
            "benchmark_version": request.benchmark_version,
            "evaluation_set_id": evaluation_set_id,
            "seed_set_id": request.seed_set_id,
            "benchmark_config_hash": request.benchmark_config_hash,
            "target_role": target_role,
            "source_filter": _json_clone(request.source_filter),
            "view_config": _json_clone(request.view_config),
            "rows": frozen_rows,
            "summary": summary,
            "release_gate": release_gate,
            "row_count": len(frozen_rows),
            **source_summary,
            "content_hash": content_hash,
            "created_at": now,
        }
        self.benchmark_leaderboard_snapshots[snapshot_id] = _json_clone(snapshot)
        try:
            self._persist_benchmark_leaderboard_snapshot(snapshot)
        except Exception:  # noqa: BLE001 - keep API usable if snapshot persistence is temporarily unavailable
            _log.warning("persist benchmark leaderboard snapshot failed", exc_info=True)
        return _benchmark_snapshot_detail_payload(snapshot)

    def _benchmark_snapshot_release_gate_config(self, request: BenchmarkSnapshotRequest) -> dict[str, Any]:
        benchmark_id = str(request.benchmark_id or "").strip()
        if not benchmark_id:
            return {"thresholds": {"require_suite_lifecycle": False}}
        try:
            summary = self.get_benchmark_spec_summary(benchmark_id)
        except HTTPException:
            return {
                "benchmark_id": benchmark_id,
                "benchmark_config_hash": request.benchmark_config_hash,
                "thresholds": {"require_suite_lifecycle": False},
            }
        return {
            **summary,
            "suite": _json_clone(summary),
            "benchmark_id": benchmark_id,
            "benchmark_config_hash": request.benchmark_config_hash or summary.get("config_hash"),
        }

    def _list_benchmark_snapshots(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return benchmark leaderboard snapshot summaries without frozen rows."""
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope and normalized_scope not in {"role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported benchmark snapshot scope")
        normalized_target_role = str(target_role or "").strip().lower()
        snapshots = self._load_benchmark_snapshot_summaries(
            scope=normalized_scope or None,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=normalized_target_role or None,
            limit=limit,
        )
        return {
            "kind": "benchmark_leaderboard_snapshots",
            "schema_version": 1,
            "scope": normalized_scope or None,
            "evaluation_set_id": evaluation_set_id,
            "benchmark_id": benchmark_id,
            "target_role": normalized_target_role or None,
            "items": snapshots,
        }

    def _get_benchmark_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Return one frozen benchmark leaderboard snapshot with copied rows."""
        normalized_id = str(snapshot_id or "").strip()
        if not normalized_id:
            raise HTTPException(status_code=404, detail="benchmark snapshot not found")
        snapshot = self._load_benchmark_snapshot_detail(normalized_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="benchmark snapshot not found")
        return _benchmark_snapshot_detail_payload(snapshot)

    def _benchmark_snapshot_export(self, snapshot_id: str, *, format: str = "json") -> dict[str, Any]:
        """Return an immutable snapshot export payload for release/audit workflows."""
        snapshot = self.get_benchmark_snapshot(snapshot_id)
        normalized_format = str(format or "json").strip().lower()
        if normalized_format == "json":
            content = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
        elif normalized_format == "markdown":
            content = _benchmark_snapshot_markdown(snapshot)
        elif normalized_format == "csv":
            content = _benchmark_snapshot_csv(snapshot)
        else:
            raise HTTPException(status_code=422, detail="unsupported benchmark snapshot export format")
        export_content_hash = _text_content_hash(content)
        return {
            "kind": "benchmark_leaderboard_snapshot_export",
            "schema_version": 1,
            "snapshot_id": snapshot["snapshot_id"],
            "format": normalized_format,
            "content": content,
            "content_hash": snapshot.get("content_hash"),
            "export_content_hash": export_content_hash,
            "artifact_hash": export_content_hash,
            "release_gate": _json_clone(snapshot.get("release_gate") or {}),
            "release_manifest": _json_clone(snapshot.get("release_manifest") or {}),
            "snapshot": snapshot,
        }

    def _benchmark_snapshot_compare(
        self,
        snapshot_id: str,
        *,
        against_snapshot_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Compare the current leaderboard or another frozen release snapshot against one snapshot."""
        normalized_id = str(snapshot_id or "").strip()
        if not normalized_id:
            raise HTTPException(status_code=404, detail="benchmark snapshot not found")
        snapshot = self._load_benchmark_snapshot_detail(normalized_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="benchmark snapshot not found")
        scope = str(snapshot.get("scope") or "").strip().lower() or "role_version"
        if scope not in {"role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported benchmark snapshot scope")
        evaluation_set_id = str(snapshot.get("evaluation_set_id") or "").strip() or None
        target_role = str(snapshot.get("target_role") or "").strip().lower() or None
        frozen_rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
        normalized_against_id = str(against_snapshot_id or "").strip()
        against_snapshot: dict[str, Any] | None = None
        if normalized_against_id:
            against_snapshot = self._load_benchmark_snapshot_detail(normalized_against_id)
            if against_snapshot is None:
                raise HTTPException(status_code=404, detail="benchmark snapshot not found")
            current_rows = against_snapshot.get("rows") if isinstance(against_snapshot.get("rows"), list) else []
            current_rows = current_rows[:limit]
            compare_mode = "snapshot_to_snapshot"
            initial_warnings = _benchmark_snapshot_pair_boundary_warnings(
                snapshot,
                against_snapshot,
                scope=scope,
                target_role=target_role,
            )
        else:
            current_rows = self.leaderboard_entries(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role if scope == "role_version" else None,
                limit=limit,
            )
            current_rows = _filter_benchmark_snapshot_rows(current_rows, snapshot.get("source_filter"))
            compare_mode = "current_vs_snapshot"
            initial_warnings = []
        compare = _benchmark_snapshot_compare_payload(
            snapshot,
            current_rows,
            frozen_rows,
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            compare_mode=compare_mode,
            against_snapshot=against_snapshot,
            initial_boundary_warnings=initial_warnings,
        )
        return compare

    def _save_benchmark_view(self, request: BenchmarkViewRequest) -> dict[str, Any]:
        """Persist a reusable benchmark leaderboard/table view."""
        view_key = str(request.view_key or "").strip()
        if not view_key:
            raise HTTPException(status_code=422, detail="view_key is required")
        now = beijing_now_iso()
        existing = self.benchmark_saved_views.get(view_key) or {}
        created_at = existing.get("created_at") or now
        view = {
            "kind": "benchmark_saved_view",
            "schema_version": 1,
            "view_key": view_key,
            "name": str(request.name or "").strip() or "Default view",
            "scope": request.scope,
            "benchmark_id": request.benchmark_id,
            "evaluation_set_id": request.evaluation_set_id,
            "target_role": request.target_role,
            "view_config": _json_clone(request.view_config),
            "created_at": created_at,
            "updated_at": now,
        }
        self.benchmark_saved_views[view_key] = _json_clone(view)
        try:
            self._persist_benchmark_saved_view(view)
        except Exception:  # noqa: BLE001 - saved views remain usable in memory
            _log.warning("persist benchmark saved view failed", exc_info=True)
        return _benchmark_view_payload(view)

    def _list_benchmark_views(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        view_key: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return saved benchmark table/filter views."""
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope and normalized_scope not in {"role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported benchmark view scope")
        normalized_target_role = str(target_role or "").strip().lower()
        rows = self._load_benchmark_saved_views(
            scope=normalized_scope or None,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=normalized_target_role or None,
            view_key=view_key,
            limit=limit,
        )
        return {
            "kind": "benchmark_saved_views",
            "schema_version": 1,
            "scope": normalized_scope or None,
            "evaluation_set_id": evaluation_set_id,
            "benchmark_id": benchmark_id,
            "target_role": normalized_target_role or None,
            "items": rows,
        }

    def _get_benchmark_view(self, view_key: str) -> dict[str, Any]:
        """Return one saved benchmark view."""
        normalized_key = str(view_key or "").strip()
        if not normalized_key:
            raise HTTPException(status_code=404, detail="benchmark view not found")
        rows = self._load_benchmark_saved_views(view_key=normalized_key, limit=1)
        if not rows:
            raise HTTPException(status_code=404, detail="benchmark view not found")
        return rows[0]

    def _delete_benchmark_view(self, view_key: str) -> dict[str, Any]:
        """Delete a saved benchmark view."""
        normalized_key = str(view_key or "").strip()
        if not normalized_key:
            raise HTTPException(status_code=404, detail="benchmark view not found")
        existed = normalized_key in self.benchmark_saved_views
        self.benchmark_saved_views.pop(normalized_key, None)
        try:
            existed = self._delete_benchmark_saved_view(normalized_key) or existed
        except Exception:  # noqa: BLE001 - cache delete still applies
            _log.warning("delete benchmark saved view failed", exc_info=True)
        if not existed:
            raise HTTPException(status_code=404, detail="benchmark view not found")
        return {
            "kind": "benchmark_saved_view_deleted",
            "schema_version": 1,
            "view_key": normalized_key,
            "deleted": True,
        }

    def _persist_benchmark_leaderboard_snapshot(self, snapshot: dict[str, Any]) -> None:
        conn = None
        try:
            from app.lib.score import open_eval_connection

            conn = open_eval_connection(self.paths)
            BenchmarkSnapshotRepository(conn).save(snapshot)
        finally:
            if conn is not None:
                conn.close()

    def _load_benchmark_snapshot_summaries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        conn = None
        try:
            from app.lib.score import open_eval_connection

            conn = open_eval_connection(self.paths)
            snapshots = BenchmarkSnapshotRepository(conn).list(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                limit=limit,
            )
            rows = [_benchmark_snapshot_summary_payload(snapshot) for snapshot in snapshots]
        except Exception:  # noqa: BLE001 - fallback to process cache when storage is unavailable
            _log.warning("load benchmark leaderboard snapshots failed", exc_info=True)
            rows = [
                _benchmark_snapshot_summary_payload(snapshot)
                for snapshot in self.benchmark_leaderboard_snapshots.values()
            ]
            rows = _filter_benchmark_snapshot_cache(
                rows,
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                limit=limit,
            )
        finally:
            if conn is not None:
                conn.close()
        return rows

    def _load_benchmark_snapshot_detail(self, snapshot_id: str) -> dict[str, Any] | None:
        conn = None
        try:
            from app.lib.score import open_eval_connection

            conn = open_eval_connection(self.paths)
            snapshot = BenchmarkSnapshotRepository(conn).get(snapshot_id)
            if snapshot is None:
                return self.benchmark_leaderboard_snapshots.get(snapshot_id)
            return snapshot
        except Exception:  # noqa: BLE001 - fallback to process cache when storage is unavailable
            _log.warning("load benchmark leaderboard snapshot detail failed", exc_info=True)
            return self.benchmark_leaderboard_snapshots.get(snapshot_id)
        finally:
            if conn is not None:
                conn.close()

    def _persist_benchmark_saved_view(self, view: dict[str, Any]) -> None:
        conn = None
        try:
            from app.lib.score import open_eval_connection

            conn = open_eval_connection(self.paths)
            BenchmarkSavedViewRepository(conn).save(view)
        finally:
            if conn is not None:
                conn.close()

    def _load_benchmark_saved_views(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        view_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        conn = None
        try:
            from app.lib.score import open_eval_connection

            conn = open_eval_connection(self.paths)
            views = BenchmarkSavedViewRepository(conn).list(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                view_key=view_key,
                limit=limit,
            )
            rows = [_benchmark_view_payload(view) for view in views]
        except Exception:  # noqa: BLE001 - fallback to process cache when storage is unavailable
            _log.warning("load benchmark saved views failed", exc_info=True)
            rows = [
                _benchmark_view_payload(view)
                for view in self.benchmark_saved_views.values()
            ]
            rows = _filter_benchmark_view_cache(
                rows,
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                view_key=view_key,
                limit=limit,
            )
        finally:
            if conn is not None:
                conn.close()
        return rows

    def _delete_benchmark_saved_view(self, view_key: str) -> bool:
        conn = None
        try:
            from app.lib.score import open_eval_connection

            conn = open_eval_connection(self.paths)
            return BenchmarkSavedViewRepository(conn).delete(view_key)
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _leaderboard_row_payload(row: Any) -> dict[str, Any]:
        payload = _row_to_dict(row)
        by_role = _decode_json_field(payload.get("by_role_category_scores"), fallback={})
        summary = _decode_json_field(payload.get("summary"), fallback={})
        game_count = int(payload.get("games_played") or 0)
        scope = str(payload.get("scope") or "")
        subject_id = str(payload.get("subject_id") or "")
        target_version_id = payload.get("target_version_id")
        model_id = payload.get("model_id")
        model_config_hash = payload.get("model_config_hash")
        score = float(payload.get("avg_role_score") or 0.0)
        strength_score = float(payload.get("strength_score") or score or 0.0)
        source_run_id = _first_text(
            payload.get("source_run_id"),
            payload.get("run_id"),
            payload.get("batch_id"),
            summary.get("source_run_id") if isinstance(summary, dict) else None,
            summary.get("run_id") if isinstance(summary, dict) else None,
            summary.get("batch_id") if isinstance(summary, dict) else None,
            payload.get("comparison_group_id"),
        )
        result_batch_id = _first_text(
            payload.get("result_batch_id"),
            summary.get("result_batch_id") if isinstance(summary, dict) else None,
        )
        report_id = _first_text(
            payload.get("report_id"),
            summary.get("report_id") if isinstance(summary, dict) else None,
            f"benchmark_report:{source_run_id}" if source_run_id else "",
        )
        row_payload = {
            "scope": scope,
            "hash": subject_id or str(target_version_id or model_config_hash or model_id or ""),
            "subject_id": subject_id,
            "model_id": model_id,
            "model_config_hash": model_config_hash,
            "target_role": payload.get("target_role"),
            "target_version_id": target_version_id,
            "comparison_group_id": payload.get("comparison_group_id"),
            "evaluation_set_id": payload.get("evaluation_set_id"),
            "seed_set_id": payload.get("seed_set_id"),
            "benchmark_config_hash": _first_text(
                payload.get("benchmark_config_hash"),
                payload.get("config_hash"),
                summary.get("benchmark_config_hash") if isinstance(summary, dict) else None,
                summary.get("config_hash") if isinstance(summary, dict) else None,
            ) or None,
            "game_count": game_count,
            "games_played": game_count,
            "valid_game_rate": float(payload.get("valid_game_rate") or 0.0),
            "strength_score": strength_score,
            "avg_role_score": score,
            "target_role_role_weighted_score": score,
            "by_role_category_scores": by_role,
            "avg_speech_score": float(payload.get("avg_speech_score") or 0.0),
            "avg_vote_score": float(payload.get("avg_vote_score") or 0.0),
            "avg_skill_score": float(payload.get("avg_skill_score") or 0.0),
            "avg_logic_score": float(payload.get("avg_logic_score") or 0.0),
            "avg_team_score": float(payload.get("avg_team_score") or 0.0),
            "risk_penalty": float(payload.get("risk_penalty") or 0.0),
            "fallback_rate": float(payload.get("fallback_rate") or 0.0),
            "target_role_fallback_rate": float(payload.get("fallback_rate") or 0.0),
            "llm_error_rate": float(payload.get("llm_error_rate") or 0.0),
            "policy_adjusted_rate": float(payload.get("policy_adjusted_rate") or 0.0),
            "target_side_win_rate": float(payload.get("target_side_win_rate") or 0.0),
            "rankable": bool(payload.get("rankable")),
            "data_sufficient": bool(payload.get("data_sufficient")),
            "summary": summary,
            "model_runtime": _json_clone(summary.get("model_runtime") or {}),
            "is_baseline": bool(summary.get("is_baseline", False)) if isinstance(summary, dict) else False,
            "delta_vs_baseline": {},
            "source_run_id": source_run_id,
            "batch_id": source_run_id,
            "result_batch_id": result_batch_id,
            "report_id": report_id,
            "updated_at": payload.get("updated_at"),
        }
        row_payload.update(_leaderboard_row_statistics(row_payload))
        return row_payload

    def _leaderboard_scores_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Load persisted benchmark scores for multiple roles with one DB round trip."""
        from app.lib.score import open_eval_connection

        role_keys = [str(role) for role in roles if role]
        if not role_keys:
            return {}
        scores: dict[str, dict[str, dict[str, Any]]] = {role: {} for role in role_keys}
        conn = None
        try:
            conn = open_eval_connection(self.paths)
            placeholders = ", ".join("?" for _ in role_keys)
            where = f"WHERE scope = 'role_version' AND target_role IN ({placeholders}) "
            params: list[Any] = list(role_keys)
            if evaluation_set_id:
                where += "AND evaluation_set_id = ? "
                params.append(evaluation_set_id)
            rows = conn.execute(
                "SELECT scope, subject_id, model_id, model_config_hash, target_role, target_version_id, "
                "comparison_group_id, evaluation_set_id, seed_set_id, games_played, valid_game_rate, "
                "strength_score, avg_role_score, by_role_category_scores, avg_speech_score, avg_vote_score, "
                "avg_skill_score, avg_logic_score, avg_team_score, risk_penalty, fallback_rate, llm_error_rate, "
                "policy_adjusted_rate, target_side_win_rate, rankable, data_sufficient, summary, updated_at "
                "FROM benchmark_leaderboard "
                f"{where}"
                "ORDER BY updated_at DESC",
                tuple(params),
            ).fetchall()
            for row in rows:
                role = row["target_role"]
                vid = row["target_version_id"]
                if role in scores and vid and vid not in scores[role]:  # newest row per role/version wins
                    scores[role][vid] = self._leaderboard_row_payload(row)
        except Exception:  # noqa: BLE001 — leaderboard read is best-effort
            _log.warning("leaderboard_scores_for_roles failed", exc_info=True)
        finally:
            if conn is not None:
                conn.close()
        return scores

    def _list_benchmark_specs(self) -> list[dict[str, Any]]:
        """Return configured benchmark suite summaries for API/UI use."""
        return _annotate_benchmark_suite_lineage(
            self._benchmark_spec_summaries(include_activity=True, skip_invalid=False)
        )

    def _benchmark_spec_summaries(
        self,
        *,
        include_activity: bool,
        skip_invalid: bool,
    ) -> list[dict[str, Any]]:
        from app.lib.benchmark_spec import list_benchmark_specs

        summaries: list[dict[str, Any]] = []
        overrides = self._benchmark_lifecycle_overrides()
        for spec in list_benchmark_specs(self.paths, include_inactive=True):
            try:
                spec, lifecycle_override = _apply_benchmark_lifecycle_override(spec, overrides.get(spec.id))
                summary = self._benchmark_spec_summary_from_spec(
                    spec,
                    lifecycle_override=lifecycle_override,
                    include_activity=include_activity,
                )
                summaries.append(summary)
            except BenchmarkSpecError:
                if skip_invalid:
                    continue
                raise
        return summaries

    def _benchmark_spec_summary_from_spec(
        self,
        spec: BenchmarkSpec,
        *,
        lifecycle_override: dict[str, Any] | None,
        include_activity: bool,
    ) -> dict[str, Any]:
        materialized, seed_set = materialize_benchmark_spec(spec, paths=self.paths)
        summary = benchmark_spec_summary(materialized, seed_set)
        summary["lifecycle_override"] = _json_clone(lifecycle_override) if lifecycle_override else None
        if include_activity:
            summary.update(self._benchmark_suite_activity(summary))
        return summary

    def _apply_benchmark_suite_lineage(self, summary: dict[str, Any]) -> dict[str, Any]:
        lineage_summaries = self._benchmark_spec_summaries(include_activity=False, skip_invalid=True)
        if not any(item.get("id") == summary.get("id") for item in lineage_summaries):
            lineage_summaries.append(_json_clone(summary))
        _annotate_benchmark_suite_lineage(lineage_summaries)
        matched = next((item for item in lineage_summaries if item.get("id") == summary.get("id")), None)
        if matched:
            _copy_benchmark_suite_lineage(summary, matched)
        return summary

    def _get_benchmark_spec_summary(self, benchmark_id: str) -> dict[str, Any]:
        """Return a single benchmark suite summary."""
        try:
            spec, lifecycle_override = self._benchmark_spec_with_lifecycle(benchmark_id)
            summary = self._benchmark_spec_summary_from_spec(
                spec,
                lifecycle_override=lifecycle_override,
                include_activity=True,
            )
            self._apply_benchmark_suite_lineage(summary)
            return summary
        except BenchmarkSpecError as exc:
            status = 404 if "not found" in str(exc) else 422
            detail = "benchmark not found" if status == 404 else str(exc)
            raise HTTPException(status_code=status, detail=detail) from exc

    def _update_benchmark_lifecycle(self, benchmark_id: str, request: BenchmarkLifecycleRequest) -> dict[str, Any]:
        """Persist a runtime lifecycle override for a benchmark suite."""
        normalized_id = str(benchmark_id or "").strip()
        if not normalized_id:
            raise HTTPException(status_code=404, detail="benchmark not found")
        status = str(request.status or "").strip().lower()
        if status not in VALID_BENCHMARK_STATUSES:
            raise HTTPException(status_code=422, detail="unsupported benchmark lifecycle status")
        try:
            original = load_benchmark_spec(normalized_id, self.paths)
        except BenchmarkSpecError as exc:
            status_code = 404 if "not found" in str(exc) else 422
            detail = "benchmark not found" if status_code == 404 else str(exc)
            raise HTTPException(status_code=status_code, detail=detail) from exc
        now = beijing_now_iso()
        override = {
            "benchmark_id": original.id,
            "status": status,
            "enabled": status in LAUNCHABLE_BENCHMARK_STATUSES,
            "reason": str(request.reason or ""),
            "updated_at": now,
        }
        overrides = self._benchmark_lifecycle_overrides()
        overrides[original.id] = override
        self._persist_benchmark_lifecycle_overrides(overrides)
        spec, applied_override = _apply_benchmark_lifecycle_override(original, override)
        try:
            summary = self._benchmark_spec_summary_from_spec(
                spec,
                lifecycle_override=applied_override,
                include_activity=True,
            )
            self._apply_benchmark_suite_lineage(summary)
            return {
                "kind": "benchmark_suite_lifecycle",
                "schema_version": 1,
                "benchmark_id": original.id,
                "status": summary["status"],
                "launchable": summary["launchable"],
                "item": summary,
            }
        except BenchmarkSpecError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _benchmark_spec_with_lifecycle(self, benchmark_id: str) -> tuple[BenchmarkSpec, dict[str, Any] | None]:
        spec = load_benchmark_spec(benchmark_id, self.paths)
        override = self._benchmark_lifecycle_overrides().get(spec.id)
        return _apply_benchmark_lifecycle_override(spec, override)

    def _benchmark_lifecycle_overrides_path(self) -> Any:
        return self.paths.data_dir / "benchmark_suite_lifecycle_overrides.json"

    def _benchmark_lifecycle_overrides(self) -> dict[str, dict[str, Any]]:
        path = self._benchmark_lifecycle_overrides_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - normalize runtime state read failures
            raise HTTPException(status_code=500, detail=f"failed to read benchmark lifecycle overrides: {exc}") from exc
        raw_items = payload.get("items") if isinstance(payload, dict) else {}
        if not isinstance(raw_items, dict):
            return {}
        overrides: dict[str, dict[str, Any]] = {}
        for key, value in raw_items.items():
            if not isinstance(value, dict):
                continue
            benchmark_id = str(value.get("benchmark_id") or key or "").strip()
            status = str(value.get("status") or "").strip().lower()
            if not benchmark_id or status not in VALID_BENCHMARK_STATUSES:
                continue
            overrides[benchmark_id] = {
                "benchmark_id": benchmark_id,
                "status": status,
                "enabled": bool(value.get("enabled", status in LAUNCHABLE_BENCHMARK_STATUSES)),
                "reason": str(value.get("reason") or ""),
                "updated_at": str(value.get("updated_at") or ""),
            }
        return overrides

    def _persist_benchmark_lifecycle_overrides(self, overrides: dict[str, dict[str, Any]]) -> None:
        path = self._benchmark_lifecycle_overrides_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": "benchmark_suite_lifecycle_overrides",
            "schema_version": 1,
            "items": {
                benchmark_id: _json_clone(override)
                for benchmark_id, override in sorted(overrides.items())
            },
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _list_benchmark_seed_sets(self) -> dict[str, Any]:
        """Return configured benchmark seed-set registry summaries for API/UI use."""
        seed_sets = list_benchmark_seed_sets(self.paths, include_disabled=True)
        return benchmark_seed_registry_summary(seed_sets)

    def _get_benchmark_seed_set(self, seed_set_id: str) -> dict[str, Any]:
        """Return one benchmark seed set with full seeds for audit views."""
        try:
            seed_set = load_benchmark_seed_set(seed_set_id, self.paths, include_disabled=True)
            registry = benchmark_seed_registry_summary(
                list_benchmark_seed_sets(self.paths, include_disabled=True)
            )
            registry_item = next(
                (item for item in registry["items"] if item.get("id") == seed_set.id),
                {},
            )
            item = benchmark_seed_set_summary(seed_set)
            item["seeds"] = list(seed_set.seeds)
            item["overlap_warnings"] = list(registry_item.get("overlap_warnings") or [])
            return {
                "kind": "benchmark_seed_set",
                "schema_version": 1,
                "item": item,
            }
        except BenchmarkSpecError as exc:
            status = 404 if "not found" in str(exc) else 422
            detail = "benchmark seed set not found" if status == 404 else str(exc)
            raise HTTPException(status_code=status, detail=detail) from exc

    def _benchmark_suite_activity(self, summary: dict[str, Any]) -> dict[str, Any]:
        benchmark_id = str(summary.get("id") or summary.get("benchmark_id") or "")
        evaluation_set_id = str(summary.get("evaluation_set_id") or "")
        runs = [
            batch for batch in self.evolution_batches.values()
            if _is_benchmark_suite_batch(batch, benchmark_id=benchmark_id, evaluation_set_id=evaluation_set_id)
        ]
        latest_run = _benchmark_latest_run_payload(runs[0]) if runs else None
        if len(runs) > 1:
            runs.sort(key=_benchmark_run_sort_key, reverse=True)
            latest_run = _benchmark_latest_run_payload(runs[0])
        snapshots = self._load_benchmark_snapshot_summaries(
            benchmark_id=benchmark_id or None,
            evaluation_set_id=evaluation_set_id or None,
            limit=1,
        )
        return {
            "last_run": latest_run,
            "latest_snapshot": snapshots[0] if snapshots else None,
        }

    def _plan_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        """Return a launch plan and budget estimate for a benchmark request."""
        return self._benchmark_run_plan(request)

    def _benchmark_run_plan(self, request: BenchmarkRequest) -> dict[str, Any]:
        """Build the shared dry-run launch plan used by API and queue admission."""
        spec, seed_set = self._resolve_benchmark_spec(request)
        roles = self._benchmark_roles(request, spec)
        target_type = spec.target_type if spec else request.target_type
        self._validate_benchmark_target_versions(roles, request, target_type=target_type)
        if spec is not None:
            game_count = int(spec.game_count)
            max_days = int(spec.max_days)
            judge = spec.judge.model_dump(mode="json")
            benchmark = benchmark_spec_summary(spec, seed_set)
            seed_count = int(benchmark.get("seed_count") or game_count)
            seed_set_id = spec.seed_set_id
            cost_tier = str(spec.cost_tier or "standard")
        else:
            game_count = 10 if request.battle_games is None else int(request.battle_games)
            max_days = 5 if request.max_days is None else int(request.max_days)
            judge = {}
            benchmark = None
            seed_count = game_count
            seed_set_id = None
            cost_tier = "ad_hoc"

        eval_batch_count = 1 if target_type == "model" else max(1, len(roles))
        total_games = eval_batch_count * game_count
        judge_enabled = bool(judge.get("enable_decision_judge", False))
        judge_max_decisions = int(judge.get("judge_max_decisions") or 0) if judge_enabled else 0
        judge_decision_units = total_games * judge_max_decisions
        player_count = _BENCHMARK_PLAYER_COUNT
        game_decision_units = total_games * max_days * player_count
        estimated_units = game_decision_units + judge_decision_units
        estimated_tokens = _benchmark_estimated_tokens(
            game_decision_units=game_decision_units,
            judge_decision_units=judge_decision_units,
        )
        estimated_cost = _benchmark_estimated_cost(estimated_tokens)
        concurrency_policy = _benchmark_concurrency_policy(
            eval_batch_count=eval_batch_count,
            game_count=game_count,
            max_days=max_days,
            player_count=player_count,
            judge_enabled=judge_enabled,
            judge_decision_units=judge_decision_units,
            judge_concurrency=judge.get("judge_concurrency"),
        )
        expected_duration_seconds = int(concurrency_policy["expected_duration_seconds"])
        budget = _benchmark_budget_payload(
            request,
            estimated_units=estimated_units,
            estimated_tokens=estimated_tokens,
            estimated_cost=estimated_cost,
        )
        budget_exceeded = _benchmark_budget_exceeded(budget)
        warnings: list[dict[str, Any]] = []
        if budget_exceeded:
            exceeded = budget.get("exceeded") if isinstance(budget.get("exceeded"), dict) else {}
            warnings.append(
                {
                    "kind": "budget_exceeded",
                    "message": "estimated benchmark cost exceeds budget limit",
                    "estimated_units": estimated_units,
                    "limit_units": request.budget_limit_units,
                    "estimated_cost": estimated_cost,
                    "limit_cost": request.budget_limit_cost,
                    "reasons": exceeded.get("reasons", []) if isinstance(exceeded, dict) else [],
                    "evidence": exceeded.get("evidence", []) if isinstance(exceeded, dict) else [],
                }
            )
        if (
            request.stop_after_budget_units is not None
            and estimated_units > int(request.stop_after_budget_units)
        ):
            warnings.append(
                {
                    "kind": "stop_after_budget_will_trigger",
                    "message": "estimated benchmark units exceed stop-after threshold",
                    "estimated_units": estimated_units,
                    "stop_after_budget_units": int(request.stop_after_budget_units),
                }
            )
        if not request.benchmark_id:
            warnings.append(
                {
                    "kind": "ad_hoc_benchmark",
                    "message": "ad-hoc benchmark is not isolated by a versioned suite",
                }
            )

        assumptions = [
            "game_decision_units = total_games * max_days * 12 players",
            "judge_decision_units = total_games * judge_max_decisions when decision judge is enabled",
            "estimated_tokens = game units and judge units multiplied by planner token assumptions",
            "estimated_cost uses planner token cost assumptions and is reported before launch",
        ]

        return {
            "kind": "benchmark_run_plan",
            "schema_version": 2,
            "dry_run": True,
            "benchmark": benchmark,
            "target_type": target_type,
            "roles": list(roles),
            "role_count": len(roles),
            "eval_batch_count": eval_batch_count,
            "game_count_per_eval_batch": game_count,
            "max_days": max_days,
            "total_games": total_games,
            "seed_set_id": seed_set_id,
            "seed_count": seed_count,
            "cost_tier": cost_tier,
            "estimated_tokens": estimated_tokens,
            "estimated_cost": estimated_cost,
            "currency": _BENCHMARK_CURRENCY,
            "expected_duration_seconds": expected_duration_seconds,
            "concurrency_policy": concurrency_policy,
            "assumptions": assumptions,
            "judge": {
                "enabled": judge_enabled,
                "max_decisions_per_game": judge_max_decisions,
                "estimated_decisions": judge_decision_units,
                "concurrency": concurrency_policy["judge_concurrency"],
                "timeout_seconds": judge.get("judge_timeout_seconds"),
            },
            "estimates": {
                "player_count": player_count,
                "game_decision_units": game_decision_units,
                "judge_decision_units": judge_decision_units,
                "estimated_llm_call_units": estimated_units,
                "estimated_tokens": estimated_tokens,
                "estimated_cost": estimated_cost,
                "currency": _BENCHMARK_CURRENCY,
                "expected_duration_seconds": expected_duration_seconds,
                "assumptions": assumptions,
            },
            "budget": budget,
            "launchable": not budget_exceeded,
            "warnings": warnings,
        }

    def _benchmark_batch_detail(self, batch_id: str) -> dict[str, Any]:
        """Return an auditable benchmark batch detail payload."""
        batch = self._benchmark_batch_or_404(batch_id)
        from ui.backend.evolution_serializers import _benchmark_result_summary, _evolution_batch_summary

        results = _benchmark_results(batch)
        result_summaries = []
        for result in results:
            summary = _benchmark_result_summary(result)
            if isinstance(summary, dict):
                result_summaries.append(
                    {
                        **summary,
                        "result_batch_id": _benchmark_result_batch_id(result),
                        "target_role": _benchmark_result_role(result),
                        "game_count": _benchmark_result_game_count(result),
                        "diagnostic_count": len(_dict_items(result.get("diagnostics"))),
                        "warning_count": len(_text_items(result.get("warnings"))),
                    }
                )
        games = _benchmark_games_for_batch(batch)
        langfuse = _benchmark_batch_langfuse_summary(batch, games=games)
        return {
            "kind": "benchmark_batch_detail",
            "schema_version": 1,
            "batch": _evolution_batch_summary(batch),
            "batch_id": batch_id,
            "status": batch.get("status"),
            "benchmark": batch.get("benchmark"),
            "target_type": batch.get("target_type"),
            "model_runtime": _json_clone(batch.get("model_runtime") or {}),
            "roles": list(batch.get("roles", []) or []),
            "run_plan": batch.get("run_plan"),
            "result_count": len(results),
            "results": result_summaries,
            "game_summary": _benchmark_game_summary(games),
            "diagnostic_summary": _benchmark_diagnostic_summary(_benchmark_diagnostic_entries(batch)),
            "langfuse": langfuse,
        }

    def _benchmark_batch_games(
        self,
        batch_id: str,
        *,
        result_batch_id: str | None = None,
        target_role: str | None = None,
        status: str | None = None,
        seed: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return paginated benchmark game summaries for a batch."""
        batch = self._benchmark_batch_or_404(batch_id)
        games = _benchmark_games_for_batch(batch)
        if result_batch_id:
            games = [game for game in games if game.get("result_batch_id") == result_batch_id]
        if target_role:
            role_text = str(target_role).strip().lower()
            games = [game for game in games if str(game.get("target_role") or "").lower() == role_text]
        statuses = _filter_values(status)
        if statuses is not None:
            games = [game for game in games if _benchmark_game_matches_status_filter(game, statuses)]
        seeds = _filter_values(seed)
        if seeds is not None:
            games = [game for game in games if _match_filter(game.get("seed"), seeds)]
        page, pagination = _pagination(games, limit=limit, offset=offset)
        return {
            "kind": "benchmark_batch_games",
            "schema_version": 1,
            "batch_id": batch_id,
            "result_batch_id": result_batch_id,
            "target_role": target_role,
            "status": status,
            "seed": seed,
            "games": page,
            "pagination": pagination,
        }

    def _benchmark_batch_diagnostics(
        self,
        batch_id: str,
        *,
        target_role: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
    ) -> dict[str, Any]:
        """Return aggregated benchmark run diagnostics."""
        batch = self._benchmark_batch_or_404(batch_id)
        diagnostics = _benchmark_diagnostic_entries(batch)
        meta = _benchmark_batch_boundary(batch)
        kind_filter = _filter_values(kind)
        level_filter = _filter_values(level)
        status_filter = _filter_values(status)
        stage_filter = _filter_values(stage)
        seed_filter = _filter_values(seed)
        normalized_target_role = str(target_role or "").strip().lower()
        if any(value is not None for value in (kind_filter, level_filter, status_filter, stage_filter, seed_filter)) or normalized_target_role:
            diagnostics = [
                item for item in diagnostics
                if _benchmark_diagnostic_matches(
                    item,
                    meta,
                    target_role=normalized_target_role,
                    kind_filter=kind_filter,
                    level_filter=level_filter,
                    status_filter=status_filter,
                    stage_filter=stage_filter,
                    seed_filter=seed_filter,
                )
            ]
        return {
            "kind": "benchmark_batch_diagnostics",
            "schema_version": 1,
            "batch_id": batch_id,
            "status": batch.get("status"),
            "benchmark": batch.get("benchmark"),
            "target_type": batch.get("target_type"),
            "filters": {
                "target_role": target_role,
                "kind": kind,
                "level": level,
                "status": status,
                "stage": stage,
                "seed": seed,
            },
            "diagnostics": diagnostics,
            "summary": _benchmark_diagnostic_summary(diagnostics),
        }

    def _benchmark_batch_report(self, batch_id: str, *, format: str = "json") -> dict[str, Any]:
        """Return a canonical benchmark run report or a text export wrapper."""
        batch = self._benchmark_batch_or_404(batch_id)
        report = _benchmark_run_report_payload(batch)
        normalized_format = str(format or "json").strip().lower()
        if normalized_format in {"json", ""}:
            return report
        if normalized_format in {"markdown", "md"}:
            content = _benchmark_run_report_markdown(report)
            export_content_hash = _text_content_hash(content)
            export_manifest = _benchmark_run_report_reproducibility_manifest(
                batch,
                report,
                export_format="markdown",
                export_content_hash=export_content_hash,
            )
            return {
                "kind": "benchmark_run_report_export",
                "schema_version": 1,
                "run_id": report["run_id"],
                "report_id": report["report_id"],
                "format": "markdown",
                "content": content,
                "content_type": "text/markdown",
                "content_hash": report["content_hash"],
                "export_content_hash": export_content_hash,
                "artifact_hash": export_content_hash,
                "reproducibility_manifest": export_manifest,
                "reproducibility_manifest_hash": export_manifest["manifest_hash"],
                "report": report,
            }
        if normalized_format == "csv":
            content = _benchmark_run_report_csv(report)
            export_content_hash = _text_content_hash(content)
            export_manifest = _benchmark_run_report_reproducibility_manifest(
                batch,
                report,
                export_format="csv",
                export_content_hash=export_content_hash,
            )
            return {
                "kind": "benchmark_run_report_export",
                "schema_version": 1,
                "run_id": report["run_id"],
                "report_id": report["report_id"],
                "format": "csv",
                "content": content,
                "content_type": "text/csv",
                "content_hash": report["content_hash"],
                "export_content_hash": export_content_hash,
                "artifact_hash": export_content_hash,
                "reproducibility_manifest": export_manifest,
                "reproducibility_manifest_hash": export_manifest["manifest_hash"],
                "report": report,
            }
        raise HTTPException(status_code=422, detail="unsupported benchmark report format")

    def _benchmark_reports(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return reportable benchmark run summaries for the selected boundary."""
        normalized_scope = str(scope or "").strip().lower()
        normalized_evaluation_set_id = str(evaluation_set_id or "").strip()
        normalized_benchmark_id = str(benchmark_id or "").strip()
        normalized_target_role = str(target_role or "").strip().lower()
        normalized_model_id = str(model_id or "").strip()
        normalized_model_config_hash = str(model_config_hash or "").strip()
        status_filter = _filter_values(status)
        batches = [
            batch for batch in self.evolution_batches.values()
            if isinstance(batch, dict) and batch.get("kind") == "benchmark_batch"
        ]
        batches.sort(key=_benchmark_run_sort_key, reverse=True)
        items: list[dict[str, Any]] = []
        for batch in batches:
            meta = _benchmark_batch_boundary(batch)
            if normalized_scope and meta["target_type"] != normalized_scope:
                continue
            if normalized_evaluation_set_id and meta["evaluation_set_id"] != normalized_evaluation_set_id:
                continue
            if normalized_benchmark_id and meta["benchmark_id"] != normalized_benchmark_id:
                continue
            if normalized_model_id and meta["model_id"] != normalized_model_id:
                continue
            if normalized_model_config_hash and meta["model_config_hash"] != normalized_model_config_hash:
                continue
            if status_filter is not None and not _match_filter(meta["status"], status_filter):
                continue
            report = _benchmark_run_report_payload(batch)
            subject_role = str(report.get("subject", {}).get("target_role") or "").strip().lower()
            if normalized_target_role and meta["target_type"] == "role_version":
                if subject_role and subject_role != normalized_target_role:
                    continue
                if not subject_role and normalized_target_role not in meta.get("roles", []):
                    continue
            items.append(_benchmark_run_report_summary(batch, report, meta))

        page, pagination = _pagination(items, limit=limit, offset=offset)
        return {
            "kind": "benchmark_run_reports",
            "schema_version": 1,
            "scope": normalized_scope or None,
            "evaluation_set_id": normalized_evaluation_set_id or None,
            "benchmark_id": normalized_benchmark_id or None,
            "target_role": normalized_target_role or None,
            "model_id": normalized_model_id or None,
            "model_config_hash": normalized_model_config_hash or None,
            "filters": {"status": status},
            "items": page,
            "summary": _benchmark_report_history_summary(items),
            "pagination": pagination,
        }

    def _benchmark_diagnostics(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return diagnostics aggregated across benchmark runs in the selected boundary."""
        kind_filter = _filter_values(kind)
        level_filter = _filter_values(level)
        status_filter = _filter_values(status)
        stage_filter = _filter_values(stage)
        seed_filter = _filter_values(seed)
        normalized_scope = str(scope or "").strip().lower()
        normalized_evaluation_set_id = str(evaluation_set_id or "").strip()
        normalized_benchmark_id = str(benchmark_id or "").strip()
        normalized_target_role = str(target_role or "").strip().lower()
        normalized_model_id = str(model_id or "").strip()
        normalized_model_config_hash = str(model_config_hash or "").strip()

        all_diagnostics: list[dict[str, Any]] = []
        matched_batches: list[tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]] = []
        batches = [
            batch for batch in self.evolution_batches.values()
            if isinstance(batch, dict) and batch.get("kind") == "benchmark_batch"
        ]
        batches.sort(key=_benchmark_run_sort_key, reverse=True)
        for batch in batches:
            meta = _benchmark_batch_boundary(batch)
            if normalized_scope and meta["target_type"] != normalized_scope:
                continue
            if normalized_evaluation_set_id and meta["evaluation_set_id"] != normalized_evaluation_set_id:
                continue
            if normalized_benchmark_id and meta["benchmark_id"] != normalized_benchmark_id:
                continue
            if normalized_model_id and meta["model_id"] != normalized_model_id:
                continue
            if normalized_model_config_hash and meta["model_config_hash"] != normalized_model_config_hash:
                continue

            diagnostics = [
                _benchmark_annotated_diagnostic(item, meta)
                for item in _benchmark_diagnostic_entries(batch)
                if _benchmark_diagnostic_matches(
                    item,
                    meta,
                    target_role=normalized_target_role,
                    kind_filter=kind_filter,
                    level_filter=level_filter,
                    status_filter=status_filter,
                    stage_filter=stage_filter,
                    seed_filter=seed_filter,
                )
            ]
            if not diagnostics:
                continue
            all_diagnostics.extend(diagnostics)
            matched_batches.append((batch, diagnostics, meta))

        page, pagination = _pagination(all_diagnostics, limit=limit, offset=offset)
        affected_runs = [
            _benchmark_diagnostic_run_payload(batch, diagnostics, meta)
            for batch, diagnostics, meta in matched_batches
        ]
        affected_games = _benchmark_diagnostic_affected_games(matched_batches)
        return {
            "kind": "benchmark_diagnostics",
            "schema_version": 1,
            "scope": normalized_scope or None,
            "evaluation_set_id": normalized_evaluation_set_id or None,
            "benchmark_id": normalized_benchmark_id or None,
            "target_role": normalized_target_role or None,
            "model_id": normalized_model_id or None,
            "model_config_hash": normalized_model_config_hash or None,
            "filters": {
                "kind": kind,
                "level": level,
                "status": status,
                "stage": stage,
                "seed": seed,
            },
            "diagnostics": page,
            "affected_runs": affected_runs,
            "affected_games": affected_games,
            "summary": _benchmark_diagnostic_aggregate_summary(all_diagnostics),
            "pagination": pagination,
        }

    def _benchmark_batch_or_404(self, batch_id: str) -> dict[str, Any]:
        batch = self.evolution_batches.get(batch_id)
        if batch is None or str(batch.get("kind") or "") != "benchmark_batch":
            raise HTTPException(status_code=404, detail="batch not found")
        return batch

    def model_for_run(self) -> Any | None:
        if self.model is not None:
            return self.model
        use_fake = os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").lower() in {"1", "true", "yes"}
        if use_fake:
            return _FakeModel()
        try:
            return create_llm()
        except RuntimeError:
            _log.warning("LLM config missing; UI backend is using fallback model", exc_info=True)
            return _FakeModel()

    def _benchmark_model_runtime(self, request: BenchmarkRequest | None = None) -> dict[str, Any]:
        """Return model identity used to attribute model-scope benchmark runs."""
        request_model_id = str(getattr(request, "model_id", "") or "").strip() if request else ""
        request_config_hash = str(getattr(request, "model_config_hash", "") or "").strip() if request else ""
        if request_model_id and request_config_hash:
            return _benchmark_model_runtime_payload(
                source="request",
                model_id=request_model_id,
                model_config_hash=request_config_hash,
                hash_input=None,
                hash_provided=True,
            )

        if self.model is not None:
            model_id = request_model_id or _model_identifier(self.model) or self.model.__class__.__name__
            hash_input = _injected_model_runtime_hash_input(self.model, model_id=model_id)
            runtime_hash = request_config_hash or _stable_runtime_hash(hash_input)
            return _benchmark_model_runtime_payload(
                source="injected_model",
                model_id=model_id,
                model_config_hash=runtime_hash,
                hash_input=hash_input,
                hash_provided=bool(request_config_hash),
            )

        use_fake = os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").lower() in {"1", "true", "yes"}
        if use_fake:
            model_id = request_model_id or "ui-backend-fake-llm"
            hash_input = {"source": "fake", "model_id": model_id}
            return _benchmark_model_runtime_payload(
                source="fake",
                model_id=model_id,
                model_config_hash=request_config_hash or _stable_runtime_hash(hash_input),
                hash_input=hash_input,
                hash_provided=bool(request_config_hash),
            )

        try:
            cfg = load_llm_config()
            public_cfg = {
                key: cfg.get(key)
                for key in (
                    "base_url",
                    "model",
                    "timeout",
                    "temperature",
                    "thinking",
                    "max_retries",
                    "runtime_max_attempts",
                    "runtime_timeout",
                    "runtime_retry_initial_delay",
                    "runtime_retry_max_delay",
                    "runtime_circuit_failures",
                    "runtime_circuit_cooldown",
                )
            }
            model_id = request_model_id or str(cfg.get("model") or "configured-llm")
            public_cfg["model"] = model_id
            public_cfg["source"] = "configured_llm"
            return _benchmark_model_runtime_payload(
                source="configured_llm",
                model_id=model_id,
                model_config_hash=request_config_hash or _stable_runtime_hash(public_cfg),
                hash_input=public_cfg,
                hash_provided=bool(request_config_hash),
            )
        except RuntimeError:
            model_id = request_model_id or "ui-backend-fallback-llm"
            hash_input = {"source": "fallback", "model_id": model_id}
            return _benchmark_model_runtime_payload(
                source="fallback",
                model_id=model_id,
                model_config_hash=request_config_hash or _stable_runtime_hash(hash_input),
                hash_input=hash_input,
                hash_provided=bool(request_config_hash),
            )

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
        request = automatic_evolution_request(request)
        roles = request.roles or ["villager"]
        if len(roles) == 1:
            return self._create_evolution_run(roles[0], request)

        batch_id = f"evo_batch_{uuid.uuid4().hex[:10]}"
        now = beijing_now_iso()
        batch = {
            "kind": "role_evolution_batch",
            "schema_version": 1,
            "batch_id": batch_id,
            "roles": roles,
            "status": "running",
            "stop_requested": False,
            "cancelled": False,
            "interrupted": False,
            "failed": False,
            "started_at": now,
            "last_heartbeat_at": now,
            "finished_at": None,
            "current_stage": "queued",
            "progress": {
                "stage": "queued",
                "percent": 0.0,
                "completed_roles": 0,
                "role_count": len(roles),
                "total_roles": len(roles),
                "updated_at": now,
            },
            "overall_progress": {
                "stage": "queued",
                "percent": 0.0,
                "completed_roles": 0,
                "role_count": len(roles),
                "total_roles": len(roles),
                "updated_at": now,
            },
            "diagnostics": [],
            "runs": [],
            "run_summaries": [],
            "config": request.model_dump(),
        }
        self.evolution_batches[batch_id] = batch
        for role in roles:
            run = self._create_evolution_run(role, request, batch_id=batch_id, status="queued")
            batch["runs"].append(run["run_id"])
        self._persist_background_tasks()
        return batch

    def _create_evolution_run(
        self,
        role: str,
        request: EvolutionStartRequest,
        *,
        batch_id: str | None = None,
        status: str = "running",
    ) -> dict[str, Any]:
        run_id = f"evolve_{role}_{uuid.uuid4().hex[:8]}"
        now = beijing_now_iso()
        stage = "queued"
        run = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": run_id,
            "batch_id": batch_id,
            "role": role,
            "status": status,
            "stop_requested": False,
            "cancelled": False,
            "interrupted": False,
            "failed": False,
            "started_at": now,
            "last_heartbeat_at": now,
            "finished_at": None,
            "current_stage": stage,
            "parent_hash": f"baseline_{role}",
            "candidate_hash": None,
            "training_games": [],
            "training_game_count": int(request.training_games or 0),
            "training_completed": 0,
            "battle_games": [],
            "battle_game_count": int(request.battle_games or 0),
            "battle_completed": 0,
            "battle_result": {},
            "proposals": [],
            "diff": [],
            "errors": [],
            "diagnostics": [],
            "warnings": [],
            "progress": {
                "stage": stage,
                "percent": 0.0,
                "completed_games": 0,
                "target_games": int(request.training_games or 0),
                "updated_at": now,
            },
            "overall_progress": {
                "stage": stage,
                "percent": 0.0,
                "training_completed": 0,
                "training_total": int(request.training_games or 0),
                "battle_completed": 0,
                "battle_total": int(request.battle_games or 0) * 2,
                "battle_requested_per_side": int(request.battle_games or 0),
                "updated_at": now,
            },
            "config": request.model_dump(),
        }
        self.evolution_runs[run_id] = run
        self._persist_background_tasks()
        return run

    @staticmethod
    def _count_evolution_games(value: Any) -> int:
        if isinstance(value, list):
            return len([item for item in value if isinstance(item, dict)])
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def _evolution_overall_progress(self, run: dict[str, Any]) -> dict[str, Any]:
        progress = run.get("progress") if isinstance(run.get("progress"), dict) else {}
        config = run.get("config") if isinstance(run.get("config"), dict) else {}
        training_total = self._count_evolution_games(run.get("training_game_count") or config.get("training_games"))
        battle_per_side = self._count_evolution_games(run.get("battle_game_count") or config.get("battle_games"))
        training_completed = self._count_evolution_games(run.get("training_completed") or run.get("training_games"))
        battle_completed = self._count_evolution_games(run.get("battle_completed") or run.get("battle_games"))
        total = training_total + battle_per_side * 2
        completed = training_completed + battle_completed
        terminal = str(run.get("status") or "").lower() in {"reviewing", "promoted", "rejected", "completed"}
        percent = (completed / total) if total > 0 else self._task_progress_percent(run)
        if terminal:
            percent = max(percent, 1.0)
        return {
            "stage": str(run.get("current_stage") or progress.get("stage") or run.get("status") or ""),
            "percent": max(0.0, min(1.0, float(percent))),
            "training_completed": training_completed,
            "training_total": training_total,
            "battle_completed": battle_completed,
            "battle_total": battle_per_side * 2,
            "battle_requested_per_side": battle_per_side,
            "updated_at": run.get("last_heartbeat_at") or progress.get("updated_at") or beijing_now_iso(),
        }

    def _sync_evolution_progress(self, run_id: str, snapshot: dict[str, Any]) -> None:
        run = self.evolution_runs.get(run_id)
        if run is None or run.get("stop_requested") or run.get("cancelled"):
            return
        for key in (
            "status",
            "current_stage",
            "parent_hash",
            "candidate_hash",
            "candidate_skill_dir",
            "baseline_skill_dir",
            "battle_result",
            "recommendation",
            "last_heartbeat_at",
        ):
            if key in snapshot and snapshot.get(key) is not None:
                run[key] = snapshot[key]
        for key in ("training_games", "battle_games", "proposals", "diff", "diagnostics", "warnings", "errors"):
            value = snapshot.get(key)
            if isinstance(value, list):
                run[key] = value
        if isinstance(snapshot.get("progress"), dict):
            run["progress"] = dict(snapshot["progress"])
        run["training_game_count"] = self._count_evolution_games(
            snapshot.get("training_game_count") or run.get("training_game_count")
        )
        run["battle_game_count"] = self._count_evolution_games(
            snapshot.get("battle_game_count") or run.get("battle_game_count")
        )
        run["training_completed"] = self._count_evolution_games(run.get("training_games"))
        run["battle_completed"] = self._count_evolution_games(run.get("battle_games"))
        heartbeat = self._touch_background_task(run, timestamp=snapshot.get("last_heartbeat_at"))
        run["overall_progress"] = self._evolution_overall_progress(run)
        run["overall_progress"]["updated_at"] = heartbeat
        self._refresh_evolution_batch(run.get("batch_id"))
        self._persist_background_tasks()

    def _evolution_cancel_check(self, run_id: str) -> bool:
        run = self.evolution_runs.get(run_id)
        if run is None:
            return True
        if run.get("stop_requested") or run.get("cancelled"):
            return True
        batch_id = run.get("batch_id")
        batch = self.evolution_batches.get(str(batch_id)) if batch_id else None
        return bool(batch and (batch.get("stop_requested") or batch.get("cancelled")))

    def _run_summary_for_batch(self, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run.get("run_id"),
            "role": run.get("role"),
            "status": run.get("status"),
            "current_stage": run.get("current_stage"),
            "progress": run.get("progress") if isinstance(run.get("progress"), dict) else {},
            "overall_progress": run.get("overall_progress") if isinstance(run.get("overall_progress"), dict) else self._evolution_overall_progress(run),
            "training_completed": self._count_evolution_games(run.get("training_completed") or run.get("training_games")),
            "training_game_count": self._count_evolution_games(run.get("training_game_count")),
            "battle_completed": self._count_evolution_games(run.get("battle_completed") or run.get("battle_games")),
            "battle_game_count": self._count_evolution_games(run.get("battle_game_count")),
            "candidate_hash": run.get("candidate_hash"),
            "parent_hash": run.get("parent_hash"),
            "recommendation": run.get("recommendation"),
            "error": run.get("error"),
            "diagnostic_count": len(run.get("diagnostics", []) or []),
            "warning_count": len(run.get("warnings", []) or []),
            "error_count": len(run.get("errors", []) or []),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "last_heartbeat_at": run.get("last_heartbeat_at"),
        }

    def _refresh_evolution_batch(self, batch_id: Any) -> None:
        if not batch_id:
            return
        batch = self.evolution_batches.get(str(batch_id))
        if batch is None or batch.get("kind") != "role_evolution_batch":
            return
        run_ids = [str(item) for item in batch.get("runs", []) or []]
        summaries = [
            self._run_summary_for_batch(self.evolution_runs[run_id])
            for run_id in run_ids
            if run_id in self.evolution_runs
        ]
        batch["run_summaries"] = summaries
        total = len(run_ids)
        completed = len([
            item for item in summaries
            if str(item.get("status") or "").lower() in {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}
        ])
        running = next((item for item in summaries if str(item.get("status") or "").lower() in {"queued", "running", "training", "consolidating", "applying", "battling"}), None)
        heartbeat = self._touch_background_task(batch)
        batch_status = str(batch.get("status") or "").lower()
        if batch.get("stop_requested") or batch.get("cancelled"):
            current_stage = "stopped"
        elif batch_status in {"completed", "failed", "interrupted"}:
            current_stage = batch_status
        elif running:
            current_stage = running.get("current_stage")
        else:
            current_stage = batch.get("current_stage") or batch.get("status")
        batch["current_stage"] = current_stage
        batch["progress"] = {
            "stage": current_stage,
            "percent": (completed / total) if total else 0.0,
            "completed_roles": completed,
            "role_count": total,
            "total_roles": total,
            "updated_at": heartbeat,
        }
        batch["overall_progress"] = dict(batch["progress"])

    def _mark_evolution_stopped(self, entity: dict[str, Any]) -> None:
        entity["status"] = "failed"
        entity["error"] = entity.get("error") or MANUAL_STOP_REASON
        _set_task_contract(entity, stop_requested=True, cancelled=True, interrupted=False, failed=False)
        heartbeat = self._touch_background_task(entity)
        entity["finished_at"] = entity.get("finished_at") or heartbeat
        entity["current_stage"] = "stopped"
        progress = entity.get("progress")
        progress = dict(progress) if isinstance(progress, dict) else {}
        progress["stage"] = "stopped"
        progress.setdefault("percent", self._task_progress_percent(entity))
        progress["updated_at"] = heartbeat
        entity["progress"] = progress
        if entity.get("kind") == "role_evolution_run":
            entity["overall_progress"] = self._evolution_overall_progress(entity)
        elif entity.get("kind") == "role_evolution_batch":
            self._refresh_evolution_batch(entity.get("batch_id"))

    async def run_queued_evolution(self, run_id: str, request: EvolutionStartRequest) -> None:
        run = self.evolution_runs.get(run_id)
        if run is None:
            return
        request = automatic_evolution_request(request)
        if self._evolution_cancel_check(run_id):
            self._mark_evolution_stopped(run)
            self._persist_background_tasks()
            return
        role = str(run.get("role") or "villager")
        run["status"] = "training"
        run["current_stage"] = "training"
        run.setdefault("started_at", beijing_now_iso())
        self._touch_background_task(run)
        run["overall_progress"] = self._evolution_overall_progress(run)
        self._persist_background_tasks()
        try:
            result = await run_evolution(
                role=role,
                training_games=request.training_games,
                battle_games=request.battle_games,
                max_days=request.max_days,
                auto_promote=request.auto_promote,
                run_id=run_id,
                model=self.model_for_run(),
                paths=self.paths,
                progress_sink=lambda snapshot: self._sync_evolution_progress(run_id, snapshot),
                cancel_check=lambda: self._evolution_cancel_check(run_id),
            )
        except Exception as exc:  # pragma: no cover - defensive background failure path
            if self._evolution_cancel_check(run_id) or str(exc) == MANUAL_STOP_REASON:
                self._mark_evolution_stopped(run)
                self._refresh_evolution_batch(run.get("batch_id"))
                self._persist_background_tasks()
                return
            run["status"] = "failed"
            _set_task_contract(run, failed=True, cancelled=False, interrupted=False)
            run["finished_at"] = beijing_now_iso()
            run.setdefault("errors", []).append(str(exc))
            run.setdefault("diagnostics", []).append(
                {
                    "kind": "evolution_error",
                    "stage": "evolution.run",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                }
            )
            run["error"] = str(exc)
            self._touch_background_task(run)
            self._persist_background_tasks()
            return

        if self._evolution_cancel_check(run_id):
            self._mark_evolution_stopped(run)
            self._refresh_evolution_batch(run.get("batch_id"))
            self._persist_background_tasks()
            return
        run.update(result)
        run["run_id"] = result.get("run_id") or run_id
        run["role"] = role
        run["status"] = result.get("status", "reviewing")
        _set_task_contract(run, failed=run["status"] == "failed", cancelled=False, interrupted=False)
        run["started_at"] = run.get("started_at") or beijing_now_iso()
        run["finished_at"] = result.get("finished_at") or beijing_now_iso()
        self._touch_background_task(run)
        run["training_completed"] = self._count_evolution_games(run.get("training_games"))
        run["battle_completed"] = self._count_evolution_games(run.get("battle_games"))
        run["overall_progress"] = self._evolution_overall_progress(run)
        self._refresh_evolution_batch(run.get("batch_id"))
        self._persist_background_tasks()

    async def run_queued_evolution_batch(self, batch_id: str, request: EvolutionStartRequest) -> None:
        request = automatic_evolution_request(request)
        batch = self.evolution_batches.get(batch_id)
        if batch is None:
            return
        batch["status"] = "running"
        _set_task_contract(batch, failed=False, cancelled=False, interrupted=False)
        self._refresh_evolution_batch(batch_id)
        self._touch_background_task(batch)
        self._persist_background_tasks()
        try:
            for run_id in list(batch.get("runs", [])):
                if batch.get("stop_requested") or batch.get("cancelled") or batch.get("status") in {"failed", "rejected"}:
                    break
                self._touch_background_task(batch)
                self._refresh_evolution_batch(batch_id)
                self._persist_background_tasks()
                await self.run_queued_evolution(str(run_id), request)
                self._touch_background_task(batch)
                self._refresh_evolution_batch(batch_id)
                self._persist_background_tasks()
            if batch.get("stop_requested") or batch.get("cancelled"):
                batch["status"] = "failed"
                batch["error"] = batch.get("error") or MANUAL_STOP_REASON
                _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
                self._mark_evolution_stopped(batch)
            elif batch.get("status") == "running":
                batch["status"] = "completed"
                _set_task_contract(batch, stop_requested=False, cancelled=False, interrupted=False, failed=False)
        except Exception as exc:  # pragma: no cover - defensive background failure path
            batch["status"] = "failed"
            batch["error"] = str(exc)
            self._append_background_diagnostic(
                batch,
                {
                    "kind": "evolution_batch_error",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                },
                stage="evolution.batch",
                timestamp=beijing_now_iso(),
            )
            _set_task_contract(batch, failed=True, cancelled=False, interrupted=False)
        finally:
            batch["finished_at"] = beijing_now_iso()
            self._touch_background_task(batch)
            self._refresh_evolution_batch(batch_id)
            self._persist_background_tasks()

    async def _run_single_evolution(self, role: str, request: EvolutionStartRequest) -> dict[str, Any]:
        request = automatic_evolution_request(request)
        run = self._create_evolution_run(role, request)
        run_id = run["run_id"]
        result = await run_evolution(
            role=role,
            training_games=request.training_games,
            battle_games=request.battle_games,
            max_days=request.max_days,
            auto_promote=request.auto_promote,
            run_id=run_id,
            model=self.model_for_run(),
            paths=self.paths,
        )
        run.update(result)
        run["run_id"] = result.get("run_id") or run_id
        run["role"] = role
        run["status"] = result.get("status", "reviewing")
        _set_task_contract(run, failed=run["status"] == "failed", cancelled=False, interrupted=False)
        run["started_at"] = run.get("started_at") or beijing_now_iso()
        run["finished_at"] = result.get("finished_at") or beijing_now_iso()
        self._touch_background_task(run)
        self._persist_background_tasks()
        return run

    def _queue_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        run_plan = self._benchmark_run_plan(request)
        if _benchmark_budget_exceeded(run_plan.get("budget", {})):
            raise HTTPException(status_code=422, detail=_benchmark_budget_error_detail(run_plan))
        spec, seed_set = self._resolve_benchmark_spec(request)
        benchmark_meta = self._benchmark_metadata(spec, seed_set) if spec else None
        roles = self._benchmark_roles(request, spec)
        model_runtime = self.benchmark_model_runtime(request)
        request_config = self._benchmark_request_config(request, spec)
        if spec is not None or request.target_type == "model" or request.model_id or request.model_config_hash:
            request_config["model_id"] = model_runtime["model_id"]
            request_config["model_config_hash"] = model_runtime["model_config_hash"]
            request_config["model_runtime"] = _json_clone(model_runtime["model_runtime"])
        batch_id = f"bench_{uuid.uuid4().hex[:10]}"
        now = beijing_now_iso()
        batch = {
            "kind": "benchmark_batch",
            "schema_version": 2 if spec else 1,
            "batch_id": batch_id,
            "benchmark": benchmark_meta,
            "target_type": spec.target_type if spec else request.target_type,
            "model_id": model_runtime["model_id"],
            "model_config_hash": model_runtime["model_config_hash"],
            "model_runtime": _json_clone(model_runtime["model_runtime"]),
            "roles": roles,
            "status": "running",
            "stop_requested": False,
            "cancelled": False,
            "interrupted": False,
            "failed": False,
            "started_at": now,
            "last_heartbeat_at": now,
            "finished_at": None,
            "current_stage": "queued",
            "progress": {
                "stage": "queued",
                "percent": 0.0,
                "completed_roles": 0,
                "role_count": len(roles),
                "total_roles": len(roles),
                "updated_at": now,
            },
            "diagnostics": [],
            "config": request_config,
            "run_plan": run_plan,
            "result": None,
            "error": None,
        }
        self.evolution_batches[batch_id] = batch
        self._persist_background_tasks()
        return batch

    def _validate_benchmark_target_versions(self, roles: list[str], request: BenchmarkRequest, *, target_type: str) -> None:
        """Allow explicit canary evaluation targets while keeping shadow out of benchmark runs."""
        if target_type != "role_version":
            return
        for role in roles:
            version_id = request.target_versions.get(role)
            if not version_id:
                continue
            try:
                release_stage = registry_version_release_stage(self.registry, role, version_id)
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=domain_error_detail(
                        code="benchmark_target_version_not_found",
                        message="Benchmark target version was not found.",
                        detail=f"benchmark target version not found: {role}/{version_id}",
                        diagnostics=[{
                            "kind": "benchmark_target_version_not_found",
                            "role": str(role),
                            "version_id": str(version_id),
                        }],
                    ),
                ) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if str(release_stage or "").strip().lower() == "shadow":
                raise HTTPException(
                    status_code=409,
                    detail=domain_error_detail(
                        code="benchmark_target_version_not_allowed",
                        message="Benchmark target version is not allowed.",
                        detail=(
                            f"benchmark target version not allowed: {role}/{version_id} "
                            "is release_stage=shadow; promote to canary before explicit evaluation"
                        ),
                        diagnostics=[
                            release_stage_diagnostic(
                                role=role,
                                version_id=version_id,
                                release_stage="shadow",
                                kind="benchmark_target_version_not_allowed",
                                allowed_flow="benchmark_canary_or_baseline",
                            )
                        ],
                    ),
                )

    async def _run_queued_benchmark(self, batch_id: str, request: BenchmarkRequest) -> None:
        batch = self.evolution_batches.get(batch_id)
        if batch is None:
            return
        if batch.get("stop_requested") or batch.get("cancelled") or batch.get("status") in {"failed", "cancelled"}:
            batch["finished_at"] = batch.get("finished_at") or beijing_now_iso()
            batch["error"] = batch.get("error") or MANUAL_STOP_REASON
            _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
            self._mark_benchmark_stage(
                batch,
                "stopped",
                status="failed",
                percent=self._task_progress_percent(batch),
                diagnostic={"kind": "benchmark_stopped", "message": batch["error"]},
            )
            self._persist_background_tasks()
            return

        # Role-version benchmarks run one evaluation batch per requested role.
        # Model benchmarks are model-scope: a single batch runs the full fixed
        # role set without assigning target_role/target_version_id.
        if str(batch.get("target_type") or request.target_type or "role_version") == "model":
            roles = [None]
        else:
            roles = [r for r in (batch.get("roles") or request.roles or []) if r] or [None]
        role_count = len(roles)
        results: list[dict[str, Any]] = []
        self._mark_benchmark_stage(
            batch,
            "preparing",
            status="running",
            percent=0.0,
            role_count=role_count,
            completed_roles=0,
        )
        self._persist_background_tasks()
        try:
            for index, role in enumerate(roles):
                if batch.get("stop_requested") or batch.get("cancelled"):
                    break
                role_label = role or "all"
                self._mark_benchmark_stage(
                    batch,
                    "evaluating",
                    status="running",
                    percent=index / role_count if role_count else 0.0,
                    role=role_label,
                    role_index=index + 1,
                    role_count=role_count,
                    completed_roles=index,
                )
                self._persist_background_tasks()
                results.append(
                    await run_evaluation(
                        batch_config=self._benchmark_batch_config(batch_id, role, request, index),
                        model=self.model_for_run(),
                        paths=self.paths,
                    )
                )
                self._mark_benchmark_stage(
                    batch,
                    "evaluating",
                    status="running",
                    percent=(index + 1) / role_count if role_count else 1.0,
                    role=role_label,
                    role_index=index + 1,
                    role_count=role_count,
                    completed_roles=index + 1,
                )
                self._persist_background_tasks()
        except Exception as exc:  # pragma: no cover - defensive background failure path
            batch["finished_at"] = beijing_now_iso()
            batch["error"] = str(exc)
            _set_task_contract(batch, failed=True, cancelled=False, interrupted=False)
            self._mark_benchmark_stage(
                batch,
                "failed",
                status="failed",
                percent=self._task_progress_percent(batch),
                diagnostic={
                    "kind": "benchmark_error",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                },
            )
            self._persist_background_tasks()
            return

        if batch.get("stop_requested") or batch.get("cancelled") or batch.get("status") in {"failed", "cancelled"}:
            batch["finished_at"] = batch.get("finished_at") or beijing_now_iso()
            batch["error"] = batch.get("error") or MANUAL_STOP_REASON
            _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
            self._mark_benchmark_stage(
                batch,
                "stopped",
                status="failed",
                percent=self._task_progress_percent(batch),
                completed_roles=len(results),
                role_count=role_count,
                diagnostic={"kind": "benchmark_stopped", "message": batch["error"]},
            )
            self._persist_background_tasks()
            return

        batch["status"] = "completed"
        _set_task_contract(batch, stop_requested=False, cancelled=False, interrupted=False, failed=False)
        batch["started_at"] = (results[0].get("started_at") if results else None) or batch.get("started_at") or beijing_now_iso()
        batch["finished_at"] = beijing_now_iso()
        # Keep the first result as the headline; expose all per-role results too.
        batch["result"] = results[0] if results else None
        batch["results"] = results
        self._mark_benchmark_stage(
            batch,
            "completed",
            status="completed",
            percent=1.0,
            role_count=role_count,
            completed_roles=len(results),
        )
        self.invalidate_role_overview_cache()
        self._persist_background_tasks()

    def _benchmark_batch_config(
        self, batch_id: str, role: str | None, request: BenchmarkRequest, index: int
    ) -> dict[str, Any]:
        """Build an eval batch config from benchmark spec metadata or legacy request."""
        batch = self.evolution_batches.get(batch_id, {})
        spec_snapshot = _benchmark_spec_snapshot(batch)
        benchmark_meta = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
        target_type = str(batch.get("target_type") or request.target_type or "role_version")
        if spec_snapshot:
            game_count = int(spec_snapshot.get("game_count", request.battle_games or 0) or 0)
            max_days = int(spec_snapshot.get("max_days", request.max_days or 5) or request.max_days or 5)
            seed_sequence = _benchmark_seed_sequence(spec_snapshot, game_count)
            seed_start = (
                int(seed_sequence[0])
                if seed_sequence
                else int(spec_snapshot.get("seed_start", 0) or 0) + index * game_count
            )
            paired_seed = bool(spec_snapshot.get("paired_seed", True))
            gates = spec_snapshot.get("gates") if isinstance(spec_snapshot.get("gates"), dict) else {}
            judge = spec_snapshot.get("judge") if isinstance(spec_snapshot.get("judge"), dict) else {}
        else:
            game_count = 10 if request.battle_games is None else request.battle_games
            max_days = 5 if request.max_days is None else request.max_days
            seed_sequence = []
            seed_start = None
            paired_seed = False
            gates = {}
            judge = {}

        cfg: dict[str, Any] = {
            "batch_id": _benchmark_eval_batch_id(batch_id, role),
            "comparison_group_id": batch_id,
            "comparison_type": target_type,
            "scope": target_type,
            "game_count": game_count,
            "max_days": max_days,
            "paired_seed": paired_seed,
        }
        frozen_config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
        frozen_runtime = batch.get("model_runtime")
        if not isinstance(frozen_runtime, dict) or not frozen_runtime:
            frozen_runtime = frozen_config.get("model_runtime")
        if isinstance(frozen_runtime, dict) and frozen_runtime:
            cfg["model_id"] = batch.get("model_id") or frozen_config.get("model_id") or frozen_runtime.get("model_id")
            cfg["model_config_hash"] = (
                batch.get("model_config_hash")
                or frozen_config.get("model_config_hash")
                or frozen_runtime.get("model_config_hash")
            )
            cfg["model_runtime"] = _json_clone(frozen_runtime)
        else:
            model_runtime = self.benchmark_model_runtime(request)
            cfg["model_id"] = model_runtime["model_id"]
            cfg["model_config_hash"] = model_runtime["model_config_hash"]
            cfg["model_runtime"] = model_runtime["model_runtime"]
            if isinstance(batch, dict):
                batch["model_id"] = model_runtime["model_id"]
                batch["model_config_hash"] = model_runtime["model_config_hash"]
                batch["model_runtime"] = _json_clone(model_runtime["model_runtime"])
                if isinstance(batch.get("config"), dict):
                    batch["config"]["model_id"] = model_runtime["model_id"]
                    batch["config"]["model_config_hash"] = model_runtime["model_config_hash"]
                    batch["config"]["model_runtime"] = _json_clone(model_runtime["model_runtime"])
        for key, value in (
            ("evaluation_set_id", benchmark_meta.get("evaluation_set_id")),
            ("seed_set_id", benchmark_meta.get("seed_set_id")),
            ("benchmark_id", benchmark_meta.get("id")),
            ("benchmark_version", benchmark_meta.get("version")),
            ("benchmark_config_hash", benchmark_meta.get("config_hash")),
        ):
            if value is not None:
                cfg[key] = value
        _apply_benchmark_langfuse_config_defaults(cfg, frozen_config=frozen_config, request=request)
        if seed_start is not None:
            cfg["seed_start"] = seed_start
        if seed_sequence:
            cfg["seeds"] = seed_sequence
        _apply_benchmark_gates(cfg, gates)
        _apply_benchmark_judge(cfg, judge)
        if role and target_type == "role_version":
            explicit_target = request.target_versions.get(role)
            if explicit_target:
                self._validate_benchmark_target_versions([role], request, target_type=target_type)
            target_version = explicit_target or self.registry.get_baseline(role)
            if target_version:
                cfg["target_role"] = role
                cfg["target_version_id"] = target_version
        return cfg

    def _resolve_benchmark_spec(
        self, request: BenchmarkRequest
    ) -> tuple[BenchmarkSpec | None, BenchmarkSeedSet | None]:
        if not request.benchmark_id:
            return None, None
        try:
            spec, _lifecycle_override = self._benchmark_spec_with_lifecycle(request.benchmark_id)
            spec, seed_set = materialize_benchmark_spec(spec, paths=self.paths)
            if not spec.launchable:
                reason = benchmark_spec_summary(spec, seed_set).get("launch_disabled_reason") or (
                    f"benchmark suite status={spec.lifecycle_status} cannot be launched"
                )
                raise HTTPException(
                    status_code=409,
                    detail=domain_error_detail(
                        code="benchmark_suite_not_launchable",
                        message="Benchmark suite cannot be launched.",
                        detail=reason,
                        diagnostics=[{
                            "kind": "benchmark_suite_not_launchable",
                            "benchmark_id": spec.id,
                            "status": spec.lifecycle_status,
                        }],
                    ),
                )
            return spec, seed_set
        except BenchmarkSpecError as exc:
            status = 404 if "not found" in str(exc) else 422
            detail = "benchmark not found" if status == 404 else str(exc)
            raise HTTPException(status_code=status, detail=detail) from exc

    def _benchmark_roles(self, request: BenchmarkRequest, spec: BenchmarkSpec | None) -> list[str]:
        if spec is None:
            return list(request.roles)
        if spec.target_type == "model":
            return list(spec.roles)
        if not request.roles:
            return list(spec.roles)
        allowed = set(spec.roles)
        unsupported = [role for role in request.roles if role not in allowed]
        if unsupported:
            raise HTTPException(
                status_code=422,
                detail=f"roles not in benchmark spec: {', '.join(unsupported)}",
            )
        return list(request.roles)

    def _benchmark_metadata(self, spec: BenchmarkSpec, seed_set: BenchmarkSeedSet | None = None) -> dict[str, Any]:
        snapshot = spec.model_dump(mode="json")
        meta = {
            "id": spec.id,
            "version": spec.version,
            "target_type": spec.target_type,
            "config_hash": benchmark_config_hash(snapshot),
            "evaluation_set_id": spec.evaluation_set_id,
            "seed_set_id": spec.seed_set_id,
            "seed_count": len(snapshot.get("seeds") or []) or spec.game_count,
            "seed_preview": list(snapshot.get("seeds") or [])[:5],
            "spec_snapshot": snapshot,
        }
        if seed_set is not None:
            seed_snapshot = seed_set.model_dump(mode="json")
            meta["seed_set"] = benchmark_seed_set_summary(seed_set)
            meta["seed_set_version"] = seed_set.version
            meta["seed_set_config_hash"] = seed_set_config_hash(seed_snapshot)
            meta["seed_set_tier"] = seed_set.tier
            meta["seed_set_usage_boundary"] = seed_set.usage_boundary
            meta["seed_set_immutable"] = seed_set.immutable
            meta["seed_set_non_overlap_group"] = seed_set.non_overlap_group
            meta["seed_set_snapshot"] = seed_snapshot
        return meta

    @staticmethod
    def _benchmark_request_config(request: BenchmarkRequest, spec: BenchmarkSpec | None = None) -> dict[str, Any]:
        payload = request.model_dump(exclude_none=True)
        if spec is not None:
            payload["target_type"] = spec.target_type
        if not payload.get("target_versions"):
            payload.pop("target_versions", None)
        if payload.get("target_type") == "role_version" and not payload.get("benchmark_id"):
            payload.pop("target_type", None)
        return payload


def _benchmark_results(batch: dict[str, Any]) -> list[dict[str, Any]]:
    results = batch.get("results")
    if isinstance(results, list):
        return [dict(item) for item in results if isinstance(item, dict)]
    result = batch.get("result")
    return [dict(result)] if isinstance(result, dict) else []


def _benchmark_result_batch_id(result: dict[str, Any]) -> str:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    return str(result.get("batch_id") or config.get("batch_id") or "")


def _benchmark_result_role(result: dict[str, Any]) -> str | None:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    role = result.get("target_role") or config.get("target_role")
    return str(role) if role else None


def _benchmark_result_game_count(result: dict[str, Any]) -> int:
    for key in ("game_count", "completed", "attempted_game_count"):
        try:
            if result.get(key) is not None:
                return max(0, int(result.get(key) or 0))
        except (TypeError, ValueError):
            continue
    games = result.get("games")
    return len([item for item in games if isinstance(item, dict)]) if isinstance(games, list) else 0


def _benchmark_eval_batch_id(batch_id: str, role: str | None) -> str:
    return f"{batch_id}_{role}" if role else batch_id


def _apply_benchmark_langfuse_config_defaults(
    cfg: dict[str, Any],
    *,
    frozen_config: dict[str, Any],
    request: BenchmarkRequest,
) -> None:
    for key in LANGFUSE_EVAL_CONFIG_KEYS:
        value = _optional_text(frozen_config.get(key)) or _optional_text(getattr(request, key, None))
        if value is not None:
            cfg[key] = value

    evaluation_set_id = _optional_text(cfg.get("evaluation_set_id"))
    benchmark_id = _optional_text(cfg.get("benchmark_id"))
    if _optional_text(cfg.get("langfuse_dataset_name")) is None and evaluation_set_id is not None:
        cfg["langfuse_dataset_name"] = evaluation_set_id
    if _optional_text(cfg.get("langfuse_experiment_name")) is None:
        experiment_name = benchmark_id or evaluation_set_id
        if experiment_name is not None:
            cfg["langfuse_experiment_name"] = experiment_name
    if _optional_text(cfg.get("langfuse_run_name")) is None:
        run_name = _optional_text(cfg.get("batch_id"))
        if run_name is not None:
            cfg["langfuse_run_name"] = run_name


def _benchmark_games_for_batch(batch: dict[str, Any]) -> list[dict[str, Any]]:
    parent_batch_id = str(batch.get("batch_id") or "")
    games_out: list[dict[str, Any]] = []
    for result in _benchmark_results(batch):
        result_batch_id = _benchmark_result_batch_id(result)
        target_role = _benchmark_result_role(result)
        games = result.get("games")
        if not isinstance(games, list):
            continue
        for index, game in enumerate(games, start=1):
            if not isinstance(game, dict):
                continue
            games_out.append(
                _benchmark_game_item(
                    parent_batch_id=parent_batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    target_type=str(batch.get("target_type") or ""),
                    result=result,
                    game=game,
                    index=index,
                )
            )
    return games_out


def _benchmark_game_item(
    *,
    parent_batch_id: str,
    result_batch_id: str,
    target_role: str | None,
    target_type: str,
    result: dict[str, Any],
    game: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    game_id = str(game.get("game_id") or game.get("id") or game.get("source_game_id") or "")
    history_game_id = str(game.get("history_game_id") or game_id or "")
    events = game.get("events") if isinstance(game.get("events"), list) else []
    decisions = game.get("decisions") if isinstance(game.get("decisions"), list) else []
    diagnostics = _dict_items(game.get("diagnostics"))
    item = {
        "batch_id": parent_batch_id,
        "result_batch_id": result_batch_id,
        "target_type": target_type,
        "target_role": target_role,
        "index": index,
        "game_id": game_id,
        "id": str(game.get("id") or game_id),
        "history_game_id": history_game_id or None,
        "replay_available": bool(history_game_id),
        "replay_unavailable_reason": None if history_game_id else "missing game id for replay",
        "status": _benchmark_game_status(game),
        "seed": game.get("seed"),
        "winner": game.get("winner"),
        "phase": game.get("phase") or "benchmark",
        "side": game.get("side"),
        "event_count": int(game.get("event_count") or len(events)),
        "decision_count": int(game.get("decision_count") or len(decisions)),
        "day": game.get("day", game.get("days", 0)),
        "days": game.get("days", game.get("day", 0)),
        "in_progress": bool(game.get("in_progress", False)),
        "source_run_id": game.get("source_run_id") or result_batch_id,
        "source_game_id": game.get("source_game_id") or game_id,
        "diagnostic_count": len(diagnostics),
    }
    errors = _text_items(game.get("errors"))
    if errors and "error_count" not in item:
        item["error_count"] = len(errors)
    fallbacks = _dict_items(game.get("fallbacks"))
    if fallbacks and "fallback_count" not in item:
        item["fallback_count"] = len(fallbacks)
    llm_errors = _text_items(game.get("llm_errors"))
    if llm_errors and "llm_error_count" not in item:
        item["llm_error_count"] = len(llm_errors)
    policy_adjustments = _dict_items(game.get("policy_adjustments"))
    if policy_adjustments and "policy_adjusted_count" not in item:
        item["policy_adjusted_count"] = len(policy_adjustments)
    for key in (
        "error",
        "rankable",
        "rankable_reason",
        "timeout",
        "abnormal",
        "fallback",
        "fallback_count",
        "llm_error",
        "llm_error_count",
        "policy_adjusted",
        "policy_adjusted_count",
    ):
        if key in game:
            item[key] = game.get(key)
    langfuse = _benchmark_game_langfuse_block(
        game=game,
        result=result,
        result_batch_id=result_batch_id,
        index=index,
    )
    if langfuse:
        item["langfuse"] = langfuse
        item["observability"] = {"langfuse": _json_clone(langfuse)}
    return item


def _benchmark_game_langfuse_block(
    *,
    game: dict[str, Any],
    result: dict[str, Any],
    result_batch_id: str,
    index: int,
) -> dict[str, Any]:
    result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
    score_summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
    game_sources = _langfuse_sources(game)
    batch_sources = [result_config, result, score_summary]
    seed = game.get("seed")
    dataset_item_id = (
        _langfuse_text(game_sources, "dataset_item_id")
        or _benchmark_langfuse_dataset_item_id_from_config(result_config, seed=seed, index=index)
        or _langfuse_text(batch_sources, "dataset_item_id")
    )
    dataset_run_url = _langfuse_text(game_sources, "dataset_run_url")
    experiment_url = _langfuse_text(game_sources, "experiment_url")
    if dataset_run_url is None:
        dataset_run_url = experiment_url
    if experiment_url is None:
        experiment_url = dataset_run_url

    block = {
        "trace_id": _langfuse_text(game_sources, "trace_id"),
        "trace_url": _langfuse_text(game_sources, "trace_url"),
        "dataset_name": _langfuse_text(game_sources, "dataset_name")
        or _langfuse_text(batch_sources, "dataset_name")
        or _optional_text(result_config.get("evaluation_set_id")),
        "dataset_id": _langfuse_text(game_sources, "dataset_id"),
        "dataset_item_id": dataset_item_id,
        "dataset_item_url": _langfuse_text(game_sources, "dataset_item_url"),
        "dataset_run_id": _langfuse_text(game_sources, "dataset_run_id")
        or _langfuse_text(batch_sources, "dataset_run_id"),
        "dataset_run_item_id": _langfuse_text(game_sources, "dataset_run_item_id"),
        "dataset_run_url": dataset_run_url,
        "experiment_name": _langfuse_text(game_sources, "experiment_name")
        or _langfuse_text(batch_sources, "experiment_name")
        or _optional_text(result_config.get("benchmark_id"))
        or _optional_text(result_config.get("evaluation_set_id")),
        "run_name": _langfuse_text(game_sources, "run_name")
        or _langfuse_text(batch_sources, "run_name")
        or _optional_text(result_config.get("batch_id"))
        or _optional_text(result_batch_id),
        "experiment_url": experiment_url,
    }
    return {key: value for key, value in block.items() if value is not None}


_LANGFUSE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "trace_id": ("trace_id", "langfuse_trace_id"),
    "trace_url": ("trace_url", "langfuse_trace_url"),
    "dataset_name": ("dataset_name", "langfuse_dataset_name"),
    "dataset_id": ("dataset_id", "langfuse_dataset_id"),
    "dataset_item_id": ("dataset_item_id", "langfuse_dataset_item_id"),
    "dataset_item_url": ("dataset_item_url", "langfuse_dataset_item_url"),
    "dataset_run_id": ("dataset_run_id", "langfuse_dataset_run_id"),
    "dataset_run_item_id": ("dataset_run_item_id", "langfuse_dataset_run_item_id"),
    "dataset_run_url": ("dataset_run_url", "langfuse_dataset_run_url"),
    "experiment_name": ("experiment_name", "langfuse_experiment_name"),
    "run_name": ("run_name", "langfuse_run_name"),
    "experiment_url": ("experiment_url", "langfuse_experiment_url"),
}


def _langfuse_sources(value: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    langfuse = value.get("langfuse")
    if isinstance(langfuse, dict):
        sources.append(langfuse)
    observability = value.get("observability")
    if isinstance(observability, dict):
        observed_langfuse = observability.get("langfuse")
        if isinstance(observed_langfuse, dict):
            sources.append(observed_langfuse)
    sources.append(value)
    return sources


def _langfuse_text(sources: list[dict[str, Any]], field: str) -> str | None:
    for source in sources:
        for key in _LANGFUSE_FIELD_ALIASES.get(field, (field,)):
            text = _optional_text(source.get(key))
            if text is not None:
                return text
    return None


def _benchmark_langfuse_dataset_item_id_from_config(
    cfg: dict[str, Any],
    *,
    seed: Any,
    index: int,
) -> str | None:
    configured = cfg.get("langfuse_dataset_item_id")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    zero_index = max(0, int(index or 1) - 1)
    if isinstance(configured, list):
        for candidate_index in (zero_index, index):
            if 0 <= candidate_index < len(configured):
                value = _optional_text(configured[candidate_index])
                if value is not None:
                    return value
    if isinstance(configured, dict):
        for key in (seed, str(seed) if seed is not None else None, zero_index, str(zero_index), index, str(index)):
            if key is not None and key in configured:
                value = _optional_text(configured[key])
                if value is not None:
                    return value

    evaluation_set_id = _optional_text(cfg.get("evaluation_set_id"))
    seed_set_id = _optional_text(cfg.get("seed_set_id"))
    seed_text = _optional_text(seed)
    if evaluation_set_id is None or seed_set_id is None or seed_text is None:
        return None
    return f"{evaluation_set_id}:{seed_set_id}:{seed_text}"


def _benchmark_batch_langfuse_summary(batch: dict[str, Any], *, games: list[dict[str, Any]]) -> dict[str, Any]:
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    results = _benchmark_results(batch)
    result_configs = [
        result.get("config")
        for result in results
        if isinstance(result.get("config"), dict)
    ]
    config_sources = [source for source in [config, *result_configs] if isinstance(source, dict)]
    game_blocks = [game.get("langfuse") for game in games if isinstance(game.get("langfuse"), dict)]
    return {
        "dataset_names": _unique_texts(
            *[_langfuse_text(config_sources, "dataset_name")],
            *[block.get("dataset_name") for block in game_blocks if isinstance(block, dict)],
        ),
        "experiment_names": _unique_texts(
            *[_langfuse_text(config_sources, "experiment_name")],
            *[block.get("experiment_name") for block in game_blocks if isinstance(block, dict)],
        ),
        "run_names": _unique_texts(
            *[_langfuse_text(config_sources, "run_name")],
            *[block.get("run_name") for block in game_blocks if isinstance(block, dict)],
        ),
        "trace_count": len(_unique_texts(*[block.get("trace_id") for block in game_blocks if isinstance(block, dict)])),
        "dataset_run_count": len(
            _unique_texts(*[block.get("dataset_run_id") for block in game_blocks if isinstance(block, dict)])
        ),
        "dataset_run_item_count": len(
            _unique_texts(*[block.get("dataset_run_item_id") for block in game_blocks if isinstance(block, dict)])
        ),
        "dataset_item_count": len(
            _unique_texts(*[block.get("dataset_item_id") for block in game_blocks if isinstance(block, dict)])
        ),
        "links": {
            "trace_urls": _unique_texts(*[block.get("trace_url") for block in game_blocks if isinstance(block, dict)]),
            "dataset_run_urls": _unique_texts(
                *[block.get("dataset_run_url") for block in game_blocks if isinstance(block, dict)]
            ),
            "experiment_urls": _unique_texts(
                *[block.get("experiment_url") for block in game_blocks if isinstance(block, dict)]
            ),
        },
    }


def _benchmark_game_matches_status_filter(game: dict[str, Any], statuses: set[str]) -> bool:
    if "problem" in statuses and _benchmark_game_is_problem(game):
        return True
    explicit = {status for status in statuses if status != "problem"}
    if not explicit:
        return False
    return _match_filter(game.get("status", "completed"), explicit)


def _benchmark_game_is_problem(game: dict[str, Any]) -> bool:
    status = str(game.get("status") or "").strip().lower()
    if status in {"failed", "timeout", "abnormal", "cancelled", "interrupted"}:
        return True
    if int(game.get("diagnostic_count") or 0) > 0:
        return True
    if game.get("error") or game.get("timeout") or game.get("abnormal"):
        return True
    for key in ("fallback", "llm_error", "policy_adjusted", "errors", "fallbacks", "llm_errors", "policy_adjustments"):
        if game.get(key):
            return True
    for key in ("error_count", "fallback_count", "llm_error_count", "policy_adjusted_count"):
        try:
            if int(game.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _benchmark_game_status(game: dict[str, Any]) -> str:
    status = str(game.get("status") or "").strip().lower()
    if status:
        return status
    if game.get("error") or game.get("failed"):
        return "failed"
    if game.get("timeout"):
        return "timeout"
    if game.get("abnormal"):
        return "abnormal"
    return "completed"


def _benchmark_game_summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(game.get("status") or "unknown") for game in games)
    return {
        "total": len(games),
        "by_status": dict(sorted(counts.items())),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "timeout": counts.get("timeout", 0),
        "abnormal": counts.get("abnormal", 0),
    }


def _benchmark_diagnostic_entries(batch: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    batch_id = str(batch.get("batch_id") or "")
    for diagnostic in _dict_items(batch.get("diagnostics")):
        entries.append(_benchmark_diagnostic_entry(diagnostic, batch_id=batch_id, origin="batch"))
    if batch.get("error"):
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "benchmark_error",
                    "stage": batch.get("current_stage") or batch.get("status"),
                    "level": "error",
                    "message": str(batch.get("error")),
                },
                batch_id=batch_id,
                origin="batch",
            )
        )

    for result in _benchmark_results(batch):
        result_batch_id = _benchmark_result_batch_id(result)
        target_role = _benchmark_result_role(result)
        for diagnostic in _dict_items(result.get("diagnostics")):
            entries.append(
                _benchmark_diagnostic_entry(
                    diagnostic,
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    origin="result",
                )
            )
        for warning in _text_items(result.get("warnings")):
            entries.append(
                _benchmark_diagnostic_entry(
                    {
                        "kind": "result_warning",
                        "stage": "result.warning",
                        "level": "warning",
                        "message": warning,
                    },
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    origin="result",
                )
            )
        for error in _text_items(result.get("errors")):
            entries.append(
                _benchmark_diagnostic_entry(
                    {
                        "kind": "result_error",
                        "stage": "result.error",
                        "level": "error",
                        "message": error,
                    },
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    origin="result",
                )
            )
        entries.extend(_benchmark_quality_diagnostics(batch_id, result_batch_id, target_role, result))
        entries.extend(_benchmark_game_diagnostics(batch_id, result_batch_id, target_role, result))
    return _dedupe_benchmark_diagnostics(entries)


def _benchmark_quality_diagnostics(
    batch_id: str,
    result_batch_id: str,
    target_role: str | None,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if result.get("rankable") is False:
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "rankable_failed",
                    "stage": "leaderboard.rankable",
                    "level": "warning",
                    "message": str(result.get("rankable_reason") or "result is not rankable"),
                },
                batch_id=batch_id,
                result_batch_id=result_batch_id,
                target_role=target_role,
                origin="result",
            )
        )
    fairness = result.get("fairness") if isinstance(result.get("fairness"), dict) else {}
    if fairness and fairness.get("is_fair") is False:
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "fairness_failed",
                    "stage": "fairness.validate",
                    "level": "warning",
                    "message": str(fairness.get("reason") or "fairness check failed"),
                },
                batch_id=batch_id,
                result_batch_id=result_batch_id,
                target_role=target_role,
                origin="result",
            )
        )
    gate = result.get("leaderboard_gate") if isinstance(result.get("leaderboard_gate"), dict) else {}
    if gate and gate.get("accepted") is False:
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "leaderboard_gate_failed",
                    "stage": "leaderboard.gate",
                    "level": "warning",
                    "message": str(gate.get("reason") or result.get("leaderboard_skipped_reason") or "leaderboard gate failed"),
                    "metrics": gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {},
                },
                batch_id=batch_id,
                result_batch_id=result_batch_id,
                target_role=target_role,
                origin="result",
            )
        )
    summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
    judge = summary.get("decision_judge_aggregate") if isinstance(summary.get("decision_judge_aggregate"), dict) else {}
    judge_status = str(judge.get("status") or "").lower()
    if judge_status and judge_status not in {"ok", "disabled"}:
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "decision_judge_degraded",
                    "stage": "aggregate.decision_judge",
                    "level": "warning" if judge_status in {"degraded", "skipped"} else "error",
                    "message": str(judge.get("reason") or f"decision judge status: {judge_status}"),
                    "status": judge_status,
                    "metrics": judge.get("metrics") if isinstance(judge.get("metrics"), dict) else {},
                },
                batch_id=batch_id,
                result_batch_id=result_batch_id,
                target_role=target_role,
                origin="result",
            )
        )
    return entries


def _benchmark_game_diagnostics(
    batch_id: str,
    result_batch_id: str,
    target_role: str | None,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for game in result.get("games", []) or []:
        if not isinstance(game, dict):
            continue
        game_id = str(game.get("game_id") or game.get("id") or game.get("source_game_id") or "")
        status = _benchmark_game_status(game)
        message = str(game.get("error") or game.get("rankable_reason") or status)
        if status not in {"completed", "reviewing"} or game.get("error") or game.get("timeout") or game.get("abnormal"):
            entries.append(
                _benchmark_diagnostic_entry(
                    {
                        "kind": "game_failure",
                        "stage": "game.run",
                        "level": "warning" if status in {"timeout", "abnormal"} else "error",
                        "message": message,
                        "game_id": game_id,
                        "status": status,
                        "seed": game.get("seed"),
                    },
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    history_game_id=game.get("history_game_id") or game_id,
                    origin="game",
                )
            )
        for diagnostic in _dict_items(game.get("diagnostics")):
            entries.append(
                _benchmark_diagnostic_entry(
                    diagnostic,
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    game_id=game_id,
                    seed=game.get("seed"),
                    status=status,
                    history_game_id=game.get("history_game_id") or game_id,
                    origin="game",
                )
            )
    return entries


def _benchmark_diagnostic_entry(
    diagnostic: dict[str, Any],
    *,
    batch_id: str,
    origin: str,
    result_batch_id: str | None = None,
    target_role: str | None = None,
    game_id: str | None = None,
    seed: Any = None,
    status: str | None = None,
    history_game_id: str | None = None,
) -> dict[str, Any]:
    item = dict(diagnostic)
    item.setdefault("kind", "diagnostic")
    item.setdefault("stage", origin)
    item.setdefault("level", "warning")
    item["origin"] = origin
    item["batch_id"] = batch_id
    if result_batch_id:
        item["result_batch_id"] = result_batch_id
    if target_role:
        item["target_role"] = target_role
    if game_id:
        item["game_id"] = game_id
    if seed is not None:
        item.setdefault("seed", seed)
    if status:
        item.setdefault("status", status)
    if history_game_id:
        item.setdefault("history_game_id", history_game_id)
    if "message" not in item:
        item["message"] = str(item.get("kind") or "diagnostic")
    return item


def _benchmark_diagnostic_summary(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind = Counter(str(item.get("kind") or "diagnostic") for item in diagnostics)
    by_level = Counter(str(item.get("level") or "warning") for item in diagnostics)
    by_origin = Counter(str(item.get("origin") or "unknown") for item in diagnostics)
    return {
        "total": len(diagnostics),
        "by_kind": dict(sorted(by_kind.items())),
        "by_level": dict(sorted(by_level.items())),
        "by_origin": dict(sorted(by_origin.items())),
        "has_errors": bool(by_level.get("error")),
    }


_BENCHMARK_DIAGNOSTIC_KIND_LABELS = {
    "diagnostic": "诊断",
    "leaderboard_gate_failed": "门禁失败",
    "rankable_gate_failed": "门禁失败",
    "game_failure": "失败局",
    "game_timeout": "超时局",
    "timeout": "超时",
    "llm_error": "LLM 错误",
    "fallback": "Fallback",
    "decision_judge_degraded": "决策 Judge 降级",
    "decision_judge_skipped": "决策 Judge 跳过",
    "judge_degraded": "Judge 降级",
    "judge_skipped": "Judge 跳过",
}

_BENCHMARK_DIAGNOSTIC_LEVEL_LABELS = {
    "info": "信息",
    "warning": "警告",
    "warn": "警告",
    "error": "错误",
    "failed": "失败",
    "failure": "失败",
    "timeout": "超时",
}


def _benchmark_report_diagnostic_kind_label(value: Any) -> str:
    text = str(value or "diagnostic").strip()
    return _BENCHMARK_DIAGNOSTIC_KIND_LABELS.get(text) or _BENCHMARK_DIAGNOSTIC_KIND_LABELS.get(text.lower()) or text


def _benchmark_report_diagnostic_level_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "无等级"
    return _BENCHMARK_DIAGNOSTIC_LEVEL_LABELS.get(text.lower()) or text


def _benchmark_diagnostic_aggregate_summary(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _benchmark_diagnostic_summary(diagnostics)
    by_stage = Counter(str(item.get("stage") or "unknown") for item in diagnostics)
    by_target_role = Counter(str(item.get("target_role") or "all") for item in diagnostics)
    by_batch = Counter(str(item.get("batch_id") or "unknown") for item in diagnostics)
    by_seed = Counter(str(item.get("seed") or "unknown") for item in diagnostics if item.get("seed") is not None)
    summary.update(
        {
            "by_stage": dict(sorted(by_stage.items())),
            "by_target_role": dict(sorted(by_target_role.items())),
            "by_batch": dict(sorted(by_batch.items())),
            "by_seed": dict(sorted(by_seed.items())),
            "affected_run_count": len(by_batch),
            "affected_game_count": len(
                {
                    (str(item.get("batch_id") or ""), str(item.get("game_id") or ""))
                    for item in diagnostics
                    if item.get("game_id")
                }
            ),
        }
    )
    return summary


def _benchmark_run_report_payload(batch: dict[str, Any]) -> dict[str, Any]:
    from ui.backend.evolution_serializers import _benchmark_result_summary

    batch_id = str(batch.get("batch_id") or "")
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    meta = _benchmark_batch_boundary(batch)
    results = _benchmark_results(batch)
    result_rows: list[dict[str, Any]] = []
    for index, result in enumerate(results, start=1):
        result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
        summary = _benchmark_result_summary(result)
        if not isinstance(summary, dict):
            summary = {}
        result_batch_id = _benchmark_result_batch_id(result) or f"{batch_id}_result_{index}"
        target_role = _benchmark_result_role(result)
        rankable = result.get("rankable")
        result_rows.append(
            {
                **summary,
                "result_batch_id": result_batch_id,
                "target_role": target_role,
                "target_version_id": result.get("target_version_id") or result_config.get("target_version_id"),
                "model_id": result.get("model_id") or result_config.get("model_id"),
                "model_config_hash": result.get("model_config_hash") or result_config.get("model_config_hash"),
                "game_count": _benchmark_result_game_count(result),
                "diagnostic_count": len(_dict_items(result.get("diagnostics"))),
                "warning_count": len(_text_items(result.get("warnings"))),
                "rankable": rankable,
                "rankable_label": "可入榜" if rankable is not False else "未入榜",
                "rankable_reason": str(result.get("rankable_reason") or result.get("leaderboard_skipped_reason") or ""),
                "completed": result.get("completed"),
                "errored": result.get("errored"),
            }
        )

    games = _benchmark_games_for_batch(batch)
    diagnostics = _benchmark_diagnostic_entries(batch)
    problem_games = [
        game for game in games
        if (
            _benchmark_problem_status_weight(game.get("status")) > 0
            or int(game.get("diagnostic_count") or 0) > 0
        )
    ]
    problem_games.sort(
        key=lambda game: (
            _benchmark_problem_status_weight(game.get("status")),
            int(game.get("diagnostic_count") or 0),
            str(game.get("game_id") or ""),
        ),
        reverse=True,
    )
    diagnostic_groups = _benchmark_report_diagnostic_groups(diagnostics)
    top_tags = _benchmark_report_top_tags(results, diagnostics)
    subject = _benchmark_report_subject(results, config, meta)
    model_runtime = _benchmark_report_model_runtime(batch, results, config, meta)
    evaluation_set_id = meta.get("evaluation_set_id") or str(benchmark.get("evaluation_set_id") or "")
    seed_set_id = meta.get("seed_set_id") or str(benchmark.get("seed_set_id") or config.get("seed_set_id") or "")
    benchmark_config_hash = str(
        benchmark.get("config_hash")
        or benchmark.get("benchmark_config_hash")
        or config.get("benchmark_config_hash")
        or config.get("config_hash")
        or ""
    )
    summary = {
        "result_count": len(result_rows),
        "rankable_count": sum(1 for row in result_rows if row.get("rankable") is not False),
        "unrankable_count": sum(1 for row in result_rows if row.get("rankable") is False),
        "game_summary": _benchmark_game_summary(games),
        "problem_game_count": len(problem_games),
        "diagnostic_summary": _benchmark_diagnostic_summary(diagnostics),
        "diagnostic_group_count": len(diagnostic_groups),
    }
    report_id = f"benchmark_report:{batch_id}"
    payload = {
        "kind": "benchmark_run_report",
        "schema_version": 1,
        "report_id": report_id,
        "generated_at": beijing_now_iso(),
        "run_id": batch_id,
        "batch_id": batch_id,
        "status": batch.get("status"),
        "evaluation_set_id": evaluation_set_id or "ad-hoc",
        "seed_set_id": seed_set_id or "ad-hoc",
        "benchmark_config_hash": benchmark_config_hash,
        "suite": {
            "label": str(benchmark.get("name") or benchmark.get("label") or benchmark.get("id") or meta.get("benchmark_id") or "临时评测"),
            "benchmark_id": meta.get("benchmark_id") or "",
            "benchmark_version": meta.get("benchmark_version"),
            "target_type": meta.get("target_type"),
            "evaluation_set_id": evaluation_set_id or "ad-hoc",
            "seed_set_id": seed_set_id or "ad-hoc",
            "benchmark_config_hash": benchmark_config_hash,
        },
        "subject": subject,
        "model_runtime": model_runtime,
        "summary": summary,
        "results": result_rows,
        "gates": _benchmark_report_gate_rows(result_rows, diagnostic_groups),
        "problem_games": [
            {
                "game_id": game.get("game_id") or game.get("id"),
                "status": game.get("status"),
                "seed": game.get("seed"),
                "target_role": game.get("target_role"),
                "result_batch_id": game.get("result_batch_id"),
                "diagnostic_count": int(game.get("diagnostic_count") or 0),
                "replay_available": bool(game.get("replay_available")),
                "history_game_id": game.get("history_game_id"),
                "replay_unavailable_reason": game.get("replay_unavailable_reason"),
            }
            for game in problem_games[:80]
        ],
        "diagnostics": diagnostic_groups,
        "tags": top_tags,
        "reproducibility": {
            "套件": str(benchmark.get("name") or benchmark.get("id") or meta.get("benchmark_id") or "临时评测"),
            "评测 ID": meta.get("benchmark_id") or "ad-hoc",
            "评测集": evaluation_set_id or "ad-hoc",
            "种子集": seed_set_id or "ad-hoc",
            "Config Hash": benchmark_config_hash or "未上报",
            "模型 ID": subject.get("model_id") or "未上报",
            "模型配置 Hash": subject.get("model_config_hash") or "未上报",
            "模型运行来源": model_runtime.get("source") or "未上报",
            "目标角色": subject.get("target_role") or "未上报",
            "目标版本": subject.get("target_version_id") or "基线版本",
        },
        "leaderboard": {
            "scope": "model" if meta.get("target_type") == "model" else "role_version",
            "evaluation_set_id": evaluation_set_id,
            "target_role": subject.get("target_role"),
        },
    }
    payload["langfuse"] = _benchmark_batch_langfuse_summary(batch, games=games)
    payload["content_hash"] = _benchmark_report_content_hash(payload)
    payload["artifacts"] = {
        "schema_version": 1,
        "report_id": report_id,
        "content_hash": payload["content_hash"],
        "exports": {
            "json": f"/api/benchmark/batch/{batch_id}/report",
            "markdown": f"/api/benchmark/batch/{batch_id}/report?format=markdown",
            "csv": f"/api/benchmark/batch/{batch_id}/report?format=csv",
        },
    }
    manifest = _benchmark_run_report_reproducibility_manifest(batch, payload)
    payload["reproducibility_manifest"] = manifest
    payload["reproducibility_manifest_hash"] = manifest["manifest_hash"]
    payload["artifacts"]["reproducibility_manifest_hash"] = manifest["manifest_hash"]
    return payload


def _benchmark_run_report_summary(
    batch: dict[str, Any],
    report: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    batch_id = str(report.get("batch_id") or report.get("run_id") or meta.get("batch_id") or "")
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    diagnostic_summary = summary.get("diagnostic_summary") if isinstance(summary.get("diagnostic_summary"), dict) else {}
    suite = report.get("suite") if isinstance(report.get("suite"), dict) else {}
    subject = report.get("subject") if isinstance(report.get("subject"), dict) else {}
    return {
        "kind": "benchmark_run_report_summary",
        "schema_version": 1,
        "report_id": str(report.get("report_id") or f"benchmark_report:{batch_id}"),
        "run_id": str(report.get("run_id") or batch_id),
        "batch_id": batch_id,
        "status": report.get("status") or meta.get("status"),
        "generated_at": report.get("generated_at"),
        "created_at": batch.get("finished_at") or batch.get("updated_at") or batch.get("started_at"),
        "started_at": batch.get("started_at"),
        "finished_at": batch.get("finished_at"),
        "scope": meta.get("target_type"),
        "target_type": meta.get("target_type"),
        "benchmark_id": meta.get("benchmark_id"),
        "benchmark_version": meta.get("benchmark_version"),
        "evaluation_set_id": report.get("evaluation_set_id") or suite.get("evaluation_set_id"),
        "seed_set_id": report.get("seed_set_id") or suite.get("seed_set_id"),
        "benchmark_config_hash": report.get("benchmark_config_hash") or suite.get("benchmark_config_hash"),
        "suite": _json_clone(suite),
        "subject": _json_clone(subject),
        "model_runtime": _json_clone(report.get("model_runtime") or {}),
        "summary": _json_clone(summary),
        "result_count": int(summary.get("result_count") or 0),
        "rankable_count": int(summary.get("rankable_count") or 0),
        "unrankable_count": int(summary.get("unrankable_count") or 0),
        "problem_game_count": int(summary.get("problem_game_count") or 0),
        "diagnostic_count": int(diagnostic_summary.get("total") or 0),
        "content_hash": report.get("content_hash") or _benchmark_report_content_hash(report),
        "reproducibility_manifest_hash": report.get("reproducibility_manifest_hash"),
        "links": {
            "json": f"/api/benchmark/batch/{batch_id}/report",
            "markdown": f"/api/benchmark/batch/{batch_id}/report?format=markdown",
            "csv": f"/api/benchmark/batch/{batch_id}/report?format=csv",
        },
    }


def _benchmark_report_history_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = Counter(str(item.get("status") or "unknown") for item in items)
    by_scope = Counter(str(item.get("scope") or "unknown") for item in items)
    return {
        "total": len(items),
        "by_status": dict(sorted(by_status.items())),
        "by_scope": dict(sorted(by_scope.items())),
        "rankable_count": sum(int(item.get("rankable_count") or 0) for item in items),
        "unrankable_count": sum(int(item.get("unrankable_count") or 0) for item in items),
        "problem_game_count": sum(int(item.get("problem_game_count") or 0) for item in items),
        "diagnostic_count": sum(int(item.get("diagnostic_count") or 0) for item in items),
    }


def _benchmark_report_subject(
    results: list[dict[str, Any]],
    batch_config: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    first_result = results[0] if results else {}
    result_config = first_result.get("config") if isinstance(first_result.get("config"), dict) else {}
    target_role = _benchmark_result_role(first_result) if first_result else None
    target_version_id = first_result.get("target_version_id") or result_config.get("target_version_id")
    model_id = (
        first_result.get("model_id")
        or result_config.get("model_id")
        or batch_config.get("model_id")
        or meta.get("model_id")
    )
    model_config_hash = (
        first_result.get("model_config_hash")
        or result_config.get("model_config_hash")
        or batch_config.get("model_config_hash")
        or meta.get("model_config_hash")
    )
    if meta.get("target_type") == "model":
        label = " / ".join([value for value in (str(model_id or ""), str(model_config_hash or "")) if value]) or "当前后端模型"
    else:
        label = " / ".join([value for value in (str(target_role or ""), str(target_version_id or "基线版本")) if value])
    return {
        "label": label,
        "target_role": target_role,
        "target_version_id": target_version_id,
        "model_id": model_id,
        "model_config_hash": model_config_hash,
    }


def _benchmark_report_model_runtime(
    batch: dict[str, Any],
    results: list[dict[str, Any]],
    batch_config: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    first_result = results[0] if results else {}
    result_config = first_result.get("config") if isinstance(first_result.get("config"), dict) else {}
    candidates = (
        batch.get("model_runtime"),
        batch_config.get("model_runtime"),
        first_result.get("model_runtime"),
        result_config.get("model_runtime"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            runtime = _json_clone(candidate)
            runtime.setdefault("model_id", meta.get("model_id") or first_result.get("model_id") or result_config.get("model_id"))
            runtime.setdefault(
                "model_config_hash",
                meta.get("model_config_hash") or first_result.get("model_config_hash") or result_config.get("model_config_hash"),
            )
            return runtime
    return {
        "schema_version": 1,
        "source": "unknown",
        "model_id": meta.get("model_id") or first_result.get("model_id") or result_config.get("model_id") or "",
        "model_config_hash": (
            meta.get("model_config_hash")
            or first_result.get("model_config_hash")
            or result_config.get("model_config_hash")
            or ""
        ),
        "hash_provided": False,
        "hash_input": {},
    }


def _benchmark_run_report_reproducibility_manifest(
    batch: dict[str, Any],
    report: dict[str, Any],
    *,
    export_format: str | None = None,
    export_content_hash: str | None = None,
) -> dict[str, Any]:
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    suite = report.get("suite") if isinstance(report.get("suite"), dict) else {}
    model_runtime = report.get("model_runtime") if isinstance(report.get("model_runtime"), dict) else {}
    content_hash = str(report.get("content_hash") or "")
    run_payload = {
        "benchmark": {
            "id": suite.get("benchmark_id") or benchmark.get("id") or config.get("benchmark_id"),
            "version": suite.get("benchmark_version") or benchmark.get("version") or config.get("benchmark_version"),
            "evaluation_set_id": report.get("evaluation_set_id") or suite.get("evaluation_set_id"),
            "config_hash": report.get("benchmark_config_hash") or suite.get("benchmark_config_hash"),
            "seed_set_id": report.get("seed_set_id") or suite.get("seed_set_id"),
            "seed_set_version": benchmark.get("seed_set_version") or config.get("seed_set_version"),
            "seed_set_config_hash": benchmark.get("seed_set_config_hash") or config.get("seed_set_config_hash"),
            "source_filter": config.get("source_filter") if isinstance(config.get("source_filter"), dict) else {},
        },
        "model_runtime": _json_clone(model_runtime),
        "request": _json_clone(config),
        "planner": _json_clone(batch.get("run_plan") if isinstance(batch.get("run_plan"), dict) else {}),
        "artifacts": {
            "content_hash": content_hash,
            "json": {"artifact_hash": content_hash},
        },
        "created_at": batch.get("finished_at") or batch.get("updated_at") or batch.get("started_at") or report.get("generated_at"),
    }
    report_payload = {
        "subject": _json_clone(report.get("subject") or {}),
        "model_runtime": _json_clone(model_runtime),
        "artifacts": _json_clone(report.get("artifacts") or {"content_hash": content_hash}),
        "content_hash": content_hash,
    }
    export_payload = None
    if export_format:
        export_payload = {
            "export": {
                "format": export_format,
                "export_content_hash": export_content_hash,
                "artifact_hash": export_content_hash,
            }
        }
    return build_benchmark_reproducibility_manifest(
        run_payload=run_payload,
        report_payload=report_payload,
        export_payload=export_payload,
        created_at=str(run_payload.get("created_at") or ""),
    )


def _benchmark_report_content_hash(report: dict[str, Any]) -> str:
    stable_report = _json_clone(report)
    if isinstance(stable_report, dict):
        stable_report.pop("generated_at", None)
        stable_report.pop("content_hash", None)
        stable_report.pop("artifacts", None)
        stable_report.pop("reproducibility_manifest", None)
        stable_report.pop("reproducibility_manifest_hash", None)
    return _stable_payload_hash(stable_report if isinstance(stable_report, dict) else {})


def _benchmark_report_gate_rows(
    result_rows: list[dict[str, Any]],
    diagnostic_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, result in enumerate(result_rows, start=1):
        rows.append(
            {
                "key": result.get("result_batch_id") or f"result-{index}",
                "title": result.get("target_role") or result.get("model_id") or result.get("result_batch_id") or f"结果 {index}",
                "status": result.get("rankable_label") or ("可入榜" if result.get("rankable") is not False else "未入榜"),
                "reason": result.get("rankable_reason") or "未上报门禁原因",
                "meta": " / ".join(
                    str(value) for value in (
                        result.get("target_version_id"),
                        f"{result.get('completed')} 局完成" if result.get("completed") is not None else "",
                        f"{result.get('game_count')} 局" if result.get("game_count") is not None else "",
                    )
                    if value
                ),
                "blocked": result.get("rankable") is False,
            }
        )
    for group in diagnostic_groups[:8]:
        rows.append(
            {
                "key": f"kind-{group.get('kind')}",
                "title": group.get("label") or _benchmark_report_diagnostic_kind_label(group.get("kind")),
                "status": f"{group.get('total', 0)} 条诊断",
                "reason": "所选运行上报了该诊断类型",
                "meta": "诊断类型",
                "blocked": False,
            }
        )
    return rows[:16]


def _benchmark_report_diagnostic_groups(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in diagnostics:
        kind = str(item.get("kind") or "diagnostic")
        level = str(item.get("level") or "info").lower()
        group = groups.setdefault(
            kind,
            {
                "kind": kind,
                "label": _benchmark_report_diagnostic_kind_label(kind),
                "total": 0,
                "levels": Counter(),
                "games": set(),
                "stages": set(),
            },
        )
        group["total"] += 1
        group["levels"][level] += 1
        if item.get("game_id"):
            group["games"].add(str(item.get("game_id")))
        if item.get("stage"):
            group["stages"].add(str(item.get("stage")))
    rows: list[dict[str, Any]] = []
    for group in groups.values():
        level_label = ", ".join(
            f"{_benchmark_report_diagnostic_level_label(level)}: {count}"
            for level, count in group["levels"].most_common(2)
        )
        rows.append(
            {
                "kind": group["kind"],
                "label": group["label"],
                "total": group["total"],
                "level": level_label or "无等级",
                "game_count": len(group["games"]),
                "stage_count": len(group["stages"]),
            }
        )
    rows.sort(key=lambda row: (-int(row.get("total") or 0), str(row.get("label") or "")))
    return rows[:24]


def _benchmark_report_top_tags(
    results: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for result in results:
        summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
        judge = summary.get("decision_judge_aggregate") if isinstance(summary.get("decision_judge_aggregate"), dict) else {}
        for tag in judge.get("top_mistake_tags", []) or []:
            if not isinstance(tag, dict):
                continue
            label = str(tag.get("tag") or "").strip()
            if label:
                counts[label] += int(tag.get("count") or 1)
    for item in diagnostics:
        label = str(item.get("kind") or "").strip()
        if label:
            counts[label] += 1
    return [{"label": label, "count": count} for label, count in counts.most_common(12)]


def _benchmark_problem_status_weight(status: Any) -> int:
    text = str(status or "").strip().lower()
    if text == "failed":
        return 5
    if text == "timeout":
        return 4
    if text == "abnormal":
        return 3
    if text in {"cancelled", "interrupted"}:
        return 2
    if text == "completed":
        return 0
    return 1 if text else 0


def _benchmark_run_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# 评测运行报告：{_markdown_value(report.get('run_id'))}",
        "",
        "## 报告头",
        f"- 报告 ID: {_markdown_value(report.get('report_id'))}",
        f"- 运行 ID: {_markdown_value(report.get('run_id'))}",
        f"- 套件: {_markdown_value(report.get('suite', {}).get('label'))}",
        f"- 状态: {_markdown_value(report.get('status'))}",
        f"- 对象类型: {_markdown_value(report.get('suite', {}).get('target_type'))}",
        f"- 评测集: {_markdown_value(report.get('suite', {}).get('evaluation_set_id'))}",
        f"- 种子集: {_markdown_value(report.get('suite', {}).get('seed_set_id'))}",
        f"- 评测对象: {_markdown_value(report.get('subject', {}).get('label'))}",
        f"- 内容 Hash: {_markdown_value(report.get('content_hash'))}",
        "",
        "## 摘要",
    ]
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    game_summary = summary.get("game_summary") if isinstance(summary.get("game_summary"), dict) else {}
    diagnostic_summary = summary.get("diagnostic_summary") if isinstance(summary.get("diagnostic_summary"), dict) else {}
    lines.extend(
        [
            f"- 可入榜: {summary.get('rankable_count', 0)}/{summary.get('result_count', 0)}",
            f"- 结果数: {summary.get('result_count', 0)}",
            f"- 对局数: {game_summary.get('total', 0)}（{summary.get('problem_game_count', 0)} 个问题样本）",
            f"- 诊断数: {diagnostic_summary.get('total', 0)}",
            "",
            "## 门禁摘要",
        ]
    )
    gates = report.get("gates") if isinstance(report.get("gates"), list) else []
    lines.extend(
        [
            f"- {_markdown_value(row.get('title'))}: {_markdown_value(row.get('status'))} - {_markdown_value(row.get('reason'))}"
            for row in gates[:16]
            if isinstance(row, dict)
        ] or ["- 未加载门禁行"]
    )
    lines.extend(["", "## 问题对局"])
    problem_games = report.get("problem_games") if isinstance(report.get("problem_games"), list) else []
    lines.extend(
        [
            f"- {_markdown_value(game.get('game_id'))}: {_markdown_value(game.get('status'))} / 种子 {_markdown_value(game.get('seed'))} / 诊断 {game.get('diagnostic_count', 0)} / 回放 {_markdown_value(game.get('history_game_id') or game.get('replay_unavailable_reason') or '不可用')}"
            for game in problem_games[:8]
            if isinstance(game, dict)
        ] or ["- 未加载对局样本"]
    )
    lines.extend(["", "## 诊断与标签"])
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), list) else []
    tags = report.get("tags") if isinstance(report.get("tags"), list) else []
    if diagnostics:
        lines.extend(
            f"- {_markdown_value(group.get('label'))}: {group.get('total', 0)} ({_markdown_value(group.get('level'))})"
            for group in diagnostics[:12]
            if isinstance(group, dict)
        )
    elif tags:
        lines.extend(
            f"- {_markdown_value(tag.get('label'))}: {tag.get('count', 0)}"
            for tag in tags[:12]
            if isinstance(tag, dict)
        )
    else:
        lines.append("- 未加载诊断")
    lines.extend(["", "## 复现包"])
    reproducibility = report.get("reproducibility") if isinstance(report.get("reproducibility"), dict) else {}
    lines.extend(f"- {_markdown_value(key)}: {_markdown_value(value)}" for key, value in reproducibility.items())
    model_runtime = report.get("model_runtime") if isinstance(report.get("model_runtime"), dict) else {}
    if model_runtime:
        lines.extend(
            [
                "",
                "## 模型运行配置",
                f"- 来源: {_markdown_value(model_runtime.get('source'))}",
                f"- 模型 ID: {_markdown_value(model_runtime.get('model_id'))}",
                f"- 配置 Hash: {_markdown_value(model_runtime.get('model_config_hash'))}",
                f"- Hash 来源: {'请求提供' if model_runtime.get('hash_provided') else '后端自动生成'}",
            ]
        )
    return "\n".join(lines)


def _benchmark_run_report_csv(report: dict[str, Any]) -> str:
    rows: list[list[Any]] = [["区段", "标签", "值", "详情"]]
    suite = report.get("suite") if isinstance(report.get("suite"), dict) else {}
    subject = report.get("subject") if isinstance(report.get("subject"), dict) else {}
    rows.extend(
        [
            ["报告头", "运行 ID", report.get("run_id"), ""],
            ["报告头", "报告 ID", report.get("report_id"), ""],
            ["报告头", "套件", suite.get("label"), ""],
            ["报告头", "状态", report.get("status"), ""],
            ["报告头", "对象类型", suite.get("target_type"), ""],
            ["报告头", "评测集", suite.get("evaluation_set_id"), ""],
            ["报告头", "种子集", suite.get("seed_set_id"), ""],
            ["报告头", "评测对象", subject.get("label"), ""],
            ["报告头", "内容 Hash", report.get("content_hash"), ""],
        ]
    )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    rows.extend(
        [
            ["摘要", "结果数", summary.get("result_count", 0), ""],
            ["摘要", "可入榜", summary.get("rankable_count", 0), f"{summary.get('unrankable_count', 0)} 个未入榜"],
            ["摘要", "问题对局", summary.get("problem_game_count", 0), ""],
        ]
    )
    for gate in report.get("gates", []) or []:
        if isinstance(gate, dict):
            rows.append(["门禁", gate.get("title"), gate.get("status"), gate.get("reason")])
    for game in report.get("problem_games", []) or []:
        if isinstance(game, dict):
            rows.append([
                "对局",
                game.get("game_id"),
                game.get("status"),
                f"种子 {game.get('seed')} / 诊断 {game.get('diagnostic_count', 0)} / 日志 {game.get('history_game_id') or ''}",
            ])
    for group in report.get("diagnostics", []) or []:
        if isinstance(group, dict):
            rows.append(["诊断", group.get("label"), group.get("total"), group.get("level")])
    reproducibility = report.get("reproducibility") if isinstance(report.get("reproducibility"), dict) else {}
    rows.extend(["复现包", key, value, ""] for key, value in reproducibility.items())
    model_runtime = report.get("model_runtime") if isinstance(report.get("model_runtime"), dict) else {}
    if model_runtime:
        rows.extend(
            [
                ["模型运行配置", "来源", model_runtime.get("source"), ""],
                ["模型运行配置", "模型 ID", model_runtime.get("model_id"), ""],
                ["模型运行配置", "配置 Hash", model_runtime.get("model_config_hash"), ""],
                ["模型运行配置", "Hash 来源", "请求提供" if model_runtime.get("hash_provided") else "后端自动生成", ""],
            ]
        )
    return "\n".join(",".join(_csv_value(value) for value in row) for row in rows)


def _markdown_value(value: Any) -> str:
    return str(value if value is not None else "--").replace("\n", " ").replace("|", "\\|")


def _csv_value(value: Any) -> str:
    text = str(value if value is not None else "")
    if any(char in text for char in [",", "\"", "\n", "\r"]):
        return '"' + text.replace('"', '""') + '"'
    return text


def _benchmark_batch_boundary(batch: dict[str, Any]) -> dict[str, Any]:
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    results = _benchmark_results(batch)

    def first_result_value(*keys: str) -> Any:
        for result in results:
            result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
            for key in keys:
                value = result.get(key)
                if value not in (None, ""):
                    return value
                value = result_config.get(key)
                if value not in (None, ""):
                    return value
        return None

    target_type = str(
        batch.get("target_type")
        or benchmark.get("target_type")
        or config.get("target_type")
        or first_result_value("target_type", "comparison_type")
        or "role_version"
    ).strip().lower()
    roles = batch.get("roles") if isinstance(batch.get("roles"), list) else []
    return {
        "batch_id": str(batch.get("batch_id") or batch.get("run_id") or ""),
        "status": str(batch.get("status") or "").strip().lower(),
        "target_type": "model" if target_type == "model" else "role_version",
        "benchmark_id": str(benchmark.get("id") or batch.get("benchmark_id") or config.get("benchmark_id") or first_result_value("benchmark_id") or ""),
        "benchmark_version": benchmark.get("version") or batch.get("benchmark_version") or config.get("benchmark_version") or first_result_value("benchmark_version"),
        "evaluation_set_id": str(benchmark.get("evaluation_set_id") or batch.get("evaluation_set_id") or config.get("evaluation_set_id") or first_result_value("evaluation_set_id") or ""),
        "seed_set_id": str(benchmark.get("seed_set_id") or batch.get("seed_set_id") or config.get("seed_set_id") or first_result_value("seed_set_id") or ""),
        "model_id": str(batch.get("model_id") or config.get("model_id") or first_result_value("model_id") or ""),
        "model_config_hash": str(batch.get("model_config_hash") or config.get("model_config_hash") or first_result_value("model_config_hash") or ""),
        "roles": [str(role).strip().lower() for role in roles if str(role).strip()],
    }


def _benchmark_diagnostic_matches(
    item: dict[str, Any],
    meta: dict[str, Any],
    *,
    target_role: str,
    kind_filter: set[str] | None,
    level_filter: set[str] | None,
    status_filter: set[str] | None,
    stage_filter: set[str] | None,
    seed_filter: set[str] | None,
) -> bool:
    if target_role:
        item_role = str(item.get("target_role") or "").strip().lower()
        if item_role and item_role != target_role:
            return False
        if not item_role and meta.get("target_type") == "role_version" and target_role not in meta.get("roles", []):
            return False
    return (
        _match_filter(item.get("kind"), kind_filter)
        and _match_filter(item.get("level"), level_filter)
        and _match_filter(item.get("status") or meta.get("status"), status_filter)
        and _match_filter(item.get("stage"), stage_filter)
        and _match_filter(item.get("seed"), seed_filter)
    )


def _benchmark_annotated_diagnostic(item: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(item)
    annotated["batch_id"] = meta["batch_id"]
    annotated["batch_status"] = meta["status"]
    annotated["target_type"] = meta["target_type"]
    annotated["benchmark_id"] = meta["benchmark_id"]
    annotated["evaluation_set_id"] = meta["evaluation_set_id"]
    annotated["seed_set_id"] = meta["seed_set_id"]
    if meta.get("model_id"):
        annotated["model_id"] = meta["model_id"]
    if meta.get("model_config_hash"):
        annotated["model_config_hash"] = meta["model_config_hash"]
    return annotated


def _benchmark_diagnostic_run_payload(
    batch: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    meta: dict[str, Any],
) -> dict[str, Any]:
    payload = _benchmark_latest_run_payload(batch)
    payload.update(
        {
            "id": meta["batch_id"],
            "batch_id": meta["batch_id"],
            "status": meta["status"] or payload.get("status"),
            "benchmark_id": meta["benchmark_id"],
            "benchmark_version": meta["benchmark_version"],
            "evaluation_set_id": meta["evaluation_set_id"],
            "seed_set_id": meta["seed_set_id"],
            "target_type": meta["target_type"],
            "roles": meta["roles"],
            "model_id": meta["model_id"] or None,
            "model_config_hash": meta["model_config_hash"] or None,
            "diagnostic_count": len(diagnostics),
            "diagnostic_summary": _benchmark_diagnostic_summary(diagnostics),
        }
    )
    return payload


def _benchmark_diagnostic_affected_games(
    matched_batches: list[tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]]
) -> list[dict[str, Any]]:
    affected: list[dict[str, Any]] = []
    for batch, diagnostics, _meta in matched_batches:
        diagnostic_counts = Counter(
            str(item.get("game_id") or "") for item in diagnostics if item.get("game_id")
        )
        if not diagnostic_counts:
            continue
        game_by_id = {
            str(game.get("game_id") or game.get("id") or ""): game
            for game in _benchmark_games_for_batch(batch)
        }
        for game_id, count in diagnostic_counts.items():
            game = dict(game_by_id.get(game_id) or {"game_id": game_id, "id": game_id})
            game["batch_id"] = str(batch.get("batch_id") or game.get("batch_id") or "")
            game["diagnostic_count"] = int(count)
            affected.append(game)
    affected.sort(
        key=lambda game: (
            int(game.get("diagnostic_count") or 0),
            str(game.get("batch_id") or ""),
            str(game.get("game_id") or ""),
        ),
        reverse=True,
    )
    return affected[:80]


def _dedupe_benchmark_diagnostics(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for item in diagnostics:
        key = (
            str(item.get("origin") or ""),
            str(item.get("result_batch_id") or ""),
            str(item.get("game_id") or ""),
            str(item.get("kind") or ""),
            str(item.get("stage") or ""),
            str(item.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _text_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_non_empty(*values: Any) -> Any | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
            continue
        if value != "":
            return value
    return None


def _unique_non_empty(values: Any) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _unique_texts(*values: Any) -> list[str]:
    return _unique_non_empty(values)


def _benchmark_spec_snapshot(batch: dict[str, Any]) -> dict[str, Any]:
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    snapshot = benchmark.get("spec_snapshot") if isinstance(benchmark.get("spec_snapshot"), dict) else {}
    return dict(snapshot)


def _decode_json_field(value: Any, *, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _leaderboard_subject_key(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    for key in ("subject_id", "hash", "model_config_hash", "target_version_id", "model_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _first_int(*values: Any, default: int = 0) -> int:
    for value in values:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            continue
        return number
    return default


def _first_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            return number
    return default


def _filter_unrankable_evidence_for_compare(
    rows: list[dict[str, Any]],
    *,
    scope: str | None,
    evaluation_set_id: str | None,
    target_role: str | None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if row.get("rankable") is not False:
            continue
        row_scope = str(row.get("scope") or "").strip().lower()
        if scope and row_scope and row_scope != scope:
            continue
        row_eval = str(row.get("evaluation_set_id") or "").strip()
        if evaluation_set_id and row_eval and row_eval != str(evaluation_set_id):
            continue
        row_role = str(row.get("target_role") or "").strip().lower()
        if target_role and row_role and row_role != str(target_role).strip().lower():
            continue
        evidence.append(_leaderboard_unrankable_evidence_row(row, index=index))
    return evidence


def _benchmark_result_has_unrankable_evidence(result: dict[str, Any]) -> bool:
    if result.get("rankable") is False:
        return True
    gate = result.get("leaderboard_gate") if isinstance(result.get("leaderboard_gate"), dict) else {}
    if gate.get("accepted") is False:
        return True
    return bool(result.get("leaderboard_skipped_reason"))


def _dedupe_unrankable_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        subject = str(row.get("subject_id") or row.get("model_config_hash") or row.get("target_version_id") or "")
        batch_id = str(row.get("batch_id") or "")
        result_batch_id = str(row.get("result_batch_id") or "")
        key = (
            str(row.get("scope") or ""),
            str(row.get("evaluation_set_id") or ""),
            str(row.get("target_role") or ""),
            subject,
            batch_id,
            result_batch_id,
        )
        if not any(key):
            key = (str(row.get("evidence_key") or ""),)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _leaderboard_unrankable_evidence_row(row: dict[str, Any], *, index: int) -> dict[str, Any]:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    completed_games = _first_int(
        row.get("completed_games"),
        row.get("games_played"),
        row.get("completed"),
        summary.get("completed_games"),
        summary.get("games_played"),
        row.get("game_count"),
    )
    total_games = _first_int(
        row.get("total_games"),
        row.get("game_count"),
        summary.get("total_games"),
        summary.get("game_count"),
        completed_games,
    )
    valid_game_rate = _first_float(row.get("valid_game_rate"), summary.get("valid_game_rate"))
    return {
        "evidence_key": _leaderboard_subject_key(row) or f"unrankable:{index}",
        "scope": row.get("scope"),
        "subject_id": row.get("subject_id") or row.get("hash"),
        "model_id": row.get("model_id"),
        "model_config_hash": row.get("model_config_hash"),
        "target_role": row.get("target_role"),
        "target_version_id": row.get("target_version_id"),
        "evaluation_set_id": row.get("evaluation_set_id"),
        "seed_set_id": row.get("seed_set_id"),
        "batch_id": row.get("batch_id") or summary.get("batch_id") or row.get("comparison_group_id"),
        "result_batch_id": row.get("result_batch_id") or summary.get("result_batch_id"),
        "status": "unrankable",
        "rankable": False,
        "reason": _first_text(
            row.get("rankable_reason"),
            row.get("leaderboard_skipped_reason"),
            row.get("reason"),
            summary.get("rankable_reason"),
            summary.get("leaderboard_skipped_reason"),
            summary.get("reason"),
            "rankable gate failed",
        ),
        "completed_games": completed_games,
        "total_games": total_games,
        "valid_game_rate": valid_game_rate,
        "updated_at": row.get("updated_at"),
        "source": row.get("source") or "leaderboard",
    }


def _select_leaderboard_baseline(
    rows: list[dict[str, Any]],
    *,
    baseline_subject_id: str | None = None,
) -> dict[str, Any] | None:
    wanted = str(baseline_subject_id or "").strip()
    if wanted:
        for row in rows:
            keys = {
                _leaderboard_subject_key(row),
                str(row.get("subject_id") or "").strip(),
                str(row.get("hash") or "").strip(),
                str(row.get("model_config_hash") or "").strip(),
                str(row.get("target_version_id") or "").strip(),
                str(row.get("model_id") or "").strip(),
            }
            if wanted in keys:
                return row
    for row in rows:
        if row.get("is_baseline") is True:
            return row
    for row in rows:
        if row.get("rankable") is not False:
            return row
    return rows[0] if rows else None


def _leaderboard_metric(row: dict[str, Any] | None, *keys: str) -> float:
    if not row:
        return 0.0
    for key in keys:
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if value == value:
            return value
    return 0.0


_LEADERBOARD_CONFIDENCE_LEVEL = 0.95
_LEADERBOARD_Z_95 = 1.96
_LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE = 30
_LEADERBOARD_MIN_PAIRED_OVERLAP = _LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE


def _leaderboard_score(row: dict[str, Any] | None, *, scope: str | None) -> float:
    if scope == "model":
        return _leaderboard_metric(row, "strength_score", "avg_role_score", "target_role_role_weighted_score")
    return _leaderboard_metric(row, "avg_role_score", "target_role_role_weighted_score", "strength_score")


def _leaderboard_row_statistics(row: dict[str, Any] | None) -> dict[str, Any]:
    """Return row-level binomial confidence evidence for leaderboard payloads."""
    if not row:
        return _empty_leaderboard_statistics()
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    sample_size = _first_int(
        row.get("sample_size"),
        summary.get("sample_size"),
        row.get("completed_games"),
        row.get("completed"),
        summary.get("completed_games"),
        summary.get("win_rate_denominator"),
        row.get("games_played"),
        row.get("game_count"),
        summary.get("games_played"),
        summary.get("game_count"),
        default=0,
    )
    win_rate = _probability_from_value(
        _first_float(
            row.get("target_side_win_rate"),
            row.get("win_rate"),
            summary.get("target_side_win_rate"),
            summary.get("win_rate"),
            default=0.0,
        )
    )
    standard_error = _binomial_standard_error(win_rate, sample_size)
    ci_low, ci_high = _wilson_confidence_interval(win_rate, sample_size)
    paired_sample_size = _first_int(
        row.get("paired_sample_size"),
        summary.get("paired_sample_size"),
        summary.get("paired_valid_count"),
        default=0,
    )
    paired_delta = _optional_probability_delta(
        row.get("paired_delta"),
        summary.get("paired_delta"),
        summary.get("paired_seed_delta"),
    )
    warnings = _stat_warning_list(row.get("warnings"), summary.get("warnings"))
    if sample_size < _LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE:
        warnings.append("low_sample")
    warnings = _dedupe_warning_codes(warnings)
    return {
        "sample_size": sample_size,
        "paired_sample_size": paired_sample_size,
        "win_rate_ci": {
            "low": ci_low,
            "high": ci_high,
            "level": _LEADERBOARD_CONFIDENCE_LEVEL,
        },
        "ci_low": ci_low,
        "ci_high": ci_high,
        "standard_error": standard_error,
        "paired_delta": paired_delta,
        "significant": bool(row.get("significant", False)),
        "significance_label": str(row.get("significance_label") or "待比较"),
        "warnings": warnings,
    }


def _empty_leaderboard_statistics() -> dict[str, Any]:
    return {
        "sample_size": 0,
        "paired_sample_size": 0,
        "win_rate_ci": {"low": 0.0, "high": 0.0, "level": _LEADERBOARD_CONFIDENCE_LEVEL},
        "ci_low": 0.0,
        "ci_high": 0.0,
        "standard_error": 0.0,
        "paired_delta": None,
        "significant": False,
        "significance_label": "待比较",
        "warnings": ["low_sample"],
    }


def _probability_from_value(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    if abs(number) > 1 and abs(number) <= 100:
        number = number / 100.0
    return max(0.0, min(1.0, number))


def _optional_probability_delta(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        if abs(number) > 1 and abs(number) <= 100:
            number = number / 100.0
        return number
    return None


def _binomial_standard_error(win_rate: float, sample_size: int) -> float:
    if sample_size <= 0:
        return 0.0
    probability = max(0.0, min(1.0, float(win_rate)))
    return math.sqrt((probability * (1.0 - probability)) / sample_size)


def _wilson_confidence_interval(win_rate: float, sample_size: int) -> tuple[float, float]:
    if sample_size <= 0:
        return 0.0, 0.0
    probability = max(0.0, min(1.0, float(win_rate)))
    z_squared = _LEADERBOARD_Z_95 ** 2
    denominator = 1.0 + (z_squared / sample_size)
    center = (probability + (z_squared / (2 * sample_size))) / denominator
    half_width = (
        _LEADERBOARD_Z_95
        * math.sqrt((probability * (1.0 - probability) / sample_size) + (z_squared / (4 * sample_size ** 2)))
        / denominator
    )
    return (
        max(0.0, min(1.0, center - half_width)),
        max(0.0, min(1.0, center + half_width)),
    )


def _stat_warning_list(*values: Any) -> list[str]:
    warnings: list[str] = []
    for value in values:
        if isinstance(value, str):
            warnings.append(value)
        elif isinstance(value, list):
            warnings.extend(str(item) for item in value)
        elif isinstance(value, dict):
            warnings.extend(str(key) for key, enabled in value.items() if enabled)
    return warnings


def _dedupe_warning_codes(values: list[str]) -> list[str]:
    allowed = {"low_sample", "unpaired_seeds", "insufficient_overlap"}
    warnings: list[str] = []
    for value in values:
        code = str(value or "").strip()
        if code in allowed and code not in warnings:
            warnings.append(code)
    return warnings


def _leaderboard_seed_metrics(row: dict[str, Any] | None) -> dict[str, float]:
    if not row:
        return {}
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    candidates = (
        row.get("seed_metrics"),
        row.get("paired_seed_metrics"),
        row.get("per_seed_metrics"),
        summary.get("seed_metrics"),
        summary.get("paired_seed_metrics"),
        summary.get("per_seed_metrics"),
        summary.get("seed_results"),
        summary.get("per_seed"),
    )
    metrics: dict[str, float] = {}
    for candidate in candidates:
        if isinstance(candidate, dict):
            iterable = [{"seed": seed, "value": value} for seed, value in candidate.items()]
        elif isinstance(candidate, list):
            iterable = candidate
        else:
            continue
        for index, item in enumerate(iterable):
            if not isinstance(item, dict):
                continue
            key = _leaderboard_seed_metric_key(item, index)
            if not key:
                continue
            value = _seed_metric_value(item)
            if value is not None:
                metrics[key] = value
    return metrics


def _leaderboard_seed_metric_key(item: dict[str, Any], index: int) -> str:
    pair_key = _first_text(item.get("pair_key"), item.get("paired_key"), item.get("pair_id"))
    if pair_key:
        return f"pair:{pair_key}"
    seed = _first_text(item.get("seed"), item.get("seed_id"), item.get("id"))
    game_index = _first_text(item.get("game_index"), item.get("game_slot"), item.get("slot_index"), item.get("ordinal"))
    if seed and game_index:
        return f"seed:{seed}:game:{game_index}"
    game_id = _first_text(item.get("source_game_id"), item.get("game_id"))
    if seed and game_id:
        return f"seed:{seed}:source:{game_id}"
    if seed:
        return f"seed:{seed}"
    if game_id:
        return f"game:{game_id}"
    return f"index:{index}"


def _seed_metric_value(item: dict[str, Any]) -> float | None:
    for key in (
        "target_side_win",
        "target_side_won",
        "win",
        "won",
        "value",
        "target_side_win_rate",
        "score",
    ):
        value = item.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        text = str(value).strip().lower()
        if text in {"win", "won", "true", "yes"}:
            return 1.0
        if text in {"loss", "lost", "false", "no"}:
            return 0.0
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return _probability_from_value(number)
    return None


def _leaderboard_paired_evidence(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> tuple[float | None, int, list[str]]:
    if not baseline:
        return None, 0, []
    row_metrics = _leaderboard_seed_metrics(row)
    baseline_metrics = _leaderboard_seed_metrics(baseline)
    if not row_metrics or not baseline_metrics:
        return None, 0, ["unpaired_seeds"]
    overlap = sorted(set(row_metrics).intersection(baseline_metrics))
    if not overlap:
        return None, 0, ["insufficient_overlap"]
    deltas = [row_metrics[seed] - baseline_metrics[seed] for seed in overlap]
    paired_delta = sum(deltas) / len(deltas)
    warnings: list[str] = []
    if len(overlap) < min(len(row_metrics), len(baseline_metrics)):
        warnings.append("unpaired_seeds")
    if len(overlap) < _LEADERBOARD_MIN_PAIRED_OVERLAP:
        warnings.append("insufficient_overlap")
    return paired_delta, len(overlap), warnings


def _leaderboard_compare_statistics(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    boundary_warnings: list[str],
    is_reference: bool,
    win_rate_delta: float,
) -> dict[str, Any]:
    row_stats = _leaderboard_row_statistics(row)
    baseline_stats = _leaderboard_row_statistics(baseline)
    warnings = list(row_stats["warnings"])
    if baseline and baseline_stats["sample_size"] < _LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE:
        warnings.append("low_sample")
    paired_delta, paired_sample_size, paired_warnings = _leaderboard_paired_evidence(row, baseline)
    warnings.extend(paired_warnings)
    paired_delta_error = None
    if paired_sample_size > 0:
        paired_delta_error = math.sqrt((float(row_stats["standard_error"] or 0.0) ** 2) + (float(baseline_stats["standard_error"] or 0.0) ** 2))
    combined_standard_error = math.sqrt(
        float(row_stats["standard_error"] or 0.0) ** 2
        + float(baseline_stats["standard_error"] or 0.0) ** 2
    )
    warning_codes = _dedupe_warning_codes(warnings)
    statistically_significant = bool(
        baseline
        and not is_reference
        and not boundary_warnings
        and paired_delta is not None
        and "low_sample" not in warning_codes
        and "unpaired_seeds" not in warning_codes
        and "insufficient_overlap" not in warning_codes
        and paired_delta_error
        and paired_delta_error > 0
        and abs(float(paired_delta or 0.0)) > (_LEADERBOARD_Z_95 * paired_delta_error)
    )
    if is_reference:
        label = "基线参考"
    elif boundary_warnings:
        label = "不可比较"
    elif statistically_significant:
        label = "显著提升" if win_rate_delta > 0 else "显著回退"
    elif baseline:
        label = "差异不显著"
    else:
        label = "等待基线"
    return {
        **row_stats,
        "paired_sample_size": paired_sample_size,
        "paired_delta": paired_delta,
        "standard_error": row_stats["standard_error"],
        "combined_standard_error": combined_standard_error,
        "significant": statistically_significant,
        "significance_label": label,
        "warnings": warning_codes,
    }


def _leaderboard_boundary_warnings(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    scope: str | None,
    target_role: str | None,
) -> list[str]:
    if not baseline:
        return []
    warnings: list[str] = []
    if scope and str(row.get("scope") or "").strip().lower() != scope:
        warnings.append("scope_mismatch")
    row_eval = str(row.get("evaluation_set_id") or "").strip()
    baseline_eval = str(baseline.get("evaluation_set_id") or "").strip()
    if row_eval and baseline_eval and row_eval != baseline_eval:
        warnings.append("evaluation_set_mismatch")
    row_seed = str(row.get("seed_set_id") or "").strip()
    baseline_seed = str(baseline.get("seed_set_id") or "").strip()
    if row_seed and baseline_seed and row_seed != baseline_seed:
        warnings.append("seed_set_mismatch")
    expected_role = str(target_role or baseline.get("target_role") or "").strip()
    row_role = str(row.get("target_role") or "").strip()
    if scope == "role_version" and expected_role and row_role and row_role != expected_role:
        warnings.append("target_role_mismatch")
    return warnings


def _leaderboard_compare_row(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    scope: str | None,
    target_role: str | None,
) -> dict[str, Any]:
    row_key = _leaderboard_subject_key(row)
    baseline_key = _leaderboard_subject_key(baseline)
    score_delta = _leaderboard_score(row, scope=scope) - _leaderboard_score(baseline, scope=scope)
    win_rate_delta = _leaderboard_metric(row, "target_side_win_rate") - _leaderboard_metric(baseline, "target_side_win_rate")
    fallback_delta = _leaderboard_metric(row, "fallback_rate", "target_role_fallback_rate") - _leaderboard_metric(
        baseline, "fallback_rate", "target_role_fallback_rate"
    )
    llm_error_delta = _leaderboard_metric(row, "llm_error_rate") - _leaderboard_metric(baseline, "llm_error_rate")
    policy_adjusted_delta = _leaderboard_metric(row, "policy_adjusted_rate") - _leaderboard_metric(
        baseline, "policy_adjusted_rate"
    )
    boundary_warnings = _leaderboard_boundary_warnings(row, baseline, scope=scope, target_role=target_role)
    is_reference = bool(baseline_key and row_key == baseline_key)
    comparable = bool(baseline and not boundary_warnings)
    if is_reference:
        change = "reference"
    elif not comparable:
        change = "incomparable"
    elif score_delta > 0:
        change = "improvement"
    elif score_delta < 0:
        change = "regression"
    else:
        change = "stable"
    games = int(_leaderboard_metric(row, "games_played", "game_count", "total_games"))
    baseline_games = int(_leaderboard_metric(baseline, "games_played", "game_count", "total_games"))
    statistics = _leaderboard_compare_statistics(
        row,
        baseline,
        boundary_warnings=boundary_warnings,
        is_reference=is_reference,
        win_rate_delta=win_rate_delta,
    )
    confidence = "low_sample" if "low_sample" in statistics["warnings"] or games < 30 or baseline_games < 30 else (
        "significant" if statistics["significant"] else "not_significant"
    )
    payload = dict(row)
    payload.update(
        {
            "is_reference": is_reference,
            "baseline_subject_id": baseline_key or None,
            "comparable": comparable,
            "boundary_warnings": boundary_warnings,
            "change": change,
            "confidence": confidence,
            **statistics,
            "delta": {
                "score": score_delta,
                "target_side_win_rate": win_rate_delta,
                "paired_delta": statistics["paired_delta"],
                "fallback_rate": fallback_delta,
                "llm_error_rate": llm_error_delta,
                "policy_adjusted_rate": policy_adjusted_delta,
            },
            "delta_vs_baseline": {
                "score": score_delta,
                "target_role_role_weighted_score": score_delta,
                "strength_score": score_delta,
                "target_side_win_rate": win_rate_delta,
                "paired_delta": statistics["paired_delta"],
                "fallback_rate": fallback_delta,
                "llm_error_rate": llm_error_delta,
                "policy_adjusted_rate": policy_adjusted_delta,
            },
        }
    )
    return payload


def _leaderboard_compare_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    changes = Counter(str(row.get("change") or "unknown") for row in rows)
    return {
        "row_count": len(rows),
        "rankable_count": sum(1 for row in rows if row.get("rankable") is not False),
        "unrankable_count": sum(1 for row in rows if row.get("rankable") is False),
        "improvement_count": changes.get("improvement", 0),
        "regression_count": changes.get("regression", 0),
        "stable_count": changes.get("stable", 0),
        "incomparable_count": changes.get("incomparable", 0),
        "reference_count": changes.get("reference", 0),
        "boundary_mismatch_count": sum(1 for row in rows if row.get("boundary_warnings")),
        "significant_count": sum(1 for row in rows if row.get("significant") is True),
        "not_significant_count": sum(
            1 for row in rows
            if row.get("significant") is False and str(row.get("significance_label") or "") == "差异不显著"
        ),
        "low_sample_count": sum(1 for row in rows if "low_sample" in set(row.get("warnings") or [])),
        "unpaired_seed_count": sum(1 for row in rows if "unpaired_seeds" in set(row.get("warnings") or [])),
        "insufficient_overlap_count": sum(
            1 for row in rows if "insufficient_overlap" in set(row.get("warnings") or [])
        ),
        "by_change": dict(sorted(changes.items())),
    }


def _stable_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _default_benchmark_snapshot_title(scope: str, evaluation_set_id: str, target_role: str | None) -> str:
    subject = "model" if scope == "model" else (target_role or "role-version")
    return f"{evaluation_set_id} / {subject}"


def _benchmark_snapshot_source_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    linked_run_ids: set[str] = set()
    linked_report_ids: set[str] = set()
    linked_result_batch_ids: set[str] = set()
    rankable_count = 0

    def add_string(target: set[str], value: Any) -> None:
        text = str(value or "").strip()
        if text:
            target.add(text)

    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("rankable") is not False:
            rankable_count += 1
        for key in ("batch_id", "run_id", "source_run_id"):
            add_string(linked_run_ids, row.get(key))
        for key in ("report_id", "source_report_id"):
            add_string(linked_report_ids, row.get(key))
        add_string(linked_result_batch_ids, row.get("result_batch_id"))

    for run_id in linked_run_ids:
        linked_report_ids.add(f"benchmark_report:{run_id}")

    row_count = len(rows)
    return {
        "row_count": row_count,
        "rankable_count": rankable_count,
        "unrankable_count": row_count - rankable_count,
        "linked_run_ids": sorted(linked_run_ids),
        "linked_report_ids": sorted(linked_report_ids),
        "linked_result_batch_ids": sorted(linked_result_batch_ids),
        "source_run_count": len(linked_run_ids),
        "source_report_count": len(linked_report_ids),
        "source_result_batch_count": len(linked_result_batch_ids),
    }


def _stable_json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _text_content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _benchmark_snapshot_filter_values(value: Any) -> set[str] | None:
    if value in (None, "", [], (), set()):
        return None
    if isinstance(value, (list, tuple, set)):
        values = {str(item).strip().lower() for item in value if str(item or "").strip()}
        return values or None
    text = str(value or "").strip()
    if not text:
        return None
    return {part.strip().lower() for part in text.split(",") if part.strip()} or None


def _benchmark_snapshot_row_field(row: dict[str, Any], key: str) -> Any:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    aliases = {
        "source_run_id": ("source_run_id", "run_id", "batch_id"),
        "batch_id": ("batch_id", "source_run_id", "run_id"),
        "report_id": ("report_id", "source_report_id"),
        "source_report_id": ("source_report_id", "report_id"),
        "result_batch_id": ("result_batch_id",),
        "subject_id": ("subject_id", "hash", "model_config_hash", "model_id", "target_version_id"),
    }
    for candidate in aliases.get(key, (key,)):
        value = row.get(candidate)
        if value not in (None, ""):
            return value
        value = summary.get(candidate)
        if value not in (None, ""):
            return value
    return None


def _benchmark_snapshot_rankable_matches(row: dict[str, Any], allowed: set[str] | None) -> bool:
    if not allowed or allowed & {"all", "any", "*"}:
        return True
    is_rankable = row.get("rankable") is not False
    if allowed & {"rankable", "true", "1", "yes"}:
        return is_rankable
    if allowed & {"unrankable", "false", "0", "no"}:
        return not is_rankable
    return True


def _benchmark_snapshot_row_matches_source_filter(row: dict[str, Any], source_filter: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    for raw_key, raw_value in source_filter.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        allowed = _benchmark_snapshot_filter_values(raw_value)
        if allowed is None:
            continue
        if key == "rankable":
            if not _benchmark_snapshot_rankable_matches(row, allowed):
                return False
            continue
        value = _benchmark_snapshot_row_field(row, key)
        if str(value or "").strip().lower() not in allowed:
            return False
    return True


def _filter_benchmark_snapshot_rows(rows: list[dict[str, Any]], source_filter: Any) -> list[dict[str, Any]]:
    if not isinstance(source_filter, dict) or not source_filter:
        return rows
    return [row for row in rows if _benchmark_snapshot_row_matches_source_filter(row, source_filter)]


def _benchmark_snapshot_source_filter_summary(source_filter: Any) -> dict[str, Any]:
    if not isinstance(source_filter, dict):
        return {}
    return {
        key: _json_clone(value)
        for key, value in source_filter.items()
        if str(key or "").strip() and value not in (None, "", [], (), set())
    }


def _benchmark_snapshot_release_gate_error(
    rows: list[dict[str, Any]],
    *,
    scope: str,
    evaluation_set_id: str,
    seed_set_id: Any,
    benchmark_config_hash: Any,
    target_role: str | None,
) -> str | None:
    requested_seed = str(seed_set_id or "").strip()
    requested_hash = str(benchmark_config_hash or "").strip()
    if not requested_seed:
        return "seed_set_id is required for benchmark snapshots"
    if not requested_hash:
        return "benchmark_config_hash is required for benchmark snapshots"

    requested_role = str(target_role or "").strip().lower()
    requested_eval = str(evaluation_set_id or "").strip()
    for row in rows:
        if not isinstance(row, dict):
            return "snapshot rows must be structured objects"
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        row_scope = str(row.get("scope") or summary.get("scope") or "").strip().lower()
        if not row_scope:
            return "snapshot rows must include scope"
        if row_scope != scope:
            return "snapshot boundary mismatch: rows do not match requested scope"
        row_eval = str(row.get("evaluation_set_id") or summary.get("evaluation_set_id") or "").strip()
        if not row_eval or row_eval != requested_eval:
            return "snapshot boundary mismatch: rows do not match requested evaluation_set_id"
        row_seed = str(row.get("seed_set_id") or summary.get("seed_set_id") or "").strip()
        if not row_seed:
            return "snapshot rows must include seed_set_id"
        if row_seed != requested_seed:
            return "snapshot boundary mismatch: rows do not match requested seed_set_id"
        if scope == "role_version":
            row_role = str(row.get("target_role") or summary.get("target_role") or "").strip().lower()
            if not row_role or row_role != requested_role:
                return "snapshot boundary mismatch: rows do not match requested target_role"
        if scope == "model":
            row_model_id = str(row.get("model_id") or summary.get("model_id") or "").strip()
            row_model_hash = str(row.get("model_config_hash") or summary.get("model_config_hash") or "").strip()
            if not row_model_id:
                return "snapshot model rows must include model_id"
            if not row_model_hash:
                return "snapshot model rows must include model_config_hash"
        row_hash = str(
            row.get("benchmark_config_hash")
            or row.get("config_hash")
            or summary.get("benchmark_config_hash")
            or summary.get("config_hash")
            or ""
        ).strip()
        if not row_hash:
            return "snapshot rows must include benchmark_config_hash"
        if row_hash != requested_hash:
            return "snapshot boundary mismatch: rows do not match requested benchmark_config_hash"
        source_run = _first_text(
            row.get("source_run_id"),
            row.get("run_id"),
            row.get("batch_id"),
            summary.get("source_run_id"),
            summary.get("run_id"),
            summary.get("batch_id"),
        )
        result_source = _first_text(
            row.get("result_batch_id"),
            summary.get("result_batch_id"),
        )
        report_source = _first_text(
            row.get("report_id"),
            row.get("source_report_id"),
            summary.get("report_id"),
            summary.get("source_report_id"),
        )
        if not source_run:
            return "snapshot rows must include source_run_id"
        if not report_source:
            return "snapshot rows must include report_id"
        if not result_source:
            return "snapshot rows must include result_batch_id"
    return None


def _benchmark_snapshot_release_gate(
    rows: list[dict[str, Any]],
    *,
    request: BenchmarkSnapshotRequest,
    scope: str,
    evaluation_set_id: str,
    seed_set_id: Any,
    benchmark_config_hash: Any,
    target_role: str | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config_payload = _json_clone(config or {})
    legacy_error = _benchmark_snapshot_release_gate_error(
        rows,
        scope=scope,
        evaluation_set_id=evaluation_set_id,
        seed_set_id=seed_set_id,
        benchmark_config_hash=benchmark_config_hash,
        target_role=target_role,
    )
    request_payload = {
        "scope": scope,
        "benchmark_id": request.benchmark_id,
        "benchmark_version": request.benchmark_version,
        "evaluation_set_id": evaluation_set_id,
        "seed_set_id": seed_set_id,
        "benchmark_config_hash": benchmark_config_hash,
        "target_role": target_role,
        "source_filter": _json_clone(request.source_filter),
        "view_config": _json_clone(request.view_config),
        "rows": rows,
    }
    gate = evaluate_benchmark_release_gate(
        request=request_payload,
        rows=rows,
        config=config_payload,
    )
    if legacy_error:
        legacy_issue = {
            "code": _benchmark_snapshot_release_gate_legacy_code(legacy_error),
            "severity": "error",
            "message": legacy_error,
            "evidence": {
                "scope": scope,
                "evaluation_set_id": evaluation_set_id,
                "seed_set_id": seed_set_id,
                "benchmark_config_hash": benchmark_config_hash,
                "target_role": target_role,
            },
            "affected_ids": [
                str(value)
                for value in (request.benchmark_id, evaluation_set_id, seed_set_id, target_role)
                if str(value or "").strip()
            ],
        }
        blockers = [legacy_issue, *[dict(item) for item in gate.get("blockers") or [] if isinstance(item, dict)]]
        gate = {
            **gate,
            "ok": False,
            "blockers": blockers,
        }
    summary = dict(gate.get("summary") if isinstance(gate.get("summary"), dict) else {})
    summary.update(
        {
            "blocker_count": len(gate.get("blockers") or []),
            "warning_count": len(gate.get("warnings") or []),
        }
    )
    gate["summary"] = summary
    return _json_clone(gate)


def _benchmark_snapshot_release_gate_legacy_code(message: str) -> str:
    text = str(message or "").lower()
    if "seed_set_id" in text:
        return "seed_set_id_missing_or_mismatch"
    if "benchmark_config_hash" in text or "config_hash" in text:
        return "benchmark_config_hash_missing_or_mismatch"
    if "source_run_id" in text:
        return "source_run_id_missing"
    if "report_id" in text:
        return "report_id_missing"
    if "result_batch_id" in text:
        return "result_batch_id_missing"
    if "model_config_hash" in text:
        return "model_config_hash_missing"
    if "model_id" in text:
        return "model_id_missing"
    if "scope" in text:
        return "scope_missing_or_mismatch"
    if "target_role" in text:
        return "target_role_missing_or_mismatch"
    if "evaluation_set_id" in text:
        return "evaluation_set_id_missing_or_mismatch"
    return "snapshot_release_gate_failed"


def _benchmark_snapshot_release_gate_error_detail(release_gate: dict[str, Any]) -> dict[str, Any]:
    blockers = [dict(item) for item in release_gate.get("blockers") or [] if isinstance(item, dict)]
    warnings = [dict(item) for item in release_gate.get("warnings") or [] if isinstance(item, dict)]
    first_blocker = blockers[0] if blockers else {}
    message = str(first_blocker.get("message") or "benchmark snapshot release gate failed")
    return domain_error_detail(
        code="benchmark_snapshot_release_gate_failed",
        message=message,
        detail=message,
        diagnostics=[
            {
                "kind": "benchmark_snapshot_release_gate_failed",
                "release_gate_ok": bool(release_gate.get("ok")),
                "blockers": blockers,
                "warnings": warnings,
                "summary": _json_clone(release_gate.get("summary") or {}),
            }
        ],
    )


def _benchmark_snapshot_string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(item).strip() for item in value if str(item or "").strip()})
    text = str(value or "").strip()
    return [text] if text else []


def _benchmark_snapshot_int(*values: Any, default: int = 0) -> int:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def _benchmark_snapshot_summary_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    derived = _benchmark_snapshot_source_summary(rows) if rows else {}
    summary = dict(snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {})
    for key in (
        "row_count",
        "rankable_count",
        "unrankable_count",
        "linked_run_ids",
        "linked_report_ids",
        "linked_result_batch_ids",
        "source_run_count",
        "source_report_count",
        "source_result_batch_count",
    ):
        if key not in summary and key in derived:
            summary[key] = _json_clone(derived[key])
    row_count = _benchmark_snapshot_int(snapshot.get("row_count"), summary.get("row_count"), derived.get("row_count"))
    rankable_count = _benchmark_snapshot_int(snapshot.get("rankable_count"), summary.get("rankable_count"), derived.get("rankable_count"))
    unrankable_count = _benchmark_snapshot_int(
        snapshot.get("unrankable_count"),
        summary.get("unrankable_count"),
        derived.get("unrankable_count"),
        default=max(row_count - rankable_count, 0),
    )
    linked_run_ids = _benchmark_snapshot_string_list(
        snapshot.get("linked_run_ids") or summary.get("linked_run_ids") or derived.get("linked_run_ids")
    )
    linked_report_ids = _benchmark_snapshot_string_list(
        snapshot.get("linked_report_ids") or summary.get("linked_report_ids") or derived.get("linked_report_ids")
    )
    linked_result_batch_ids = _benchmark_snapshot_string_list(
        snapshot.get("linked_result_batch_ids")
        or summary.get("linked_result_batch_ids")
        or derived.get("linked_result_batch_ids")
    )
    source_run_count = _benchmark_snapshot_int(
        snapshot.get("source_run_count"),
        summary.get("source_run_count"),
        derived.get("source_run_count"),
        default=len(linked_run_ids),
    )
    source_report_count = _benchmark_snapshot_int(
        snapshot.get("source_report_count"),
        summary.get("source_report_count"),
        derived.get("source_report_count"),
        default=len(linked_report_ids),
    )
    source_result_batch_count = _benchmark_snapshot_int(
        snapshot.get("source_result_batch_count"),
        summary.get("source_result_batch_count"),
        derived.get("source_result_batch_count"),
        default=len(linked_result_batch_ids),
    )
    summary.update(
        {
            "row_count": row_count,
            "rankable_count": rankable_count,
            "unrankable_count": unrankable_count,
            "linked_run_ids": linked_run_ids,
            "linked_report_ids": linked_report_ids,
            "linked_result_batch_ids": linked_result_batch_ids,
            "source_run_count": source_run_count,
            "source_report_count": source_report_count,
            "source_result_batch_count": source_result_batch_count,
        }
    )
    release_gate = snapshot.get("release_gate")
    if not isinstance(release_gate, dict):
        release_gate = summary.get("release_gate") if isinstance(summary.get("release_gate"), dict) else {}
    release_gate = _json_clone(release_gate or {})
    if release_gate:
        gate_summary = release_gate.get("summary") if isinstance(release_gate.get("summary"), dict) else {}
        summary.update(
            {
                "release_gate_ok": bool(release_gate.get("ok")),
                "release_gate_blocker_count": _benchmark_snapshot_int(
                    summary.get("release_gate_blocker_count"),
                    gate_summary.get("blocker_count"),
                    len(release_gate.get("blockers") or []),
                ),
                "release_gate_warning_count": _benchmark_snapshot_int(
                    summary.get("release_gate_warning_count"),
                    gate_summary.get("warning_count"),
                    len(release_gate.get("warnings") or []),
                ),
                "release_gate": release_gate,
            }
        )
    release_manifest = _benchmark_snapshot_release_manifest(snapshot, summary=summary)
    return {
        "kind": "benchmark_leaderboard_snapshot",
        "schema_version": int(snapshot.get("schema_version") or 1),
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "title": str(snapshot.get("title") or ""),
        "release_notes": str(snapshot.get("release_notes") or ""),
        "scope": snapshot.get("scope"),
        "benchmark_id": snapshot.get("benchmark_id"),
        "benchmark_version": snapshot.get("benchmark_version"),
        "evaluation_set_id": snapshot.get("evaluation_set_id"),
        "seed_set_id": snapshot.get("seed_set_id"),
        "benchmark_config_hash": snapshot.get("benchmark_config_hash"),
        "target_role": snapshot.get("target_role"),
        "source_filter": _json_clone(snapshot.get("source_filter") or {}),
        "view_config": _json_clone(snapshot.get("view_config") or {}),
        "summary": _json_clone(summary),
        "row_count": row_count,
        "rankable_count": rankable_count,
        "unrankable_count": unrankable_count,
        "linked_run_ids": linked_run_ids,
        "linked_report_ids": linked_report_ids,
        "linked_result_batch_ids": linked_result_batch_ids,
        "source_run_count": source_run_count,
        "source_report_count": source_report_count,
        "source_result_batch_count": source_result_batch_count,
        "release_gate": release_gate,
        "release_manifest": release_manifest,
        "content_hash": snapshot.get("content_hash"),
        "created_at": snapshot.get("created_at"),
    }


def _benchmark_snapshot_release_manifest(snapshot: dict[str, Any], *, summary: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    linked_run_ids = _benchmark_snapshot_string_list(summary.get("linked_run_ids") or snapshot.get("linked_run_ids"))
    linked_report_ids = _benchmark_snapshot_string_list(summary.get("linked_report_ids") or snapshot.get("linked_report_ids"))
    linked_result_batch_ids = _benchmark_snapshot_string_list(
        summary.get("linked_result_batch_ids") or snapshot.get("linked_result_batch_ids")
    )
    release_gate = summary.get("release_gate") if isinstance(summary.get("release_gate"), dict) else {}
    gate_summary = release_gate.get("summary") if isinstance(release_gate.get("summary"), dict) else {}
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "content_hash": snapshot.get("content_hash"),
        "created_at": snapshot.get("created_at"),
        "boundaries": {
            "scope": snapshot.get("scope"),
            "benchmark_id": snapshot.get("benchmark_id"),
            "benchmark_version": snapshot.get("benchmark_version"),
            "evaluation_set_id": snapshot.get("evaluation_set_id"),
            "seed_set_id": snapshot.get("seed_set_id"),
            "benchmark_config_hash": snapshot.get("benchmark_config_hash"),
            "target_role": snapshot.get("target_role"),
        },
        "release_gate": {
            "ok": bool(release_gate.get("ok")) if release_gate else None,
            "blocker_count": _benchmark_snapshot_int(
                summary.get("release_gate_blocker_count"),
                gate_summary.get("blocker_count"),
                len(release_gate.get("blockers") or []),
            ),
            "warning_count": _benchmark_snapshot_int(
                summary.get("release_gate_warning_count"),
                gate_summary.get("warning_count"),
                len(release_gate.get("warnings") or []),
            ),
            "thresholds": _json_clone(gate_summary.get("thresholds") or {}),
            "suite_lifecycle": _json_clone(gate_summary.get("suite_lifecycle") or {}),
            "diagnostics": _json_clone(gate_summary.get("diagnostics") or {}),
        },
        "source": {
            "row_count": summary.get("row_count", 0),
            "rankable_count": summary.get("rankable_count", 0),
            "unrankable_count": summary.get("unrankable_count", 0),
            "source_filter_applied": _json_clone(summary.get("source_filter_applied") or {}),
            "linked_run_ids": linked_run_ids,
            "linked_report_ids": linked_report_ids,
            "linked_result_batch_ids": linked_result_batch_ids,
        },
        "artifacts": {
            "snapshot": f"/api/benchmark/snapshots/{snapshot_id}",
            "exports": {
                "json": f"/api/benchmark/snapshots/{snapshot_id}/export?format=json",
                "markdown": f"/api/benchmark/snapshots/{snapshot_id}/export?format=markdown",
                "csv": f"/api/benchmark/snapshots/{snapshot_id}/export?format=csv",
            },
            "reports": linked_report_ids,
            "runs": linked_run_ids,
            "result_batches": linked_result_batch_ids,
        },
    }


def _benchmark_snapshot_release_gate_export_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    release_gate = snapshot.get("release_gate") if isinstance(snapshot.get("release_gate"), dict) else {}
    if not release_gate and isinstance(summary.get("release_gate"), dict):
        release_gate = summary["release_gate"]
    manifest = snapshot.get("release_manifest") if isinstance(snapshot.get("release_manifest"), dict) else {}
    manifest_gate = manifest.get("release_gate") if isinstance(manifest.get("release_gate"), dict) else {}
    gate_summary = release_gate.get("summary") if isinstance(release_gate.get("summary"), dict) else {}
    ok_value = release_gate.get("ok")
    if not isinstance(ok_value, bool):
        ok_value = manifest_gate.get("ok") if isinstance(manifest_gate.get("ok"), bool) else None
    blocker_count = _benchmark_snapshot_int(
        summary.get("release_gate_blocker_count"),
        gate_summary.get("blocker_count"),
        manifest_gate.get("blocker_count"),
        len(release_gate.get("blockers") or []),
    )
    warning_count = _benchmark_snapshot_int(
        summary.get("release_gate_warning_count"),
        gate_summary.get("warning_count"),
        manifest_gate.get("warning_count"),
        len(release_gate.get("warnings") or []),
    )
    return {
        "ok": ok_value,
        "label": "通过" if ok_value is True else ("阻断" if ok_value is False else "未上报"),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "thresholds": _json_clone(gate_summary.get("thresholds") or manifest_gate.get("thresholds") or {}),
        "suite_lifecycle": _json_clone(
            gate_summary.get("suite_lifecycle") or manifest_gate.get("suite_lifecycle") or {}
        ),
    }


def _benchmark_snapshot_detail_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _benchmark_snapshot_summary_payload(snapshot)
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    payload["rows"] = _json_clone(rows)
    return payload


def _benchmark_snapshot_markdown(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    manifest = snapshot.get("release_manifest") if isinstance(snapshot.get("release_manifest"), dict) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    release_gate = _benchmark_snapshot_release_gate_export_summary(snapshot)
    thresholds = release_gate["thresholds"]
    lifecycle = release_gate["suite_lifecycle"]
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    lines = [
        f"# 榜单快照：{_markdown_value(snapshot.get('title'))}",
        "",
        "## 快照头",
        f"- 快照 ID: {_markdown_value(snapshot.get('snapshot_id'))}",
        f"- 范围: {_markdown_value(snapshot.get('scope'))}",
        f"- 套件: {_markdown_value(snapshot.get('benchmark_id'))} v{_markdown_value(snapshot.get('benchmark_version'))}",
        f"- 评测集: {_markdown_value(snapshot.get('evaluation_set_id'))}",
        f"- 种子集: {_markdown_value(snapshot.get('seed_set_id'))}",
        f"- Config Hash: {_markdown_value(snapshot.get('benchmark_config_hash'))}",
        f"- 目标角色: {_markdown_value(snapshot.get('target_role'))}",
        f"- 内容 Hash: {_markdown_value(snapshot.get('content_hash'))}",
        f"- 创建时间: {_markdown_value(snapshot.get('created_at'))}",
        f"- 发布门禁: {release_gate['label']} / 阻断 {release_gate['blocker_count']} / 警告 {release_gate['warning_count']}",
        f"- 套件状态: {_markdown_value(lifecycle.get('status') or '未上报')} / launchable={_markdown_value(lifecycle.get('launchable'))}",
        f"- 门禁阈值: sample={_markdown_value(thresholds.get('min_sample_size'))}, completed={_markdown_value(thresholds.get('min_completed_games'))}, paired={_markdown_value(thresholds.get('min_paired_overlap'))}",
        "",
        "## 发布说明",
        _markdown_value(snapshot.get("release_notes") or "未填写"),
        "",
        "## 摘要",
        f"- 行数: {summary.get('row_count', snapshot.get('row_count', 0))}",
        f"- 可入榜: {summary.get('rankable_count', snapshot.get('rankable_count', 0))}",
        f"- 未入榜: {summary.get('unrankable_count', snapshot.get('unrankable_count', 0))}",
        f"- 来源运行: {summary.get('source_run_count', snapshot.get('source_run_count', 0))}",
        f"- 来源报告: {summary.get('source_report_count', snapshot.get('source_report_count', 0))}",
        f"- 来源过滤: {_markdown_value(source.get('source_filter_applied') or summary.get('source_filter_applied') or {})}",
        "",
        "## 冻结行",
    ]
    for index, row in enumerate(rows[:100], start=1):
        if not isinstance(row, dict):
            continue
        score = _leaderboard_score(row, scope=str(snapshot.get("scope") or "role_version"))
        win_rate = _leaderboard_metric(row, "target_side_win_rate")
        lines.append(
            f"- {index}. {_markdown_value(row.get('subject_id') or row.get('hash'))}: "
            f"分数 {score:.4f} / 胜率 {win_rate:.4f} / "
            f"{'可入榜' if row.get('rankable') is not False else '未入榜'} / "
            f"运行 {_markdown_value(row.get('source_run_id') or row.get('batch_id'))} / "
            f"报告 {_markdown_value(row.get('report_id'))}"
        )
    if len(rows) > 100:
        lines.append(f"- 另有 {len(rows) - 100} 行未在 Markdown 预览中展开。")
    if not rows:
        lines.append("- 无冻结行")
    return "\n".join(lines)


def _benchmark_snapshot_csv(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    manifest = snapshot.get("release_manifest") if isinstance(snapshot.get("release_manifest"), dict) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    release_gate = _benchmark_snapshot_release_gate_export_summary(snapshot)
    thresholds = release_gate["thresholds"]
    lifecycle = release_gate["suite_lifecycle"]
    rows: list[list[Any]] = [
        ["区段", "标签", "值", "详情"],
        ["快照头", "快照 ID", snapshot.get("snapshot_id"), ""],
        ["快照头", "标题", snapshot.get("title"), ""],
        ["快照头", "范围", snapshot.get("scope"), ""],
        ["快照头", "套件", snapshot.get("benchmark_id"), snapshot.get("benchmark_version")],
        ["快照头", "评测集", snapshot.get("evaluation_set_id"), ""],
        ["快照头", "种子集", snapshot.get("seed_set_id"), ""],
        ["快照头", "Config Hash", snapshot.get("benchmark_config_hash"), ""],
        ["快照头", "内容 Hash", snapshot.get("content_hash"), ""],
        ["发布门禁", "状态", release_gate["label"], f"阻断 {release_gate['blocker_count']} / 警告 {release_gate['warning_count']}"],
        ["发布门禁", "套件状态", lifecycle.get("status") or "未上报", f"launchable={lifecycle.get('launchable')}"],
        [
            "发布门禁",
            "阈值",
            json.dumps(thresholds, ensure_ascii=False),
            "min_sample_size / min_completed_games / min_paired_overlap",
        ],
        ["发布说明", "说明", snapshot.get("release_notes"), ""],
        ["摘要", "行数", summary.get("row_count", snapshot.get("row_count", 0)), ""],
        ["摘要", "可入榜", summary.get("rankable_count", snapshot.get("rankable_count", 0)), ""],
        ["摘要", "未入榜", summary.get("unrankable_count", snapshot.get("unrankable_count", 0)), ""],
        ["摘要", "来源运行", summary.get("source_run_count", snapshot.get("source_run_count", 0)), ""],
        ["摘要", "来源报告", summary.get("source_report_count", snapshot.get("source_report_count", 0)), ""],
        ["摘要", "来源过滤", json.dumps(source.get("source_filter_applied") or summary.get("source_filter_applied") or {}, ensure_ascii=False), ""],
    ]
    scope = str(snapshot.get("scope") or "role_version")
    for row in snapshot.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        subject = row.get("subject_id") or row.get("hash") or row.get("model_config_hash") or row.get("model_id")
        rows.append([
            "冻结行",
            subject,
            _leaderboard_score(row, scope=scope),
            (
                f"胜率 {row.get('target_side_win_rate', '')} / "
                f"入榜 {row.get('rankable') is not False} / "
                f"运行 {row.get('source_run_id') or row.get('batch_id') or ''} / "
                f"报告 {row.get('report_id') or ''}"
            ),
        ])
    return "\n".join(",".join(_csv_value(value) for value in row) for row in rows)


def _benchmark_snapshot_compare_payload(
    snapshot: dict[str, Any],
    current_rows: list[dict[str, Any]],
    frozen_rows: list[dict[str, Any]],
    *,
    scope: str,
    evaluation_set_id: str | None,
    target_role: str | None,
    compare_mode: str = "current_vs_snapshot",
    against_snapshot: dict[str, Any] | None = None,
    initial_boundary_warnings: list[str] | None = None,
) -> dict[str, Any]:
    current_by_key = _benchmark_snapshot_row_map(current_rows)
    frozen_by_key = _benchmark_snapshot_row_map(frozen_rows)
    changed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    boundary_warnings: set[str] = set(initial_boundary_warnings or [])

    for key, current in current_by_key.items():
        frozen = frozen_by_key.get(key)
        if frozen is None:
            row = _benchmark_snapshot_member_row(current, key, snapshot, scope=scope, target_role=target_role)
            added.append(row)
            boundary_warnings.update(row.get("boundary_warnings") or [])
            continue
        row = _benchmark_snapshot_changed_row(current, frozen, key, snapshot, scope=scope, target_role=target_role)
        boundary_warnings.update(row.get("boundary_warnings") or [])
        if _benchmark_snapshot_row_changed(row):
            changed.append(row)

    for key, frozen in frozen_by_key.items():
        if key in current_by_key:
            continue
        row = _benchmark_snapshot_member_row(frozen, key, snapshot, scope=scope, target_role=target_role)
        removed.append(row)
        boundary_warnings.update(row.get("boundary_warnings") or [])

    changed.sort(
        key=lambda row: (
            abs(float(row.get("score_delta") or 0)),
            abs(float(row.get("win_rate_delta") or 0)),
            str(row.get("key") or ""),
        ),
        reverse=True,
    )
    added.sort(key=lambda row: (-_leaderboard_score(row, scope=scope), str(row.get("key") or "")))
    removed.sort(key=lambda row: (-_leaderboard_score(row, scope=scope), str(row.get("key") or "")))
    if not current_rows:
        boundary_warnings.add("empty_current_leaderboard")
    summary = {
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "compare_mode": compare_mode,
        "scope": scope,
        "evaluation_set_id": evaluation_set_id,
        "target_role": target_role,
        "current_row_count": len(current_rows),
        "snapshot_row_count": len(frozen_rows),
        "changed_count": len(changed),
        "added_count": len(added),
        "removed_count": len(removed),
        "boundary_warning_count": len(boundary_warnings),
        "rankable_current_count": sum(1 for row in current_rows if row.get("rankable") is not False),
        "rankable_snapshot_count": sum(1 for row in frozen_rows if row.get("rankable") is not False),
    }
    if against_snapshot is not None:
        summary["against_snapshot_id"] = str(against_snapshot.get("snapshot_id") or "")
    return {
        "kind": "benchmark_snapshot_compare",
        "schema_version": 1,
        "compare_mode": compare_mode,
        "snapshot": _benchmark_snapshot_summary_payload(snapshot),
        **({"against_snapshot": _benchmark_snapshot_summary_payload(against_snapshot)} if against_snapshot is not None else {}),
        "current": {
            "scope": scope,
            "evaluation_set_id": evaluation_set_id,
            "target_role": target_role,
            **({"snapshot_id": str(against_snapshot.get("snapshot_id") or "")} if against_snapshot is not None else {}),
            "row_count": len(current_rows),
            "rows": [_benchmark_snapshot_member_row(row, _benchmark_snapshot_row_key(row), snapshot, scope=scope, target_role=target_role) for row in current_rows],
        },
        "frozen": {
            "row_count": len(frozen_rows),
            "rows": [_benchmark_snapshot_member_row(row, _benchmark_snapshot_row_key(row), snapshot, scope=scope, target_role=target_role) for row in frozen_rows],
        },
        "summary": summary,
        "changed": changed,
        "added": added,
        "removed": removed,
        "boundary_warnings": sorted(boundary_warnings),
    }


def _benchmark_snapshot_row_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        key = _benchmark_snapshot_row_key(row) or f"row-{index}"
        if key not in mapped:
            mapped[key] = row
    return mapped


def _benchmark_snapshot_row_key(row: dict[str, Any] | None) -> str:
    return _leaderboard_subject_key(row)


def _benchmark_snapshot_member_row(
    row: dict[str, Any],
    key: str,
    snapshot: dict[str, Any],
    *,
    scope: str,
    target_role: str | None,
) -> dict[str, Any]:
    payload = dict(row)
    payload["key"] = key or _benchmark_snapshot_row_key(row)
    payload["boundary_warnings"] = _benchmark_snapshot_boundary_warnings(
        row,
        snapshot,
        scope=scope,
        target_role=target_role,
    )
    return payload


def _benchmark_snapshot_changed_row(
    current: dict[str, Any],
    frozen: dict[str, Any],
    key: str,
    snapshot: dict[str, Any],
    *,
    scope: str,
    target_role: str | None,
) -> dict[str, Any]:
    score_delta = _leaderboard_score(current, scope=scope) - _leaderboard_score(frozen, scope=scope)
    win_rate_delta = _leaderboard_metric(current, "target_side_win_rate") - _leaderboard_metric(frozen, "target_side_win_rate")
    games_delta = int(_leaderboard_metric(current, "games_played", "game_count", "total_games")) - int(
        _leaderboard_metric(frozen, "games_played", "game_count", "total_games")
    )
    rankable_changed = (current.get("rankable") is not False) != (frozen.get("rankable") is not False)
    boundary_warnings = _benchmark_snapshot_boundary_warnings(current, snapshot, scope=scope, target_role=target_role)
    if boundary_warnings:
        change = "incomparable"
    elif score_delta > 0:
        change = "improvement"
    elif score_delta < 0:
        change = "regression"
    elif win_rate_delta or games_delta or rankable_changed:
        change = "changed"
    else:
        change = "stable"
    return {
        "key": key,
        "current": _benchmark_snapshot_member_row(current, key, snapshot, scope=scope, target_role=target_role),
        "snapshot": _benchmark_snapshot_member_row(frozen, key, snapshot, scope=scope, target_role=target_role),
        "score_delta": score_delta,
        "scoreDelta": score_delta,
        "win_rate_delta": win_rate_delta,
        "winRateDelta": win_rate_delta,
        "games_delta": games_delta,
        "gamesDelta": games_delta,
        "rankable_changed": rankable_changed,
        "rankableChanged": rankable_changed,
        "boundary_warnings": boundary_warnings,
        "change": change,
    }


def _benchmark_snapshot_row_changed(row: dict[str, Any]) -> bool:
    return (
        abs(float(row.get("score_delta") or 0)) > 0.000001
        or abs(float(row.get("win_rate_delta") or 0)) > 0.000001
        or int(row.get("games_delta") or 0) != 0
        or bool(row.get("rankable_changed"))
        or bool(row.get("boundary_warnings"))
    )


def _benchmark_snapshot_pair_boundary_warnings(
    snapshot: dict[str, Any],
    against_snapshot: dict[str, Any],
    *,
    scope: str,
    target_role: str | None,
) -> list[str]:
    warnings: list[str] = []
    against_scope = str(against_snapshot.get("scope") or "").strip().lower()
    if against_scope and against_scope != scope:
        warnings.append("scope_mismatch")
    for key, warning in [
        ("evaluation_set_id", "evaluation_set_mismatch"),
        ("seed_set_id", "seed_set_mismatch"),
        ("benchmark_config_hash", "benchmark_config_hash_mismatch"),
        ("benchmark_id", "benchmark_id_mismatch"),
    ]:
        left = str(snapshot.get(key) or "").strip()
        right = str(against_snapshot.get(key) or "").strip()
        if left and right and left != right:
            warnings.append(warning)
    against_role = str(against_snapshot.get("target_role") or "").strip().lower()
    if scope == "role_version" and target_role and against_role and against_role != target_role:
        warnings.append("target_role_mismatch")
    if _stable_json_text(snapshot.get("source_filter") or {}) != _stable_json_text(against_snapshot.get("source_filter") or {}):
        warnings.append("source_filter_mismatch")
    return sorted(set(warnings))


def _benchmark_snapshot_boundary_warnings(
    row: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    scope: str,
    target_role: str | None,
) -> list[str]:
    warnings: list[str] = []
    row_scope = str(row.get("scope") or "").strip().lower()
    if row_scope and row_scope != scope:
        warnings.append("scope_mismatch")
    row_eval = str(row.get("evaluation_set_id") or "").strip()
    snapshot_eval = str(snapshot.get("evaluation_set_id") or "").strip()
    if row_eval and snapshot_eval and row_eval != snapshot_eval:
        warnings.append("evaluation_set_mismatch")
    row_seed = str(row.get("seed_set_id") or "").strip()
    snapshot_seed = str(snapshot.get("seed_set_id") or "").strip()
    if row_seed and snapshot_seed and row_seed != snapshot_seed:
        warnings.append("seed_set_mismatch")
    row_hash = str(row.get("benchmark_config_hash") or row.get("config_hash") or "").strip()
    snapshot_hash = str(snapshot.get("benchmark_config_hash") or "").strip()
    if row_hash and snapshot_hash and row_hash != snapshot_hash:
        warnings.append("benchmark_config_hash_mismatch")
    row_role = str(row.get("target_role") or "").strip().lower()
    if scope == "role_version" and target_role and row_role and row_role != target_role:
        warnings.append("target_role_mismatch")
    return warnings


def _filter_benchmark_snapshot_cache(
    rows: list[dict[str, Any]],
    *,
    scope: str | None = None,
    evaluation_set_id: str | None = None,
    benchmark_id: str | None = None,
    target_role: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filtered = rows
    if scope:
        filtered = [row for row in filtered if row.get("scope") == scope]
    if evaluation_set_id:
        filtered = [row for row in filtered if row.get("evaluation_set_id") == evaluation_set_id]
    if benchmark_id:
        filtered = [row for row in filtered if row.get("benchmark_id") == benchmark_id]
    if target_role:
        filtered = [row for row in filtered if row.get("target_role") == target_role]
    filtered.sort(key=lambda row: (str(row.get("created_at") or ""), str(row.get("snapshot_id") or "")), reverse=True)
    return filtered[:max(1, min(int(limit or 50), 500))]


def _benchmark_view_payload(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "benchmark_saved_view",
        "schema_version": 1,
        "view_key": str(view.get("view_key") or ""),
        "name": str(view.get("name") or "Default view"),
        "scope": str(view.get("scope") or "role_version"),
        "benchmark_id": view.get("benchmark_id"),
        "evaluation_set_id": view.get("evaluation_set_id"),
        "target_role": view.get("target_role"),
        "view_config": _json_clone(view.get("view_config") or {}),
        "created_at": view.get("created_at"),
        "updated_at": view.get("updated_at"),
    }


def _apply_benchmark_lifecycle_override(
    spec: BenchmarkSpec,
    override: dict[str, Any] | None,
) -> tuple[BenchmarkSpec, dict[str, Any] | None]:
    if not isinstance(override, dict) or not override:
        return spec, None
    status = str(override.get("status") or "").strip().lower()
    if status not in VALID_BENCHMARK_STATUSES:
        return spec, None
    applied = {
        "benchmark_id": spec.id,
        "status": status,
        "enabled": bool(override.get("enabled", status in LAUNCHABLE_BENCHMARK_STATUSES)),
        "reason": str(override.get("reason") or ""),
        "updated_at": str(override.get("updated_at") or ""),
    }
    return spec.model_copy(update={"status": status, "enabled": applied["enabled"]}), applied


def _benchmark_suite_lineage_key(item: dict[str, Any]) -> tuple[str, str]:
    target_type = str(item.get("target_type") or "role_version")
    family_id = str(item.get("suite_family_id") or item.get("id") or item.get("benchmark_id") or "")
    return target_type, family_id


def _benchmark_suite_lineage_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "version": item.get("version"),
        "suite_version": item.get("suite_version") or f"v{item.get('version')}",
        "evaluation_set_id": item.get("evaluation_set_id"),
        "config_hash": item.get("config_hash"),
        "status": item.get("status"),
        "launchable": bool(item.get("launchable")),
        "seed_set_id": item.get("seed_set_id"),
        "seed_set_config_hash": (item.get("seed_set") or {}).get("config_hash")
        if isinstance(item.get("seed_set"), dict)
        else None,
    }


def _copy_benchmark_suite_lineage(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in (
        "suite_family_id",
        "suite_version",
        "version_lineage",
        "version_count",
        "latest_version",
        "latest_launchable_version",
        "is_latest_version",
        "is_latest_launchable_version",
    ):
        target[key] = _json_clone(source.get(key))


def _annotate_benchmark_suite_lineage(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in summaries:
        groups.setdefault(_benchmark_suite_lineage_key(item), []).append(item)
    for items in groups.values():
        ordered = sorted(
            items,
            key=lambda item: (int(item.get("version") or 0), str(item.get("id") or "")),
            reverse=True,
        )
        lineage = [_benchmark_suite_lineage_item(item) for item in ordered]
        latest = next((entry for entry in lineage if entry.get("id")), lineage[0] if lineage else None)
        latest_launchable = next((entry for entry in lineage if entry.get("launchable")), None)
        latest_id = latest.get("id") if latest else None
        latest_launchable_id = latest_launchable.get("id") if latest_launchable else None
        for item in items:
            item["version_lineage"] = _json_clone(lineage)
            item["version_count"] = len(lineage)
            item["latest_version"] = _json_clone(latest) if latest else None
            item["latest_launchable_version"] = _json_clone(latest_launchable) if latest_launchable else None
            item["is_latest_version"] = bool(latest_id and item.get("id") == latest_id)
            item["is_latest_launchable_version"] = bool(latest_launchable_id and item.get("id") == latest_launchable_id)
    return summaries


def _filter_benchmark_view_cache(
    rows: list[dict[str, Any]],
    *,
    scope: str | None = None,
    evaluation_set_id: str | None = None,
    benchmark_id: str | None = None,
    target_role: str | None = None,
    view_key: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filtered = rows
    if view_key:
        filtered = [row for row in filtered if row.get("view_key") == view_key]
    if scope:
        filtered = [row for row in filtered if row.get("scope") == scope]
    if evaluation_set_id:
        filtered = [row for row in filtered if row.get("evaluation_set_id") == evaluation_set_id]
    if benchmark_id:
        filtered = [row for row in filtered if row.get("benchmark_id") == benchmark_id]
    if target_role:
        filtered = [row for row in filtered if row.get("target_role") == target_role]
    filtered.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row.get("view_key") or "")), reverse=True)
    return filtered[:max(1, min(int(limit or 50), 500))]


def _is_benchmark_suite_batch(
    batch: dict[str, Any],
    *,
    benchmark_id: str,
    evaluation_set_id: str,
) -> bool:
    if not isinstance(batch, dict):
        return False
    if batch.get("kind") != "benchmark_batch":
        return False
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    batch_benchmark_id = str(benchmark.get("id") or batch.get("benchmark_id") or "")
    batch_evaluation_set_id = str(
        benchmark.get("evaluation_set_id")
        or batch.get("evaluation_set_id")
        or config.get("evaluation_set_id")
        or ""
    )
    if benchmark_id and batch_benchmark_id != benchmark_id:
        return False
    if evaluation_set_id and batch_evaluation_set_id != evaluation_set_id:
        return False
    return True


def _benchmark_run_sort_key(batch: dict[str, Any]) -> tuple[str, str, str]:
    activity_at = batch.get("finished_at") or batch.get("last_heartbeat_at") or batch.get("updated_at") or batch.get("started_at")
    return (
        str(activity_at or ""),
        str(batch.get("started_at") or ""),
        str(batch.get("batch_id") or batch.get("run_id") or ""),
    )


def _benchmark_latest_run_payload(batch: dict[str, Any]) -> dict[str, Any]:
    progress = batch.get("progress") if isinstance(batch.get("progress"), dict) else {}
    diagnostics = batch.get("diagnostics") if isinstance(batch.get("diagnostics"), list) else []
    roles = batch.get("roles") if isinstance(batch.get("roles"), list) else []
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    return {
        "batch_id": batch.get("batch_id") or batch.get("run_id"),
        "status": batch.get("status"),
        "current_stage": batch.get("current_stage") or batch.get("stage") or progress.get("stage"),
        "target_type": batch.get("target_type") or benchmark.get("target_type"),
        "started_at": batch.get("started_at"),
        "finished_at": batch.get("finished_at"),
        "last_heartbeat_at": batch.get("last_heartbeat_at"),
        "role_count": len(roles),
        "result_count": int(batch.get("result_count") or len(batch.get("results") or []) or (1 if batch.get("result") else 0)),
        "diagnostic_count": int(batch.get("diagnostic_count") or len(diagnostics)),
    }


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {key: row[key] for key in keys()}
    return {}


def _model_identifier(model: Any) -> str | None:
    for attr in ("model_name", "model", "model_id", "deployment_name", "azure_deployment", "name"):
        value = getattr(model, attr, None)
        if value:
            return str(value)
    return None


def _runtime_public_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        values: list[Any] = []
        for item in value:
            public_item = _runtime_public_value(item)
            if public_item is not None:
                values.append(public_item)
        return values
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key or "").strip()
            if not key_text or any(secret in key_text.lower() for secret in ("key", "secret", "token", "password")):
                continue
            public_item = _runtime_public_value(item)
            if public_item is not None:
                sanitized[key_text] = public_item
        return sanitized
    return str(value)


def _injected_model_runtime_hash_input(model: Any, *, model_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": "injected_model",
        "model_id": model_id,
        "class": f"{model.__class__.__module__}.{model.__class__.__qualname__}",
    }
    for attr in (
        "temperature",
        "top_p",
        "max_tokens",
        "timeout",
        "request_timeout",
        "max_retries",
        "model_kwargs",
    ):
        value = getattr(model, attr, None)
        public_value = _runtime_public_value(value)
        if public_value not in (None, "", {}, []):
            payload[attr] = public_value
    return payload


def _benchmark_model_runtime_payload(
    *,
    source: str,
    model_id: str,
    model_config_hash: str,
    hash_input: dict[str, Any] | None,
    hash_provided: bool,
) -> dict[str, Any]:
    runtime = {
        "schema_version": 1,
        "source": source,
        "hash_source": source,
        "hash_algorithm": "sha256",
        "hash_input_schema_version": 1,
        "model_id": model_id,
        "model_config_hash": model_config_hash,
        "hash_provided": bool(hash_provided),
        "externally_provided": bool(hash_provided),
        "hash_input": _json_clone(hash_input or {}),
    }
    return {
        "model_id": model_id,
        "model_config_hash": model_config_hash,
        "model_runtime": runtime,
    }


def _stable_runtime_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _benchmark_seed_sequence(spec_snapshot: dict[str, Any], game_count: int) -> list[int]:
    seeds = spec_snapshot.get("seeds")
    if not isinstance(seeds, list):
        return []
    normalized: list[int] = []
    for item in seeds[:game_count]:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return normalized if len(normalized) >= game_count else []


def _apply_benchmark_gates(cfg: dict[str, Any], gates: dict[str, Any]) -> None:
    if not gates:
        return
    if gates.get("min_completed_games") is not None:
        cfg["data_sufficient_min_games"] = gates["min_completed_games"]
        cfg["leaderboard_min_games"] = gates["min_completed_games"]
    if gates.get("min_valid_game_rate") is not None:
        cfg["data_sufficient_min_valid_game_rate"] = gates["min_valid_game_rate"]
        cfg["leaderboard_min_valid_game_rate"] = gates["min_valid_game_rate"]
    if gates.get("max_llm_error_rate") is not None:
        cfg["max_llm_error_rate"] = gates["max_llm_error_rate"]
        cfg["leaderboard_llm_error_rate_ceiling"] = gates["max_llm_error_rate"]
    if gates.get("max_fallback_rate") is not None:
        cfg["max_fallback_rate"] = gates["max_fallback_rate"]
        cfg["leaderboard_fallback_rate_ceiling"] = gates["max_fallback_rate"]
    if gates.get("max_policy_adjusted_rate") is not None:
        cfg["max_policy_adjusted_rate"] = gates["max_policy_adjusted_rate"]
        cfg["leaderboard_policy_adjusted_rate_ceiling"] = gates["max_policy_adjusted_rate"]


def _apply_benchmark_judge(cfg: dict[str, Any], judge: dict[str, Any]) -> None:
    if not judge:
        return
    if judge.get("enable_decision_judge") is not None:
        cfg["eval_decision_judge"] = bool(judge.get("enable_decision_judge"))
    if judge.get("judge_max_decisions") is not None:
        cfg["eval_judge_max_decisions"] = judge["judge_max_decisions"]
    if judge.get("judge_concurrency") is not None:
        cfg["eval_judge_concurrency"] = judge["judge_concurrency"]
    if judge.get("judge_timeout_seconds") is not None:
        cfg["eval_judge_timeout_seconds"] = judge["judge_timeout_seconds"]



