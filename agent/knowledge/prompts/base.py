"""Prompt templates that ask for the extended decision schema."""

from __future__ import annotations

from typing import Any

from engine.models import ActionRequest, Role

from agent.common.json import compact_json as _compact
from agent.knowledge.prompts.instructions import action_instruction

from agent.knowledge.prompts.formatting import format_field_notes

_OUTPUT_FORMAT_INSTRUCTIONS = """\
# 输出格式要求

- 必须只输出 JSON。
- 字段如下：

```json
{
  "choice": string | null,
  "target": number | null,
  "public_text": string,
  "private_reasoning": string,
  "confidence": 0.0~1.0,
  "alternatives": [number],
  "rejected_reasons": [string],
  "selected_skills": [string]
}
```

- `public_text` 是公开发言内容。
- `private_reasoning` 是私有推理，不能出现在公开发言中。
- `target` 必须来自 candidates，除非该行动允许弃权或不需要目标。
- `choice` 必须和当前动作匹配。
- `confidence` 是置信度（0.0 到 1.0）。\
"""


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


def _line_list(items: Any) -> list[str]:
    if not items:
        return []
    if isinstance(items, str):
        return [items] if items.strip() else []
    if isinstance(items, list):
        return [str(item) if not isinstance(item, dict) else _compact(item) for item in items]
    return [_compact(items)]


def _format_pinned_fact(fact: Any) -> str:
    if not isinstance(fact, dict):
        return str(fact)
    content = str(fact.get("content") or "").strip()
    if not content:
        content = _compact(fact)
    day = fact.get("day")
    phase = fact.get("phase")
    prefix = ""
    if day is not None and phase:
        prefix = f"第{day}天 {phase}: "
    return prefix + content


def _format_player_models(player_models: Any) -> str:
    if not player_models:
        return ""
    profile_lines = []
    for pid_str, info in sorted(player_models.items()):
        parts_list = []
        sc = info.get("speech_count", 0)
        if sc:
            parts_list.append(f"发言{sc}次")
        for vote in info.get("votes_cast", []):
            parts_list.append(f"投票给P{vote.get('target')}")
        received = info.get("votes_received", [])
        if received:
            parts_list.append(f"被{'、'.join(f'P{r}' for r in received)}投票")
        for a in info.get("attacked", []):
            parts_list.append(f"攻击过P{a}")
        for d in info.get("defended", []):
            parts_list.append(f"辩护过P{d}")
        for f in info.get("followed", []):
            parts_list.append(f"跟票P{f}")
        if parts_list:
            profile_lines.append(f"  - P{pid_str}: {'，'.join(parts_list)}")
    return "\n".join(profile_lines)


def _format_self_commitments(commitments: Any) -> str:
    lines = []
    for item in commitments or []:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        parts = [
            f"第{item.get('day')}天",
            str(item.get("phase") or ""),
            str(item.get("action_type") or ""),
        ]
        action = " ".join(part for part in parts if part)
        target = item.get("target")
        choice = item.get("choice")
        text = item.get("text") or ""
        details = []
        if choice is not None:
            details.append(f"choice={choice}")
        if target is not None:
            details.append(f"target=P{target}")
        if text:
            details.append(f"text={text}")
        lines.append(f"- {action}: {'; '.join(details) if details else _compact(item)}")
    return "\n".join(lines)


def _format_recent_timeline(timeline: Any) -> str:
    if not timeline:
        return ""
    lines = []
    for block in timeline:
        if not isinstance(block, dict):
            lines.append(str(block))
            continue
        label = block.get("phase_key") or f"day{block.get('day')}/{block.get('phase')}"
        lines.append(f"{label}:")
        events = block.get("events") or []
        if not events:
            lines.append("- 无公开事件")
            continue
        for event in events:
            if isinstance(event, dict):
                text = str(event.get("text") or event.get("content") or _compact(event))
            else:
                text = str(event)
            lines.append(f"- {text}")
    return "\n".join(lines)


def _format_short_term_memory(memory_context: dict) -> str:
    parts = []

    rolling_lines = _line_list(memory_context.get("rolling_summary"))
    if rolling_lines:
        parts.append("前史摘要:\n" + "\n".join(f"- {line}" for line in rolling_lines))

    pinned_facts = memory_context.get("pinned_facts") or []
    if pinned_facts:
        facts = "\n".join(f"- {_format_pinned_fact(fact)}" for fact in pinned_facts)
        parts.append("不可丢关键事实:\n" + facts)

    player_models = _format_player_models(memory_context.get("player_models"))
    if player_models:
        parts.append("玩家画像:\n" + player_models)

    commitments = _format_self_commitments(memory_context.get("self_commitments"))
    if commitments:
        parts.append("我的公开口径:\n" + commitments)

    timeline = _format_recent_timeline(memory_context.get("recent_timeline"))
    if timeline:
        parts.append("最近两个阶段完整时间流:\n" + timeline)

    return "\n\n".join(parts) + ("\n\n" if parts else "")


def build_request_prompt(
    request: ActionRequest,
    memory_context: dict,
    *,
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
    has_phase_memory = any(
        memory_context.get(key)
        for key in (
            "rolling_summary",
            "pinned_facts",
            "recent_timeline",
            "player_models",
            "self_commitments",
        )
    )
    if field_notes and not has_phase_memory:
        formatted = format_field_notes(field_notes)
        if formatted:
            field_notes_block = f"结构化现场笔记:\n{formatted}\n\n"

    # Multi-skill context block
    skill_context_block = ""
    if skill_context:
        skill_context_block = f"已注入策略 Skill:\n{skill_context}\n\n"

    memory_block = _format_short_term_memory(memory_context)

    return (
        f"当前阶段: {request.phase.value}\n"
        f"当前天数: {observation.day}\n"
        f"本次行动: {request.action_type.value}\n"
        f"可选目标 candidates: {list(request.candidates)}\n"
        f"存活玩家: {list(observation.alive_players)}\n"
        f"死亡玩家: {list(observation.dead_players)}\n"
        f"当前警长: {observation.sheriff_id}\n"
        f"你知道的身份: {private_facts.get('known_roles', [])}\n"
        f"预言家查验结果: {private_facts.get('seer_checks', [])}\n"
        f"行动补充信息: {private_facts.get('metadata', {})}\n"
        f"{memory_block}"
        f"{field_notes_block}"
        f"{skill_context_block}"
        f"{hints_block}"
        f"{action_instruction(request.action_type)}\n"
        f"{_OUTPUT_FORMAT_INSTRUCTIONS}\n"
    )
