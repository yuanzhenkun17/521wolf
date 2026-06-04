"""Structured models for the learning_v2 evidence layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.common import DictMixin


@dataclass(slots=True)
class GameEvidenceBundle(DictMixin):
    game_dir: Path
    game_id: str
    archive: dict[str, Any]
    agent_decisions: list[dict[str, Any]]
    game_events: list[dict[str, Any]]
    meta: dict[str, Any]


@dataclass(slots=True)
class PlayerView(DictMixin):
    player_id: int | None
    role: str
    candidates: list[Any] = field(default_factory=list)
    observation_summary: Any = None
    memory_context: dict[str, Any] = field(default_factory=dict)
    belief_context: dict[str, Any] = field(default_factory=dict)
    prompt_messages: list[dict[str, Any]] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentReasoning(DictMixin):
    private_reasoning: str = ""
    alternatives: list[Any] = field(default_factory=list)
    rejected_reasons: list[str] = field(default_factory=list)
    confidence: float | None = None
    memory_summary: list[Any] = field(default_factory=list)
    raw_output: str = ""


@dataclass(slots=True)
class DecisionResult(DictMixin):
    selected_target: Any = None
    selected_choice: Any = None
    public_text: str = ""
    final_response: Any = None
    source: str = ""
    errors: list[Any] = field(default_factory=list)
    policy_adjustments: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class GodViewAfterGame(DictMixin):
    player_roles: dict[str, str] = field(default_factory=dict)
    winner: str = ""
    target_true_role: str | None = None
    eventual_outcome: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DecisionEvidenceInput(DictMixin):
    decision_id: str
    decision_index: int | None
    day: int | None
    phase: str
    action_type: str
    player_view: PlayerView
    agent_reasoning: AgentReasoning
    decision_result: DecisionResult
    god_view_after_game: GodViewAfterGame


@dataclass(slots=True)
class KeyDecision(DictMixin):
    decision_id: str
    day: int | None
    phase: str
    action_type: str
    player_id: int | None
    role: str
    key_reason: str
    impact_level: str
    turning_point_id: str | None = None
    selection_notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DecisionEvidence(DictMixin):
    decision_id: str
    result_quality: str = "unclear"
    process_quality: str = "unclear"
    sample_type: str = "unclear"
    dimension_scores: dict[str, Any] = field(default_factory=dict)
    evidence_notes: list[str] = field(default_factory=list)
    better_alternatives: dict[str, Any] = field(default_factory=dict)
    role_specific_evaluation: dict[str, Any] = field(default_factory=dict)
    information_flow_effect: dict[str, Any] = field(default_factory=dict)
    error_types: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GameEvidence(DictMixin):
    winner: str = ""
    win_path: dict[str, Any] = field(default_factory=dict)
    turning_points: list[dict[str, Any]] = field(default_factory=list)
    information_threads: list[dict[str, Any]] = field(default_factory=list)
    team_coordination: dict[str, Any] = field(default_factory=dict)
    positive_samples: list[str] = field(default_factory=list)
    negative_samples: list[str] = field(default_factory=list)
    misleading_conclusions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExperienceCandidate(DictMixin):
    candidate_id: str
    role: str = ""
    faction: str = ""
    candidate_type: str = ""
    topic: str = ""
    sample_source: str = ""
    evidence_decision_ids: list[str] = field(default_factory=list)
    scenario: str = ""
    conditions: list[str] = field(default_factory=list)
    recommendation: str = ""
    anti_pattern: str = ""
    risk_boundaries: list[str] = field(default_factory=list)
    counter_conditions: list[str] = field(default_factory=list)
    supporting_evidence: list[Any] = field(default_factory=list)
    opposing_evidence: list[Any] = field(default_factory=list)
    confidence: str = "low"
    validation_need: dict[str, Any] = field(default_factory=dict)
    misleading_risk: str = "medium"


@dataclass(slots=True)
class EvidenceRunResult(DictMixin):
    game_id: str
    output_dir: Path | None = None
    evidence_inputs: list[DecisionEvidenceInput] = field(default_factory=list)
    key_decisions: list[KeyDecision] = field(default_factory=list)
    decision_evidence: list[DecisionEvidence] = field(default_factory=list)
    game_evidence: GameEvidence = field(default_factory=GameEvidence)
    experience_candidates: list[ExperienceCandidate] = field(default_factory=list)
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)
