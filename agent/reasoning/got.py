"""GoT (Graph-of-Thought) reasoning for high-risk, high-conflict decisions.

GoT is intentionally sparse. It is heavier than ToT, so the runtime only uses
it when the request explicitly asks for it or when belief context shows a
high-conflict situation. On failure, callers should fall back to ToT/normal LLM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agent.prompts.parsing import load_json_object
from agent.runtime.context import AgentContext
from agent.runtime.model import ModelAdapter


GOT_ACTIONS: frozenset[str] = frozenset({
    "exile_vote",
    "pk_vote",
    "witch_act",
    "hunter_shoot",
    "white_wolf_explode",
    "werewolf_kill",
    "seer_check",
})


def need_got(ctx: AgentContext, *, threshold: float = 0.3) -> bool:
    """Return whether the current decision should use GoT.

    Explicit request metadata has priority. Automatic triggering is deliberately
    conservative to avoid spending extra tokens on routine decisions.
    """
    action_type = ctx.request.action_type.value
    if action_type not in GOT_ACTIONS:
        return False

    metadata = {**ctx.request.observation.metadata, **ctx.request.metadata}
    if metadata.get("enable_got") is True:
        return True
    if metadata.get("high_conflict") is True:
        return True
    if str(metadata.get("reasoning_mode", "")).lower() == "got":
        return True

    return _belief_conflict_high(ctx, threshold=threshold)


@dataclass(slots=True)
class GoTEvidenceNode:
    node_id: str
    kind: str
    summary: str
    source: str = ""
    reliability: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "summary": self.summary,
            "source": self.source,
            "reliability": round(self.reliability, 3),
        }


@dataclass(slots=True)
class GoTHypothesis:
    hypothesis_id: str
    claim: str
    supporting_evidence: list[str] = field(default_factory=list)
    conflicting_evidence: list[str] = field(default_factory=list)
    expected_action: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "claim": self.claim,
            "supporting_evidence": self.supporting_evidence,
            "conflicting_evidence": self.conflicting_evidence,
            "expected_action": self.expected_action,
            "confidence": round(self.confidence, 3),
        }


@dataclass(slots=True)
class GoTResult:
    enabled: bool
    evidence_nodes: list[GoTEvidenceNode] = field(default_factory=list)
    hypotheses: list[GoTHypothesis] = field(default_factory=list)
    selected_hypothesis_id: str | None = None
    judge_reason: str = ""
    confidence: float = 0.0
    final_action: dict[str, Any] | None = None
    public_text: str = ""
    private_reasoning: str = ""
    prompt_messages: list[dict[str, str]] = field(default_factory=list)
    raw_output: str = ""

    @property
    def selected(self) -> GoTHypothesis | None:
        for item in self.hypotheses:
            if item.hypothesis_id == self.selected_hypothesis_id:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "evidence_nodes": [node.to_dict() for node in self.evidence_nodes],
            "hypotheses": [hyp.to_dict() for hyp in self.hypotheses],
            "selected_hypothesis_id": self.selected_hypothesis_id,
            "judge_reason": self.judge_reason,
            "confidence": round(self.confidence, 3),
            "final_action": self.final_action,
            "public_text": self.public_text,
            "private_reasoning": self.private_reasoning,
            "raw_output": self.raw_output,
        }


_GOT_USER_PROMPT = (
    "你需要用 Graph-of-Thought 处理一个高风险狼人杀决策。\n\n"
    "请把局势拆成证据节点、身份/阵营假设、证据之间的支持与冲突，"
    "再选择最稳健的最终行动。\n\n"
    "必须遵守:\n"
    "1. 只能使用 observation / memory / belief / skill 中可见的信息。\n"
    "2. 不要把私有推理直接写进公开发言。\n"
    "3. target 必须来自 candidates，除非该动作允许不选择目标。\n"
    "4. 至少给出 2 个互相竞争的 hypotheses。\n"
    "5. conflicting_evidence 必须真实指出反证或不确定性。\n\n"
    "输出 JSON 格式:\n"
    "{\n"
    '  "evidence_nodes": [\n'
    "    {\n"
    '      "node_id": "e1",\n'
    '      "kind": "speech|vote|claim|skill|death|belief|memory",\n'
    '      "summary": "证据摘要",\n'
    '      "source": "信息来源",\n'
    '      "reliability": 0.0\n'
    "    }\n"
    "  ],\n"
    '  "hypotheses": [\n'
    "    {\n"
    '      "hypothesis_id": "h1",\n'
    '      "claim": "身份/阵营假设",\n'
    '      "supporting_evidence": ["e1"],\n'
    '      "conflicting_evidence": ["e2"],\n'
    '      "expected_action": {"choice": "vote", "target": 3},\n'
    '      "confidence": 0.0\n'
    "    }\n"
    "  ],\n"
    '  "selected_hypothesis_id": "h1",\n'
    '  "final_action": {"choice": "vote", "target": 3},\n'
    '  "public_text": "公开发言/行动说明",\n'
    '  "private_reasoning": "私有推理摘要",\n'
    '  "judge_reason": "为什么选择该假设",\n'
    '  "confidence": 0.0\n'
    "}"
)


def build_got_prompt(ctx: AgentContext) -> list[dict[str, str]]:
    messages = list(ctx.messages) or [
        {"role": "system", "content": f"你是 {ctx.player_id} 号玩家，身份: {ctx.role}。"}
    ]
    messages.append({
        "role": "user",
        "content": (
            f"当前行为: {ctx.request.action_type.value}\n"
            f"可选目标 candidates: {list(ctx.request.candidates)}\n"
            f"你的观察: {json.dumps(ctx.request.observation, ensure_ascii=False, default=str)}\n"
            f"你的记忆: {json.dumps(ctx.memory_context, ensure_ascii=False, default=str)}\n"
            f"你的信念: {json.dumps(ctx.belief_context, ensure_ascii=False, default=str)}\n\n"
            + _GOT_USER_PROMPT
        ),
    })
    return messages


async def run_got_selection(ctx: AgentContext, model: ModelAdapter) -> GoTResult:
    """Run one GoT reasoning call and parse the selected action."""
    messages = build_got_prompt(ctx)
    raw = await model.complete(messages, name=f"got_node/{ctx.player_id}/{ctx.request.action_type.value}")
    data = load_json_object(raw)

    evidence_nodes = [
        GoTEvidenceNode(
            node_id=str(item.get("node_id") or f"e{i + 1}"),
            kind=str(item.get("kind") or "unknown"),
            summary=str(item.get("summary") or ""),
            source=str(item.get("source") or ""),
            reliability=_as_float(item.get("reliability"), 0.5),
        )
        for i, item in enumerate(data.get("evidence_nodes", []))
        if isinstance(item, dict)
    ]

    hypotheses = [
        GoTHypothesis(
            hypothesis_id=str(item.get("hypothesis_id") or f"h{i + 1}"),
            claim=str(item.get("claim") or ""),
            supporting_evidence=[str(e) for e in item.get("supporting_evidence", [])],
            conflicting_evidence=[str(e) for e in item.get("conflicting_evidence", [])],
            expected_action=dict(item.get("expected_action") or {}),
            confidence=_as_float(item.get("confidence"), 0.0),
        )
        for i, item in enumerate(data.get("hypotheses", []))
        if isinstance(item, dict)
    ]
    if len(hypotheses) < 2:
        raise RuntimeError("GoT requires at least 2 hypotheses")

    selected_id = str(data.get("selected_hypothesis_id") or "")
    if selected_id not in {item.hypothesis_id for item in hypotheses}:
        raise RuntimeError(f"GoT selected_hypothesis_id not found: {selected_id!r}")

    final_action = dict(data.get("final_action") or {})
    if not final_action:
        selected = next(item for item in hypotheses if item.hypothesis_id == selected_id)
        final_action = dict(selected.expected_action)
    if not final_action:
        raise RuntimeError("GoT selected no final action")

    return GoTResult(
        enabled=True,
        evidence_nodes=evidence_nodes,
        hypotheses=hypotheses,
        selected_hypothesis_id=selected_id,
        judge_reason=str(data.get("judge_reason") or data.get("reason") or ""),
        confidence=_as_float(data.get("confidence"), 0.7),
        final_action=final_action,
        public_text=str(data.get("public_text") or ""),
        private_reasoning=str(data.get("private_reasoning") or ""),
        prompt_messages=messages,
        raw_output=raw,
    )


def _belief_conflict_high(ctx: AgentContext, *, threshold: float = 0.3) -> bool:
    suspects = ctx.belief_context.get("top_suspicions", [])
    if not isinstance(suspects, list) or len(suspects) < 3:
        return False

    probs: list[float] = []
    for item in suspects[:3]:
        if not isinstance(item, dict):
            continue
        value = (
            item.get("wolf_prob")
            or item.get("probability")
            or item.get("confidence")
            or item.get("score")
        )
        prob = _as_float(value, -1.0)
        if prob >= 0:
            probs.append(prob)

    if len(probs) < 3:
        return False
    return max(probs) >= 0.45 and (max(probs) - min(probs)) <= threshold


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
