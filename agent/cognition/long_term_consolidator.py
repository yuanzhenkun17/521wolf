"""Long-term memory consolidator — sliding window skill updates.

Every N games, reads recent mid-term memory analyses and produces
skill modification proposals. This replaces the old string-counting
RoleLongTermMemory system with LLM-based consolidation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.models import Role

from agent.cognition.mid_memory import GameAnalysis
from agent.prompts.parsing import load_json_object
from agent.runtime.model import ModelAdapter
from agent.skill_system.loader import MarkdownSkill, load_markdown_skills


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SKILL_ROOT = _PROJECT_ROOT / "skills"


@dataclass(slots=True)
class SkillEditProposal:
    skill: str
    operation: str  # "append_rule" | "rewrite_section" | "deprecate_rule"
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
class SkillConsolidation:
    role: str
    generated_at: str
    source_games: list[str]
    trends: list[str] = field(default_factory=list)
    skill_proposals: list[SkillEditProposal] = field(default_factory=list)
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "generated_at": self.generated_at,
            "source_games": self.source_games,
            "trends": self.trends,
            "skill_proposals": [p.to_dict() for p in self.skill_proposals],
            "errors": self.errors,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Long-Term Consolidation: {self.role}",
            "",
            f"- Source games: {', '.join(self.source_games)}",
            f"- Generated: {self.generated_at}",
            "",
        ]
        if self.trends:
            lines.extend(["## Trends", ""])
            for t in self.trends:
                lines.append(f"- {t}")
            lines.append("")
        if self.skill_proposals:
            lines.extend(["## Skill Proposals", ""])
            for p in self.skill_proposals:
                lines.extend([
                    f"### {p.skill}",
                    "",
                    f"- Operation: {p.operation}",
                    f"- Proposal: {p.proposal}",
                    f"- Risk: {p.risk or '-'}",
                    f"- Confidence: {p.confidence:.1%}",
                    "",
                ])
        if self.errors:
            lines.extend(["## Errors", ""])
            for e in self.errors:
                lines.append(f"- {e}")
        return "\n".join(lines).rstrip() + "\n"


async def consolidate_from_mid_memories(
    *,
    model: ModelAdapter,
    mid_memories: list[GameAnalysis],
    role: Role,
    skill_root: Path | str | None = None,
) -> SkillConsolidation:
    """Analyze recent mid-term memories and propose skill updates."""
    skills = _load_role_skills(role, skill_root=skill_root)
    messages = _build_messages(
        mid_memories=mid_memories,
        skills=skills,
        role=role,
    )

    source_games = [m.game_id for m in mid_memories]
    raw = ""
    try:
        raw = await model.complete(messages, name=f"consolidation/{role.value}")
        return _parse_consolidation(
            role=role.value,
            raw_output=raw,
            source_games=source_games,
        )
    except Exception as exc:
        return SkillConsolidation(
            role=role.value,
            generated_at=_now(),
            source_games=source_games,
            raw_output=raw,
            errors=[str(exc)],
        )


def write_consolidation(
    consolidation: SkillConsolidation,
    *,
    output_dir: Path | str,
) -> tuple[Path, Path]:
    """Write consolidation to JSON and markdown."""
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / f"{consolidation.role}.json"
    md_path = base / f"{consolidation.role}.md"
    json_path.write_text(
        json.dumps(consolidation.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(consolidation.to_markdown(), encoding="utf-8")
    return json_path, md_path


# ── Internal helpers ──────────────────────────────────────────────────────


def _build_messages(
    *,
    mid_memories: list[GameAnalysis],
    skills: list[MarkdownSkill],
    role: Role,
) -> list[dict[str, str]]:
    summaries = []
    for m in mid_memories:
        summary = {
            "game_id": m.game_id,
            "winner": m.winner,
            "strategic_insights": m.strategic_insights,
            "error_patterns": m.error_patterns,
            "turning_points": [
                {"description": tp.description, "root_cause": tp.root_cause}
                for tp in m.turning_points[:3]
            ],
            "decision_reviews": [
                {"action_type": dr.action_type, "verdict": dr.verdict, "quality_score": dr.quality_score}
                for dr in m.decision_reviews[:5]
            ],
        }
        summaries.append(summary)

    skills_text = "\n".join(
        f"## {s.name}\n{s.body[:800]}\n" for s in skills
    )

    return [
        {
            "role": "system",
            "content": (
                "你是狼人杀 Agent 的长期记忆整合器。"
                "你需要分析最近 N 局的中期记忆报告，发现跨局趋势，并提出 skill 修改建议。"
                "必须输出 JSON，不要输出额外自然语言。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"分析角色: {role.value}\n\n"
                f"最近 {len(mid_memories)} 局中期记忆摘要:\n"
                f"{_compact_json(summaries)}\n\n"
                f"当前角色 skills:\n{skills_text}\n\n"
                "请分析跨局趋势并提出 skill 修改建议，要求:\n"
                "1. trends: 3-5 条跨局趋势（比如'最近 3 局女巫都在首夜毒错人'）\n"
                "2. skill_proposals: 对 skill 的修改建议，每个包含 skill 名、操作类型、具体内容、风险和置信度\n"
                "3. 只在有足够证据时提建议，不要基于单局数据做判断\n\n"
                "输出 JSON schema:\n"
                "{\n"
                '  "trends": ["趋势1", "趋势2"],\n'
                '  "skill_proposals": [\n'
                "    {\n"
                '      "skill": "skill_name",\n'
                '      "operation": "append_rule|rewrite_section|deprecate_rule",\n'
                '      "proposal": "具体修改内容",\n'
                '      "risk": "风险评估",\n'
                '      "evidence_games": ["game_id"],\n'
                '      "confidence": 0.0\n'
                "    }\n"
                "  ]\n"
                "}"
            ),
        },
    ]


def _parse_consolidation(
    *,
    role: str,
    raw_output: str,
    source_games: list[str],
) -> SkillConsolidation:
    data = load_json_object(raw_output)

    proposals = [
        SkillEditProposal(
            skill=str(p.get("skill", "")),
            operation=str(p.get("operation", "append_rule")),
            proposal=str(p.get("proposal", "")),
            risk=str(p.get("risk", "")),
            evidence_cards=[str(g) for g in p.get("evidence_games", [])],
            confidence=_as_float(p.get("confidence"), 0.0),
        )
        for p in data.get("skill_proposals", [])
        if isinstance(p, dict)
    ][:8]

    return SkillConsolidation(
        role=role,
        generated_at=_now(),
        source_games=source_games,
        trends=[str(t) for t in data.get("trends", [])][:5],
        skill_proposals=proposals,
        raw_output=raw_output,
    )


def _load_role_skills(role: Role, *, skill_root: Path | str | None = None) -> list[MarkdownSkill]:
    root = Path(skill_root) if skill_root else DEFAULT_SKILL_ROOT
    skills = load_markdown_skills(root)
    return [s for s in skills if s.scope == "common" or s.role == role]


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
