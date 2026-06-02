"""ToT (Tree-of-Thought) — single-call multi-candidate reasoning for key decisions.

The LLM generates 3 candidates and self-selects the best one in one API call.
This removes the separate judge round (and all the ID-matching edge cases that
came with it).
"""

from __future__ import annotations

import json
import re

from dataclasses import dataclass, field
from typing import Any

from agent.knowledge.prompts.parsing import load_json_object
from agent.core.context import AgentContext
from agent.infrastructure.llm import ModelAdapter
from agent.common import as_float as _as_float


# actions that qualify for ToT
KEY_ACTIONS: frozenset[str] = frozenset({
    "exile_vote",
    "pk_vote",
    "witch_act",
    "seer_check",
    "werewolf_kill",
    "hunter_shoot",
    "white_wolf_explode",
})


def need_tot(action_type: str) -> bool:
    return action_type in KEY_ACTIONS


# data structures
@dataclass(slots=True)
class ToTCandidate:
    candidate_id: str
    action: dict[str, Any]
    public_text: str
    private_reasoning: str
    expected_gain: str
    risk: str

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "action": self.action,
            "public_text": self.public_text,
            "private_reasoning": self.private_reasoning,
            "expected_gain": self.expected_gain,
            "risk": self.risk,
        }


@dataclass(slots=True)
class ToTResult:
    enabled: bool
    candidates: list[ToTCandidate] = field(default_factory=list)
    selected_id: str | None = None
    judge_reason: str = ""
    confidence: float = 0.0
    final_action: dict[str, Any] | None = None
    prompt_messages: list[dict[str, str]] = field(default_factory=list)
    raw_output: str = ""

    @property
    def selected(self) -> ToTCandidate | None:
        for c in self.candidates:
            if c.candidate_id == self.selected_id:
                return c
        return None

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "candidates": [c.to_dict() for c in self.candidates],
            "selected_id": self.selected_id,
            "judge_reason": self.judge_reason,
            "raw_output": self.raw_output,
        }


# prompt
_TOT_USER_PROMPT = (
    "你需要选出当前局势下的最优行动方案。\n\n"
    "请先生成 3 个不同策略方向的候选方案 (a/b/c)，"
    "再从其中选出你认为最优的一个。\n\n"
    "每个候选必须包含:\n"
    '- "candidate_id": 必须为 a / b / c\n'
    '- "action": {{"choice": str, "target": number|null}}\n'
    '- "public_text": 公开发言内容\n'
    '- "private_reasoning": 私有推理\n'
    '- "expected_gain": 预期收益\n'
    '- "risk": 风险\n\n'
    "要求:\n"
    "1. 3 个方案必须覆盖不同的策略方向\n"
    "2. 不能使用 observation 中不存在的私有信息\n"
    "3. target 必须是 candidates 列表中的数字，除非允许弃权\n"
    "4. selected_id 必须是 a, b, c 之一\n\n"
    "输出 JSON 格式:\n"
    '{{"candidates": [...], "selected_id": "a", "reason": "选择理由", "confidence": 0.0~1.0}}'
)


def _build_tot_prompt(ctx: AgentContext) -> list[dict[str, str]]:
    messages = list(ctx.messages) or [
        {"role": "system", "content": f"你是 {ctx.player_id} 号玩家，身份: {ctx.role}。"}
    ]
    messages.append(
        {
            "role": "user",
            "content": (
                f"当前行为: {ctx.request.action_type.value}\n"
                f"可选目标 candidates: {list(ctx.request.candidates)}\n"
                f"你的观察: {json.dumps(ctx.request.observation, ensure_ascii=False, default=str)}\n"
                f"你的记忆: {json.dumps(ctx.memory_context, ensure_ascii=False, default=str)}\n"
                f"你的信念: {json.dumps(ctx.belief_context, ensure_ascii=False, default=str)}\n\n"
                + _TOT_USER_PROMPT
            ),
        }
    )
    return messages


# main entry
async def run_tot_selection(
    ctx: AgentContext,
    model: ModelAdapter,
) -> ToTResult:
    """Generate candidates + self-select best in a single LLM call.

    Raises RuntimeError on LLM / parse / validation failure so the caller
    can fall back to the normal pipeline.
    """
    messages = _build_tot_prompt(ctx)
    raw = await model.complete(messages, name=f"reason_with_tree_step/{ctx.player_id}/{ctx.request.action_type.value}")
    data = load_json_object(raw)

    raw_candidates = data.get("candidates", [])
    if len(raw_candidates) < 3:
        raise RuntimeError("ToT requires at least 3 candidates")

    candidates: list[ToTCandidate] = []
    for i, rc in enumerate(raw_candidates):
        candidates.append(ToTCandidate(
            candidate_id=chr(ord("a") + i),
            action=rc.get("action", {}),
            public_text=str(rc.get("public_text", "")),
            private_reasoning=str(rc.get("private_reasoning", "")),
            expected_gain=str(rc.get("expected_gain", "")),
            risk=str(rc.get("risk", "")),
        ))

    raw_selected = str(data.get("selected_id", ""))
    selected_id = _normalize_id(raw_selected)

    if selected_id not in {c.candidate_id for c in candidates}:
        raise RuntimeError(
            f"ToT selected_id mismatch: got {raw_selected!r}, normalized to {selected_id!r}"
        )

    final_action = None
    for c in candidates:
        if c.candidate_id == selected_id:
            final_action = c.action
            break

    return ToTResult(
        enabled=True,
        candidates=candidates,
        selected_id=selected_id,
        judge_reason=str(data.get("reason", "")),
        confidence=_as_float(data.get("confidence"), 0.7),
        final_action=final_action,
        prompt_messages=messages,
        raw_output=raw,
    )


def _normalize_id(raw: str) -> str:
    cleaned = raw.strip().lower()
    if cleaned in {"1", "2", "3"}:
        return chr(ord("a") + int(cleaned) - 1)
    match = re.search(r"[a-c]", cleaned)
    if match:
        return match.group(0)
    return cleaned
