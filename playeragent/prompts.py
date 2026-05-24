from __future__ import annotations

from werewolf.models import ActionRequest, ActionType, Role, Team

from playeragent.decision import StrategyAdvice


def default_persona(player_id: int, role: Role) -> str:
    base = [
        "发言简洁，优先保命。",
        "愿意竞选警长，喜欢带队归票。",
        "谨慎观察，投票跟随自己认为可信的人。",
        "攻击性稍强，会主动给出怀疑对象。",
    ][(player_id - 1) % 4]
    if role.team is Team.WEREWOLVES:
        return base + " 作为狼人时注意隐藏视角，尽量把票引向好人。"
    if role is Role.SEER:
        return base + " 作为预言家时可以积极争取警徽并表达查验逻辑。"
    if role is Role.WITCH:
        return base + " 作为女巫时谨慎用药，不轻易暴露身份。"
    if role is Role.GUARD:
        return base + " 作为守卫时关注可能被刀的位置。"
    if role is Role.HUNTER:
        return base + " 作为猎人时避免过早暴露，但可强势站边。"
    return base


def build_messages(
    request: ActionRequest,
    *,
    player_id: int,
    role: Role,
    persona: str,
    memory_context: dict,
    belief_context: dict | None = None,
    strategy_advice: StrategyAdvice | None = None,
):
    return [
        {"role": "system", "content": build_system_prompt(player_id=player_id, role=role, persona=persona)},
        {
            "role": "user",
            "content": build_request_prompt(
                request,
                memory_context,
                belief_context=belief_context or {},
                strategy_advice=strategy_advice,
            ),
        },
    ]


def build_system_prompt(*, player_id: int, role: Role, persona: str) -> str:
    return (
        "你正在扮演一名狼人杀玩家。你只能根据自己可见的信息行动，不能假设上帝视角。\n"
        f"你是 {player_id} 号玩家，身份: {role.value}。\n"
        f"你的简单性格: {persona}\n"
        "请有基本判断：好人应找狼、狼人应隐藏身份并推动好人出局、神职应合理使用技能。\n"
        "如果竞选警长对你的身份有帮助，可以主动竞选；如果局势不明，可以保守发言。\n"
        "必须区分 private_reasoning 和 public_speech：内部判断不能直接泄露到公开发言。\n"
        "不要在公开发言中泄露你不可公开解释的私有视角，例如狼人队友、上帝视角或系统真实身份。\n"
        "必须只输出 JSON，不要输出解释性自然语言。"
    )


def build_request_prompt(
    request: ActionRequest,
    memory_context: dict,
    *,
    belief_context: dict,
    strategy_advice: StrategyAdvice | None,
) -> str:
    observation = request.observation
    private_facts = memory_context["private_facts"]
    advice = strategy_advice.to_prompt_dict() if strategy_advice is not None else {}
    return (
        f"你是 {request.player_id} 号玩家。\n"
        f"身份: {observation.self_role.value}\n"
        f"当前阶段: {request.phase.value}\n"
        f"当前天数: {observation.day}\n"
        f"本次行动: {request.action_type.value}\n"
        f"可选目标 candidates: {list(request.candidates)}\n"
        f"存活玩家: {list(observation.alive_players)}\n"
        f"死亡玩家: {list(observation.dead_players)}\n"
        f"当前警长: {observation.sheriff_id}\n"
        f"公开局势摘要: {memory_context['public_summary']}\n"
        f"结构化事实记忆: {memory_context.get('memory_events', [])}\n"
        f"你知道的身份: {private_facts['known_roles']}\n"
        f"预言家查验结果: {private_facts['seer_checks']}\n"
        f"行动补充信息: {private_facts['metadata']}\n"
        f"你的历史动作摘要: {memory_context['self_history']}\n"
        f"你的近期私有决策理由: {memory_context.get('decisions', [])}\n"
        f"你记录的怀疑对象: {memory_context['suspicions']}\n"
        f"你听到的身份声明: {memory_context['claims_seen']}\n"
        f"当前主观判断 Belief: {belief_context}\n"
        f"当前角色策略建议: {advice}\n\n"
        f"{action_instruction(request.action_type)}\n"
        f"{strategy_instruction(request)}\n"
        "必须只输出 JSON，字段如下：\n"
        '{"choice": string|null, "target": number|null, "text": string, "reasoning": string, '
        '"alternatives": [number], "rejected_reasons": [string]}\n'
        "text 是公开内容，reasoning 是私有推理。target 必须是 candidates 里的数字，除非该行动允许弃权或不需要目标。"
    )


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
