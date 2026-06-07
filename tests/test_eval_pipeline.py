"""Tests for the upgraded batch-evaluation pipeline.

Covers the three behaviors wired beyond the basic scoring path:
1. role-version resolution → role_skill_dirs (only evaluated role uses the version)
2. cross-batch comparison-group fairness
3. batch + leaderboard persistence to wolf.db
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

from app.config import PathConfig
from app.graphs.subgraphs.eval.nodes import (
    _resolve_role_version_dirs,
    fairness_node,
    persist_batch_node,
    run_games_node,
)


SEER_SKILL = """---
name: seer_vote
role: seer
applicable_actions:
  - vote
status: active
evolution:
  enabled: true
  allowed_actions:
    - append_rule
---

# Seer
Vote suspicious players.
"""


class FakeGameSubgraph:
    def __init__(self):
        self.invocations: list[dict] = []

    async def ainvoke(self, game_state: dict):
        self.invocations.append(dict(game_state))
        return {
            "winner": "villagers",
            "roles": {"1": "seer", "2": "werewolf"},
            "game_events": [{"day": 2}],
            "decisions": [
                {"player_id": 1, "action_type": "vote", "selected_target": 2, "source": "llm", "confidence": 0.9},
            ],
        }


# ---------------------------------------------------------------------------
# role-version resolution
# ---------------------------------------------------------------------------

def test_resolve_role_version_dirs_from_registry(tmp_path):
    from app.lib.version import VersionRegistry

    reg = VersionRegistry(tmp_path / "registry")
    vid = reg.publish_skills("seer", {"vote.md": SEER_SKILL}, source="test")

    class _Paths:
        registry_dir = tmp_path / "registry"

    dirs = _resolve_role_version_dirs({"target_role": "seer", "target_version_id": vid}, _Paths())
    assert "seer" in dirs
    from pathlib import Path

    assert (Path(dirs["seer"]) / "vote.md").exists()


def test_resolve_role_version_dirs_empty_when_unspecified(tmp_path):
    class _Paths:
        registry_dir = tmp_path / "registry"

    assert _resolve_role_version_dirs({"game_count": 5}, _Paths()) == {}


def test_resolve_role_version_dirs_keeps_partial_success_and_warns(tmp_path):
    from pathlib import Path

    from app.lib.version import VersionRegistry

    reg = VersionRegistry(tmp_path / "registry")
    vid = reg.publish_skills("seer", {"vote.md": SEER_SKILL}, source="test")

    class _Paths:
        registry_dir = tmp_path / "registry"

    warnings: list[str] = []
    diagnostics: list[dict] = []
    dirs = _resolve_role_version_dirs(
        {"role_version_config": {"seer": vid, "witch": "missing_v1"}},
        _Paths(),
        warnings=warnings,
        diagnostics=diagnostics,
    )

    assert set(dirs) == {"seer"}
    assert (Path(dirs["seer"]) / "vote.md").exists()
    assert len(warnings) == 1
    assert "failed to resolve role version witch/missing_v1" in warnings[0]
    assert diagnostics == [
        {
            "kind": "role_version_error",
            "stage": "role_version.resolve",
            "level": "warning",
            "message": warnings[0],
            "exception_type": "FileNotFoundError",
            "exception_message": "Version witch/missing_v1 not found",
        }
    ]


def test_run_games_node_isolates_evaluated_role(tmp_path):
    from app.lib.version import VersionRegistry

    paths = PathConfig(root=tmp_path)
    reg = VersionRegistry(paths.registry_dir)
    vid = reg.publish_skills("seer", {"vote.md": SEER_SKILL}, source="test")
    game = FakeGameSubgraph()
    state = {
        "batch_id": "b1",
        "batch_config": {
            "game_count": 2,
            "max_days": 4,
            "skill_dir": str(tmp_path / "baseline"),
            "target_role": "seer",
            "target_version_id": vid,
        },
        "paths": paths,
        "game_subgraph": game,
    }
    out = asyncio.run(run_games_node(state))
    assert len(out["games"]) == 2
    # Every game pins the seer to the version dir; baseline stays as skill_dir.
    for inv in game.invocations:
        assert "seer" in inv["role_skill_dirs"]
        assert inv["skill_dir"] == str(tmp_path / "baseline")
    # Real scores were produced.
    assert len(out["player_scores"]) > 0


def test_missing_target_role_version_is_warning_and_unrankable(tmp_path):
    paths = PathConfig(root=tmp_path)
    game = FakeGameSubgraph()
    state = {
        "batch_id": "missing_version",
        "batch_config": {
            "game_count": 1,
            "max_days": 4,
            "skill_dir": str(tmp_path / "baseline"),
            "target_role": "seer",
            "target_version_id": "seer_missing",
            "mode": "dev",
        },
        "paths": paths,
        "game_subgraph": game,
    }

    out = asyncio.run(run_games_node(state))

    assert out["role_version_resolution_failed"] is True
    assert out["role_version_resolution_missing"] == {"seer": "seer_missing"}
    assert "role_skill_dirs" not in game.invocations[0]
    assert any("failed to resolve role version seer/seer_missing" in item for item in out["warnings"])
    assert out["diagnostics"][0]["kind"] == "role_version_error"
    assert out["diagnostics"][0]["stage"] == "role_version.resolve"
    assert out["diagnostics"][0]["level"] == "warning"
    assert out["diagnostics"][0]["exception_type"] == "FileNotFoundError"

    out = asyncio.run(fairness_node(out))
    assert out["rankable"] is False
    assert out["rankable_reason"] == "role version resolution failed"


# ---------------------------------------------------------------------------
# cross-batch fairness
# ---------------------------------------------------------------------------

def test_fairness_standalone_is_fair(tmp_path):
    state = {
        "batch_id": "b1",
        "batch_config": {"game_count": 2, "mode": "dev"},
        "games": [{"error": None}, {"error": None}],
        "paths": PathConfig(root=tmp_path),
    }
    out = asyncio.run(fairness_node(state))
    assert out["fairness"]["is_fair"] is True
    assert out["fairness"]["reason"] == "standalone batch"
    assert out["rankable"] is True


def test_fairness_role_version_group_needs_sibling(tmp_path):
    paths = PathConfig(root=tmp_path)
    # Seed a sibling batch in the same group with a *different* (model, seed_set).
    from app.lib.score import open_eval_connection, save_evaluation_batch

    conn = open_eval_connection(paths)
    save_evaluation_batch(conn, {
        "batch_id": "sibling",
        "comparison_group_id": "grp1",
        "comparison_type": "role_version",
        "target_role": "seer",
        "model_id": "modelB",
        "seed_set_id": "seedsB",
        "game_count": 2,
    })
    conn.close()

    state = {
        "batch_id": "b_current",
        "batch_config": {
            "game_count": 2,
            "mode": "dev",
            "comparison_group_id": "grp1",
            "comparison_type": "role_version",
            "target_role": "seer",
            "model_id": "modelA",
            "seed_set_id": "seedsA",
        },
        "games": [{"error": None}, {"error": None}],
        "paths": paths,
    }
    out = asyncio.run(fairness_node(state))
    assert out["fairness"]["is_fair"] is True
    assert "seer" in out["fairness"]["reason"]


def test_fairness_group_fails_with_single_batch(tmp_path):
    state = {
        "batch_id": "lonely",
        "batch_config": {
            "game_count": 2,
            "mode": "dev",
            "comparison_group_id": "grp_empty",
            "comparison_type": "model",
            "model_id": "m1",
            "seed_set_id": "s1",
        },
        "games": [{"error": None}, {"error": None}],
        "paths": PathConfig(root=tmp_path),
    }
    out = asyncio.run(fairness_node(state))
    assert out["fairness"]["is_fair"] is False
    assert out["rankable"] is False


def test_fairness_group_storage_failure_becomes_warning(monkeypatch, tmp_path):
    import app.lib.score as score_lib

    def fail_open(paths):
        raise RuntimeError("db locked")

    monkeypatch.setattr(score_lib, "open_eval_connection", fail_open)

    state = {
        "batch_id": "locked",
        "batch_config": {
            "game_count": 2,
            "mode": "dev",
            "comparison_group_id": "grp_locked",
            "comparison_type": "model",
            "model_id": "m1",
            "seed_set_id": "s1",
        },
        "games": [{"error": None}, {"error": None}],
        "paths": PathConfig(root=tmp_path),
    }
    out = asyncio.run(fairness_node(state))

    assert out["fairness"]["is_fair"] is False
    assert out["fairness"]["reason"] == "fairness check failed: RuntimeError: db locked"
    assert out["rankable"] is False
    assert out["warnings"] == ["fairness check failed: RuntimeError: db locked"]
    assert out["diagnostics"] == [
        {
            "kind": "fairness_error",
            "stage": "fairness.compute",
            "level": "warning",
            "message": "fairness check failed: RuntimeError: db locked",
            "exception_type": "RuntimeError",
            "exception_message": "db locked",
        }
    ]


def test_fairness_group_query_failure_becomes_warning(monkeypatch, tmp_path):
    import app.lib.score as score_lib

    class FailingConn:
        closed = False

        def execute(self, *args, **kwargs):
            raise RuntimeError("query failed")

        def close(self):
            self.closed = True

    conn = FailingConn()
    monkeypatch.setattr(score_lib, "open_eval_connection", lambda paths: conn)

    state = {
        "batch_id": "query_failed",
        "batch_config": {
            "game_count": 2,
            "mode": "dev",
            "comparison_group_id": "grp_query_failed",
            "comparison_type": "model",
            "model_id": "m1",
            "seed_set_id": "s1",
        },
        "games": [{"error": None}, {"error": None}],
        "paths": PathConfig(root=tmp_path),
    }
    out = asyncio.run(fairness_node(state))

    assert conn.closed is True
    assert out["fairness"]["is_fair"] is False
    assert out["fairness"]["reason"] == "fairness check failed: RuntimeError: query failed"
    assert out["rankable"] is False
    assert out["warnings"] == ["fairness check failed: RuntimeError: query failed"]
    assert out["diagnostics"][0]["kind"] == "fairness_error"
    assert out["diagnostics"][0]["stage"] == "fairness.compute"
    assert out["diagnostics"][0]["exception_message"] == "query failed"


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def test_run_games_node_aborts_cleanly_on_systemic_failure(tmp_path):
    """A crashing game subgraph trips fail-fast; the node records it, no raise."""
    class Boom:
        async def ainvoke(self, state):
            raise RuntimeError("model down")

    state = {
        "batch_id": "ab",
        "batch_config": {"game_count": 20, "max_days": 4},
        "paths": PathConfig(root=tmp_path),
        "game_subgraph": Boom(),
    }
    out = asyncio.run(run_games_node(state))
    assert out["games"] == []
    assert out["player_scores"] == []
    assert any("aborted" in e for e in out.get("errors", []))


def test_best_effort_persistence_helpers_return_warnings():
    from app.lib.score import persist_leaderboard_entry, save_evaluation_batch

    class FailingConn:
        def execute(self, *args, **kwargs):
            raise RuntimeError("disk full")

        def commit(self):
            raise AssertionError("commit should not run after execute failure")

    batch_warning = save_evaluation_batch(FailingConn(), {"batch_id": "warn_batch"})
    leaderboard_warning = persist_leaderboard_entry(FailingConn(), {"batch_id": "warn_batch"})

    assert batch_warning is not None
    assert "save_evaluation_batch failed: RuntimeError: disk full" in batch_warning
    assert batch_warning.diagnostic == {
        "kind": "persistence_error",
        "stage": "persist_batch.save_evaluation_batch",
        "level": "warning",
        "message": "save_evaluation_batch failed: RuntimeError: disk full",
        "exception_type": "RuntimeError",
        "exception_message": "disk full",
    }
    assert leaderboard_warning is not None
    assert "persist_leaderboard_entry failed: RuntimeError: disk full" in leaderboard_warning
    assert leaderboard_warning.diagnostic == {
        "kind": "persistence_error",
        "stage": "persist_batch.persist_leaderboard_entry",
        "level": "warning",
        "message": "persist_leaderboard_entry failed: RuntimeError: disk full",
        "exception_type": "RuntimeError",
        "exception_message": "disk full",
    }


def test_persist_batch_node_exposes_persistence_warnings(monkeypatch, tmp_path):
    import app.lib.score as score_lib

    class DummyConn:
        closed = False

        def close(self):
            self.closed = True

    conn = DummyConn()

    def fake_open(paths):
        return conn

    def fake_save(conn_arg, batch):
        assert conn_arg is conn
        assert batch["batch_id"] == "warn1"
        return "save_evaluation_batch failed: RuntimeError: readonly db"

    def fake_leaderboard(conn_arg, entry):
        assert conn_arg is conn
        assert entry["batch_id"] == "warn1"
        return "persist_leaderboard_entry failed: RuntimeError: readonly db"

    monkeypatch.setattr(score_lib, "open_eval_connection", fake_open)
    monkeypatch.setattr(score_lib, "save_evaluation_batch", fake_save)
    monkeypatch.setattr(score_lib, "persist_leaderboard_entry", fake_leaderboard)

    state = {
        "batch_id": "warn1",
        "batch_config": {"game_count": 1, "mode": "dev"},
        "games": [{"error": None}],
        "score_summary": {"avg_role_score": 5.0},
        "warnings": ["preexisting warning"],
        "paths": PathConfig(root=tmp_path),
    }
    out = asyncio.run(persist_batch_node(state))

    assert conn.closed is True
    assert out["warnings"] == [
        "preexisting warning",
        "save_evaluation_batch failed: RuntimeError: readonly db",
        "persist_leaderboard_entry failed: RuntimeError: readonly db",
    ]
    assert out["result"]["warnings"] == out["warnings"]
    assert out["diagnostics"] == [
        {
            "kind": "persistence_error",
            "stage": "persist_batch.save_evaluation_batch",
            "level": "warning",
            "message": "save_evaluation_batch failed: RuntimeError: readonly db",
            "exception_type": "RuntimeError",
            "exception_message": "readonly db",
        },
        {
            "kind": "persistence_error",
            "stage": "persist_batch.persist_leaderboard_entry",
            "level": "warning",
            "message": "persist_leaderboard_entry failed: RuntimeError: readonly db",
            "exception_type": "RuntimeError",
            "exception_message": "readonly db",
        },
    ]
    assert out["result"]["diagnostics"] == out["diagnostics"]


def test_eval_graph_exposes_persistence_warnings_in_final_state(monkeypatch, tmp_path):
    import app.lib.score as score_lib
    from app.graphs.subgraphs.eval.builder import build_eval_graph

    class DummyConn:
        closed = False

        def close(self):
            self.closed = True

    conn = DummyConn()

    monkeypatch.setattr(score_lib, "open_eval_connection", lambda paths: conn)
    monkeypatch.setattr(
        score_lib,
        "save_evaluation_batch",
        lambda conn_arg, batch: "save_evaluation_batch failed: RuntimeError: readonly db",
    )
    monkeypatch.setattr(
        score_lib,
        "persist_leaderboard_entry",
        lambda conn_arg, entry: "persist_leaderboard_entry failed: RuntimeError: readonly db",
    )

    graph = build_eval_graph(game_subgraph=FakeGameSubgraph())
    out = asyncio.run(
        graph.ainvoke({
            "batch_config": {"batch_id": "graph_warn", "game_count": 1, "max_days": 4, "mode": "dev"},
            "paths": PathConfig(root=tmp_path),
        })
    )

    assert conn.closed is True
    assert out["warnings"] == [
        "save_evaluation_batch failed: RuntimeError: readonly db",
        "persist_leaderboard_entry failed: RuntimeError: readonly db",
    ]
    assert out["result"]["warnings"] == out["warnings"]
    assert [item["stage"] for item in out["diagnostics"]] == [
        "persist_batch.save_evaluation_batch",
        "persist_batch.persist_leaderboard_entry",
    ]
    assert out["result"]["diagnostics"] == out["diagnostics"]
    assert out["result"]["batch_id"] == "graph_warn"
    assert out["result"]["completed"] == 1


def test_persist_batch_node_writes_batch_and_leaderboard(tmp_path):
    paths = PathConfig(root=tmp_path)
    state = {
        "batch_id": "persist1",
        "batch_config": {
            "game_count": 2,
            "mode": "dev",
            "target_role": "seer",
            "target_version_id": "seer_v3",
        },
        "games": [{"error": None}, {"error": None}],
        "score_summary": {
            "avg_role_score": 6.2,
            "by_role_category": {"seer": 7.0},
            "avg_speech_score": 8.0,
            "avg_vote_score": 5.0,
            "avg_skill_score": 6.0,
            "avg_logic_score": 6.2,
            "avg_team_score": 5.5,
            "strength_score": 6.2,
            "avg_risk_penalty": 0.0,
        },
        "rankable": True,
        "rankable_reason": "ok",
        "valid_game_rate": 1.0,
        "paths": paths,
    }
    out = asyncio.run(persist_batch_node(state))
    assert out["result"]["batch_id"] == "persist1"
    manifest_path = paths.runs_dir / "evaluation_batches" / "persist1" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert out["result"]["metadata"]["manifest_path"] == str(manifest_path)
    assert out["result"]["manifest"] == manifest
    assert manifest["schema_version"] == 1
    assert manifest["run_type"] == "eval"
    assert manifest["batch_id"] == "persist1"
    assert manifest["status"] == "completed"
    assert manifest["metadata"]["completed"] == 2
    assert manifest["paths"]["games_dir"] == str(paths.runs_dir / "evaluation_batches" / "persist1" / "games")

    conn = sqlite3.connect(paths.wolf_db_path)
    conn.row_factory = sqlite3.Row
    batch = conn.execute("SELECT * FROM evaluation_batches WHERE id = ?", ("persist1",)).fetchone()
    assert batch is not None
    assert batch["target_role"] == "seer"
    assert batch["rankable"] == 1
    assert batch["created_at"].endswith("+08:00")

    lb = conn.execute(
        "SELECT * FROM benchmark_leaderboard WHERE scope = 'role_version' AND subject_id = ?",
        ("seer_v3",),
    ).fetchone()
    conn.close()
    assert lb is not None
    assert lb["target_role"] == "seer"
    assert abs(lb["avg_role_score"] - 6.2) < 1e-6
    assert lb["games_played"] == 2
    assert lb["updated_at"].endswith("+08:00")
