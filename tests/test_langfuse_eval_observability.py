"""Eval batch Langfuse observability contracts.

These tests use a fake observability module and fake persistence hooks. They
must not construct a real Langfuse client or touch the network.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

from app.graphs.subgraphs.eval import nodes as eval_nodes


class _FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _RecordingContext:
    def __init__(self, captured: list[dict[str, Any]], kwargs: dict[str, Any]) -> None:
        self._captured = captured
        self._kwargs = kwargs

    def __enter__(self) -> "_RecordingContext":
        self._captured.append({"name": "context_enter", "kwargs": self._kwargs})
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self._captured.append({"name": "context_exit", "kwargs": self._kwargs})
        return False


def _install_fake_observability(monkeypatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    fake = types.ModuleType("app.services.observability")

    def create_trace_id(*, seed: str | None = None) -> str:
        captured.append({"name": "create_trace_id", "seed": seed})
        return f"trace-{seed or 'eval'}"

    def langfuse_context(**kwargs: Any) -> _RecordingContext:
        captured.append({"name": "langfuse_context", "kwargs": kwargs})
        return _RecordingContext(captured, kwargs)

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

    def score_dataset_run(
        dataset_run_id: str,
        name: str,
        value: Any,
        *,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        captured.append({
            "name": "score_dataset_run",
            "dataset_run_id": dataset_run_id,
            "score_name": name,
            "value": value,
            "data_type": data_type,
            "comment": comment,
            "metadata": metadata,
        })

    def flush_langfuse() -> None:
        captured.append({"name": "flush_langfuse"})

    fake.create_trace_id = create_trace_id
    fake.langfuse_context = langfuse_context
    fake.score_current_trace = score_current_trace
    fake.score_dataset_run = score_dataset_run
    fake.flush_langfuse = flush_langfuse
    monkeypatch.setitem(sys.modules, "app.services.observability", fake)
    return captured


def _patch_eval_persistence(monkeypatch) -> _FakeConn:
    import app.lib.score as score_lib

    conn = _FakeConn()
    monkeypatch.setattr(score_lib, "open_eval_connection", lambda paths: conn)
    monkeypatch.setattr(score_lib, "save_evaluation_batch", lambda conn_arg, batch: None)
    monkeypatch.setattr(score_lib, "persist_leaderboard_entry", lambda conn_arg, entry: None)
    return conn


def _score_summary() -> dict[str, Any]:
    return {
        "avg_role_score": 6.2,
        "strength_score": 6.3,
        "fallback_rate": 0.1,
        "llm_error_rate": 0.2,
        "policy_adjusted_rate": 0.3,
        "decision_quality": {
            "fallback_rate": 0.1,
            "llm_error_rate": 0.2,
            "policy_adjusted_rate": 0.3,
        },
        "decision_judge_aggregate": {
            "avg_score": 8.75,
            "bad_rate": 0.25,
        },
    }


def test_persist_batch_node_writes_eval_langfuse_scores(monkeypatch):
    captured = _install_fake_observability(monkeypatch)
    conn = _patch_eval_persistence(monkeypatch)

    state = {
        "batch_id": "eval_obs_1",
        "batch_config": {
            "game_count": 2,
            "mode": "dev",
            "target_role": "seer",
            "target_version_id": "seer_v1",
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "langfuse_dataset_name": "dataset-a",
            "langfuse_dataset_item_id": "role-baseline-v1@v1:role-baseline-quick-202606:270600",
            "langfuse_experiment_name": "experiment-a",
            "langfuse_run_name": "run-a",
        },
        "games": [
            {"winner": "villagers", "error": None},
            {"winner": "werewolves", "error": None},
        ],
        "score_summary": _score_summary(),
        "rankable": True,
        "rankable_reason": "ok",
        "valid_game_rate": 1.0,
        "warnings": [],
        "diagnostics": [],
    }

    out = asyncio.run(eval_nodes.persist_batch_node(state))

    assert conn.closed is True
    assert out["result"]["batch_id"] == "eval_obs_1"
    assert out["langfuse_trace_id"] == "trace-eval_obs_1"
    assert {"name": "create_trace_id", "seed": "eval_obs_1"} in captured

    context_calls = [call for call in captured if call["name"] == "langfuse_context"]
    assert context_calls
    context = context_calls[-1]["kwargs"]
    assert context["trace_name"] == "eval.batch"
    assert context["trace_id"] == "trace-eval_obs_1"
    assert context["session_id"] == "eval_obs_1"
    assert context["metadata"]["stage"] == "persist_batch"
    assert context["metadata"]["batch_id"] == "eval_obs_1"
    assert context["metadata"]["target_role"] == "seer"
    assert context["metadata"]["evaluation_set_id"] == "role-baseline-v1@v1"
    assert context["metadata"]["seed_set_id"] == "role-baseline-quick-202606"
    assert context["metadata"]["langfuse_dataset_name"] == "dataset-a"
    assert context["metadata"]["langfuse_dataset_item_id"] == (
        "role-baseline-v1@v1:role-baseline-quick-202606:270600"
    )
    assert context["metadata"]["langfuse_experiment_name"] == "experiment-a"
    assert context["metadata"]["experiment_name"] == "experiment-a"
    assert context["metadata"]["langfuse_run_name"] == "run-a"
    assert context["metadata"]["run_name"] == "run-a"
    assert {"werewolf", "eval", "dev", "role:seer", "rankable"}.issubset(set(context["tags"]))

    score_calls = [call for call in captured if call["name"] == "score_current_trace"]
    by_name = {call["score_name"]: call for call in score_calls}
    expected_values = {
        "eval.avg_role_score": 6.2,
        "eval.strength_score": 6.3,
        "eval.valid_game_rate": 1.0,
        "eval.fallback_rate": 0.1,
        "eval.llm_error_rate": 0.2,
        "eval.policy_adjusted_rate": 0.3,
        "eval.villagers_win_rate": 0.5,
        "eval.werewolves_win_rate": 0.5,
        "eval.decision_judge_avg_score": 8.75,
        "eval.decision_judge_bad_rate": 0.25,
    }
    for name, value in expected_values.items():
        assert by_name[name]["value"] == value
        assert by_name[name]["data_type"] == "NUMERIC"
        assert by_name[name]["metadata"]["metric_family"] == "eval"
        assert by_name[name]["metadata"]["batch_id"] == "eval_obs_1"
        assert by_name[name]["metadata"]["evaluation_set_id"] == "role-baseline-v1@v1"
        assert by_name[name]["metadata"]["seed_set_id"] == "role-baseline-quick-202606"
        assert by_name[name]["metadata"]["langfuse_dataset_name"] == "dataset-a"
        assert by_name[name]["metadata"]["langfuse_dataset_item_id"] == (
            "role-baseline-v1@v1:role-baseline-quick-202606:270600"
        )
        assert by_name[name]["metadata"]["langfuse_experiment_name"] == "experiment-a"
        assert by_name[name]["metadata"]["experiment_name"] == "experiment-a"
        assert by_name[name]["metadata"]["langfuse_run_name"] == "run-a"
        assert by_name[name]["metadata"]["run_name"] == "run-a"

    assert by_name["eval.rankable"]["value"] is True
    assert by_name["eval.rankable"]["data_type"] == "BOOLEAN"
    assert by_name["eval.rankable"]["metadata"]["rankable_reason"] == "ok"
    assert by_name["eval.data_sufficient"]["value"] is True
    assert by_name["eval.data_sufficient"]["data_type"] == "BOOLEAN"
    assert by_name["eval.low_error_rate"]["value"] is True
    assert by_name["eval.low_error_rate"]["data_type"] == "BOOLEAN"
    assert by_name["eval.leaderboard_accepted"]["value"] is True
    assert by_name["eval.leaderboard_accepted"]["data_type"] == "BOOLEAN"
    assert by_name["eval.leaderboard_accepted"]["metadata"]["leaderboard_gate_reason"] == "ok"
    assert captured[-1]["name"] == "flush_langfuse"


def test_run_games_node_creates_eval_batch_langfuse_context(monkeypatch):
    captured = _install_fake_observability(monkeypatch)
    monkeypatch.setattr(eval_nodes, "_score_game", lambda game: [])

    class _GameSubgraph:
        def __init__(self) -> None:
            self.invocations: list[dict[str, Any]] = []

        async def ainvoke(self, game_state: dict[str, Any]) -> dict[str, Any]:
            self.invocations.append(dict(game_state))
            return {
                "winner": "villagers",
                "roles": {"1": "seer"},
                "game_events": [{"day": 1}],
                "decisions": [],
            }

    game_subgraph = _GameSubgraph()
    state = {
        "batch_id": "eval_run_obs",
        "batch_config": {
            "game_count": 1,
            "max_days": 3,
            "mode": "dev",
            "model_id": "model-a",
        },
        "game_subgraph": game_subgraph,
        "warnings": [],
        "diagnostics": [],
    }

    out = asyncio.run(eval_nodes.run_games_node(state))

    assert out["langfuse_trace_id"] == "trace-eval_run_obs"
    assert len(out["games"]) == 1
    assert game_subgraph.invocations[0]["source_run_id"] == "eval_run_obs"

    context_calls = [call for call in captured if call["name"] == "langfuse_context"]
    assert context_calls
    context = context_calls[0]["kwargs"]
    assert context["trace_name"] == "eval.batch"
    assert context["trace_id"] == "trace-eval_run_obs"
    assert context["session_id"] == "eval_run_obs"
    assert context["metadata"]["stage"] == "run_games"
    assert context["metadata"]["batch_id"] == "eval_run_obs"
    assert context["metadata"]["model_id"] == "model-a"
    assert context["input"] == {
        "batch_id": "eval_run_obs",
        "game_count": 1,
        "max_days": 3,
        "seed_start": 0,
        "seed_count": 1,
        "seed_preview": [],
    }


def test_run_games_node_links_langfuse_dataset_metadata_to_games(monkeypatch):
    captured = _install_fake_observability(monkeypatch)
    monkeypatch.setattr(eval_nodes, "_score_game", lambda game: [])

    class _GameSubgraph:
        def __init__(self) -> None:
            self.invocations: list[dict[str, Any]] = []

        async def ainvoke(self, game_state: dict[str, Any]) -> dict[str, Any]:
            self.invocations.append(dict(game_state))
            return {
                "winner": "villagers",
                "roles": {"1": "seer"},
                "game_events": [{"day": 1}],
                "decisions": [],
            }

    game_subgraph = _GameSubgraph()
    state = {
        "batch_id": "eval_dataset_obs",
        "batch_config": {
            "game_count": 1,
            "max_days": 3,
            "mode": "dev",
            "model_id": "model-a",
            "model_config_hash": "sha256:model-a",
            "target_role": "seer",
            "target_version_id": "seer_v2",
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "seeds": [270600],
            "langfuse_dataset_name": "role-baseline-v1@v1",
            "langfuse_experiment_name": "seer-canary",
            "langfuse_run_name": "eval_dataset_obs:seer",
        },
        "game_subgraph": game_subgraph,
        "warnings": [],
        "diagnostics": [],
    }

    out = asyncio.run(eval_nodes.run_games_node(state))

    assert out["langfuse_trace_id"] == "trace-eval_dataset_obs"
    invocation = game_subgraph.invocations[0]
    assert invocation["batch_id"] == "eval_dataset_obs"
    assert invocation["source_run_id"] == "eval_dataset_obs"
    assert invocation["evaluation_set_id"] == "role-baseline-v1@v1"
    assert invocation["seed_set_id"] == "role-baseline-quick-202606"
    assert invocation["langfuse_dataset_name"] == "role-baseline-v1@v1"
    assert invocation["langfuse_dataset_item_id"] == (
        "role-baseline-v1@v1:role-baseline-quick-202606:270600"
    )
    assert invocation["langfuse_experiment_name"] == "seer-canary"
    assert invocation["experiment_name"] == "seer-canary"
    assert invocation["langfuse_run_name"] == "eval_dataset_obs:seer"
    assert invocation["run_name"] == "eval_dataset_obs:seer"

    context = next(call["kwargs"] for call in captured if call["name"] == "langfuse_context")
    assert context["metadata"]["batch_id"] == "eval_dataset_obs"
    assert context["metadata"]["evaluation_set_id"] == "role-baseline-v1@v1"
    assert context["metadata"]["seed_set_id"] == "role-baseline-quick-202606"
    assert context["metadata"]["langfuse_dataset_name"] == "role-baseline-v1@v1"
    assert context["metadata"]["langfuse_dataset_item_id"] == (
        "role-baseline-v1@v1:role-baseline-quick-202606:270600"
    )
    assert context["metadata"]["langfuse_experiment_name"] == "seer-canary"
    assert context["metadata"]["experiment_name"] == "seer-canary"
    assert context["metadata"]["langfuse_run_name"] == "eval_dataset_obs:seer"
    assert context["metadata"]["run_name"] == "eval_dataset_obs:seer"


def test_run_games_node_sets_langfuse_dataset_item_id_for_each_seed(monkeypatch):
    _install_fake_observability(monkeypatch)
    monkeypatch.setattr(eval_nodes, "_score_game", lambda game: [])

    class _GameSubgraph:
        def __init__(self) -> None:
            self.invocations: list[dict[str, Any]] = []

        async def ainvoke(self, game_state: dict[str, Any]) -> dict[str, Any]:
            self.invocations.append(dict(game_state))
            return {
                "winner": "villagers",
                "roles": {"1": "seer"},
                "game_events": [{"day": 1}],
                "decisions": [],
            }

    game_subgraph = _GameSubgraph()
    state = {
        "batch_id": "eval_dataset_items",
        "batch_config": {
            "game_count": 2,
            "max_days": 3,
            "evaluation_set_id": "eval-set-a",
            "seed_set_id": "seed-set-a",
            "seeds": [101, 202],
        },
        "game_subgraph": game_subgraph,
        "warnings": [],
        "diagnostics": [],
    }

    out = asyncio.run(eval_nodes.run_games_node(state))

    assert len(out["games"]) == 2
    assert [item["langfuse_dataset_item_id"] for item in game_subgraph.invocations] == [
        "eval-set-a:seed-set-a:101",
        "eval-set-a:seed-set-a:202",
    ]


def test_persist_batch_node_scores_langfuse_dataset_run(monkeypatch):
    captured = _install_fake_observability(monkeypatch)
    _patch_eval_persistence(monkeypatch)

    state = {
        "batch_id": "eval_dataset_run_score",
        "batch_config": {
            "game_count": 2,
            "mode": "dev",
            "evaluation_set_id": "eval-set-a",
            "seed_set_id": "seed-set-a",
            "langfuse_dataset_name": "eval-set-a",
            "langfuse_experiment_name": "experiment-a",
            "langfuse_run_name": "run-a",
        },
        "games": [
            {"winner": "villagers", "error": None, "langfuse_dataset_run_id": "dataset-run-1"},
            {"winner": "werewolves", "error": None, "langfuse_dataset_run_id": "dataset-run-1"},
        ],
        "score_summary": _score_summary(),
        "rankable": True,
        "rankable_reason": "ok",
        "valid_game_rate": 1.0,
        "warnings": [],
        "diagnostics": [],
    }

    out = asyncio.run(eval_nodes.persist_batch_node(state))

    assert out["result"]["batch_id"] == "eval_dataset_run_score"
    dataset_scores = [call for call in captured if call["name"] == "score_dataset_run"]
    by_name = {call["score_name"]: call for call in dataset_scores}
    assert by_name["eval.avg_role_score"]["dataset_run_id"] == "dataset-run-1"
    assert by_name["eval.avg_role_score"]["value"] == 6.2
    assert by_name["eval.avg_role_score"]["data_type"] == "NUMERIC"
    assert by_name["eval.avg_role_score"]["metadata"]["batch_id"] == "eval_dataset_run_score"
    assert by_name["eval.avg_role_score"]["metadata"]["langfuse_dataset_run_id"] == "dataset-run-1"
    assert by_name["eval.rankable"]["value"] is True
    assert by_name["eval.rankable"]["data_type"] == "BOOLEAN"


def test_eval_langfuse_observability_is_best_effort(monkeypatch):
    _patch_eval_persistence(monkeypatch)
    fake = types.ModuleType("app.services.observability")

    class _FailingContext:
        def __enter__(self) -> Any:
            raise RuntimeError("context unavailable")

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            raise RuntimeError("context exit unavailable")

    def create_trace_id(*, seed: str | None = None) -> str:
        raise RuntimeError("trace id unavailable")

    def langfuse_context(**kwargs: Any) -> _FailingContext:
        return _FailingContext()

    def score_current_trace(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("score unavailable")

    def flush_langfuse() -> None:
        raise RuntimeError("flush unavailable")

    fake.create_trace_id = create_trace_id
    fake.langfuse_context = langfuse_context
    fake.score_current_trace = score_current_trace
    fake.flush_langfuse = flush_langfuse
    monkeypatch.setitem(sys.modules, "app.services.observability", fake)

    state = {
        "batch_id": "eval_obs_failopen",
        "batch_config": {"game_count": 1, "mode": "dev"},
        "games": [{"winner": "villagers", "error": None}],
        "score_summary": _score_summary(),
        "rankable": True,
        "rankable_reason": "ok",
        "valid_game_rate": 1.0,
        "warnings": [],
        "diagnostics": [],
    }

    out = asyncio.run(eval_nodes.persist_batch_node(state))

    assert out["result"]["batch_id"] == "eval_obs_failopen"
    assert out["result"]["rankable"] is True
