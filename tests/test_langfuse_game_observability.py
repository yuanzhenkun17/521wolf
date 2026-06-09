"""Focused game Langfuse observability contracts."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

from app.graphs.subgraphs.game import nodes as game_nodes


class _RecordingContext:
    id = "obs-game-123"

    def __init__(self, captured: list[dict[str, Any]], kwargs: dict[str, Any]) -> None:
        self._captured = captured
        self._kwargs = kwargs

    def __enter__(self) -> "_RecordingContext":
        self._captured.append({"name": "context_enter", "kwargs": self._kwargs})
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self._captured.append({"name": "context_exit", "kwargs": self._kwargs})
        return False


class _Winner:
    value = "villagers"


class _Engine:
    async def run_until_finished(self) -> _Winner:
        return _Winner()


def _install_fake_observability(monkeypatch, *, fail_link: bool = False) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    fake = types.ModuleType("app.services.observability")

    def create_trace_id(*, seed: str | None = None) -> str:
        captured.append({"name": "create_trace_id", "seed": seed})
        return f"trace-{seed}"

    def langfuse_context(**kwargs: Any) -> _RecordingContext:
        captured.append({"name": "langfuse_context", "kwargs": kwargs})
        return _RecordingContext(captured, kwargs)

    def link_langfuse_dataset_run_item(**kwargs: Any) -> Any:
        captured.append({"name": "link_langfuse_dataset_run_item", "kwargs": kwargs})
        if fail_link:
            raise RuntimeError("dataset link down")
        return types.SimpleNamespace(
            trace_id=kwargs["trace_id"],
            trace_url=f"https://langfuse.local/traces/{kwargs['trace_id']}",
            dataset_name=kwargs["dataset_name"],
            dataset_item_id=kwargs["dataset_item_id"],
            dataset_run_id="dataset-run-123",
            dataset_run_item_id="dataset-run-item-123",
            experiment_name=kwargs["experiment_name"],
            run_name=kwargs["run_name"],
            experiment_url="https://langfuse.local/datasets/dataset-123/runs/dataset-run-123",
        )

    def update_observation(observation: Any, *, metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        captured.append({
            "name": "update_observation",
            "observation_id": getattr(observation, "id", None),
            "metadata": metadata,
            "kwargs": kwargs,
        })

    def score_current_trace(
        name: str,
        value: Any,
        *,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        captured.append({
            "name": "score_current_trace",
            "score_name": name,
            "value": value,
            "data_type": data_type,
            "comment": comment,
            "metadata": metadata,
        })

    fake.create_trace_id = create_trace_id
    fake.langfuse_context = langfuse_context
    fake.link_langfuse_dataset_run_item = link_langfuse_dataset_run_item
    fake.update_observation = update_observation
    fake.score_current_trace = score_current_trace
    fake.flush_langfuse = lambda: captured.append({"name": "flush_langfuse"})
    monkeypatch.setitem(sys.modules, "app.services.observability", fake)
    return captured


def _benchmark_game_state() -> dict[str, Any]:
    return {
        "engine": _Engine(),
        "game_id": "bench_game_001",
        "batch_id": "bench_langfuse",
        "source_run_id": "bench_langfuse",
        "seed": 270600,
        "storage_run_type": "evaluation_batch",
        "evaluation_set_id": "role-baseline-v1@v1",
        "seed_set_id": "role-baseline-quick-202606",
        "benchmark_id": "role-baseline-v1",
        "benchmark_version": "v1",
        "benchmark_config_hash": "sha256:benchmark",
        "model_id": "model-a",
        "model_config_hash": "sha256:model-a",
        "target_role": "seer",
        "target_version_id": "seer_v2",
        "target_type": "role_version",
        "langfuse_dataset_name": "role-baseline-v1@v1",
        "langfuse_experiment_name": "seer-canary",
        "langfuse_run_name": "bench_langfuse:seer",
        "decisions": [],
        "events": [],
        "game_events": [],
    }


def test_game_loop_links_langfuse_dataset_run_item_and_outputs_fields(monkeypatch):
    captured = _install_fake_observability(monkeypatch)

    out = asyncio.run(game_nodes.game_loop_node(_benchmark_game_state()))

    dataset_item_id = "role-baseline-v1@v1:role-baseline-quick-202606:270600"
    assert out["winner"] == "villagers"
    assert out["langfuse_trace_id"] == "trace-bench_game_001"
    assert out["langfuse_trace_url"] == "https://langfuse.local/traces/trace-bench_game_001"
    assert out["langfuse_experiment_url"] == (
        "https://langfuse.local/datasets/dataset-123/runs/dataset-run-123"
    )
    assert out["langfuse_dataset_name"] == "role-baseline-v1@v1"
    assert out["langfuse_dataset_item_id"] == dataset_item_id
    assert out["langfuse_experiment_name"] == "seer-canary"
    assert out["langfuse_run_name"] == "bench_langfuse:seer"
    assert out["langfuse_dataset_run_id"] == "dataset-run-123"
    assert out["langfuse_dataset_run_item_id"] == "dataset-run-item-123"

    link_call = next(call for call in captured if call["name"] == "link_langfuse_dataset_run_item")
    assert link_call["kwargs"]["dataset_name"] == "role-baseline-v1@v1"
    assert link_call["kwargs"]["dataset_item_id"] == dataset_item_id
    assert link_call["kwargs"]["experiment_name"] == "seer-canary"
    assert link_call["kwargs"]["run_name"] == "bench_langfuse:seer"
    assert link_call["kwargs"]["trace_id"] == "trace-bench_game_001"
    assert link_call["kwargs"]["observation_id"] == "obs-game-123"
    assert link_call["kwargs"]["metadata"]["benchmark_id"] == "role-baseline-v1"
    assert link_call["kwargs"]["metadata"]["langfuse_dataset_item_id"] == dataset_item_id

    update_call = next(call for call in captured if call["name"] == "update_observation")
    assert update_call["metadata"]["langfuse_dataset_run_id"] == "dataset-run-123"
    assert update_call["metadata"]["langfuse_dataset_run_item_id"] == "dataset-run-item-123"
    assert update_call["metadata"]["langfuse_trace_url"] == "https://langfuse.local/traces/trace-bench_game_001"
    assert update_call["metadata"]["langfuse_experiment_url"] == (
        "https://langfuse.local/datasets/dataset-123/runs/dataset-run-123"
    )

    score_calls = [call for call in captured if call["name"] == "score_current_trace"]
    winner_score = next(call for call in score_calls if call["score_name"] == "winner")
    assert winner_score["metadata"]["benchmark_id"] == "role-baseline-v1"
    assert winner_score["metadata"]["langfuse_dataset_run_id"] == "dataset-run-123"
    assert winner_score["metadata"]["langfuse_dataset_run_item_id"] == "dataset-run-item-123"
    assert winner_score["metadata"]["langfuse_experiment_url"] == (
        "https://langfuse.local/datasets/dataset-123/runs/dataset-run-123"
    )
    assert captured[-1]["name"] == "flush_langfuse"


def test_game_loop_langfuse_dataset_link_failure_is_best_effort(monkeypatch):
    captured = _install_fake_observability(monkeypatch, fail_link=True)

    out = asyncio.run(game_nodes.game_loop_node(_benchmark_game_state()))

    assert out["winner"] == "villagers"
    assert out["finished"] is True
    assert out["langfuse_trace_id"] == "trace-bench_game_001"
    assert "langfuse_dataset_run_id" not in out
    assert any(call["name"] == "link_langfuse_dataset_run_item" for call in captured)
    assert any(call["name"] == "score_current_trace" for call in captured)
