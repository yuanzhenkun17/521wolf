"""Tests for evolution system fixes: replay, attribution, progress, helpers."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


# ── Scenario replay helpers ──────────────────────────────────────────────


def test_choices_match_identical():
    from app.graphs.subgraphs.evolve.nodes import _choices_match

    assert _choices_match("vote_3", "vote_3") is True
    assert _choices_match(5, 5) is True
    assert _choices_match("Kill", "kill") is True


def test_choices_match_different():
    from app.graphs.subgraphs.evolve.nodes import _choices_match

    assert _choices_match("vote_3", "vote_7") is False
    assert _choices_match(None, "vote_3") is False
    assert _choices_match("vote_3", None) is False


def test_parse_replay_decision_json():
    from app.graphs.subgraphs.evolve.nodes import _parse_replay_decision

    result = _parse_replay_decision('{"choice": "vote_3", "reason": "suspicious"}')
    assert result["choice"] == "vote_3"
    assert result["reason"] == "suspicious"


def test_parse_replay_decision_fallback():
    from app.graphs.subgraphs.evolve.nodes import _parse_replay_decision

    result = _parse_replay_decision("I choose to vote for player 3")
    assert "choice" in result


def test_build_replay_messages_structure():
    from app.graphs.subgraphs.evolve.nodes import _build_replay_messages

    snapshot = {
        "role": "werewolf",
        "phase": "night",
        "day": 1,
        "action_type": "kill",
        "actor_id": 3,
        "public_event_prefix": [{"text": "Player 1 spoke"}],
        "actor_observation": {"reason": "Player 5 is suspicious"},
        "legal_actions": ["kill_1", "kill_5"],
        "players_public_state": [
            {"id": 1, "alive": True},
            {"id": 5, "alive": True},
        ],
        "skill_inventory": {"active_skills": ["stealth_attack"]},
    }
    messages = _build_replay_messages(snapshot)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "werewolf" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "kill" in messages[1]["content"]


# ── Scenario replay result ───────────────────────────────────────────────


def test_contract_only_scenario_result():
    from app.graphs.subgraphs.evolve.nodes import _contract_only_scenario_result

    snapshot = {
        "scenario_id": "s1",
        "source_game_id": "g1",
        "role": "villager",
        "actor_id": 1,
        "phase": "day",
        "legal_actions": ["speak"],
        "prompt_policy_version": "v1",
        "judge_policy_version": "v1",
        "rubric_version": "v1",
        "baseline_version": "base",
        "candidate_version": "cand",
    }
    result = _contract_only_scenario_result(snapshot)
    assert result["baseline_decision"] is None
    assert result["candidate_decision"] is None
    assert result["rubric_score_delta"] is None
    assert result["verdict"] == "contract_ready"
    assert result["contract_missing"] == []


def test_contract_only_scenario_result_missing_fields():
    from app.graphs.subgraphs.evolve.nodes import _contract_only_scenario_result

    snapshot = {"scenario_id": "s1", "source_game_id": "g1"}
    result = _contract_only_scenario_result(snapshot)
    assert result["verdict"] == "contract_incomplete"
    assert len(result["contract_missing"]) > 0


def test_replay_scenario_result_with_mock_model():
    from app.graphs.subgraphs.evolve.nodes import _replay_scenario_result

    snapshot = {
        "scenario_id": "s1",
        "source_game_id": "g1",
        "role": "villager",
        "phase": "day",
        "day": 1,
        "action_type": "speak",
        "actor_id": 1,
        "public_event_prefix": [],
        "actor_observation": {"choice": "accuse_3"},
        "legal_actions": ["speak"],
        "players_public_state": [],
        "skill_inventory": {},
    }
    mock_model = AsyncMock()

    async def fake_run_decision_chain(model, *, messages, **kwargs):
        return '{"choice": "accuse_3", "reason": "same"}'

    with patch(
        "app.services.chain.run_decision_chain",
        side_effect=fake_run_decision_chain,
    ):
        result = asyncio.run(
            _replay_scenario_result(None, snapshot, model=mock_model)
        )
    assert result["verdict"] == "replayed"
    assert result["baseline_decision"]["choice"] == "accuse_3"
    assert result["candidate_decision"]["choice"] == "accuse_3"
    assert result["rubric_score_delta"] == 0.0


def test_replay_scenario_result_different_decisions():
    from app.graphs.subgraphs.evolve.nodes import _replay_scenario_result

    snapshot = {
        "scenario_id": "s2",
        "source_game_id": "g2",
        "role": "werewolf",
        "phase": "night",
        "day": 2,
        "action_type": "kill",
        "actor_id": 3,
        "public_event_prefix": [],
        "actor_observation": {"choice": "kill_5"},
        "legal_actions": ["kill_5", "kill_7"],
        "players_public_state": [],
        "skill_inventory": {},
    }
    mock_model = AsyncMock()

    async def fake_run_decision_chain(model, *, messages, **kwargs):
        return '{"choice": "kill_7", "reason": "different target"}'

    with patch(
        "app.services.chain.run_decision_chain",
        side_effect=fake_run_decision_chain,
    ):
        result = asyncio.run(
            _replay_scenario_result(None, snapshot, model=mock_model)
        )
    assert result["verdict"] == "replayed"
    assert result["rubric_score_delta"] == -1.0


def test_replay_scenario_result_llm_failure():
    from app.graphs.subgraphs.evolve.nodes import _replay_scenario_result

    snapshot = {
        "scenario_id": "s3",
        "source_game_id": "g3",
        "role": "villager",
        "phase": "day",
        "day": 1,
        "action_type": "speak",
        "actor_id": 1,
        "public_event_prefix": [],
        "actor_observation": {"choice": "accuse_2"},
        "legal_actions": ["speak"],
        "players_public_state": [],
        "skill_inventory": {},
    }

    async def failing_chain(model, *, messages, **kwargs):
        raise RuntimeError("LLM timeout")

    with patch(
        "app.services.chain.run_decision_chain",
        side_effect=failing_chain,
    ):
        result = asyncio.run(
            _replay_scenario_result(None, snapshot, model=AsyncMock())
        )
    assert result["verdict"] == "replay_error"
    assert result["replay_error"] == "LLM timeout"


# ── Per-proposal attribution enrichment ──────────────────────────────────


def test_enrich_attribution_with_replay_positive():
    from app.lib.evolve import _enrich_attribution_with_replay

    rows = [
        {"proposal_id": "p1", "status": "attribution_inconclusive", "reason": "ablation_not_run"},
    ]
    replay_results = [
        {"verdict": "replayed", "proposal_ids": ["p1"], "rubric_score_delta": 0.5},
        {"verdict": "replayed", "proposal_ids": ["p1"], "rubric_score_delta": 0.3},
    ]
    _enrich_attribution_with_replay(rows, replay_results)
    assert rows[0]["status"] == "attribution_estimated"
    assert rows[0]["reason"] == "scenario_replay_positive"
    assert rows[0]["estimated_contribution"] == 0.4
    assert rows[0]["attribution_confidence"] == "medium"


def test_enrich_attribution_with_replay_neutral():
    from app.lib.evolve import _enrich_attribution_with_replay

    rows = [
        {"proposal_id": "p2", "status": "attribution_inconclusive"},
    ]
    replay_results = [
        {"verdict": "replayed", "proposal_ids": ["p2"], "rubric_score_delta": 0.0},
    ]
    _enrich_attribution_with_replay(rows, replay_results)
    assert rows[0]["status"] == "attribution_estimated"
    assert rows[0]["reason"] == "scenario_replay_neutral"
    assert rows[0]["estimated_contribution"] == 0.0


def test_enrich_attribution_no_matching_proposals():
    from app.lib.evolve import _enrich_attribution_with_replay

    rows = [
        {"proposal_id": "p3", "status": "attribution_inconclusive"},
    ]
    replay_results = [
        {"verdict": "replayed", "proposal_ids": ["p_other"], "rubric_score_delta": 0.5},
    ]
    _enrich_attribution_with_replay(rows, replay_results)
    assert rows[0]["status"] == "attribution_inconclusive"


# ── Progress formula ─────────────────────────────────────────────────────


def test_overall_progress_formula_symmetric():
    from ui.backend.evolution_serializers import _overall_progress

    entity = {
        "training_game_count": 5,
        "battle_game_count": 5,
        "training_completed": 5,
        "battle_completed": 5,
        "status": "completed",
    }
    progress = _overall_progress(entity)
    assert progress["percent"] == 1.0
    assert progress["battle_total"] == 10


def test_overall_progress_partial_training_only():
    from ui.backend.evolution_serializers import _overall_progress

    entity = {
        "training_game_count": 4,
        "battle_game_count": 0,
        "training_completed": 2,
        "battle_completed": 0,
        "status": "running",
    }
    progress = _overall_progress(entity)
    assert progress["percent"] == 0.5


def test_overall_progress_partial_battle_only():
    from ui.backend.evolution_serializers import _overall_progress

    entity = {
        "training_game_count": 0,
        "battle_game_count": 4,
        "training_completed": 0,
        "battle_completed": 2,
        "status": "running",
    }
    progress = _overall_progress(entity)
    assert progress["percent"] == 0.5


# ── DRY helper delegation ────────────────────────────────────────────────


def test_serializers_proposal_status_delegates_to_service():
    from ui.backend.evolution_serializers import _proposal_status

    assert _proposal_status({"status": "applied"}) == "applied"
    assert _proposal_status({"status": "accepted"}) == "accepted"
    assert _proposal_status({"status": "rejected"}) == "rejected"
    assert _proposal_status({"status": ""}) == "proposed"


def test_serializers_clean_id_list_delegates():
    from ui.backend.evolution_serializers import _clean_id_list

    assert _clean_id_list(["a", "b", ""]) == ["a", "b"]
    assert _clean_id_list(None) == []
    assert _clean_id_list([1, 2]) == ["1", "2"]


def test_serializers_first_id_list_delegates():
    from ui.backend.evolution_serializers import _first_id_list

    assert _first_id_list(None, ["x", "y"]) == ["x", "y"]
    assert _first_id_list(None, None) is None


# ── Repro command ────────────────────────────────────────────────────────


def test_repro_command_generates_real_command():
    from app.lib.evolve import _repro_command

    run = {
        "run_id": "evo_123",
        "role": "werewolf",
        "config": {
            "training_games": 10,
            "battle_games": 5,
            "benchmark_id": "main_v1",
        },
    }
    cmd = _repro_command(run)
    assert "run_full_local_samples" in cmd
    assert "--roles werewolf" in cmd
    assert "evo_123" in cmd


def test_repro_command_respects_existing():
    from app.lib.evolve import _repro_command

    run = {"run_id": "evo_456", "repro_command": "custom command"}
    assert _repro_command(run) == "custom command"


# ── Empty candidate rejection ────────────────────────────────────────────


def test_evolution_skill_contents_raises_on_empty():
    from ui.backend.evolution_actions import _evolution_skill_contents

    run = {"run_id": "test_run", "diff": []}
    store = type("S", (), {"registry": None})()
    with pytest.raises(ValueError, match="no accepted proposals"):
        _evolution_skill_contents("villager", run, proposals=[])


# ── Convergence detection ───────────────────────────────────────────────


def test_detect_evolution_convergence_not_enough_rounds():
    from app.lib.evolve import detect_evolution_convergence

    runs = [{"role": "villager", "status": "completed", "started_at": "2026-01-01", "gate_report": {"metrics": {"role_score_delta": 0.001}}}]
    result = detect_evolution_convergence("villager", runs, convergence_rounds=3, min_improvement_ratio=0.01)
    assert result["converged"] is False
    assert "1 of 3" in result["reason"]


def test_detect_evolution_convergence_converged():
    from app.lib.evolve import detect_evolution_convergence

    runs = []
    for i in range(3):
        runs.append({
            "role": "villager",
            "status": "completed",
            "started_at": f"2026-01-0{i+1}",
            "gate_report": {
                "metrics": {"role_score_delta": 0.001},
                "role_score": {"baseline": 5.0},
            },
        })
    result = detect_evolution_convergence("villager", runs, convergence_rounds=3, min_improvement_ratio=0.01)
    assert result["converged"] is True
    assert result["rounds_checked"] == 3


def test_detect_evolution_convergence_not_converged():
    from app.lib.evolve import detect_evolution_convergence

    runs = []
    for i in range(3):
        runs.append({
            "role": "villager",
            "status": "completed",
            "started_at": f"2026-01-0{i+1}",
            "gate_report": {
                "metrics": {"role_score_delta": 0.5},
                "role_score": {"baseline": 5.0},
            },
        })
    result = detect_evolution_convergence("villager", runs, convergence_rounds=3, min_improvement_ratio=0.01)
    assert result["converged"] is False
    assert "improvement detected" in result["reason"]


# ── Auto-rollback on regression ─────────────────────────────────────────


def test_recommendation_rejects_on_regression():
    from app.graphs.subgraphs.evolve._decide import _recommendation

    proposals = [{"proposal_id": "p1"}]
    battle = {"significant": True, "win_rate_delta": -0.15}
    cfg = {"regression_threshold": 0.05}
    result = _recommendation(proposals, battle, cfg=cfg)
    assert result == "reject"


def test_recommendation_promotes_when_no_regression():
    from app.graphs.subgraphs.evolve._decide import _recommendation

    proposals = [{"proposal_id": "p1"}]
    battle = {"significant": True, "win_rate_delta": 0.10}
    cfg = {"regression_threshold": 0.05}
    result = _recommendation(proposals, battle, cfg=cfg)
    assert result == "promote"


# ── Per-role gate thresholds ────────────────────────────────────────────


def test_gate_thresholds_role_overrides():
    from app.lib.evolve import _gate_thresholds

    thresholds = {"min_role_score_delta": 0.0, "min_candidate_edge_rate": 0.50}
    config = {"role_thresholds": {"seer": {"min_role_score_delta": 0.5, "min_candidate_edge_rate": 0.55}}}
    result = _gate_thresholds(thresholds, role="seer", config=config)
    assert result["min_role_score_delta"] == 0.5
    assert result["min_candidate_edge_rate"] == 0.55
    assert result["role_overrides_applied"] is True


def test_gate_thresholds_no_role_overrides():
    from app.lib.evolve import _gate_thresholds

    thresholds = {"min_role_score_delta": 0.0}
    result = _gate_thresholds(thresholds, role="villager", config=None)
    assert result["min_role_score_delta"] == 0.0
    assert result.get("role_overrides_applied", False) is False


# ── Background exception paths (pragma: no cover) ───────────────────────


def test_run_queued_evolution_handles_runner_failure():
    """run_queued_evolution marks run as failed when the runner raises."""
    import asyncio

    from ui.backend.constants import MANUAL_STOP_REASON
    from ui.backend.schemas import EvolutionStartRequest
    from ui.backend.services.evolution_run_service import EvolutionRunService

    class FakeContext:
        paths = None
        model = None
        evolution_runs: dict = {}
        evolution_batches: dict = {}
        background_state_lock = type("L", (), {"acquire": lambda s: None, "release": lambda s: None})()
        _task_event_log = None

        def evolution_runner(self):
            async def _failing_runner(**kwargs):
                raise RuntimeError("simulated runner crash")
            return _failing_runner

        def model_for_run(self, **kwargs):
            return None

        def heartbeat(self, **kwargs):
            pass

        def cancel_requested(self):
            return False

        def _persist_background_tasks(self):
            pass

        def _touch_background_task(self, entity, **kwargs):
            return "2026-01-01T00:00:00"

        def _append_background_diagnostic(self, entity, diag, **kwargs):
            entity.setdefault("diagnostics", []).append(diag)

        def _task_progress_percent(self, entity):
            return 0.0

        def mark_evolution_stopped(self, entity):
            entity["status"] = "failed"
            entity["error"] = entity.get("error") or "stopped"

        def run_summary_for_batch(self, run):
            return {"status": run.get("status"), "current_stage": run.get("current_stage")}

        def refresh_evolution_batch(self, batch_id):
            pass

    ctx = FakeContext()
    svc = EvolutionRunService(ctx)
    run_id = "test_run_001"
    ctx.evolution_runs = {
        run_id: {
            "run_id": run_id,
            "role": "villager",
            "kind": "role_evolution_run",
            "status": "running",
            "config": {"training_games": 1, "battle_games": 1},
        }
    }
    request = EvolutionStartRequest(roles=["villager"], training_games=1, battle_games=1)

    async def _run():
        await svc.run_queued_evolution(run_id, request)

    asyncio.run(_run())
    run = ctx.evolution_runs[run_id]
    assert run["status"] == "failed"
    assert "simulated runner crash" in str(run.get("error", ""))
    assert any(d.get("kind") == "evolution_error" for d in run.get("diagnostics", []))


def test_run_queued_evolution_batch_handles_failure():
    """run_queued_evolution_batch marks batch as failed when setup raises."""
    import asyncio

    from ui.backend.schemas import EvolutionStartRequest
    from ui.backend.services.evolution_run_service import EvolutionRunService

    class FakeContext:
        paths = None
        model = None
        evolution_runs: dict = {}
        evolution_batches: dict = {}
        background_state_lock = type("L", (), {"acquire": lambda s: None, "release": lambda s: None})()
        _task_event_log = None

        def evolution_runner(self):
            async def _failing_runner(**kwargs):
                raise RuntimeError("batch runner crash")
            return _failing_runner

        def model_for_run(self, **kwargs):
            return None

        def heartbeat(self, **kwargs):
            pass

        def cancel_requested(self):
            return False

        def _persist_background_tasks(self):
            pass

        def _touch_background_task(self, entity, **kwargs):
            return "2026-01-01T00:00:00"

        def _append_background_diagnostic(self, entity, diag, **kwargs):
            entity.setdefault("diagnostics", []).append(diag)

        def refresh_evolution_batch(self, batch_id):
            pass

        def evolution_cancel_check(self, run_id, external=None):
            return False

        def evolution_queue_progress(self, entity, **kwargs):
            return {}

        def sync_evolution_progress(self, run_id, snapshot):
            pass

        def count_evolution_games(self, value):
            return 0

        def evolution_overall_progress(self, run):
            return {"percent": 0.0}

        def configured_evolution_role_concurrency(self, config=None):
            raise RuntimeError("concurrency config corrupted")

        def _task_progress_percent(self, entity):
            return 0.0

        def mark_evolution_stopped(self, entity):
            entity["status"] = "failed"
            entity["error"] = entity.get("error") or "stopped"

        def run_summary_for_batch(self, run):
            return {"status": run.get("status"), "current_stage": run.get("current_stage")}

    ctx = FakeContext()
    svc = EvolutionRunService(ctx)
    batch_id = "batch_001"
    run_id = "run_in_batch_001"
    ctx.evolution_batches = {
        batch_id: {
            "batch_id": batch_id,
            "kind": "role_evolution_batch",
            "status": "running",
            "runs": [run_id],
            "config": {"training_games": 1, "battle_games": 1},
        }
    }
    ctx.evolution_runs = {
        run_id: {
            "run_id": run_id,
            "role": "villager",
            "kind": "role_evolution_run",
            "status": "queued",
            "config": {"training_games": 1, "battle_games": 1},
        }
    }
    request = EvolutionStartRequest(roles=["villager"], training_games=1, battle_games=1)

    def _raising_concurrency(config=None):
        raise RuntimeError("concurrency config corrupted")

    svc.configured_evolution_role_concurrency = _raising_concurrency

    async def _run():
        await svc.run_queued_evolution_batch(batch_id, request)

    asyncio.run(_run())
    batch = ctx.evolution_batches[batch_id]
    assert batch["status"] == "failed"
    assert "concurrency config corrupted" in str(batch.get("error", ""))
