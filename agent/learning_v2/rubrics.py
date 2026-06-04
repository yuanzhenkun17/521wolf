"""Role-specific evaluation rubrics for evidence prompts."""

from __future__ import annotations

from typing import Any

from agent.common.action_types import AGENT_ACTION_TYPES

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

# Action focus rubrics — each key must be a valid ActionType value.
ACTION_FOCUS: dict[str, list[str]] = {
    "seer_check": ["information_use", "role_objective_alignment", "risk_control"],
    "witch_act": ["information_use", "risk_control", "role_objective_alignment"],
    "guard_protect": ["risk_control", "role_objective_alignment"],
    "hunter_shoot": ["risk_control", "information_use", "role_objective_alignment"],
    "werewolf_kill": ["threat_targeting", "pack_coordination", "risk_control"],
    "speak": ["communication_value", "team_coordination", "reasoning_quality"],
    "sheriff_speak": ["communication_value", "team_coordination", "reasoning_quality"],
    "exile_vote": ["information_use", "team_coordination", "risk_control"],
    "pk_vote": ["information_use", "team_coordination", "risk_control"],
}

# Runtime validation: ensure all ACTION_FOCUS keys are valid ActionType values.
assert ACTION_FOCUS.keys() <= AGENT_ACTION_TYPES, (
    f"ACTION_FOCUS keys contain invalid action types: "
    f"{set(ACTION_FOCUS.keys()) - AGENT_ACTION_TYPES}"
)


def get_role_rubric(role: str) -> dict[str, Any]:
    return ROLE_RUBRICS.get(
        role,
        {"phase_objective": "根据当前身份服务阵营胜利。", "decision_expectations": [], "role_specific_risks": []},
    )


def get_action_focus(action_type: str, role: str = "") -> list[str]:
    if role in {"werewolf", "white_wolf_king"} and action_type == "speak":
        return ["deception_value", "pack_coordination", "risk_control"]
    return ACTION_FOCUS.get(action_type, ["role_objective_alignment", "information_use", "reasoning_quality"])
