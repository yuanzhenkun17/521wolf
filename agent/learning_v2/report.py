"""Markdown report rendering for learning_v2 evidence."""

from __future__ import annotations

import json

from agent.learning_v2.models import EvidenceRunResult


def render_evidence_report(result: EvidenceRunResult) -> str:
    lines: list[str] = [
        "# 对局证据报告",
        "",
        "## 对局概览",
        "",
        f"- game_id: `{result.game_id}`",
        f"- key_decisions: `{len(result.key_decisions)}`",
        f"- decision_evidence: `{len(result.decision_evidence)}`",
        f"- experience_candidates: `{len(result.experience_candidates)}`",
        "",
        "## 胜负路径",
        "",
        _format_json(result.game_evidence.win_path or {"winner": result.game_evidence.winner}),
        "",
        "## 关键转折",
        "",
        _format_json(result.game_evidence.turning_points),
        "",
        "## 关键决策证据",
        "",
    ]
    if result.decision_evidence:
        for item in result.decision_evidence:
            lines.extend(
                [
                    f"### `{item.decision_id}`",
                    "",
                    f"- result_quality: `{item.result_quality}`",
                    f"- process_quality: `{item.process_quality}`",
                    f"- sample_type: `{item.sample_type}`",
                    f"- notes: {'；'.join(item.evidence_notes) if item.evidence_notes else ''}",
                    "",
                ]
            )
    else:
        lines.extend(["暂无 LLM 决策证据。", ""])

    lines.extend(
        [
            "## 角色目标评估",
            "",
            _format_json([item.role_specific_evaluation for item in result.decision_evidence]),
            "",
            "## 更优替代决策",
            "",
            _format_json({item.decision_id: item.better_alternatives for item in result.decision_evidence}),
            "",
            "## 信息流分析",
            "",
            _format_json(result.game_evidence.information_threads),
            "",
            "## 阵营协作分析",
            "",
            _format_json(result.game_evidence.team_coordination),
            "",
            "## 正样本",
            "",
            _format_json(result.game_evidence.positive_samples),
            "",
            "## 负样本",
            "",
            _format_json(result.game_evidence.negative_samples),
            "",
            "## 经验候选",
            "",
            _format_json([item.to_dict() for item in result.experience_candidates]),
            "",
            "## 不应学习的误导性结论",
            "",
            _format_json(result.game_evidence.misleading_conclusions),
        ]
    )
    if result.errors:
        lines.extend(["", "## 错误", "", _format_json(result.errors)])
    return "\n".join(lines).rstrip() + "\n"


def _format_json(value: object) -> str:
    if value in ({}, [], None):
        return "暂无。"
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n```"

