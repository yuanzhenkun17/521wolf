"""Tests for the shared concurrent game-batch runner."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.graphs.shared.nodes.game_batch import (
    BatchAbortedError,
    normalize_game_result,
    per_game_dir,
    run_game_batch,
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


def test_winner_counts_tallies_unknown():
    games = [{"winner": "villagers"}, {"winner": "werewolves"}, {"winner": None}, {"winner": "villagers"}]
    assert winner_counts(games) == {"villagers": 2, "werewolves": 1, "unknown": 1}


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


def test_run_game_batch_empty():
    class Never:
        async def ainvoke(self, state):
            raise AssertionError("should not be called")

    assert asyncio.run(run_game_batch(Never(), 0, lambda i: {}, label="t")) == []


def test_game_persist_node_finalizes_new_artifact_dir_atomically(tmp_path):
    from app.graphs.subgraphs.game.nodes import persist_node

    game_dir = tmp_path / "runs" / "game_001"
    state = {
        "game_id": "game_001",
        "game_dir": str(game_dir),
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

    assert game_dir.exists()
    assert (game_dir / "meta.json").exists()
    assert (game_dir / "game_events.jsonl").read_text(encoding="utf-8").strip()
    assert (game_dir / "agent_decisions.jsonl").read_text(encoding="utf-8").strip()
    manifest = json.loads((game_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["run_type"] == "game"
    assert manifest["game_id"] == "game_001"
    assert manifest["seed"] == 7
    assert manifest["status"] == "completed"
    assert manifest["paths"]["game_dir"] == str(game_dir)
    assert out["manifest"] == manifest
    assert not list(game_dir.parent.glob(".game_001.*.tmp"))


def test_game_persist_node_failure_does_not_expose_final_dir(tmp_path, monkeypatch):
    from app.graphs.subgraphs.game.nodes import persist_node
    from app.util import json as json_util

    game_dir = tmp_path / "runs" / "game_broken"

    def fail_write_json(path, data):
        raise OSError("disk full")

    monkeypatch.setattr(json_util, "write_json", fail_write_json)

    with pytest.raises(OSError, match="disk full"):
        asyncio.run(
            persist_node({
                "game_id": "game_broken",
                "game_dir": str(game_dir),
                "seed": 1,
                "roles": {},
                "finished": True,
                "game_events": [{"day": 1}],
                "decisions": [],
            })
        )

    assert not game_dir.exists()
    assert not list(game_dir.parent.glob(".game_broken.*.tmp"))
