"""Top-level learning_v2 evidence pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from agent.common import read_json, read_jsonl, write_json, write_jsonl, write_text
from agent.infrastructure.llm import ModelAdapter
from agent.learning_v2.judge import judge_game_evidence
from agent.learning_v2.models import (
    DecisionEvidenceInput,
    EvidenceRunResult,
    GameEvidence,
    GameEvidenceBundle,
    KeyDecision,
)
from agent.learning_v2.normalizer import normalize_decisions
from agent.learning_v2.selector import select_key_decisions


async def run_evidence_pipeline(
    game_dir: Path | str,
    model: ModelAdapter | None = None,
    output_dir: Path | str | None = None,
    *,
    use_llm: bool = True,
) -> EvidenceRunResult:
    bundle = load_game_bundle(game_dir)
    evidence_inputs = normalize_decisions(bundle)
    key_decisions = select_key_decisions(evidence_inputs, bundle)

    if use_llm:
        if model is None:
            result = _base_result(bundle.game_id, bundle.archive.get("winner"), evidence_inputs, key_decisions)
            result.errors.append("use_llm=True requires a model")
        else:
            result = await judge_game_evidence(model, bundle, evidence_inputs, key_decisions)
    else:
        result = _base_result(bundle.game_id, bundle.archive.get("winner"), evidence_inputs, key_decisions)

    out = Path(output_dir) if output_dir else Path(game_dir) / "learning_v2"
    result.output_dir = out
    report = render_evidence_report(result)
    write_evidence_outputs(result, report, out)
    return result


def _base_result(
    game_id: str,
    winner: object,
    evidence_inputs: list[DecisionEvidenceInput],
    key_decisions: list[KeyDecision],
) -> EvidenceRunResult:
    return EvidenceRunResult(
        game_id=game_id,
        evidence_inputs=evidence_inputs,
        key_decisions=key_decisions,
        game_evidence=GameEvidence(winner=str(winner or "")),
    )


def load_game_bundle(game_dir: Path | str) -> GameEvidenceBundle:
    base = Path(game_dir)
    archive = read_json(base / "archive.json")
    meta_path = base / "meta.json"
    meta = read_json(meta_path) if meta_path.exists() else {}
    game_id = str(archive.get("game_id") or meta.get("game_id") or base.name)
    return GameEvidenceBundle(
        game_dir=base,
        game_id=game_id,
        archive=archive,
        agent_decisions=read_jsonl(base / "agent_decisions.jsonl"),
        game_events=read_jsonl(base / "game_events.jsonl"),
        meta=meta,
    )


def write_evidence_outputs(
    result: EvidenceRunResult,
    report_markdown: str,
    output_dir: Path | str,
) -> None:
    base = Path(output_dir)
    write_jsonl(base / "evidence_inputs.jsonl", result.evidence_inputs)
    write_json(base / "key_decisions.json", [item.to_dict() for item in result.key_decisions])
    write_jsonl(base / "decision_evidence.jsonl", result.decision_evidence)
    write_json(base / "game_evidence.json", result.game_evidence.to_dict())
    write_jsonl(base / "experience_candidates.jsonl", result.experience_candidates)
    write_text(base / "evidence_report.md", report_markdown)
    if result.raw_output:
        write_text(base / "raw_judge_output.txt", result.raw_output)
    if result.errors:
        write_json(base / "errors.json", result.errors)


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
