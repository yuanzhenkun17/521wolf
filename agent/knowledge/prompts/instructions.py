"""Action instructions and strategy hints for prompt construction."""

from __future__ import annotations

from engine.models import ActionRequest, ActionType


def action_instruction(action_type: ActionType) -> str:
    instructions = {
        ActionType.SHERIFF_RUN: '警长竞选报名：想竞选输出 {"choice":"run"}，否则 {"choice":"pass"}。',
        ActionType.SHERIFF_SPEAK: "警上发言：在 text 中说明你为什么竞选或你的判断。",
        ActionType.SHERIFF_WITHDRAW: '退水选择：继续竞选输出 {"choice":"stay"}，退水输出 {"choice":"withdraw"}。如果没有明确让位对象，不要因为信息少就退水。',
        ActionType.SHERIFF_VOTE: "警长投票：target 选择你支持的警长候选人，也可以为 null。",
        ActionType.SHERIFF_BADGE: '警徽处理：移交输出 {"choice":"transfer","target":座位号}，撕毁输出 {"choice":"destroy"}。',
        ActionType.SPEECH_ORDER: '白天发言顺序：顺序发言输出 {"choice":"forward"}，逆序发言输出 {"choice":"reverse"}。',
        ActionType.GUARD_PROTECT: "守卫守护：target 选择一个 candidates 中的玩家。",
        ActionType.WEREWOLF_KILL: "狼人夜刀：target 选择一个 candidates 中的非狼人玩家，不允许空刀。",
        ActionType.SEER_CHECK: "预言家查验：target 选择一个 candidates 中的玩家。",
        ActionType.WITCH_ACT: '女巫用药：可输出 {"choice":"save"}、{"choice":"poison","target":座位号} 或 {"choice":"none"}。',
        ActionType.LAST_WORD: "遗言：在 text 中留下你的判断。",
        ActionType.SPEAK: "白天发言：在 text 中陈述你的判断、怀疑对象或站边。",
        ActionType.WHITE_WOLF_EXPLODE: '白狼王自爆：自爆带人则给 target；不自爆输出 {"choice":"pass"}。',
        ActionType.EXILE_VOTE: "放逐投票：target 选择 candidates 中你最想放逐的人，也可以为 null。",
        ActionType.PK_SPEAK: "PK 发言：在 text 中表达你为什么不该被出。",
        ActionType.PK_VOTE: "PK 投票：target 选择 candidates 中你要投出的玩家，也可以为 null。",
        ActionType.HUNTER_SHOOT: "猎人开枪：target 选择 candidates 中你要带走的玩家。",
    }
    return instructions[action_type]


def strategy_instruction(request: ActionRequest) -> str:
    if request.action_type is ActionType.SHERIFF_WITHDRAW:
        return (
            "警长退水策略：metadata 中 runners/remaining_runners 是当前仍在警上的候选人。"
            "如果你是最后一名仍在警上的候选人，必须选择 stay，避免集体退水导致无人竞选。"
            "如果还有其他更可信候选人，可以有理由地 withdraw；否则默认 stay。"
        )
    return ""
