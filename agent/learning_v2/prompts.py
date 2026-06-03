"""Prompt construction for batch evidence judging."""

from __future__ import annotations

import json
from typing import Any

from agent.learning_v2.models import DecisionEvidenceInput, GameEvidenceBundle, KeyDecision
from agent.learning_v2.rubrics import get_action_focus, get_role_rubric


SYSTEM_PROMPT = """你是狼人杀 selfplay 的证据层评估器。

你的任务不是修改 skill，也不是给玩家简单打分。你只生成证据。

硬性规则：
1. 过程判断只能基于 player_view。
2. 结果判断才允许使用 god_view_after_game。
3. 每个判断必须引用 decision_id。
4. 每个关键决策都必须输出 better_alternatives；没有更优替代时写 no_better_alternative。
5. 每个关键决策都必须输出 role_specific_evaluation。
6. 单局只能生成 experience_candidates，不能写长期经验，不能修改 skill。
7. 区分 strategy_error 和 execution_issue。

只输出一个 JSON object，不要输出 Markdown。
"""


def build_batch_evidence_messages(
    *,
    bundle: GameEvidenceBundle,
    evidence_inputs: list[DecisionEvidenceInput],
    key_decisions: list[KeyDecision],
) -> list[dict[str, str]]:
    key_ids = {item.decision_id for item in key_decisions}
    compact_inputs = [item.to_dict() for item in evidence_inputs if item.decision_id in key_ids]
    rubrics = {
        item.decision_id: {
            "role_rubric": get_role_rubric(item.player_view.role),
            "action_focus": get_action_focus(item.action_type, item.player_view.role),
        }
        for item in evidence_inputs
        if item.decision_id in key_ids
    }
    payload: dict[str, Any] = {
        "game": {
            "game_id": bundle.game_id,
            "winner": bundle.archive.get("winner"),
            "player_roles": bundle.archive.get("player_roles"),
        },
        "key_decisions": [item.to_dict() for item in key_decisions],
        "decision_inputs": compact_inputs,
        "role_and_action_rubrics": rubrics,
        "required_output_schema": _schema_hint(),
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2, default=str)},
    ]


def _schema_hint() -> dict[str, Any]:
    return {
        "decision_evidence": [
            {
                "decision_id": "string",
                "result_quality": "positive|negative|mixed|neutral|unclear",
                "process_quality": "strong|reasonable|weak|poor|unclear",
                "sample_type": "strong_positive|lucky_positive|reasonable_failure|true_error|execution_issue|low_learning_value|unclear",
                "dimension_scores": {
                    "role_objective_alignment": "0-5",
                    "information_use": "0-5",
                    "reasoning_quality": "0-5",
                    "communication_value": "0-5",
                    "team_coordination": "0-5",
                    "risk_control": "0-5",
                },
                "evidence_notes": ["string"],
                "better_alternatives": {
                    "available_actions": [],
                    "recommended_alternative": {},
                    "why_better": [],
                    "risks": [],
                    "counterfactual_outcome": {},
                    "no_better_alternative": False,
                    "reason": "",
                },
                "role_specific_evaluation": {
                    "role": "string",
                    "phase_objective": "string",
                    "decision_expectation": "string",
                    "alignment_reason": "string",
                    "role_specific_risks": [],
                },
                "information_flow_effect": {
                    "received_information": [],
                    "ignored_information": [],
                    "communicated_information": [],
                    "influenced_players": [],
                    "distortion_or_misread": [],
                },
                "error_types": [],
            }
        ],
        "game_evidence": {
            "winner": "string",
            "win_path": {},
            "turning_points": [],
            "information_threads": [],
            "team_coordination": {},
            "positive_samples": [],
            "negative_samples": [],
            "misleading_conclusions": [],
        },
        "experience_candidates": [
            {
                "candidate_id": "string",
                "role": "string",
                "faction": "string",
                "candidate_type": "positive_pattern|anti_pattern|boundary_warning",
                "topic": "string",
                "sample_source": "string",
                "evidence_decision_ids": [],
                "scenario": "string",
                "conditions": [],
                "recommendation": "string",
                "anti_pattern": "string",
                "risk_boundaries": [],
                "counter_conditions": [],
                "supporting_evidence": [],
                "opposing_evidence": [],
                "confidence": "low|medium|high",
                "validation_need": {"needs_multi_game_validation": True},
                "misleading_risk": "low|medium|high",
            }
        ],
    }

