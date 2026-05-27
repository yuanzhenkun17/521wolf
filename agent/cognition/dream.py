"""Forked reflection agent for post-game consolidation.

The dream agent is a post-game thinker. It does not return game actions and it
does not edit skills directly. It reads experience cards, rule-based long-term
memory, optional memory/belief snapshots, and role skills, then proposes
auditable insights and skill edits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.models import Role

from agent.cognition.experience import ExperienceCard
from agent.cognition.long_memory import RoleLongTermMemory
from agent.prompts.parsing import load_json_object
from agent.runtime.model import ModelAdapter
from agent.skill_system.loader import MarkdownSkill, load_markdown_skills


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DREAM_BASE_DIR = _PROJECT_ROOT / "data" / "dreams"
DEFAULT_SKILL_ROOT = _PROJECT_ROOT / "skills"


@dataclass(slots=True)
class DreamInsight:
    title: str
    evidence_cards: list[str]
    reasoning_summary: str
    suggested_rule: str
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "evidence_cards": self.evidence_cards,
            "reasoning_summary": self.reasoning_summary,
            "suggested_rule": self.suggested_rule,
            "confidence": round(self.confidence, 3),
        }


@dataclass(slots=True)
class SkillEditProposal:
    skill: str
    operation: str
    proposal: str
    risk: str = ""
    evidence_cards: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "operation": self.operation,
            "proposal": self.proposal,
            "risk": self.risk,
            "evidence_cards": self.evidence_cards,
            "confidence": round(self.confidence, 3),
        }


@dataclass(slots=True)
class DreamReport:
    role: str
    generated_at: str
    source_card_count: int
    rule_memory_summary: dict[str, Any]
    insights: list[DreamInsight] = field(default_factory=list)
    skill_edit_proposals: list[SkillEditProposal] = field(default_factory=list)
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "generated_at": self.generated_at,
            "source_card_count": self.source_card_count,
            "rule_memory_summary": self.rule_memory_summary,
            "insights": [insight.to_dict() for insight in self.insights],
            "skill_edit_proposals": [
                proposal.to_dict() for proposal in self.skill_edit_proposals
            ],
            "raw_output": self.raw_output,
            "errors": self.errors,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Dream Report: {self.role}",
            "",
            f"- Source cards: {self.source_card_count}",
            f"- Generated at: {self.generated_at}",
            "",
            "## Insights",
            "",
        ]
        if not self.insights:
            lines.append("- 暂无反思结论。")
        for insight in self.insights:
            lines.extend([
                f"### {insight.title}",
                "",
                f"- Evidence cards: {', '.join(insight.evidence_cards) or '-'}",
                f"- Confidence: {insight.confidence:.1%}",
                f"- Reasoning: {insight.reasoning_summary}",
                f"- Suggested rule: {insight.suggested_rule}",
                "",
            ])
        lines.extend(["", "## Skill Edit Proposals", ""])
        if not self.skill_edit_proposals:
            lines.append("- 暂无 skill 修改建议。")
        for proposal in self.skill_edit_proposals:
            lines.extend([
                f"### {proposal.skill}",
                "",
                f"- Operation: {proposal.operation}",
                f"- Proposal: {proposal.proposal}",
                f"- Risk: {proposal.risk or '-'}",
                f"- Confidence: {proposal.confidence:.1%}",
                "",
            ])
        if self.errors:
            lines.extend(["", "## Errors", ""])
            for error in self.errors:
                lines.append(f"- {error}")
        return "\n".join(lines).rstrip() + "\n"


@dataclass(slots=True)
class DreamAgent:
    """A forked post-game reflection agent for one role."""

    role: Role
    model: ModelAdapter
    experience_cards: list[ExperienceCard | dict]
    rule_memory: RoleLongTermMemory | None = None
    memory_snapshot: dict[str, Any] | None = None
    belief_snapshot: dict[str, Any] | None = None
    skills: list[MarkdownSkill] = field(default_factory=list)

    async def reflect(self) -> DreamReport:
        messages = self._build_messages()
        raw = ""
        try:
            raw = await self.model.complete(
                messages,
                name=f"dream/{self.role.value}",
            )
            report = parse_dream_report(
                role=self.role,
                raw_output=raw,
                source_card_count=len(self.experience_cards),
                rule_memory=self.rule_memory,
            )
            return report
        except Exception as exc:
            return fallback_dream_report(
                role=self.role,
                cards=self.experience_cards,
                rule_memory=self.rule_memory,
                raw_output=raw,
                error=str(exc),
            )

    def _build_messages(self) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是狼人杀 Agent 的局后反思子 Agent。"
                    "你只负责总结经验和提出 skill 修改建议，不能直接修改文件。"
                    "必须输出 JSON，不要输出额外自然语言。"
                ),
            },
            {
                "role": "user",
                "content": build_dream_prompt(
                    role=self.role,
                    cards=self.experience_cards,
                    rule_memory=self.rule_memory,
                    memory_snapshot=self.memory_snapshot or {},
                    belief_snapshot=self.belief_snapshot or {},
                    skills=self.skills,
                ),
            },
        ]


def build_dream_prompt(
    *,
    role: Role,
    cards: list[ExperienceCard | dict],
    rule_memory: RoleLongTermMemory | None = None,
    memory_snapshot: dict[str, Any] | None = None,
    belief_snapshot: dict[str, Any] | None = None,
    skills: list[MarkdownSkill] | None = None,
) -> str:
    return (
        f"反思角色: {role.value}\n\n"
        f"规则统计长期记忆:\n{_compact_json(_rule_memory_summary(rule_memory))}\n\n"
        f"经验卡片:\n{_compact_json([_card_dict(card) for card in cards])}\n\n"
        f"Memory snapshot:\n{_compact_json(memory_snapshot or {})}\n\n"
        f"Belief snapshot:\n{_compact_json(belief_snapshot or {})}\n\n"
        f"当前角色 skills:\n{_skills_text(skills or [])}\n\n"
        "请生成结构化反思报告，要求:\n"
        "1. insights 必须引用 evidence_cards。\n"
        "2. skill_edit_proposals 只能是建议，不能假设已经修改文件。\n"
        "3. 如果证据不足，少提建议并降低 confidence。\n"
        "4. 不要泄露非该角色视角之外的信息作为行动依据。\n\n"
        "输出 JSON schema:\n"
        "{\n"
        '  "insights": [\n'
        "    {\n"
        '      "title": "string",\n'
        '      "evidence_cards": ["card_id"],\n'
        '      "reasoning_summary": "string",\n'
        '      "suggested_rule": "string",\n'
        '      "confidence": 0.0\n'
        "    }\n"
        "  ],\n"
        '  "skill_edit_proposals": [\n'
        "    {\n"
        '      "skill": "skill_name",\n'
        '      "operation": "append_rule|rewrite_section|deprecate_rule",\n'
        '      "proposal": "string",\n'
        '      "risk": "string",\n'
        '      "evidence_cards": ["card_id"],\n'
        '      "confidence": 0.0\n'
        "    }\n"
        "  ]\n"
        "}"
    )


def parse_dream_report(
    *,
    role: Role,
    raw_output: str,
    source_card_count: int,
    rule_memory: RoleLongTermMemory | None = None,
) -> DreamReport:
    data = load_json_object(raw_output)
    insights = [
        DreamInsight(
            title=str(item.get("title") or ""),
            evidence_cards=[str(card) for card in item.get("evidence_cards", [])],
            reasoning_summary=str(item.get("reasoning_summary") or ""),
            suggested_rule=str(item.get("suggested_rule") or ""),
            confidence=_as_float(item.get("confidence"), 0.0),
        )
        for item in data.get("insights", [])
        if isinstance(item, dict)
    ]
    proposals = [
        SkillEditProposal(
            skill=str(item.get("skill") or ""),
            operation=str(item.get("operation") or "append_rule"),
            proposal=str(item.get("proposal") or ""),
            risk=str(item.get("risk") or ""),
            evidence_cards=[str(card) for card in item.get("evidence_cards", [])],
            confidence=_as_float(item.get("confidence"), 0.0),
        )
        for item in data.get("skill_edit_proposals", [])
        if isinstance(item, dict)
    ]
    return DreamReport(
        role=role.value,
        generated_at=_now(),
        source_card_count=source_card_count,
        rule_memory_summary=_rule_memory_summary(rule_memory),
        insights=insights[:8],
        skill_edit_proposals=proposals[:8],
        raw_output=raw_output,
    )


def fallback_dream_report(
    *,
    role: Role,
    cards: list[ExperienceCard | dict],
    rule_memory: RoleLongTermMemory | None,
    raw_output: str = "",
    error: str = "",
) -> DreamReport:
    """Build a deterministic report if LLM reflection fails."""
    summary = _rule_memory_summary(rule_memory)
    insights: list[DreamInsight] = []
    for item in summary.get("recurring_mistakes", [])[:3]:
        insights.append(DreamInsight(
            title=f"高频教训: {item.get('title', '')}",
            evidence_cards=[str(card_id) for card_id in item.get("source_cards", [])],
            reasoning_summary=str(item.get("description", "")),
            suggested_rule=str(item.get("description", "")),
            confidence=_as_float(item.get("confidence"), 0.35),
        ))
    return DreamReport(
        role=role.value,
        generated_at=_now(),
        source_card_count=len(cards),
        rule_memory_summary=summary,
        insights=insights,
        raw_output=raw_output,
        errors=[error] if error else [],
    )


async def dream_for_role(
    *,
    role: Role,
    model: ModelAdapter,
    cards: list[ExperienceCard | dict],
    rule_memory: RoleLongTermMemory | None = None,
    memory_snapshot: dict[str, Any] | None = None,
    belief_snapshot: dict[str, Any] | None = None,
    skill_root: Path | str | None = None,
) -> DreamReport:
    agent = DreamAgent(
        role=role,
        model=model,
        experience_cards=cards,
        rule_memory=rule_memory,
        memory_snapshot=memory_snapshot,
        belief_snapshot=belief_snapshot,
        skills=load_role_skills(role, skill_root=skill_root),
    )
    return await agent.reflect()


def write_dream_report(
    report: DreamReport,
    *,
    output_dir: Path | str | None = None,
) -> tuple[Path, Path]:
    base = Path(output_dir) if output_dir else DREAM_BASE_DIR / report.role
    base.mkdir(parents=True, exist_ok=True)
    stem = f"dream_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    json_path = base / f"{stem}.json"
    md_path = base / f"{stem}.md"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, md_path


def load_role_skills(
    role: Role,
    *,
    skill_root: Path | str | None = None,
) -> list[MarkdownSkill]:
    root = Path(skill_root) if skill_root else DEFAULT_SKILL_ROOT
    skills = load_markdown_skills(root)
    return [
        skill for skill in skills
        if skill.scope == "common" or skill.role == role
    ]


def _rule_memory_summary(memory: RoleLongTermMemory | None) -> dict[str, Any]:
    if memory is None:
        return {}
    return {
        "role": memory.role,
        "source_card_count": memory.source_card_count,
        "win_rate": memory.win_rate,
        "avg_score": memory.avg_score,
        "effective_strategies": [
            item.to_dict() for item in memory.effective_strategies[:5]
        ],
        "recurring_mistakes": [
            item.to_dict() for item in memory.recurring_mistakes[:5]
        ],
        "situational_rules": [
            item.to_dict() for item in memory.situational_rules[:5]
        ],
        "skill_update_suggestions": memory.skill_update_suggestions,
    }


def _card_dict(card: ExperienceCard | dict) -> dict:
    if isinstance(card, dict):
        return card
    return card.to_dict()


def _skills_text(skills: list[MarkdownSkill]) -> str:
    parts: list[str] = []
    for skill in skills:
        parts.append(f"## {skill.name}")
        parts.append(f"- scope: {skill.scope}")
        if skill.role:
            parts.append(f"- role: {skill.role.value}")
        if skill.applicable_actions:
            parts.append(
                "- actions: "
                + ", ".join(sorted(action.value for action in skill.applicable_actions))
            )
        parts.append(skill.body[:1200])
        parts.append("")
    return "\n".join(parts).strip()


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
