"""Evidence pipeline — extraction, normalization, selection.

LLM evaluation calls live in app/services/chain.py (evidence_chain).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.util.action_types import (
    AGENT_ACTION_TYPES,
    DAY_INTERRUPT_ACTION_TYPES,
    NIGHT_SKILL_ACTION_TYPES,
    SPEECH_ACTION_TYPES,
    VOTE_ACTION_TYPES,
)
from app.util.json import DictMixin
from app.util.targets import EVENT_TARGET_KEYS, read_target_id


# ---------------------------------------------------------------------------
# Dataclass models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PlayerView(DictMixin):
    player_id: int | None
    role: str
    candidates: list[Any] = field(default_factory=list)
    observation_summary: dict[str, Any] | None = None
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
    selected_target: int | None = None
    selected_choice: str | None = None
    public_text: str = ""
    final_response: dict[str, Any] | None = None
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
    player_view: PlayerView = field(default_factory=lambda: PlayerView(player_id=None, role=""))
    agent_reasoning: AgentReasoning = field(default_factory=AgentReasoning)
    decision_result: DecisionResult = field(default_factory=DecisionResult)
    god_view_after_game: GodViewAfterGame = field(default_factory=GodViewAfterGame)


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
class GameEvidenceBundle(DictMixin):
    game_dir: Path
    game_id: str
    archive: dict[str, Any]
    agent_decisions: list[dict[str, Any]]
    game_events: list[dict[str, Any]]
    meta: dict[str, Any]


@dataclass(slots=True)
class EvidenceRunResult(DictMixin):
    game_id: str
    output_dir: Path | None = None
    input_source: str = "artifact"
    review_summary: dict[str, Any] = field(default_factory=dict)
    evidence_inputs: list[DecisionEvidenceInput] = field(default_factory=list)
    key_decisions: list[KeyDecision] = field(default_factory=list)
    decision_evidence: list[DecisionEvidence] = field(default_factory=list)
    game_evidence: GameEvidence = field(default_factory=GameEvidence)
    experience_candidates: list[ExperienceCandidate] = field(default_factory=list)
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------

def normalize_decisions(bundle: GameEvidenceBundle) -> list[DecisionEvidenceInput]:
    """Normalize raw archive decisions into structured DecisionEvidenceInput objects."""
    agent_by_id = _decisions_by_id(bundle.agent_decisions)
    roles = _bundle_roles(bundle)
    winner = str(bundle.archive.get("winner") or bundle.meta.get("winner") or "")
    final_state = _dict_value(bundle.archive.get("final_state") or bundle.meta.get("final_state"))

    normalized: list[DecisionEvidenceInput] = []
    for fallback_index, row in enumerate(_source_decisions(bundle), start=1):
        if not isinstance(row, dict):
            continue
        normalized.append(
            _normalize_decision_row(
                row=row,
                agent_by_id=agent_by_id,
                fallback_index=fallback_index,
                roles=roles,
                winner=winner,
                final_state=final_state,
            )
        )
    return normalized


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------

def select_key_decisions(
    evidence_inputs: list[DecisionEvidenceInput],
    bundle: GameEvidenceBundle,
) -> list[KeyDecision]:
    """Select high-impact key decisions from normalized evidence inputs."""
    selected: dict[str, KeyDecision] = {}

    for item in evidence_inputs:
        if _is_rule_key_action(item):
            selected[item.decision_id] = _to_key(
                item,
                key_reason="rule_natural_key_action",
                impact_level=_impact_for_action(
                    item.action_type,
                    item.decision_result.selected_choice,
                    item.decision_result.selected_target,
                ),
                note="规则上直接改变死亡、信息、轮次或票型的动作。",
            )
        elif _has_execution_signal(item):
            selected[item.decision_id] = _to_key(
                item,
                key_reason="execution_signal",
                impact_level="contextual",
                note="该决策存在 fallback、错误、策略修正或低置信度信号。",
            )

    for window in _detect_turning_windows(bundle.game_events):
        for item in evidence_inputs:
            if item.day != window.day:
                continue
            if window.phase and not _phase_matches(item.phase, window.phase):
                continue
            if item.action_type not in window.action_types:
                continue
            if item.decision_id in selected:
                _append_note(selected[item.decision_id], window.note)
                if selected[item.decision_id].turning_point_id is None:
                    selected[item.decision_id].turning_point_id = window.turning_point_id
                continue
            selected[item.decision_id] = _to_key(
                item,
                key_reason="turning_point_window",
                impact_level="contextual",
                turning_point_id=window.turning_point_id,
                note=window.note,
            )

    input_by_id = {item.decision_id: item for item in evidence_inputs}
    ranked = sorted(
        selected.values(),
        key=lambda item: _key_decision_sort_key(item, input_by_id.get(item.decision_id)),
    )
    return _diversify_key_decisions(ranked)


# ---------------------------------------------------------------------------
# Rubrics
# ---------------------------------------------------------------------------

RUBRIC_DIMENSIONS = ["result_quality", "process_quality", "role_alignment", "information_flow", "sample_type"]

ROLE_RUBRICS: dict[str, dict[str, Any]] = {
    "villager": {
        "phase_objective": "找狼、归票、保护可信神职、推动好人共识。",
        "decision_expectations": [
            "基于公开信息形成合理怀疑。",
            "帮助场上形成有效归票。",
            "接住神职信息或关键逻辑。",
            "避免空泛发言和无意义跟票。",
        ],
        "role_specific_risks": ["跟错票", "未能公开阻止错误归票", "忽略可信神职信息"],
    },
    "seer": {
        "phase_objective": "最大化查验信息收益，并让可信信息被好人阵营接住。",
        "decision_expectations": [
            "查验目标有信息增量。",
            "查验结果被有效传播。",
            "规划后续信息输出。",
            "避免过早、无收益或无保护地暴露。",
        ],
        "role_specific_risks": ["查验低收益目标", "信息没有传达", "暴露后没有让好人接住信息"],
    },
    "witch": {
        "phase_objective": "用救药和毒药控制死亡风险与收益。",
        "decision_expectations": [
            "救人考虑刀口可信度、身份价值和药效收益。",
            "毒人有足够狼证据。",
            "低信息局面谨慎用毒。",
            "评估不开药或留药的收益。",
        ],
        "role_specific_risks": ["低信息开毒", "救药浪费", "毒杀关键好人"],
    },
    "hunter": {
        "phase_objective": "通过开枪或不开枪制造威慑，并避免错误带走好人关键角色。",
        "decision_expectations": [
            "开枪目标有足够狼证据。",
            "不开枪有助于保留信息或避免误伤。",
            "用身份威慑影响狼人和票型。",
        ],
        "role_specific_risks": ["错误开枪", "带走神职", "威慑没有转化为信息收益"],
    },
    "guard": {
        "phase_objective": "保护高价值目标，并控制连守限制和守毒冲突风险。",
        "decision_expectations": [
            "守护目标符合刀口概率和身份价值。",
            "考虑前一夜守护记录。",
            "避免机械守护或与女巫救药冲突。",
        ],
        "role_specific_risks": ["机械守人", "守毒冲突", "忽略高价值刀口"],
    },
    "werewolf": {
        "phase_objective": "隐藏身份、误导好人、保护狼队、制造错误共识并选择高价值夜刀。",
        "decision_expectations": [
            "夜刀瞄准高价值目标。",
            "发言转移焦点且不暴露狼队。",
            "投票配合狼队节奏。",
            "必要时倒钩、冲票或牺牲队友。",
            "避免为了个人存活破坏狼队整体收益。",
        ],
        "role_specific_risks": ["暴露狼队", "夜刀低价值目标", "票型配合失败"],
    },
    "white_wolf_king": {
        "phase_objective": "在合适时机自爆带走高价值目标，并改变轮次节奏。",
        "decision_expectations": [
            "自爆时机能最大化收益。",
            "带人目标足够关键。",
            "避免过早自爆导致狼队节奏受损。",
            "利用自爆前发言制造误导或掩护队友。",
        ],
        "role_specific_risks": ["过早自爆", "带人低价值", "没有掩护队友"],
    },
}

ROLE_ACTION_RUBRICS: dict[str, dict[str, dict[str, Any]]] = {
    "seer": {
        "seer_check": {
            "focus": "查验是否解决当前站边、票型或身份链中的关键矛盾。",
            "criteria": [
                "查验目标能打开多人关系，而不是只验证低价值单点。",
                "查验结果能服务后续警徽流、遗言或白天归票。",
                "避免重复查已经高度可信、已可推出或信息增量很低的位置。",
            ],
            "mistake_tags": ["low_information_gain", "unclear_badge_flow"],
            "related_skills": ["seer/check_priority.md", "seer/sheriff_badge_flow.md"],
        },
        "sheriff_run": {
            "focus": "是否用上警行为建立可信预言家信息链。",
            "criteria": [
                "上警目的明确，能说明验人、站边和后续警徽安排。",
                "对跳或压力下仍能区分已知信息、推理和怀疑。",
            ],
            "mistake_tags": ["unclear_badge_flow", "poor_counter_claim_handling"],
            "related_skills": ["seer/sheriff_badge_flow.md", "seer/claim_and_vote.md"],
        },
        "sheriff_speak": {
            "focus": "警上发言是否清晰传播查验链和警徽流。",
            "criteria": [
                "清楚交代查验结果、警徽流和站边逻辑。",
                "被对跳时优先拆解信息收益，而不是只情绪化互踩。",
            ],
            "mistake_tags": ["unclear_badge_flow", "poor_counter_claim_handling"],
            "related_skills": ["seer/sheriff_badge_flow.md", "seer/claim_and_vote.md"],
        },
        "sheriff_badge": {
            "focus": "警徽移交或处置是否最大化预言家信息延续。",
            "criteria": [
                "优先交给能承接验人信息和归票权的可信好人。",
                "避免把警徽交给身份未明且可能扰乱信息链的位置。",
            ],
            "mistake_tags": ["unclear_badge_flow"],
            "related_skills": ["seer/sheriff_badge_flow.md"],
        },
    },
    "witch": {
        "witch_act": {
            "focus": "救药和毒药是否在收益、风险和信息边界之间取得平衡。",
            "criteria": [
                "解药优先覆盖高价值且刀口可信的好人目标。",
                "毒药需要足够狼证据，低信息局面应避免情绪毒或证明身份式用毒。",
                "考虑守卫、猎人、白狼王和药况暴露带来的次生风险。",
            ],
            "mistake_tags": ["medicine_overuse", "poison_low_confidence"],
            "related_skills": ["witch/medicine_policy.md", "witch/save_poison_boundary.md"],
        },
        "speak": {
            "focus": "白天发言是否保护药况信息，同时推动可信归票。",
            "criteria": [
                "必要时只释放能改变票型的信息，不完整暴露药况。",
                "避免为了自证提前交代全部夜间细节。",
            ],
            "mistake_tags": ["medicine_overuse", "vote_fragmentation"],
            "related_skills": ["witch/day_control_vote.md", "witch/save_poison_boundary.md"],
        },
    },
    "guard": {
        "guard_protect": {
            "focus": "守护是否符合刀口概率、高价值目标和连守节奏。",
            "criteria": [
                "优先保护信息链核心、稳定带队者或已暴露高价值神职。",
                "考虑上一轮守护和连守限制，必要时转守狼队下一刀口。",
                "避免守毒冲突和机械重复守同一类目标。",
            ],
            "mistake_tags": ["guard_tempo_error"],
            "related_skills": ["guard/protect_policy.md", "guard/protect_tempo.md"],
        },
    },
    "hunter": {
        "hunter_shoot": {
            "focus": "开枪或不开枪是否基于高置信狼证据和死亡来源判断。",
            "criteria": [
                "开枪目标应有查杀、票型、发言矛盾或收益链支持。",
                "置信度不足时，不开枪可以是保护好人阵营的正确选择。",
                "临终信息要帮助好人收敛狼坑，而不是扩大分歧。",
            ],
            "mistake_tags": ["shot_low_confidence", "vote_fragmentation"],
            "related_skills": ["hunter/shoot_policy.md", "hunter/shot_timing.md"],
        },
        "last_word": {
            "focus": "遗言是否收敛枪位和后续归票线。",
            "criteria": [
                "明确区分高置信目标、备选怀疑和不应带走的位置。",
                "给出可被复盘的票型或发言依据。",
            ],
            "mistake_tags": ["shot_low_confidence"],
            "related_skills": ["hunter/shot_timing.md"],
        },
    },
    "villager": {
        "exile_vote": {
            "focus": "投票是否基于公开信息推动好人归票收敛。",
            "criteria": [
                "优先处理能解释票型和发言矛盾的狼坑位置。",
                "避免无证据分票、情绪票或跟随未验证强势发言。",
            ],
            "mistake_tags": ["vote_fragmentation", "seer_side_misread"],
            "related_skills": ["villager/vote_policy.md", "villager/late_game_vote.md"],
        },
        "pk_vote": {
            "focus": "PK 票是否在有限候选中选择更高狼面和更高信息收益目标。",
            "criteria": [
                "比较两名候选的发言、票型、站边和被保关系。",
                "投票理由应能帮助后续回合继续推理。",
            ],
            "mistake_tags": ["vote_fragmentation", "seer_side_misread"],
            "related_skills": ["villager/late_game_vote.md", "villager/vote_policy.md"],
        },
        "speak": {
            "focus": "发言是否基于公开信息推进站边和归票。",
            "criteria": [
                "说明相信或质疑预言家线的公开依据。",
                "把怀疑对象收敛成可投票排序，避免空泛表态。",
            ],
            "mistake_tags": ["seer_side_misread", "vote_fragmentation"],
            "related_skills": ["villager/day_reasoning.md", "villager/late_game_vote.md"],
        },
    },
    "werewolf": {
        "werewolf_kill": {
            "focus": "夜刀是否优先清除关键神职、带队好人或信息链核心。",
            "criteria": [
                "目标选择能削弱好人信息链或保护狼队身份结构。",
                "避免低价值刀、情绪刀和暴露狼队站位的刀口。",
            ],
            "mistake_tags": ["low_value_night_kill", "pack_exposure"],
            "related_skills": ["werewolf/night_kill.md"],
        },
        "sheriff_run": {
            "focus": "悍跳或上警是否能制造可信伪视角并压制真信息链。",
            "criteria": [
                "伪验人、站边和发言节奏自洽。",
                "能给队友留切割或倒钩空间，而不是集体暴露。",
            ],
            "mistake_tags": ["pack_exposure", "poor_counter_claim_handling"],
            "related_skills": ["werewolf/claim_and_vote_pressure.md", "werewolf/day_cover_vote.md"],
        },
        "sheriff_speak": {
            "focus": "警上发言是否构造自洽伪视角并引导错误站边。",
            "criteria": [
                "怀疑链和验人说法能解释公开事件。",
                "不因硬保或硬踩队友造成狼队连坐。",
            ],
            "mistake_tags": ["pack_exposure", "poor_counter_claim_handling"],
            "related_skills": ["werewolf/claim_and_vote_pressure.md", "werewolf/day_cover_vote.md"],
        },
        "exile_vote": {
            "focus": "投票是否服务狼队抗推、冲票或切割节奏。",
            "criteria": [
                "票型选择要能解释，避免突兀暴露团队关系。",
                "关键轮次优先制造好人误放逐，而不是只保个人安全。",
            ],
            "mistake_tags": ["pack_exposure", "vote_fragmentation"],
            "related_skills": ["werewolf/claim_and_vote_pressure.md", "werewolf/day_cover_vote.md"],
        },
        "pk_vote": {
            "focus": "PK 票是否利用有限候选制造好人误判并保护狼队结构。",
            "criteria": [
                "在冲票、倒钩、切割之间选择团队收益最高的路线。",
                "投票理由保持前后一致，避免票型成为狼队证据。",
            ],
            "mistake_tags": ["pack_exposure"],
            "related_skills": ["werewolf/claim_and_vote_pressure.md", "werewolf/day_cover_vote.md"],
        },
    },
    "white_wolf_king": {
        "white_wolf_explode": {
            "focus": "自爆是否带来明确净收益并改变轮次节奏。",
            "criteria": [
                "带人目标应是可信神职、信息链核心或稳定带队好人。",
                "自爆时机要能挽救狼队压力、截断查验链或避免更差票型暴露。",
                "避免无收益早爆、带走低价值目标或暴露剩余队友。",
            ],
            "mistake_tags": ["bad_explode_timing", "low_value_explode_target", "pack_exposure"],
            "related_skills": ["white_wolf_king/explode_timing.md", "white_wolf_king/explode_window.md"],
        },
        "speak": {
            "focus": "自爆前发言是否误导好人并保护狼队关系。",
            "criteria": [
                "发言为可能自爆、倒钩或转移焦点留下解释空间。",
                "不在爆前把队友关系暴露成连续狼坑。",
            ],
            "mistake_tags": ["pack_exposure", "bad_explode_timing"],
            "related_skills": ["white_wolf_king/explode_window.md", "white_wolf_king/team_cover_vote.md"],
        },
    },
}

ACTION_FOCUS: dict[str, list[str]] = {
    "seer_check": ["information_use", "role_objective_alignment", "risk_control"],
    "witch_act": ["information_use", "risk_control", "role_objective_alignment"],
    "guard_protect": ["risk_control", "role_objective_alignment"],
    "hunter_shoot": ["risk_control", "information_use", "role_objective_alignment"],
    "werewolf_kill": ["threat_targeting", "pack_coordination", "risk_control"],
    "speak": ["communication_value", "team_coordination", "reasoning_quality"],
    "sheriff_speak": ["communication_value", "team_coordination", "reasoning_quality"],
    "sheriff_run": ["role_objective_alignment", "communication_value", "risk_control"],
    "sheriff_badge": ["information_flow", "team_coordination", "risk_control"],
    "last_word": ["communication_value", "information_use", "team_coordination"],
    "exile_vote": ["information_use", "team_coordination", "risk_control"],
    "pk_vote": ["information_use", "team_coordination", "risk_control"],
    "white_wolf_explode": ["timing_value", "target_value", "pack_coordination"],
}

assert ACTION_FOCUS.keys() <= AGENT_ACTION_TYPES, (
    "ACTION_FOCUS keys contain invalid action types: "
    f"{set(ACTION_FOCUS.keys()) - AGENT_ACTION_TYPES}"
)


def get_role_rubric(role: str) -> dict[str, Any]:
    return ROLE_RUBRICS.get(
        role,
        {
            "phase_objective": "根据当前身份服务阵营胜利。",
            "decision_expectations": [],
            "role_specific_risks": [],
        },
    )


def get_role_action_rubric(role: str, action_type: str) -> dict[str, Any]:
    role_text = str(role or "")
    action_text = str(action_type or "")
    role_rubrics = ROLE_ACTION_RUBRICS.get(role_text, {})
    rubric = role_rubrics.get(action_text)
    if rubric is None and action_text in {"pk_speak", "last_word"}:
        rubric = role_rubrics.get("speak")
    if rubric is None and action_text == "sheriff_vote":
        rubric = role_rubrics.get("exile_vote") or role_rubrics.get("pk_vote")
    return dict(rubric or {})


def get_decision_rubric(role: str, action_type: str) -> dict[str, Any]:
    role_text = str(role or "")
    action_text = str(action_type or "")
    role_rubric = get_role_rubric(role_text)
    action_rubric = get_role_action_rubric(role_text, action_text)
    return {
        "role": role_text,
        "action_type": action_text,
        "role_rubric": role_rubric,
        "action_focus": get_action_focus(action_text, role_text),
        "action_rubric": action_rubric,
        "expected_mistake_tags": action_rubric.get("mistake_tags", []),
        "related_skills": action_rubric.get("related_skills", []),
        "recommended_skill_files": action_rubric.get("related_skills", []),
    }


def get_action_focus(action_type: str, role: str = "") -> list[str]:
    if role in {"werewolf", "white_wolf_king"} and action_type == "speak":
        return ["deception_value", "pack_coordination", "risk_control"]
    return ACTION_FOCUS.get(action_type, ["role_objective_alignment", "information_use", "reasoning_quality"])


def score_dimension(dimension: str, evidence: DecisionEvidence) -> str:
    """Score a single evidence dimension."""
    scores = evidence.dimension_scores or {}
    if dimension in scores:
        return str(scores[dimension])
    if dimension == "result_quality":
        return evidence.result_quality
    if dimension == "process_quality":
        return evidence.process_quality
    if dimension == "sample_type":
        return evidence.sample_type
    if dimension == "role_alignment":
        value = evidence.role_specific_evaluation.get("alignment_reason") if evidence.role_specific_evaluation else None
        return "unclear" if value in (None, "") else str(value)
    if dimension == "information_flow":
        value = evidence.information_flow_effect
        return "unclear" if not value else "available"
    return "unclear"


RULE_KEY_ACTIONS: frozenset[str] = (
    NIGHT_SKILL_ACTION_TYPES
    | VOTE_ACTION_TYPES
    | DAY_INTERRUPT_ACTION_TYPES
    | frozenset({
        "hunter_shoot",
        "sheriff_run",
        "sheriff_badge",
    })
)

HIGHEST_IMPACT_ACTIONS: frozenset[str] = (
    VOTE_ACTION_TYPES
    | frozenset({
        "werewolf_kill",
    })
)

IMPACT_PRIORITY: dict[str, int] = {
    "highest": 0,
    "high": 1,
    "contextual": 2,
}

ACTION_SELECTION_PRIORITY: dict[str, int] = {
    "white_wolf_explode": 0,
    "werewolf_kill": 1,
    "witch_act": 2,
    "exile_vote": 3,
    "pk_vote": 4,
    "seer_check": 5,
    "guard_protect": 6,
    "hunter_shoot": 7,
    "sheriff_vote": 8,
    "sheriff_badge": 9,
    "sheriff_run": 10,
    "sheriff_withdraw": 11,
    "speech_order": 12,
    "speak": 80,
    "sheriff_speak": 81,
    "pk_speak": 82,
    "last_word": 83,
}

DAY_WINDOW_ACTIONS: frozenset[str] = (
    SPEECH_ACTION_TYPES
    | VOTE_ACTION_TYPES
    | frozenset({
        "sheriff_run",
    })
)

NIGHT_WINDOW_ACTIONS: frozenset[str] = (
    NIGHT_SKILL_ACTION_TYPES
    | frozenset({
        "hunter_shoot",
    })
)


@dataclass(slots=True)
class TurningWindow:
    turning_point_id: str
    day: int | None
    phase: str
    action_types: set[str] | frozenset[str]
    note: str


def _detect_turning_windows(events: list[dict[str, Any]]) -> list[TurningWindow]:
    windows: list[TurningWindow] = []
    seen_ids: set[str] = set()
    max_day = max((_as_int(event.get("day")) or 0 for event in events if isinstance(event, dict)), default=0)
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or event.get("type") or "")
        day = _as_int(event.get("day"))
        target = read_target_id(event, keys=EVENT_TARGET_KEYS, include_payload=True)
        if event_type in {"exile_result", "exile_vote_end", "pk_vote_end"}:
            _append_window(
                windows,
                seen_ids,
                TurningWindow(
                    turning_point_id=f"exile_turning_point_day_{day}_target_{target}",
                    day=day,
                    phase="day",
                    action_types=DAY_WINDOW_ACTIONS,
                    note="白天出局转折点窗口：当天发言、投票和相关遗言进入关键池。",
                ),
            )
        if event_type in {"death_result", "night_death", "werewolf_result", "witch_result", "hunter_result", "night_end"}:
            _append_window(
                windows,
                seen_ids,
                TurningWindow(
                    turning_point_id=f"death_turning_point_day_{day}_target_{target}",
                    day=day,
                    phase="night",
                    action_types=NIGHT_WINDOW_ACTIONS,
                    note="夜晚死亡/技能转折点窗口：当夜技能进入关键池。",
                ),
            )
    if max_day:
        _append_window(
            windows,
            seen_ids,
            TurningWindow(
                turning_point_id=f"endgame_turning_point_day_{max_day}",
                day=max_day,
                phase="day",
                action_types=DAY_WINDOW_ACTIONS,
                note="终局转折窗口：最后一昼夜相关决策进入关键池。",
            ),
        )
        _append_window(
            windows,
            seen_ids,
            TurningWindow(
                turning_point_id=f"endgame_turning_point_day_{max_day}_night",
                day=max_day,
                phase="night",
                action_types=NIGHT_WINDOW_ACTIONS,
                note="终局转折窗口：最后一昼夜相关夜间技能进入关键池。",
            ),
        )
    return windows


def _append_window(windows: list[TurningWindow], seen_ids: set[str], window: TurningWindow) -> None:
    if window.turning_point_id in seen_ids:
        return
    seen_ids.add(window.turning_point_id)
    windows.append(window)


def _append_note(decision: KeyDecision, note: str) -> None:
    if note not in decision.selection_notes:
        decision.selection_notes.append(note)


def _key_decision_sort_key(
    decision: KeyDecision,
    evidence_input: DecisionEvidenceInput | None,
) -> tuple[int, int, int, int, str, str]:
    return (
        IMPACT_PRIORITY.get(decision.impact_level, 3),
        ACTION_SELECTION_PRIORITY.get(decision.action_type, 60),
        _decision_index(evidence_input),
        decision.day or 0,
        decision.phase,
        decision.decision_id,
    )


def _decision_index(item: DecisionEvidenceInput | None) -> int:
    if item is None or item.decision_index is None:
        return 1_000_000
    return item.decision_index


def _diversify_key_decisions(decisions: list[KeyDecision]) -> list[KeyDecision]:
    buckets: dict[str, list[KeyDecision]] = {}
    for decision in decisions:
        buckets.setdefault(decision.action_type, []).append(decision)

    diversified: list[KeyDecision] = []
    while any(buckets.values()):
        for bucket in buckets.values():
            if bucket:
                diversified.append(bucket.pop(0))
    return diversified


def _phase_matches(actual: str, expected: str) -> bool:
    normalized = actual.lower()
    if normalized == expected:
        return True
    if expected == "day":
        return normalized.startswith("day") or normalized in {"exile_vote", "pk_vote", "sheriff_election"}
    if expected == "night":
        return normalized.startswith("night") or normalized == "night"
    return False


def _to_key(
    item: DecisionEvidenceInput,
    *,
    key_reason: str,
    impact_level: str,
    note: str,
    turning_point_id: str | None = None,
) -> KeyDecision:
    return KeyDecision(
        decision_id=item.decision_id,
        day=item.day,
        phase=item.phase,
        action_type=item.action_type,
        player_id=item.player_view.player_id,
        role=item.player_view.role,
        key_reason=key_reason,
        impact_level=impact_level,
        turning_point_id=turning_point_id,
        selection_notes=[note],
    )


def _is_rule_key_action(item: DecisionEvidenceInput) -> bool:
    if item.action_type == "white_wolf_explode":
        return (
            item.decision_result.selected_choice == "explode"
            and item.decision_result.selected_target is not None
        )
    return item.action_type in RULE_KEY_ACTIONS


def _impact_for_action(action_type: str, choice: Any, target: Any = None) -> str:
    if action_type == "witch_act" and choice == "poison":
        return "highest"
    if action_type == "white_wolf_explode":
        return "highest" if choice == "explode" and target is not None else "contextual"
    if action_type in HIGHEST_IMPACT_ACTIONS:
        return "highest"
    return "high"


def _has_execution_signal(item: DecisionEvidenceInput) -> bool:
    if item.decision_result.errors or item.decision_result.policy_adjustments:
        return True
    if item.decision_result.source in {"fallback", "llm_error", "policy_adjusted"}:
        return True
    confidence = item.agent_reasoning.confidence
    return confidence is not None and confidence < 0.35


def _decisions_by_id(decisions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("decision_id")): row
        for row in decisions
        if isinstance(row, dict) and row.get("decision_id") is not None
    }


def _source_decisions(bundle: GameEvidenceBundle) -> list[dict[str, Any]]:
    archive_decisions = bundle.archive.get("decisions") if isinstance(bundle.archive, dict) else None
    return archive_decisions if isinstance(archive_decisions, list) and archive_decisions else bundle.agent_decisions


def _bundle_roles(bundle: GameEvidenceBundle) -> dict[str, str]:
    for raw in (
        bundle.archive.get("player_roles")
        if isinstance(bundle.archive, dict) else None,
        bundle.meta.get("player_roles"),
        bundle.meta.get("roles"),
        _roles_from_events(bundle.game_events),
    ):
        roles = _normalize_roles(raw)
        if roles:
            return roles
    return {}


def _normalize_decision_row(
    *,
    row: dict[str, Any],
    agent_by_id: dict[str, dict[str, Any]],
    fallback_index: int,
    roles: dict[str, str],
    winner: str,
    final_state: dict[str, Any],
) -> DecisionEvidenceInput:
    decision_id = str(row.get("decision_id") or f"decision_{fallback_index}")
    merged = _merge_decision_rows(row, agent_by_id.get(decision_id, {}))
    parsed_decision = _dict_value(merged.get("parsed_decision"))
    final_response = _dict_value(merged.get("final_response"))
    player_id = _as_int(_first_present(merged.get("player_id"), merged.get("seat")))
    selected_target = _selected_target(merged, parsed_decision, final_response)
    selected_choice = _selected_choice(merged, parsed_decision, final_response)

    return DecisionEvidenceInput(
        decision_id=decision_id,
        decision_index=_as_int(
            _first_present(
                row.get("index"),
                row.get("decision_index"),
                merged.get("index"),
                fallback_index,
            )
        ),
        day=_as_int(merged.get("day")),
        phase=str(merged.get("phase") or ""),
        action_type=_enum_value(merged.get("action_type")),
        player_view=_build_player_view(merged, player_id, roles),
        agent_reasoning=_build_agent_reasoning(merged, parsed_decision),
        decision_result=_build_decision_result(
            merged,
            parsed_decision,
            final_response,
            selected_target=selected_target,
            selected_choice=selected_choice,
        ),
        god_view_after_game=GodViewAfterGame(
            player_roles=roles,
            winner=winner,
            target_true_role=_target_role(selected_target, roles),
            eventual_outcome={"final_state": final_state},
        ),
    )


def _merge_decision_rows(archive_row: dict[str, Any], agent_row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(archive_row)
    for key, value in agent_row.items():
        if value is not None:
            merged[key] = value
    return merged


def _selected_target(
    merged: dict[str, Any],
    parsed_decision: dict[str, Any],
    final_response: dict[str, Any],
) -> int | None:
    return read_target_id(
        merged,
        final_response,
        parsed_decision,
    )


def _selected_choice(
    merged: dict[str, Any],
    parsed_decision: dict[str, Any],
    final_response: dict[str, Any],
) -> str | None:
    value = _first_present(
        merged.get("selected_choice"),
        merged.get("choice"),
        final_response.get("choice"),
        parsed_decision.get("choice"),
    )
    return str(value) if value is not None else None


def _build_player_view(
    merged: dict[str, Any],
    player_id: int | None,
    roles: dict[str, str],
) -> PlayerView:
    role = str(
        merged.get("role")
        or (roles.get(str(player_id)) if player_id is not None else "")
        or ""
    )
    return PlayerView(
        player_id=player_id,
        role=role,
        candidates=_list_value(merged.get("candidates")),
        observation_summary=_dict_or_none(merged.get("observation_summary")),
        memory_context=_dict_value(merged.get("memory_context")),
        belief_context=_dict_value(merged.get("belief_context") or merged.get("belief_snapshot")),
        prompt_messages=_list_of_dicts(merged.get("prompt_messages")),
        selected_skills=_list_str(merged.get("selected_skills")),
    )


def _build_agent_reasoning(
    merged: dict[str, Any],
    parsed_decision: dict[str, Any],
) -> AgentReasoning:
    return AgentReasoning(
        private_reasoning=str(
            merged.get("private_reasoning")
            or merged.get("reasoning")
            or parsed_decision.get("private_reasoning")
            or ""
        ),
        alternatives=_list_value(merged.get("alternatives")),
        rejected_reasons=[str(item) for item in _list_value(merged.get("rejected_reasons"))],
        confidence=_as_float(merged.get("confidence")),
        memory_summary=_list_value(merged.get("memory_summary")),
        raw_output=str(merged.get("raw_output") or ""),
    )


def _build_decision_result(
    merged: dict[str, Any],
    parsed_decision: dict[str, Any],
    final_response: dict[str, Any],
    *,
    selected_target: int | None,
    selected_choice: str | None,
) -> DecisionResult:
    return DecisionResult(
        selected_target=selected_target,
        selected_choice=selected_choice,
        public_text=str(
            merged.get("public_text")
            or merged.get("text")
            or parsed_decision.get("public_text")
            or final_response.get("text")
            or ""
        ),
        final_response=final_response or None,
        source=str(merged.get("source") or ""),
        errors=_list_value(merged.get("errors")),
        policy_adjustments=_list_value(merged.get("policy_adjustments")),
    )


def _normalize_roles(raw: Any) -> dict[str, str]:
    data = _dict_value(raw)
    if not data:
        return {}
    return {str(key): _enum_value(value) for key, value in data.items()}


def _roles_from_events(events: list[dict[str, Any]]) -> dict[str, str]:
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = _dict_value(event.get("payload"))
        roles = payload.get("roles")
        if isinstance(roles, dict):
            normalized = _normalize_roles(roles)
            if normalized:
                return normalized
    return {}


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _target_role(target: Any, roles: dict[str, str]) -> str | None:
    if target is None:
        return None
    return roles.get(str(target))


def _list_str(value: Any) -> list[str]:
    return [str(item) for item in _list_value(value) if str(item)]


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    data = _dict_value(value)
    return data or None


def _dict_value(value: Any) -> dict[str, Any]:
    decoded = _json_value(value)
    return dict(decoded) if isinstance(decoded, dict) else {}


def _list_value(value: Any) -> list[Any]:
    decoded = _json_value(value)
    if decoded is None:
        return []
    if isinstance(decoded, list):
        return list(decoded)
    if isinstance(decoded, tuple):
        return list(decoded)
    if isinstance(decoded, str):
        return [decoded] if decoded else []
    return [decoded]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in _list_value(value) if isinstance(item, dict)]


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _enum_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "")
