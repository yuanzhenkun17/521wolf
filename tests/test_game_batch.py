"""Tests for the shared concurrent game-batch runner."""

from __future__ import annotations

import asyncio

import pytest

from app.graphs.shared.nodes.game_batch import (
    BatchAbortedError,
    normalize_game_result,
    per_game_dir,
    run_game_batch,
    valid_completed_games,
    winner_counts,
)


def test_normalize_game_result_shape():
    rec = normalize_game_result(
        game_id="g1",
        seed=7,
        result={
            "winner": "villagers",
            "roles": {1: "seer"},
            "game_events": [{"day": 1}, {"day": 3}, "not-a-dict"],
            "decisions": [{"player_id": 1}],
        },
    )
    assert rec["game_id"] == "g1"
    assert rec["seed"] == 7
    assert rec["winner"] == "villagers"
    assert rec["days"] == 3  # max day, ignoring the non-dict event
    assert rec["error"] is None


def test_normalize_game_result_preserves_no_winner_terminal_metadata():
    rec = normalize_game_result(
        game_id="g_no_winner",
        seed=9,
        result={
            "winner": None,
            "outcome": "no_winner",
            "terminal_reason": "max_days_reached",
            "roles": {},
            "game_events": [{"day": 1}],
        },
    )

    assert rec["winner"] is None
    assert rec["outcome"] == "no_winner"
    assert rec["terminal_reason"] == "max_days_reached"
    assert rec["error"] is None


def test_normalize_game_result_preserves_benchmark_langfuse_metadata():
    metadata = {
        "source_run_id": "batch-a",
        "source_game_id": "batch-a_game_001",
        "evaluation_set_id": "eval-set-a",
        "seed_set_id": "seed-set-a",
        "benchmark_id": "bench-a",
        "benchmark_version": "v1",
        "benchmark_config_hash": "sha256:bench",
        "target_role": "seer",
        "target_version_id": "seer-v1",
        "model_id": "model-a",
        "model_config_hash": "sha256:model",
        "langfuse_trace_id": "trace-a",
        "langfuse_trace_url": "http://langfuse/traces/trace-a",
        "langfuse_dataset_name": "eval-set-a",
        "langfuse_dataset_item_id": "eval-set-a:seed-set-a:7",
        "langfuse_experiment_name": "experiment-a",
        "langfuse_run_name": "run-a",
        "langfuse_dataset_run_id": "dataset-run-a",
        "langfuse_dataset_run_item_id": "dataset-run-item-a",
        "langfuse_experiment_url": "http://langfuse/datasets/eval-set-a/runs/dataset-run-a",
    }

    rec = normalize_game_result(
        game_id="g_meta",
        seed=7,
        result={
            "winner": "villagers",
            "roles": {},
            "game_events": [{"day": 1}],
            **metadata,
        },
    )

    for key, value in metadata.items():
        assert rec[key] == value


def test_winner_counts_tallies_unknown():
    games = [
        {"winner": "villagers"},
        {"winner": "werewolves"},
        {"winner": None},
        {"winner": "error"},
        {"winner": "good"},
        {"winner": "villagers"},
    ]
    assert winner_counts(games) == {"villagers": 2, "werewolves": 1, "unknown": 3}


def test_valid_completed_games_requires_real_winning_side():
    games = [
        {"winner": "villagers", "error": None},
        {"winner": "werewolves", "error": None},
        {"winner": None, "error": None, "terminal_reason": "max_days_reached"},
        {"winner": "error", "error": "boom"},
        {"winner": "good", "error": None},
        {"winner": None, "error": "timeout"},
    ]

    assert valid_completed_games(games) == games[:2]


def test_per_game_dir():
    assert per_game_dir(None, "game", 0) is None
    assert per_game_dir("/runs/b1", "game", 0).endswith("game_001")
    assert per_game_dir("/runs/b1", "battle", 9).endswith("battle_010")


def test_run_game_batch_preserves_order_and_limits_concurrency():
    class Tracker:
        def __init__(self):
            self.inflight = 0
            self.peak = 0

        async def ainvoke(self, state):
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
            await asyncio.sleep(0.01)
            self.inflight -= 1
            return {"winner": "villagers", "roles": {}, "game_events": []}

    tr = Tracker()
    games = asyncio.run(
        run_game_batch(tr, 6, lambda i: {"game_id": f"g{i}", "seed": i}, concurrency=3, label="t")
    )
    assert [g["seed"] for g in games] == [0, 1, 2, 3, 4, 5]
    assert 1 < tr.peak <= 3


def test_run_game_batch_isolates_single_failure():
    class Flaky:
        async def ainvoke(self, state):
            if state["seed"] == 2:
                raise RuntimeError("one bad game")
            return {"winner": "villagers", "roles": {}, "game_events": []}

    games = asyncio.run(
        run_game_batch(Flaky(), 6, lambda i: {"game_id": f"g{i}", "seed": i}, concurrency=2, label="t")
    )
    assert len(games) == 6
    errored = [g for g in games if g.get("error")]
    assert len(errored) == 1
    assert errored[0]["seed"] == 2
    assert errored[0]["winner"] == "error"


def test_run_game_batch_isolates_build_state_failure():
    class NeverCalledForBadState:
        async def ainvoke(self, state):
            return {"winner": "villagers", "roles": {}, "game_events": []}

    def build_state(index: int):
        if index == 1:
            raise RuntimeError("bad config")
        return {"game_id": f"g{index}", "seed": index + 10}

    games = asyncio.run(
        run_game_batch(NeverCalledForBadState(), 4, build_state, concurrency=2, label="t")
    )

    assert len(games) == 4
    assert [g["game_id"] for g in games] == ["g0", "t_002", "g2", "g3"]
    errored = [g for g in games if g.get("error")]
    assert len(errored) == 1
    assert errored[0]["seed"] == 1
    assert errored[0]["error"] == "bad config"


def test_run_game_batch_fail_fast_on_consecutive_failures():
    class Boom:
        async def ainvoke(self, state):
            raise RuntimeError("systemic boom")

    with pytest.raises(BatchAbortedError) as exc:
        asyncio.run(
            run_game_batch(
                Boom(), 20, lambda i: {"game_id": f"g{i}", "seed": i},
                concurrency=1, label="t",
            )
        )
    assert "systemic boom" in str(exc.value)


def test_run_game_batch_fail_fast_disabled():
    class Boom:
        async def ainvoke(self, state):
            raise RuntimeError("boom")

    games = asyncio.run(
        run_game_batch(
            Boom(), 8, lambda i: {"game_id": f"g{i}", "seed": i},
            concurrency=2, label="t", fail_fast=False,
        )
    )
    assert len(games) == 8
    assert all(g.get("error") for g in games)


def test_run_game_batch_times_out_game_and_cleans_partial_rows():
    class FakePersistence:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConn:
        def __init__(self):
            self.calls = []
            self.commits = 0
            self.rollbacks = 0
            self.closed = False

        def execute(self, sql, params=()):
            self.calls.append((sql, tuple(params)))

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            self.closed = True

    class FakeProvider:
        def __init__(self, conn):
            self.conn = conn

        def open_wolf_connection(self):
            return self.conn

    class SlowGame:
        async def ainvoke(self, state):
            state["game_persistence"] = persistence
            await asyncio.Event().wait()

    persistence = FakePersistence()
    conn = FakeConn()
    provider = FakeProvider(conn)

    games = asyncio.run(
        run_game_batch(
            SlowGame(),
            1,
            lambda i: {
                "game_id": "g_timeout",
                "seed": 7,
                "batch_game_timeout": 0.01,
                "storage_provider": provider,
            },
            concurrency=1,
            label="t",
            fail_fast=False,
        )
    )

    assert games[0]["game_id"] == "g_timeout"
    assert games[0]["winner"] == "error"
    assert games[0]["error"] == "game timed out after 0.01s"
    assert persistence.closed is True
    assert conn.commits == 1
    assert conn.closed is True
    deleted_tables = [sql.split()[2] for sql, _ in conn.calls]
    assert "decisions" in deleted_tables
    assert "game_events" in deleted_tables
    assert "games" in deleted_tables
    assert all(params == ("g_timeout",) for _, params in conn.calls)


def test_run_game_batch_empty():
    class Never:
        async def ainvoke(self, state):
            raise AssertionError("should not be called")

    assert asyncio.run(run_game_batch(Never(), 0, lambda i: {}, label="t")) == []


def test_game_loop_node_records_timeout_and_returns_failed_state():
    from app.graphs.subgraphs.game.nodes import game_loop_node

    class SlowEngine:
        def __init__(self):
            self.records = []

        async def run_until_finished(self):
            await asyncio.Event().wait()

        def _record(self, event_type, **kwargs):
            self.records.append({"event_type": event_type, **kwargs})

    engine = SlowEngine()

    result = asyncio.run(game_loop_node({"engine": engine, "game_timeout": 0.01}))

    assert result["finished"] is True
    assert result["winner"] == "timeout"
    assert result["outcome"] == "timeout"
    assert result["terminal_reason"] == "game_timeout"
    assert "0.01" in result["error"]
    assert engine.records[0]["event_type"] == "game_timeout"
    assert engine.records[0]["payload"] == {"timeout_s": 0.01}


def test_runner_action_timeout_uses_llm_timeout_env(monkeypatch):
    from app.graphs.subgraphs.game.nodes import _runner_action_timeout

    monkeypatch.setenv("WEREWOLF_LLM_TIMEOUT", "7")
    monkeypatch.setenv("WEREWOLF_LLM_RUNTIME_TIMEOUT", "8")

    assert _runner_action_timeout({}) == 7.0
    assert _runner_action_timeout({"runner_action_timeout": 3}) == 3.0
    assert _runner_action_timeout({"config": {"runner_action_timeout": 4}}) == 4.0


def test_runner_max_retries_default_is_single_attempt(monkeypatch):
    from app.graphs.subgraphs.game.nodes import _runner_max_retries

    monkeypatch.delenv("WEREWOLF_RUNNER_MAX_RETRIES", raising=False)

    assert _runner_max_retries({}) == 1
    assert _runner_max_retries({"runner_max_retries": 3}) == 3
    assert _runner_max_retries({"config": {"runner_max_retries": 2}}) == 2


def test_game_persist_node_uses_persistence_without_artifacts(tmp_path):
    from app.graphs.subgraphs.game.nodes import persist_node

    class FakePersistence:
        def __init__(self):
            self.saved = None

        def save_game_result(self, **kwargs):
            self.saved = kwargs

    game_dir = tmp_path / "runs" / "game_001"
    persistence = FakePersistence()
    state = {
        "game_id": "game_001",
        "game_dir": str(game_dir),
        "persistence": persistence,
        "seed": 7,
        "max_days": 4,
        "roles": {1: "seer"},
        "winner": "villagers",
        "finished": True,
        "game_events": [{"day": 1, "event_type": "start"}],
        "decisions": [{"player_id": 1, "action_type": "vote"}],
        "started_at": "2026-06-07T00:00:00+08:00",
    }

    out = asyncio.run(persist_node(state))

    assert not game_dir.exists()
    assert persistence.saved is not None
    assert persistence.saved["seed"] == 7
    assert persistence.saved["player_roles"] == {1: "seer"}
    assert persistence.saved["winner"] == "villagers"
    assert persistence.saved["final_state"]["status"] == "completed"
    assert out["finished_at"]


def test_game_persist_node_without_persistence_does_not_create_artifacts(tmp_path):
    from app.graphs.subgraphs.game.nodes import persist_node

    game_dir = tmp_path / "runs" / "game_no_pg"

    out = asyncio.run(
        persist_node({
            "game_id": "game_no_pg",
            "game_dir": str(game_dir),
            "seed": 1,
            "roles": {},
            "finished": True,
            "game_events": [{"day": 1}],
            "decisions": [],
        })
    )

    assert not game_dir.exists()
    assert out["finished_at"]
