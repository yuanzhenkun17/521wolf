"""Prompt templates that ask for the extended decision schema."""

from __future__ import annotations

from typing import Any

from engine.models import ActionRequest, Role

from agent.prompts.instructions import action_instruction, strategy_instruction

from agent.prompts.formatting import format_field_notes


def build_messages(
    request: ActionRequest,
    *,
    player_id: int,
    role: Role,
    memory_context: dict,
    belief_context: dict | None = None,
    strategy_advice: dict[str, Any] | None = None,
    selected_skills: list[str] | None = None,
    skill_context: str = "",
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": build_system_prompt(
                player_id=player_id, role=role
            ),
        },
        {
            "role": "user",
            "content": build_request_prompt(
                request,
                memory_context,
                belief_context=belief_context or {},
                strategy_advice=strategy_advice or {},
                selected_skills=selected_skills or [],
                skill_context=skill_context,
            ),
        },
    ]


def build_system_prompt(*, player_id: int, role: Role) -> str:
    return (
        "你正在扮演一名狼人杀玩家。你只能根据自己可见的信息行动，不能假设上帝视角。\n"
        f"你是 {player_id} 号玩家，身份: {role.value}。\n"
        "请有基本判断：好人应找狼、狼人应隐藏身份并推动好人出局、神职应合理使用技能。\n"
        "如果竞选警长对你的身份有帮助，可以主动竞选；如果局势不明，可以保守发言。\n"
        "必须区分 private_reasoning 和 public_text：内部判断不能直接泄露到公开发言。\n"
        "不要在公开发言中泄露你不可公开解释的私有视角，例如狼人队友、上帝视角或系统真实身份。"
    )


def build_request_prompt(
    request: ActionRequest,
    memory_context: dict,
    *,
    belief_context: dict,
    strategy_advice: dict[str, Any] | None = None,
    selected_skills: list[str] | None = None,
    skill_context: str = "",
) -> str:
    observation = request.observation
    private_facts = memory_context.get("private_facts", {})

    # Skill-specific hints from skill router
    hints = (strategy_advice or {}).get("prompt_hints", [])
    hints_block = ""
    if hints:
        hints_block = "技能提示:\n" + "\n".join(f"- {h}" for h in hints) + "\n\n"

    # Structured field notes from memory
    field_notes = memory_context.get("field_notes", {})
    field_notes_block = ""
    if field_notes:
        formatted = format_field_notes(field_notes)
        if formatted:
            field_notes_block = f"结构化现场笔记:\n{formatted}\n\n"

    # Multi-skill context block
    skill_context_block = ""
    if skill_context:
        skill_context_block = f"已注入策略 Skill:\n{skill_context}\n\n"

    # Long-term memory consolidated from prior games.
    long_memory_hints = memory_context.get("long_memory_hints", [])
    long_memory_block = ""
    if long_memory_hints:
        long_memory_block = (
            "长期经验提示:\n"
            + "\n".join(f"- {hint}" for hint in long_memory_hints[:5])
            + "\n\n"
        )

    return (
        f"当前阶段: {request.phase.value}\n"
        f"当前天数: {observation.day}\n"
        f"本次行动: {request.action_type.value}\n"
        f"可选目标 candidates: {list(request.candidates)}\n"
        f"存活玩家: {list(observation.alive_players)}\n"
        f"死亡玩家: {list(observation.dead_players)}\n"
        f"当前警长: {observation.sheriff_id}\n"
        f"结构化事实记忆: {memory_context.get('memory_events', [])}\n"
        f"你知道的身份: {private_facts.get('known_roles', [])}\n"
        f"预言家查验结果: {private_facts.get('seer_checks', [])}\n"
        f"行动补充信息: {private_facts.get('metadata', {})}\n"
        f"你的历史动作摘要: {memory_context.get('self_history', [])}\n"
        f"你的近期私有决策理由: {memory_context.get('decisions', [])}\n"
        f"当前主观判断 Belief: {belief_context}\n"
        f"{field_notes_block}"
        f"{skill_context_block}"
        f"{long_memory_block}"
        f"{hints_block}"
        f"{action_instruction(request.action_type)}\n"
        f"{strategy_instruction(request)}\n"
    )
