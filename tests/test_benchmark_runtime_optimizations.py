from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.graphs.subgraphs.eval import nodes as eval_nodes
from app.lib.score import PlayerScore, aggregate_batch_scores
from ui.backend.schemas import BenchmarkRequest
from ui.backend.services.benchmark_leaderboard_payloads import _leaderboard_compare_row
from ui.backend.services.benchmark_run_service import BenchmarkRunService


class _TaskService:
    def persist_background_tasks(self) -> None:
        return None

    def mark_benchmark_stage(
        self,
        batch: dict[str, Any],
        stage: str,
        *,
        status: str,
        percent: float,
        **fields: Any,
    ) -> None:
        batch["status"] = status
        batch["current_stage"] = stage
        batch["progress"] = {"stage": stage, "percent": percent, **fields}

    @staticmethod
    def task_progress_percent(batch: dict[str, Any]) -> float:
        return float((batch.get("progress") or {}).get("percent") or 0.0)


class _Registry:
    @staticmethod
    def get_baseline(role: str) -> str:
        return f"{role}-baseline"


class _BenchmarkContext:
    def __init__(self, batch: dict[str, Any]) -> None:
        self.evolution_batches = {batch["batch_id"]: batch}
        self.task_service = _TaskService()
        self.paths = object()
        self.model = object()
        self.registry = _Registry()
        self.active = 0
        self.max_active = 0
        self.called_roles: list[str] = []

    def model_for_run(self, **_kwargs: Any) -> object:
        return self.model

    def invalidate_role_overview_cache(self) -> None:
        return None

    async def evaluate_benchmark_batch(self, *, batch_config: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        role = str(batch_config.get("target_role") or "")
        self.called_roles.append(role)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        return _completed_result(batch_config)


def _completed_result(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch_id": config["batch_id"],
        "config": dict(config),
        "game_count": int(config.get("game_count") or 0),
        "completed": int(config.get("game_count") or 0),
        "rankable": True,
        "started_at": "2026-06-12T00:00:00+08:00",
    }


def _queued_batch(*, results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "kind": "benchmark_batch",
        "batch_id": "bench_parallel",
        "target_type": "role_version",
        "roles": ["seer", "witch"],
        "status": "running",
        "config": {
            "roles": ["seer", "witch"],
            "battle_games": 1,
            "max_days": 1,
            "role_concurrency": 2,
            "game_concurrency": 4,
        },
        "results": list(results or []),
        "progress": {},
    }


def test_benchmark_roles_run_with_bounded_parallelism() -> None:
    batch = _queued_batch()
    context = _BenchmarkContext(batch)
    service = BenchmarkRunService(context)

    asyncio.run(
        service.run_queued_benchmark(
            batch["batch_id"],
            BenchmarkRequest(roles=["seer", "witch"], battle_games=1, max_days=1),
        )
    )

    assert context.max_active == 2
    assert context.called_roles == ["seer", "witch"]
    assert [result["config"]["target_role"] for result in batch["results"]] == ["seer", "witch"]
    assert all(result["config"]["game_concurrency"] == 2 for result in batch["results"])


def test_benchmark_resume_skips_completed_role() -> None:
    seer_config = {
        "batch_id": "bench_parallel_seer",
        "target_role": "seer",
        "game_count": 1,
    }
    batch = _queued_batch(results=[_completed_result(seer_config)])
    context = _BenchmarkContext(batch)
    service = BenchmarkRunService(context)

    asyncio.run(
        service.run_queued_benchmark(
            batch["batch_id"],
            BenchmarkRequest(roles=["seer", "witch"], battle_games=1, max_days=1),
        )
    )

    assert context.called_roles == ["witch"]
    assert [result["config"]["target_role"] for result in batch["results"]] == ["seer", "witch"]


def test_eval_resume_runs_only_missing_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    invoked_seeds: list[int] = []

    class _GameGraph:
        async def ainvoke(self, game_state: dict[str, Any]) -> dict[str, Any]:
            invoked_seeds.append(int(game_state["seed"]))
            return {
                "winner": "villagers",
                "roles": {},
                "game_events": [],
                "decisions": [],
            }

    monkeypatch.setattr(eval_nodes, "_score_game", lambda _game: [])
    resumed = {
        "game_id": "resume_101",
        "seed": 101,
        "winner": "villagers",
        "player_roles": {},
        "events": [],
        "decisions": [],
    }
    state = {
        "batch_id": "resume_batch",
        "batch_config": {
            "game_count": 2,
            "seeds": [101, 102],
            "resume_games": [resumed],
        },
        "paths": type("Paths", (), {"runs_dir": tmp_path})(),
        "game_subgraph": _GameGraph(),
        "warnings": [],
        "diagnostics": [],
    }

    result = asyncio.run(eval_nodes.run_games_node(state))

    assert invoked_seeds == [102]
    assert [game["seed"] for game in result["games"]] == [101, 102]


def test_score_dispersion_and_paired_significance_use_real_samples() -> None:
    summary = aggregate_batch_scores(
        [
            PlayerScore(player_id=1, role="seer", role_score=6.0),
            PlayerScore(player_id=2, role="seer", role_score=8.0),
        ],
        game_count=2,
    )
    assert summary.score_sample_size == 2
    assert summary.role_score_stddev == pytest.approx(2 ** 0.5)
    assert summary.role_score_ci_low < summary.avg_role_score < summary.role_score_ci_high

    baseline_metrics = [
        {"seed": seed, "target_side_win": False}
        for seed in range(30)
    ]
    candidate_metrics = [
        {"seed": seed, "target_side_win": True}
        for seed in range(30)
    ]
    baseline = {
        "scope": "model",
        "subject_id": "baseline",
        "sample_size": 30,
        "target_side_win_rate": 0.0,
        "seed_metrics": baseline_metrics,
    }
    candidate = {
        "scope": "model",
        "subject_id": "candidate",
        "sample_size": 30,
        "target_side_win_rate": 1.0,
        "seed_metrics": candidate_metrics,
        "summary": {
            "score_sample_size": 30,
            "role_score_stddev": 0.5,
            "role_score_standard_error": 0.1,
            "role_score_ci": {"low": 6.8, "high": 7.2, "level": 0.95},
            "valid_game_count": 30,
            "abnormal_game_count": 2,
        },
    }

    compared = _leaderboard_compare_row(candidate, baseline, scope="model", target_role=None)

    assert compared["paired_sample_size"] == 30
    assert compared["paired_wins"] == 30
    assert compared["paired_losses"] == 0
    assert compared["paired_win_rate"] == 1.0
    assert compared["paired_p_value"] < 0.05
    assert compared["significant"] is True
    assert compared["score_stddev"] == 0.5
    assert compared["valid_game_count"] == 30
    assert compared["abnormal_game_count"] == 2
