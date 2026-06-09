from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

from app.tools.export_langfuse_annotation_queue import build_annotation_queue, export_annotation_queue, main


def _sample_payload() -> dict[str, Any]:
    return {
        "kind": "benchmark_batch_detail",
        "batch_id": "bench_queue",
        "benchmark": {
            "id": "role-baseline-v1",
            "version": 1,
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "target_type": "role_version",
        },
        "results": [
            {
                "batch_id": "bench_queue_seer",
                "result_batch_id": "bench_queue_seer",
                "config": {
                    "target_role": "seer",
                    "target_version_id": "seer_candidate_v2",
                    "evaluation_set_id": "role-baseline-v1@v1",
                    "seed_set_id": "role-baseline-quick-202606",
                },
                "rankable": False,
                "rankable_reason": "quality gate failed",
                "leaderboard_gate": {
                    "accepted": False,
                    "reason": "quality_gate_failed",
                    "metrics": {"valid_game_rate": 0.5},
                },
                "score_summary": {
                    "decision_judge_aggregate": {
                        "status": "degraded",
                        "average_score": 4.6,
                        "metrics": {"judged": 2},
                    }
                },
                "games": [
                    {
                        "game_id": "bench_queue_seer_game_001",
                        "status": "completed",
                        "seed": 260600,
                        "winner": "villagers",
                        "decisions": [
                            {
                                "decision_id": "clean_d1",
                                "action_type": "seer_check",
                                "private_reasoning": "CLEAN_PRIVATE_REASONING_SHOULD_NOT_EXPORT",
                                "prompt": "CLEAN_PROMPT_SHOULD_NOT_EXPORT",
                            }
                        ],
                    },
                    {
                        "game_id": "bench_queue_seer_game_002",
                        "status": "completed",
                        "seed": 260607,
                        "winner": "werewolves",
                        "langfuse_trace_id": "trace-game-002",
                        "langfuse_trace_url": "http://langfuse.local/project/p/traces/trace-game-002",
                        "langfuse_dataset_run_id": "dataset-run-002",
                        "langfuse_dataset_run_item_id": "dataset-run-item-002",
                        "langfuse_experiment_url": (
                            "http://langfuse.local/project/p/datasets/dataset/runs/dataset-run-002"
                        ),
                        "fallback_count": 1,
                        "diagnostics": [
                            {
                                "kind": "llm_error",
                                "stage": "llm.call",
                                "level": "warning",
                                "message": "transient LLM timeout",
                                "raw_messages": [{"role": "user", "content": "RAW_MESSAGES_SHOULD_NOT_EXPORT"}],
                            }
                        ],
                        "decisions": [
                            {
                                "decision_id": "bad_d1",
                                "day": 1,
                                "phase": "night",
                                "player_id": 3,
                                "role": "seer",
                                "action_type": "seer_check",
                                "selected_target": 8,
                                "source": "fallback",
                                "private_reasoning": "BAD_PRIVATE_REASONING_SHOULD_NOT_EXPORT",
                                "prompt": "BAD_PROMPT_SHOULD_NOT_EXPORT",
                                "judge": {
                                    "score": 3.2,
                                    "quality": "bad",
                                    "reason": "missed obvious pressure chain",
                                    "suggestion": "prioritize live vote pressure",
                                },
                            }
                        ],
                    },
                    {
                        "game_id": "bench_queue_seer_game_003",
                        "status": "completed",
                        "seed": 260614,
                        "winner": "villagers",
                        "policy_adjusted_count": 1,
                        "decisions": [
                            {
                                "decision_id": "adjusted_d1",
                                "action_type": "vote",
                                "policy_adjustments": ["invalid target replaced by abstain"],
                            }
                        ],
                    },
                ],
            }
        ],
        "problem_games": [
            {
                "game_id": "bench_queue_seer_game_002",
                "status": "completed",
                "seed": 260607,
                "langfuse": {
                    "trace_id": "trace-game-002",
                    "trace_url": "http://langfuse.local/project/p/traces/trace-game-002",
                    "dataset_run_id": "dataset-run-002",
                    "dataset_run_item_id": "dataset-run-item-002",
                    "experiment_url": "http://langfuse.local/project/p/datasets/dataset/runs/dataset-run-002",
                },
                "diagnostic_count": 1,
                "error_count": 1,
                "fallback_count": 1,
                "diagnostics": [{"kind": "game_failure", "level": "warning", "message": "problem list copy"}],
            }
        ],
    }


def test_build_annotation_queue_filters_dedupes_and_sorts_by_priority() -> None:
    report = build_annotation_queue([_sample_payload()], ui_base_url="http://localhost:5173")

    assert report["dry_run"] is True
    assert report["langfuse"]["write_enabled"] is False
    items = report["items"]
    assert report["item_count"] == 3
    assert [item["priority_score"] for item in items] == sorted(
        [item["priority_score"] for item in items],
        reverse=True,
    )

    game_items = [item for item in items if item["metadata"]["annotation_scope"] == "game"]
    assert [item["metadata"]["game_id"] for item in game_items] == [
        "bench_queue_seer_game_002",
        "bench_queue_seer_game_003",
    ]
    top = game_items[0]
    assert {"llm_error", "fallback", "problem_game", "decision_judge_low_score"}.issubset(
        set(top["reason_codes"])
    )
    assert top["metadata"]["trace_id"] == "trace-game-002"
    assert top["metadata"]["trace_url"] == "http://langfuse.local/project/p/traces/trace-game-002"
    assert top["metadata"]["experiment_url"] == (
        "http://langfuse.local/project/p/datasets/dataset/runs/dataset-run-002"
    )
    assert top["metadata"]["batch_id"] == "bench_queue"
    assert top["metadata"]["result_batch_id"] == "bench_queue_seer"
    assert top["metadata"]["seed"] == 260607
    assert top["metadata"]["ui_deep_link"] == (
        "http://localhost:5173/benchmark/batch/bench_queue/games?game_id=bench_queue_seer_game_002"
    )
    assert top["metadata"]["decision_ids"] == ["bad_d1"]

    adjusted = next(item for item in game_items if item["metadata"]["game_id"] == "bench_queue_seer_game_003")
    assert adjusted["reason_codes"] == ["policy_adjusted"]

    batch_item = next(item for item in items if item["metadata"]["annotation_scope"] == "batch")
    assert {"leaderboard_gate_failed", "decision_judge_low_score"}.issubset(set(batch_item["reason_codes"]))
    assert batch_item["metadata"]["batch_id"] == "bench_queue"
    assert batch_item["metadata"]["result_batch_id"] == "bench_queue_seer"


def test_build_annotation_queue_exports_promotion_gate_boundary_samples() -> None:
    payload = {
        "run_id": "evolve_seer_001",
        "role": "seer",
        "release_gate": {
            "schema_version": "promotion_gate_v2",
            "decision": "review_required",
            "review_reasons": ["proposal_overfit_risk_high"],
            "metrics": {"paired_valid_count": 1, "scenario_count": 1},
        },
        "gate_report": {
            "gate_report_id": "gate_fixture",
            "promotion_gate": {
                "promote_allowed": False,
                "recommendation": "review",
                "reasons": ["battle_not_significant"],
                "significance": {"passed": True, "win_rate_delta": 0.04},
            },
        },
    }

    report = build_annotation_queue([payload], ui_base_url="http://localhost:5173")

    assert report["item_count"] >= 1
    gate_items = [item for item in report["items"] if item["metadata"]["annotation_scope"] == "gate"]
    assert gate_items
    assert "promotion_gate_boundary" in gate_items[0]["reason_codes"]
    assert gate_items[0]["metadata"]["run_id"] == "evolve_seer_001"
    assert gate_items[0]["metadata"]["ui_deep_link"] == "http://localhost:5173/evolution-runs/evolve_seer_001"


def test_queue_export_does_not_include_private_reasoning_or_raw_prompts() -> None:
    report = build_annotation_queue([_sample_payload()])
    serialized = json.dumps(report, ensure_ascii=False)

    assert "BAD_PRIVATE_REASONING_SHOULD_NOT_EXPORT" not in serialized
    assert "BAD_PROMPT_SHOULD_NOT_EXPORT" not in serialized
    assert "RAW_MESSAGES_SHOULD_NOT_EXPORT" not in serialized
    assert "CLEAN_PRIVATE_REASONING_SHOULD_NOT_EXPORT" not in serialized
    assert "private_reasoning_exported" in serialized
    assert all(item["privacy"]["private_reasoning_exported"] is False for item in report["items"])
    assert all(item["privacy"]["raw_prompt_exported"] is False for item in report["items"])


def test_export_annotation_queue_writes_local_json_without_observability(monkeypatch: Any, tmp_path: Path) -> None:
    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.get_langfuse_client = lambda: (_ for _ in ()).throw(
        AssertionError("local export must not construct a Langfuse client")
    )
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)

    input_path = tmp_path / "payload.json"
    output_path = tmp_path / "queue.json"
    input_path.write_text(json.dumps(_sample_payload()), encoding="utf-8")

    report = export_annotation_queue([input_path], output_path=output_path, ui_base_url="http://localhost:5173")

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["schema_version"] == "langfuse_annotation_queue_export_v1"
    assert written["item_count"] == report["item_count"]
    assert written["items"][0]["metadata"]["trace_id"] == "trace-game-002"


def test_main_prints_json_when_output_is_omitted(tmp_path: Path, capsys: Any) -> None:
    input_path = tmp_path / "payload.json"
    input_path.write_text(json.dumps(_sample_payload()), encoding="utf-8")

    exit_code = main([str(input_path), "--max-items", "1"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["item_count"] == 1
    assert output["items"][0]["metadata"]["trace_id"] == "trace-game-002"
