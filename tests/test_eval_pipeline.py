"""Tests for the upgraded batch-evaluation pipeline.

Covers the three behaviors wired beyond the basic scoring path:
1. role-version resolution → role_skill_dirs (only evaluated role uses the version)
2. cross-batch comparison-group fairness
3. batch + leaderboard persistence through the PostgreSQL storage provider
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.config import PathConfig
from app.graphs.subgraphs.eval.nodes import (
    _resolve_role_version_dirs,
    aggregate_node,
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


def _valid_game(winner: str = "villagers") -> dict:
    return {"winner": winner, "error": None}


class FakeVersionRegistry:
    def __init__(self, skill_dirs: dict[tuple[str, str], Path]) -> None:
        self.skill_dirs = skill_dirs
        self.closed = False

    def get_skill_dir(self, role: str, version_id: str) -> Path:
        try:
            return self.skill_dirs[(role, version_id)]
        except KeyError as exc:
            raise FileNotFoundError(f"Version {role}/{version_id} not found") from exc

    def close(self) -> None:
        self.closed = True


def _write_skill_dir(tmp_path: Path, role: str, version_id: str) -> Path:
    skill_dir = tmp_path / "pg_registry" / role / version_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "vote.md").write_text(SEER_SKILL, encoding="utf-8")
    return skill_dir


def _patch_version_registry(monkeypatch, registry: FakeVersionRegistry) -> None:
    import app.lib.version as version_mod

    monkeypatch.setattr(version_mod, "version_registry_from_env", lambda *, paths=None: registry)


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

def test_resolve_role_version_dirs_from_registry(tmp_path, monkeypatch):
    vid = "seer_v1"
    skill_dir = _write_skill_dir(tmp_path, "seer", vid)
    _patch_version_registry(monkeypatch, FakeVersionRegistry({("seer", vid): skill_dir}))

    class _Paths:
        registry_dir = tmp_path / "registry"

    dirs = _resolve_role_version_dirs({"target_role": "seer", "target_version_id": vid}, _Paths())
    assert "seer" in dirs

    assert (Path(dirs["seer"]) / "vote.md").exists()


def test_resolve_role_version_dirs_empty_when_unspecified(tmp_path):
    class _Paths:
        registry_dir = tmp_path / "registry"

    assert _resolve_role_version_dirs({"game_count": 5}, _Paths()) == {}


def test_resolve_role_version_dirs_keeps_partial_success_and_warns(tmp_path, monkeypatch):
    vid = "seer_v1"
    skill_dir = _write_skill_dir(tmp_path, "seer", vid)
    _patch_version_registry(monkeypatch, FakeVersionRegistry({("seer", vid): skill_dir}))

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


def test_run_games_node_isolates_evaluated_role(tmp_path, monkeypatch):
    paths = PathConfig(root=tmp_path)
    vid = "seer_v1"
    skill_dir = _write_skill_dir(tmp_path, "seer", vid)
    _patch_version_registry(monkeypatch, FakeVersionRegistry({("seer", vid): skill_dir}))
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


def test_missing_target_role_version_is_warning_and_unrankable(tmp_path, monkeypatch):
    _patch_version_registry(monkeypatch, FakeVersionRegistry({}))
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
        "games": [_valid_game("villagers"), _valid_game("werewolves")],
        "paths": PathConfig(root=tmp_path),
    }
    out = asyncio.run(fairness_node(state))
    assert out["fairness"]["is_fair"] is True
    assert out["fairness"]["reason"] == "standalone batch"
    assert out["rankable"] is True


def test_fairness_role_version_group_needs_sibling(monkeypatch, tmp_path):
    import app.lib.score as score_lib

    paths = PathConfig(root=tmp_path)

    class _Rows:
        def fetchall(self):
            return [
                {
                    "id": "sibling",
                    "comparison_group_id": "grp1",
                    "comparison_type": "role_version",
                    "mode": "dev",
                    "model_id": "modelB",
                    "model_config_hash": None,
                    "target_role": "seer",
                    "target_version_id": "seer_v2",
                    "seed_set_id": "seedsB",
                    "game_count": 2,
                }
            ]

    class _Conn:
        def __init__(self):
            self.closed = False

        def execute(self, _sql, params=()):
            assert params == ("grp1", "b_current")
            return _Rows()

        def close(self):
            self.closed = True

    conn = _Conn()
    monkeypatch.setattr(score_lib, "open_eval_connection", lambda seen_paths: conn)

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
        "games": [_valid_game("villagers"), _valid_game("werewolves")],
        "paths": paths,
    }
    out = asyncio.run(fairness_node(state))
    assert conn.closed is True
    assert out["fairness"]["is_fair"] is True
    assert "seer" in out["fairness"]["reason"]


def test_save_evaluation_batch_normalizes_empty_timestamps_to_null():
    from app.lib.score import save_evaluation_batch

    class _Conn:
        def __init__(self):
            self.params = None
            self.committed = False
            self.rolled_back = False

        def execute(self, _sql, params=()):
            self.params = tuple(params)

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    conn = _Conn()

    warning = save_evaluation_batch(
        conn,
        {"batch_id": "batch_null_times", "started_at": "", "finished_at": ""},
    )

    assert warning is None
    assert conn.params[16] is None
    assert conn.params[17] is None
    assert conn.committed is True
    assert conn.rolled_back is False


def test_fairness_group_fails_with_single_batch(monkeypatch, tmp_path):
    import app.lib.score as score_lib

    class _Rows:
        def fetchall(self):
            return []

    class _Conn:
        def __init__(self):
            self.closed = False

        def execute(self, _sql, params=()):
            assert params == ("grp_empty", "lonely")
            return _Rows()

        def close(self):
            self.closed = True

    conn = _Conn()
    monkeypatch.setattr(score_lib, "open_eval_connection", lambda paths: conn)

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
        "games": [_valid_game("villagers"), _valid_game("werewolves")],
        "paths": PathConfig(root=tmp_path),
    }
    out = asyncio.run(fairness_node(state))
    assert conn.closed is True
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
        "games": [_valid_game("villagers"), _valid_game("werewolves")],
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
        "games": [_valid_game("villagers"), _valid_game("werewolves")],
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


def test_compute_decision_quality_metrics_counts_sources_and_engine_events():
    from app.lib.score import compute_decision_quality_metrics

    metrics = compute_decision_quality_metrics([
        {
            "decisions": [
                {"source": "llm"},
                {"source": "fallback"},
                {"source": "llm_error"},
                {"source": "policy_adjusted"},
                {"source": "policy_skipped"},
                {"source": "llm", "policy_adjustments": '["target repaired"]'},
            ],
            "events": [
                {"event_type": "action_response"},
                {"event_type": "invalid_response"},
                {"type": "default_action"},
                {"event_type": "default_action"},
            ],
        },
        {"decisions": "ignored", "events": None},
    ])

    assert metrics == {
        "decision_count": 6,
        "fallback_count": 1,
        "llm_error_count": 1,
        "policy_skipped_count": 1,
        "policy_adjusted_count": 2,
        "fallback_rate": 0.166667,
        "llm_error_rate": 0.166667,
        "policy_adjusted_rate": 0.333333,
        "policy_skipped_rate": 0.166667,
        "event_count": 4,
        "invalid_response_count": 1,
        "default_action_count": 2,
        "invalid_response_rate": 0.25,
        "default_action_rate": 0.5,
    }


def test_aggregate_node_adds_decision_quality_summary(tmp_path):
    state = {
        "batch_id": "quality_batch",
        "batch_config": {"game_count": 1, "mode": "dev"},
        "games": [
            {
                **_valid_game("villagers"),
                "decisions": [
                    {"source": "fallback"},
                    {"source": "llm_error"},
                    {"source": "policy_adjusted"},
                    {"source": "llm"},
                ],
                "events": [
                    {"event_type": "invalid_response"},
                    {"event_type": "default_action"},
                    {"event_type": "action_response"},
                ],
            }
        ],
        "player_scores": [],
        "paths": PathConfig(root=tmp_path),
    }

    out = asyncio.run(aggregate_node(state))
    summary = out["score_summary"]

    assert summary["game_count"] == 1
    assert summary["decision_quality"]["decision_count"] == 4
    assert summary["decision_quality"]["fallback_count"] == 1
    assert summary["decision_quality"]["policy_skipped_count"] == 0
    assert summary["decision_quality"]["invalid_response_count"] == 1
    assert summary["decision_quality"]["default_action_count"] == 1
    assert summary["fallback_rate"] == 0.25
    assert summary["llm_error_rate"] == 0.25
    assert summary["policy_adjusted_rate"] == 0.25


def test_aggregate_node_adds_decision_judge_aggregate(tmp_path):
    judge_calls = []

    async def fake_judge(messages):
        judge_calls.append(messages)
        return (
            '{"schema_version":"1.0","decision_id":"d_check","score":4.0,'
            '"quality":"bad","reason":"查验目标信息收益不足",'
            '"evidence":["只因 2 号发言少就查验，缺少票型或身份链收益"],'
            '"evidence_refs":["rule_natural_key_action"],'
            '"counterfactual":"若改查影响站边或归票的高信息量位置，白天可更快收敛狼坑。",'
            '"mistake_tags":["low_information_gain"],'
            '"related_skills":["seer/check_priority.md"],'
            '"recommended_skill_files":["seer/check_priority.md"],'
            '"suggestion":"优先查验发言矛盾或身份价值更高的位置","confidence":0.75}'
        )

    game = {
        **_valid_game("villagers"),
        "game_id": "judge_eval_game_001",
        "player_roles": {"1": "seer", "2": "werewolf"},
        "decisions": [
            {
                "decision_id": "d_check",
                "player_id": 1,
                "role": "seer",
                "day": 1,
                "phase": "night",
                "action_type": "seer_check",
                "selected_target": 2,
                "private_reasoning": "2 号发言少，先验一下。",
                "confidence": 0.7,
            }
        ],
        "events": [
            {"event_type": "night_end", "day": 1, "phase": "night"},
        ],
    }
    state = {
        "batch_id": "judge_aggregate_batch",
        "batch_config": {
            "game_count": 1,
            "mode": "dev",
            "eval_decision_judge": True,
            "eval_judge_max_decisions": 1,
        },
        "games": [game],
        "player_scores": [],
        "paths": PathConfig(root=tmp_path),
        "decision_judge_fn": fake_judge,
    }

    out = asyncio.run(aggregate_node(state))
    aggregate = out["score_summary"]["decision_judge_aggregate"]
    report = out["games"][0]["review"]["decision_judge"]

    assert len(judge_calls) == 1
    assert report["status"] == "ok"
    assert report["metrics"]["judged"] == 1
    assert report["judgments"][0]["game_id"] == "judge_eval_game_001"
    assert report["judgments"][0]["evidence"] == ["只因 2 号发言少就查验，缺少票型或身份链收益"]
    assert "改查影响站边" in report["judgments"][0]["counterfactual"]
    assert report["judgments"][0]["related_skills"] == ["seer/check_priority.md"]
    assert report["judgments"][0]["recommended_skill_files"] == ["seer/check_priority.md"]
    assert aggregate["status"] == "ok"
    assert aggregate["game_count"] == 1
    assert aggregate["reported_games"] == 1
    assert aggregate["judged_decisions"] == 1
    assert aggregate["avg_score"] == 4.0
    assert aggregate["bad_rate"] == 1.0
    assert aggregate["quality_counts"] == {"bad": 1}
    assert aggregate["top_mistake_tags"] == [{"tag": "low_information_gain", "count": 1}]
    assert aggregate["recommended_skill_files"] == [{"path": "seer/check_priority.md", "count": 1}]
    assert aggregate["by_role"]["seer"]["avg_score"] == 4.0
    assert aggregate["by_action_type"]["seer_check"]["bad_rate"] == 1.0
    assert aggregate["lowest_decisions"][0]["decision_id"] == "d_check"
    assert aggregate["lowest_decisions"][0]["evidence"] == ["只因 2 号发言少就查验，缺少票型或身份链收益"]
    assert aggregate["lowest_decisions"][0]["recommended_skill_files"] == ["seer/check_priority.md"]


def test_decision_judge_timeout_records_degraded_reason():
    from app.lib.decision_judge import judge_key_decisions

    async def slow_judge(_messages):
        await asyncio.sleep(0.05)
        return "{}"

    report = asyncio.run(judge_key_decisions(
        object(),
        game_id="judge_timeout_game",
        winner="villagers",
        roles={"1": "seer", "2": "werewolf"},
        decisions=[
            {
                "decision_id": "d_timeout",
                "player_id": 1,
                "role": "seer",
                "day": 1,
                "phase": "night",
                "action_type": "seer_check",
                "selected_target": 2,
                "private_reasoning": "先验 2 号。",
            }
        ],
        events=[{"event_type": "night_end", "day": 1, "phase": "night"}],
        max_decisions=1,
        concurrency=1,
        timeout_seconds=0.001,
        judge_fn=slow_judge,
    ))

    assert report["status"] == "failed"
    assert report["reason"] == "timeout"
    assert report["degraded_reasons"] == ["timeout"]
    assert report["metrics"]["failed"] == 1
    assert report["diagnostics"][0]["reason"] == "timeout"
    assert report["diagnostics"][0]["decision_id"] == "d_timeout"


def test_invalid_winners_are_not_rankable_or_persisted_as_game_count(monkeypatch, tmp_path):
    import app.lib.score as score_lib

    paths = PathConfig(root=tmp_path)
    saved_batches: list[dict] = []
    leaderboard_entries: list[dict] = []

    class _Conn:
        closed = False

        def close(self):
            self.closed = True

    conn = _Conn()

    monkeypatch.setattr(score_lib, "open_eval_connection", lambda seen_paths: conn)
    monkeypatch.setattr(
        score_lib,
        "save_evaluation_batch",
        lambda conn_arg, batch: saved_batches.append(dict(batch)) or None,
    )
    monkeypatch.setattr(
        score_lib,
        "persist_leaderboard_entry",
        lambda conn_arg, entry: leaderboard_entries.append(dict(entry)) or None,
    )

    state = {
        "batch_id": "invalid_winners",
        "batch_config": {"game_count": 3, "mode": "dev"},
        "games": [
            {"winner": None, "error": None, "terminal_reason": "max_days_reached"},
            {"winner": "error", "error": None},
            {"winner": "good", "error": None},
        ],
        "player_scores": [],
        "paths": paths,
    }

    out = asyncio.run(aggregate_node(state))
    assert out["score_summary"]["game_count"] == 0

    out = asyncio.run(fairness_node(out))
    assert out["valid_game_rate"] == 0.0
    assert out["fairness"] == {"is_fair": False, "reason": "No games in batch"}
    assert out["rankable"] is False
    assert out["rankable_reason"] == "No games in batch"

    out = asyncio.run(persist_batch_node(out))

    assert conn.closed is True
    assert out["result"]["game_count"] == 0
    assert out["result"]["attempted_game_count"] == 3
    assert out["result"]["completed"] == 0
    assert out["result"]["invalid"] == 1
    assert out["result"]["timeout"] == 0
    assert out["result"]["abnormal"] == 2
    assert out["result"]["errored"] == 0
    assert out["result"]["terminal_stats"]["excluded_from_win_rate"] == 3
    assert out["result"]["terminal_stats"]["win_rate_denominator"] == 0
    assert saved_batches[0]["game_count"] == 0
    assert saved_batches[0]["rankable"] is False
    assert leaderboard_entries == []
    assert out["result"]["leaderboard_gate"]["accepted"] is False
    assert out["result"]["leaderboard_skipped_reason"] == "No games in batch; completed_games 0 < required 1"


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


def test_persist_leaderboard_entry_writes_decision_quality_columns():
    from app.lib.score import persist_leaderboard_entry

    class _Conn:
        def __init__(self):
            self.sql = ""
            self.params = ()
            self.committed = False

        def execute(self, sql, params=()):
            self.sql = sql
            self.params = tuple(params)

        def commit(self):
            self.committed = True

    summary = {
        "decision_quality": {
            "invalid_response_rate": 0.125,
            "default_action_rate": 0.25,
        }
    }
    conn = _Conn()

    warning = persist_leaderboard_entry(
        conn,
        {
            "batch_id": "quality_sql",
            "model_id": "model-a",
            "rankable": True,
            "fallback_rate": 0.1,
            "llm_error_rate": 0.2,
            "policy_adjusted_rate": 0.3,
            "summary": summary,
        },
    )

    assert warning is None
    assert conn.committed is True
    assert "fallback_rate, llm_error_rate, policy_adjusted_rate" in conn.sql
    assert "fallback_rate = excluded.fallback_rate" in conn.sql
    columns_text = conn.sql.split("(", 1)[1].split(")", 1)[0]
    columns = [column.strip() for column in columns_text.split(",")]
    assert len(columns) == len(conn.params)
    params_by_column = dict(zip(columns, conn.params))
    assert params_by_column["fallback_rate"] == 0.1
    assert params_by_column["llm_error_rate"] == 0.2
    assert params_by_column["policy_adjusted_rate"] == 0.3
    assert params_by_column["rankable"] == 1
    assert params_by_column["data_sufficient"] == 1
    persisted_summary = json.loads(params_by_column["summary"])
    assert persisted_summary["decision_quality"]["invalid_response_rate"] == 0.125
    assert persisted_summary["decision_quality"]["default_action_rate"] == 0.25


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
        "games": [_valid_game("villagers")],
        "score_summary": {"avg_role_score": 5.0},
        "rankable": True,
        "rankable_reason": "ok",
        "valid_game_rate": 1.0,
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


def test_persist_batch_node_writes_batch_and_leaderboard(tmp_path, monkeypatch):
    paths = PathConfig(root=tmp_path)
    opened: list[object] = []
    saved_batches: list[dict] = []
    leaderboard_entries: list[dict] = []

    class _FakeConn:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    def open_connection(seen_paths):
        assert seen_paths is paths
        conn = _FakeConn()
        opened.append(conn)
        return conn

    def save_batch(conn, batch):
        assert conn is opened[0]
        saved_batches.append(dict(batch))
        return None

    def persist_entry(conn, entry):
        assert conn is opened[0]
        leaderboard_entries.append(dict(entry))
        return None

    monkeypatch.setattr("app.lib.score.open_eval_connection", open_connection)
    monkeypatch.setattr("app.lib.score.save_evaluation_batch", save_batch)
    monkeypatch.setattr("app.lib.score.persist_leaderboard_entry", persist_entry)

    state = {
        "batch_id": "persist1",
        "batch_config": {
            "game_count": 2,
            "mode": "dev",
            "target_role": "seer",
            "target_version_id": "seer_v3",
        },
        "games": [_valid_game("villagers"), _valid_game("werewolves")],
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
            "decision_quality": {
                "decision_count": 4,
                "fallback_count": 1,
                "llm_error_count": 1,
                "policy_adjusted_count": 1,
                "fallback_rate": 0.25,
                "llm_error_rate": 0.25,
                "policy_adjusted_rate": 0.25,
                "event_count": 4,
                "invalid_response_count": 1,
                "default_action_count": 1,
                "invalid_response_rate": 0.25,
                "default_action_rate": 0.25,
            },
            "fallback_rate": 0.25,
            "llm_error_rate": 0.25,
            "policy_adjusted_rate": 0.25,
        },
        "rankable": True,
        "rankable_reason": "ok",
        "valid_game_rate": 1.0,
        "paths": paths,
    }
    out = asyncio.run(persist_batch_node(state))
    assert out["result"]["batch_id"] == "persist1"
    assert out["result"]["metadata"] == {"storage": "postgresql"}
    assert "manifest" not in out["result"]
    assert "manifest_path" not in out["result"]["metadata"]
    assert not (paths.runs_dir / "evaluation_batches" / "persist1" / "manifest.json").exists()

    assert len(opened) == 1
    assert opened[0].closed is True
    assert len(saved_batches) == 1
    saved_batch = saved_batches[0]
    assert saved_batch["batch_id"] == "persist1"
    assert saved_batch["comparison_group_id"] is None
    assert saved_batch["comparison_type"] == "role_version"
    assert saved_batch["mode"] == "dev"
    assert saved_batch["model_id"] is None
    assert saved_batch["model_config_hash"] is None
    assert saved_batch["target_role"] == "seer"
    assert saved_batch["target_version_id"] == "seer_v3"
    assert saved_batch["role_version_config"] is None
    assert saved_batch["game_count"] == 2
    assert saved_batch["evaluation_set_id"] is None
    assert saved_batch["seed_set_id"] is None
    assert saved_batch["max_days"] == 20
    assert saved_batch["rankable"] is True
    assert saved_batch["rankable_reason"] == "ok"
    assert saved_batch["score_summary"] == state["score_summary"]
    assert saved_batch["started_at"] == ""
    assert str(saved_batch["finished_at"]).endswith("+08:00")
    assert "created_at" not in saved_batches[0]
    assert leaderboard_entries
    assert leaderboard_entries[0]["target_role"] == "seer"
    assert leaderboard_entries[0]["target_version_id"] == "seer_v3"
    assert abs(leaderboard_entries[0]["avg_role_score"] - 6.2) < 1e-6
    assert leaderboard_entries[0]["game_count"] == 2
    assert leaderboard_entries[0]["fallback_rate"] == 0.25
    assert leaderboard_entries[0]["llm_error_rate"] == 0.25
    assert leaderboard_entries[0]["policy_adjusted_rate"] == 0.25
    assert leaderboard_entries[0]["summary"]["decision_quality"]["default_action_rate"] == 0.25


def test_persist_batch_skips_leaderboard_when_error_rate_is_high(monkeypatch, tmp_path):
    import app.lib.score as score_lib

    paths = PathConfig(root=tmp_path)
    saved_batches: list[dict] = []
    leaderboard_entries: list[dict] = []

    class _Conn:
        closed = False

        def close(self):
            self.closed = True

    conn = _Conn()

    monkeypatch.setattr(score_lib, "open_eval_connection", lambda seen_paths: conn)
    monkeypatch.setattr(
        score_lib,
        "save_evaluation_batch",
        lambda conn_arg, batch: saved_batches.append(dict(batch)) or None,
    )
    monkeypatch.setattr(
        score_lib,
        "persist_leaderboard_entry",
        lambda conn_arg, entry: leaderboard_entries.append(dict(entry)) or None,
    )

    state = {
        "batch_id": "high_error_gate",
        "batch_config": {"game_count": 2, "mode": "dev"},
        "games": [_valid_game("villagers"), _valid_game("werewolves")],
        "score_summary": {
            "avg_role_score": 6.0,
            "fallback_rate": 0.1,
            "llm_error_rate": 0.4,
            "policy_adjusted_rate": 0.0,
            "decision_quality": {"invalid_response_rate": 0.0, "default_action_rate": 0.0},
        },
        "rankable": True,
        "rankable_reason": "ok",
        "valid_game_rate": 1.0,
        "paths": paths,
    }

    out = asyncio.run(persist_batch_node(state))

    assert conn.closed is True
    assert saved_batches[0]["rankable"] is False
    assert saved_batches[0]["rankable_reason"] == "llm_error_rate 40.0% > ceiling 30.0%"
    assert leaderboard_entries == []
    assert out["result"]["low_error_rate"] is False
    assert out["result"]["rankable"] is False
    assert out["result"]["leaderboard_gate"] == {
        "accepted": False,
        "reason": "llm_error_rate 40.0% > ceiling 30.0%",
        "rankable": False,
        "data_sufficient": True,
        "low_error_rate": False,
        "completed_games": 2,
        "attempted_games": 2,
        "excluded_from_win_rate": 0,
        "valid_game_rate": 1.0,
    }
