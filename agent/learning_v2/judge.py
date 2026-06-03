"""Batch LLM judge for learning_v2 evidence."""

from __future__ import annotations

from typing import Any

from agent.infrastructure.llm import ModelAdapter
from agent.knowledge.prompts.parsing import load_json_object
from agent.learning_v2.models import (
    DecisionEvidence,
    DecisionEvidenceInput,
    EvidenceRunResult,
    ExperienceCandidate,
    GameEvidence,
    GameEvidenceBundle,
    KeyDecision,
)
from agent.learning_v2.prompts import build_batch_evidence_messages


async def judge_game_evidence(
    model: ModelAdapter,
    bundle: GameEvidenceBundle,
    evidence_inputs: list[DecisionEvidenceInput],
    key_decisions: list[KeyDecision],
) -> EvidenceRunResult:
    messages = build_batch_evidence_messages(
        bundle=bundle,
        evidence_inputs=evidence_inputs,
        key_decisions=key_decisions,
    )
    raw = ""
    try:
        raw = await model.complete(messages, name=f"learning_v2/{bundle.game_id}")
        data = load_json_object(raw)
        return EvidenceRunResult(
            game_id=bundle.game_id,
            evidence_inputs=evidence_inputs,
            key_decisions=key_decisions,
            decision_evidence=[_decision_evidence_from_dict(row) for row in data.get("decision_evidence", [])],
            game_evidence=_game_evidence_from_dict(data.get("game_evidence") or {}),
            experience_candidates=[_candidate_from_dict(row) for row in data.get("experience_candidates", [])],
            raw_output=raw,
        )
    except Exception as exc:
        return EvidenceRunResult(
            game_id=bundle.game_id,
            evidence_inputs=evidence_inputs,
            key_decisions=key_decisions,
            raw_output=raw,
            errors=[str(exc)],
        )


def _decision_evidence_from_dict(data: dict[str, Any]) -> DecisionEvidence:
    return DecisionEvidence(
        decision_id=str(data.get("decision_id") or ""),
        result_quality=str(data.get("result_quality") or "unclear"),
        process_quality=str(data.get("process_quality") or "unclear"),
        sample_type=str(data.get("sample_type") or "unclear"),
        dimension_scores=dict(data.get("dimension_scores") or {}),
        evidence_notes=[str(x) for x in data.get("evidence_notes", [])],
        better_alternatives=dict(data.get("better_alternatives") or {}),
        role_specific_evaluation=dict(data.get("role_specific_evaluation") or {}),
        information_flow_effect=dict(data.get("information_flow_effect") or {}),
        error_types=[str(x) for x in data.get("error_types", [])],
    )


def _game_evidence_from_dict(data: dict[str, Any]) -> GameEvidence:
    return GameEvidence(
        winner=str(data.get("winner") or ""),
        win_path=dict(data.get("win_path") or {}),
        turning_points=list(data.get("turning_points") or []),
        information_threads=list(data.get("information_threads") or []),
        team_coordination=dict(data.get("team_coordination") or {}),
        positive_samples=[str(x) for x in data.get("positive_samples", [])],
        negative_samples=[str(x) for x in data.get("negative_samples", [])],
        misleading_conclusions=[str(x) for x in data.get("misleading_conclusions", [])],
    )


def _candidate_from_dict(data: dict[str, Any]) -> ExperienceCandidate:
    return ExperienceCandidate(
        candidate_id=str(data.get("candidate_id") or ""),
        role=str(data.get("role") or ""),
        faction=str(data.get("faction") or ""),
        candidate_type=str(data.get("candidate_type") or ""),
        topic=str(data.get("topic") or ""),
        sample_source=str(data.get("sample_source") or ""),
        evidence_decision_ids=[str(x) for x in data.get("evidence_decision_ids", [])],
        scenario=str(data.get("scenario") or ""),
        conditions=[str(x) for x in data.get("conditions", [])],
        recommendation=str(data.get("recommendation") or ""),
        anti_pattern=str(data.get("anti_pattern") or ""),
        risk_boundaries=[str(x) for x in data.get("risk_boundaries", [])],
        counter_conditions=[str(x) for x in data.get("counter_conditions", [])],
        supporting_evidence=list(data.get("supporting_evidence") or []),
        opposing_evidence=list(data.get("opposing_evidence") or []),
        confidence=str(data.get("confidence") or "low"),
        validation_need=dict(data.get("validation_need") or {"needs_multi_game_validation": True}),
        misleading_risk=str(data.get("misleading_risk") or "medium"),
    )

