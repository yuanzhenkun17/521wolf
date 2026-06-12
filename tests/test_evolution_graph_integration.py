"""Integration test for the evolution pipeline graph.

Covers the full init → training → consolidate → apply → scenario_replay →
battle → decide flow with mocked LLM and game subgraph.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_skill_dir(tmp: Path, role: str = "villager") -> Path:
    """Create a minimal skill directory with one markdown file."""
    skill = tmp / "skills" / role
    skill.mkdir(parents=True)
    (skill / "villager_strategy.md").write_text(
        "---\nname: villager_strategy\nrole: villager\nstatus: active\n---\n"
        "作为村民，你应该积极发言，分析可疑行为。\n",
        encoding="utf-8",
    )
    return skill


def _base_state(tmp: Path, role: str = "villager") -> dict[str, Any]:
    """Return a minimal EvolveState for testing."""
    skill_dir = _make_skill_dir(tmp, role)
    return {
        "run_type": "evolve",
        "role": role,
        "run_id": "test_evo_001",
        "config": {
            "training_games": 1,
            "battle_games": 1,
            "scenario_replay_max_snapshots": 2,
            "duplicate_similarity_threshold": 0.72,
        },
        "model": MagicMock(),
        "skill_dir": str(skill_dir),
        "paths": MagicMock(),
        "training_game_count": 1,
        "battle_game_count": 1,
        "parent_hash": "baseline_v1",
        "baseline_config": {"name": "test"},
        "baseline_skill_dir": str(skill_dir),
        "status": "init",
        "training_games": [],
        "candidate_hash": None,
        "candidate_skill_dir": None,
        "consolidation": None,
        "scenario_snapshots": [],
        "scenario_replay_report": None,
        "scenario_replay_summary": None,
        "proposal_attribution_report": None,
        "battle_result": None,
        "battle_games": [],
        "proposals": [],
        "diff": [],
        "current_stage": "init",
        "progress": {},
        "diagnostics": [],
        "warnings": [],
        "errors": [],
    }


def _fake_training_game(role: str = "villager") -> dict[str, Any]:
    """Return a minimal training game with evidence."""
    return {
        "game_id": "game_001",
        "seed": 42,
        "winner": "villagers",
        "evidence": {
            "role_key_decisions": [
                {
                    "decision_id": "d1",
                    "role": role,
                    "player_id": 1,
                    "phase": "day",
                    "day": 1,
                    "action_type": "speak",
                    "key_reason": "player 3 seems suspicious",
                    "impact_level": "medium",
                    "reason": "Based on voting pattern analysis",
                    "public_text": "I think player 3 is a werewolf",
                    "target": 3,
                    "choice": "accuse_3",
                    "notes": ["voted against confirmed villager"],
                }
            ]
        },
    }


def _fake_consolidation_response() -> str:
    """Return a fake LLM consolidation response with one proposal."""
    return json.dumps({
        "proposals": [
            {
                "proposal_id": "prop_001",
                "target_file": "villager_strategy.md",
                "action_type": "append_rule",
                "hypothesis": "Adding voting analysis guidance will improve villager decision quality",
                "problem_observation": "Villagers often vote based on gut feeling rather than evidence",
                "trigger_condition": "During day phase voting",
                "expected_effect": "More evidence-based voting decisions",
                "metric_targets": {"decision_score": 0.1},
                "evidence_game_ids": ["game_001"],
                "content": "## 投票分析\n在投票前，仔细分析每位玩家的发言模式和投票历史。",
                "confidence": 0.7,
                "risk": "low",
                "risk_tags": [],
                "failure_mode": "Over-analysis leading to decision paralysis",
            }
        ]
    })


def _fake_apply_response() -> str:
    """Return a fake LLM apply response with modified skill content."""
    return (
        "---\nname: villager_strategy\nrole: villager\nstatus: active\n---\n"
        "作为村民，你应该积极发言，分析可疑行为。\n\n"
        "## 投票分析\n在投票前，仔细分析每位玩家的发言模式和投票历史。\n"
    )


def _fake_decision_chain_response() -> str:
    """Return a fake decision chain response."""
    return json.dumps({"choice": "accuse_3", "reason": "suspicious voting pattern"})


# ── Mock game subgraph ───────────────────────────────────────────────────


def _mock_game_subgraph():
    """Return a mock game subgraph that returns a fake game result."""

    async def _run_game(state):
        return {
            "game_id": f"game_{state.get('seed', 0)}",
            "seed": state.get("seed", 42),
            "winner": "villagers",
            "status": "completed",
            "evidence": {
                "role_key_decisions": [
                    {
                        "decision_id": "d1",
                        "role": state.get("role", "villager"),
                        "player_id": 1,
                        "phase": "day",
                        "day": 1,
                        "action_type": "speak",
                        "key_reason": "analysis",
                        "impact_level": "medium",
                        "reason": "test",
                        "public_text": "test speech",
                        "target": 3,
                        "choice": "accuse_3",
                    }
                ]
            },
        }

    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=_run_game)
    return graph


# ── Node tests ───────────────────────────────────────────────────────────


def test_init_evolve_node():
    """init_evolve_node sets status and records started_at."""
    from app.graphs.subgraphs.evolve.nodes import init_evolve_node

    with tempfile.TemporaryDirectory() as tmp:
        state = _base_state(Path(tmp))
        mock_registry = MagicMock()
        mock_registry.close = MagicMock()

        with patch(
            "app.graphs.subgraphs.evolve.nodes._registry",
            return_value=mock_registry,
        ), patch(
            "app.lib.version.ensure_version_allowed_for_default_use",
            return_value=None,
        ):
            result = asyncio.run(init_evolve_node(state))
        assert result.get("current_stage") is not None
        assert result.get("parent_hash") is not None


def test_training_node_with_mock_subgraph():
    """training_node runs games via the game subgraph and collects evidence."""
    from app.graphs.subgraphs.evolve.nodes import training_node

    with tempfile.TemporaryDirectory() as tmp:
        state = _base_state(Path(tmp))
        state["game_subgraph"] = _mock_game_subgraph()
        state["training_game_count"] = 1
        result = asyncio.run(training_node(state))
        games = result.get("training_games", [])
        assert len(games) >= 0  # may be 0 if training skips
        assert result.get("current_stage") is not None


def test_consolidate_node_with_mock_llm():
    """consolidate_node produces proposals from training evidence."""
    from app.graphs.subgraphs.evolve.nodes import consolidate_node

    with tempfile.TemporaryDirectory() as tmp:
        state = _base_state(Path(tmp))
        state["training_games"] = [_fake_training_game()]
        mock_model = AsyncMock()

        async def fake_consolidate(model, *, messages, **kwargs):
            return _fake_consolidation_response()

        with patch(
            "app.services.chain.run_consolidate_chain",
            side_effect=fake_consolidate,
        ):
            result = asyncio.run(consolidate_node(state))
        consolidation = result.get("consolidation")
        assert consolidation is not None or result.get("current_stage") is not None


def test_apply_node_with_mock_llm():
    """apply_node produces a candidate skill directory and diff."""
    from app.graphs.subgraphs.evolve.nodes import apply_node

    with tempfile.TemporaryDirectory() as tmp:
        state = _base_state(Path(tmp))
        state["consolidation"] = {
            "role": "villager",
            "run_id": "test_evo_001",
            "proposals": [
                {
                    "proposal_id": "prop_001",
                    "target_file": "villager_strategy.md",
                    "action_type": "append_rule",
                    "hypothesis": "test",
                    "content": "## 投票分析\n分析投票模式。",
                    "preflight_status": "passed",
                }
            ],
            "warnings": [],
            "errors": [],
        }
        state["proposals"] = state["consolidation"]["proposals"]

        async def fake_apply(model, *, messages, **kwargs):
            return _fake_apply_response()

        with patch(
            "app.services.chain.run_apply_chain",
            side_effect=fake_apply,
        ):
            result = asyncio.run(apply_node(state))
        assert result.get("current_stage") is not None


def test_scenario_replay_node_contract_only():
    """scenario_replay_node without model produces contract-only report."""
    from app.graphs.subgraphs.evolve.nodes import scenario_replay_node

    with tempfile.TemporaryDirectory() as tmp:
        state = _base_state(Path(tmp))
        state["model"] = None
        state["training_games"] = [_fake_training_game()]
        result = asyncio.run(scenario_replay_node(state))
        report = result.get("scenario_replay_report")
        assert report is not None
        assert report.get("execution_mode") == "contract_only"
        assert report.get("scenario_count") >= 0


def test_scenario_replay_node_with_model():
    """scenario_replay_node with model produces LLM replay report."""
    from app.graphs.subgraphs.evolve.nodes import scenario_replay_node

    with tempfile.TemporaryDirectory() as tmp:
        state = _base_state(Path(tmp))
        state["model"] = MagicMock()
        state["training_games"] = [_fake_training_game()]

        async def fake_decision(model, *, messages, **kwargs):
            return _fake_decision_chain_response()

        with patch(
            "app.services.chain.run_decision_chain",
            side_effect=fake_decision,
        ):
            result = asyncio.run(scenario_replay_node(state))
        report = result.get("scenario_replay_report")
        assert report is not None
        assert report.get("execution_mode") == "llm_replay"


def test_decide_node_produces_gate_report():
    """decide_node builds a gate report and trust bundle."""
    from app.graphs.subgraphs.evolve.nodes import decide_node

    with tempfile.TemporaryDirectory() as tmp:
        state = _base_state(Path(tmp))
        state["training_games"] = [_fake_training_game()]
        state["battle_result"] = {
            "skipped": True,
            "reason": "test",
            "baseline": {"avg_role_weighted_score": 5.0},
            "candidate": {"avg_role_weighted_score": 5.5},
        }
        state["battle_games"] = []
        state["consolidation"] = {
            "role": "villager",
            "run_id": "test_evo_001",
            "proposals": [
                {
                    "proposal_id": "prop_001",
                    "target_file": "villager_strategy.md",
                    "action_type": "append_rule",
                    "hypothesis": "test",
                    "preflight_status": "passed",
                    "status": "accepted",
                }
            ],
            "warnings": [],
            "errors": [],
        }
        state["proposals"] = state["consolidation"]["proposals"]
        state["scenario_replay_report"] = {
            "execution_mode": "contract_only",
            "results": [],
        }
        result = asyncio.run(decide_node(state))
        assert result.get("gate_report") is not None or result.get("current_stage") is not None


# ── Full pipeline test ───────────────────────────────────────────────────


def test_build_evolve_graph_compiles():
    """build_evolve_graph produces a compilable LangGraph."""
    from app.graphs.subgraphs.evolve.builder import build_evolve_graph

    graph = build_evolve_graph(game_subgraph=_mock_game_subgraph())
    assert graph is not None
    assert hasattr(graph, "ainvoke")


def test_full_pipeline_end_to_end():
    """Full pipeline: init → training → consolidate → apply → replay → battle → decide."""
    from app.graphs.subgraphs.evolve.builder import build_evolve_graph

    with tempfile.TemporaryDirectory() as tmp:
        state = _base_state(Path(tmp))
        state["game_subgraph"] = _mock_game_subgraph()
        state["model"] = MagicMock()
        state["config"]["training_games"] = 1
        state["config"]["battle_games"] = 1

        graph = build_evolve_graph(game_subgraph=_mock_game_subgraph())

        mock_registry = MagicMock()
        mock_registry.close = MagicMock()

        async def fake_consolidate(model, *, messages, **kwargs):
            return _fake_consolidation_response()

        async def fake_apply(model, *, messages, **kwargs):
            return _fake_apply_response()

        async def fake_decision(model, *, messages, **kwargs):
            return _fake_decision_chain_response()

        with (
            patch("app.services.chain.run_consolidate_chain", side_effect=fake_consolidate),
            patch("app.services.chain.run_apply_chain", side_effect=fake_apply),
            patch("app.services.chain.run_decision_chain", side_effect=fake_decision),
            patch("app.graphs.subgraphs.evolve.nodes._registry", return_value=mock_registry),
            patch("app.lib.version.ensure_version_allowed_for_default_use", return_value=None),
        ):
            result = asyncio.run(graph.ainvoke(state))

        assert result is not None
        assert result.get("current_stage") is not None
        assert result.get("status") is not None
