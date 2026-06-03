"""Long-term memory consolidator — sliding window skill updates.

Every N games, reads recent mid-term memory analyses and produces
skill modification proposals. This replaces the old string-counting
RoleLongTermMemory system with LLM-based consolidation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.models import Role

from agent.learning.game_analysis import GameAnalysis, filter_mid_memory_for_role, load_game_analysis
from agent.knowledge.prompts.parsing import load_json_object
from agent.learning.evolution.models import (
    EvidenceRef,
    SkillConsolidation as RoleSkillConsolidation,
    SkillProposal,
)
from agent.infrastructure.llm import ModelAdapter
from agent.knowledge.skills.loader import MarkdownSkill, load_markdown_skills
from agent.common import as_float as _as_float, compact_json as _compact_json, beijing_now_iso as _now

_log = logging.getLogger(__name__)


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


# Internal helpers
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
            "strategic_insights": [si.to_dict() for si in m.strategic_insights],
            "error_patterns": [si.to_dict() for si in m.error_patterns],
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

    skills_text = _format_skill_inventory(skills)

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
    root = skill_root if isinstance(skill_root, Path) else (Path(skill_root) if skill_root else None)
    if root is None:
        return []
    skills = load_markdown_skills(root)
    return [s for s in skills if s.role is None or s.role == role]


def _format_skill_inventory(skills: list[MarkdownSkill]) -> str:
    """Format skills with file paths and evolution constraints for the LLM."""
    if not skills:
        return "(no skills found)"

    parts: list[str] = []
    for skill in skills:
        actions = sorted(action.value for action in skill.applicable_actions)
        evolution = skill.evolution if isinstance(skill.evolution, dict) else {}
        allowed_actions = [str(a) for a in evolution.get("allowed_actions", [])]
        parts.extend([
            f"## Skill file: {skill.relative_path or skill.name}",
            f"name: {skill.name}",
            f"role: {skill.role.value if skill.role is not None else 'common'}",
            f"applicable_actions: {_compact_json(actions)}",
            f"evolution.enabled: {bool(evolution.get('enabled', False))}",
            f"evolution.allowed_actions: {_compact_json(allowed_actions)}",
            "body:",
            skill.body[:1200],
            "",
        ])
    return "\n".join(parts).strip()


def _modifiable_skill_files(skills: list[MarkdownSkill]) -> list[dict[str, Any]]:
    """Return files the applier can legally modify."""
    result: list[dict[str, Any]] = []
    for skill in skills:
        evolution = skill.evolution if isinstance(skill.evolution, dict) else {}
        allowed_actions = [str(a) for a in evolution.get("allowed_actions", [])]
        if not evolution.get("enabled") or not allowed_actions:
            continue
        result.append({
            "target_file": skill.relative_path or skill.name,
            "name": skill.name,
            "role": skill.role.value if skill.role is not None else "common",
            "allowed_actions": allowed_actions,
        })
    return result


# Role-specific consolidation (Phase 3.2)
async def consolidate_for_role(
    run_dir: Path,
    role: str,
    model: ModelAdapter,
    *,
    run_id: str = "",
    parent_hash: str = "",
    window: int = 5,
    prompt_version: str = "role_consolidation_v2",
    skill_root: Path | str | None = None,
    store: "VersionStore | None" = None,
) -> RoleSkillConsolidation:
    """Consolidate mid-memory for a specific role, producing skill modification proposals.

    Steps:
    1. Scan run_dir for mid-memory files (games/game*/mid_memory/*.json)
    2. Load the most recent ``window`` analyses
    3. Filter each analysis for the target role using ``filter_mid_memory_for_role()``
    4. Load current skills for the role
    5. Build a prompt with filtered analyses + current skills
    6. Ask LLM to produce structured proposals
    7. Parse LLM output into :class:`SkillConsolidation`
    8. Only direct insights can generate actionable proposals
    """
    # 1. Scan for mid-memory files
    mid_dir = run_dir / "games"
    if not mid_dir.exists():
        _log.warning("No games directory found at %s", mid_dir)
        return RoleSkillConsolidation(
            role=role,
            run_id=run_id,
            parent_hash=parent_hash,
            generated_at=_now(),
            source_window=window,
            prompt_version=prompt_version,
        )

    mid_memories: list[GameAnalysis] = []
    for game_dir in sorted(mid_dir.glob("game*")):
        analysis_path = game_dir / "mid_memory"
        if not analysis_path.is_dir():
            continue
        for json_file in sorted(analysis_path.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                analysis = load_game_analysis(
                    data.get("game_id", ""), mid_memory_dir=analysis_path,
                )
                if analysis is not None:
                    mid_memories.append(analysis)
            except Exception:
                continue

    # 2. Take most recent window
    recent = mid_memories[-window:]
    source_games = [m.game_id for m in recent]

    # 3. Filter each analysis for the target role
    filtered = [filter_mid_memory_for_role(m, role) for m in recent]

    # 4. Load current skills + rejected proposals for the role
    skills = _load_role_skills_for_str(role, skill_root=skill_root)
    rejected = store.load_rejected(role) if store is not None else []

    # 5–7. Build prompt, call LLM, parse
    messages = _build_role_messages(
        filtered_analyses=filtered,
        skills=skills,
        role=role,
        window=window,
        rejected=rejected,
    )

    raw = ""
    try:
        raw = await model.complete(messages, name=f"consolidation/{role}")
        return _parse_role_consolidation(
            role=role,
            raw_output=raw,
            run_id=run_id,
            parent_hash=parent_hash,
            source_window=window,
            source_games=source_games,
            prompt_version=prompt_version,
        )
    except Exception as exc:
        _log.error("consolidate_for_role(%s) failed: %s", role, exc)
        return RoleSkillConsolidation(
            role=role,
            run_id=run_id,
            parent_hash=parent_hash,
            generated_at=_now(),
            source_window=window,
            prompt_version=prompt_version,
            source_games=source_games,
        )


def _format_rejected_buffer(rejected: list[dict]) -> str:
    """Format previously rejected proposals so the LLM avoids repeating them."""
    if not rejected:
        return ""
    lines = [
        "## 近期被拒绝的提案（避免重复尝试）",
        "",
        "以下提案在上次 battle 中被拒绝，请避免生成类似方向：",
        "",
    ]
    for i, r in enumerate(rejected, 1):
        delta = r.get("metrics_delta", {})
        lines.append(
            f"{i}. **{r.get('target_file', '?')}** ({r.get('action_type', '?')}) "
            f"— {r.get('rationale', '无理由')[:120]}"
        )
        if delta:
            sd = delta.get("role_score_delta", 0)
            wd = delta.get("win_rate_delta", 0)
            lines.append(f"   效果: score {sd:+.3f}, win_rate {wd:+.1%}")
        lines.append("")
    lines.append(
        "如果本轮的训练数据分析也支持类似结论，请优先考虑**不同的方向**，"
        "不要重复已经被拒绝的方案。"
    )
    return "\n".join(lines)


def _build_role_messages(
    *,
    filtered_analyses: list[dict],
    skills: list[MarkdownSkill],
    role: str,
    window: int,
    rejected: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Build LLM messages for role-specific consolidation."""
    summaries = []
    for fa in filtered_analyses:
        summary = {
            "game_id": fa["game_id"],
            "winner": fa["winner"],
            "decision_reviews": fa["decision_reviews"],
            "strategic_insights": fa["strategic_insights"],
            "error_patterns": fa["error_patterns"],
            "turning_points": fa["turning_points"][:3],
            "counterfactuals": fa["counterfactuals"][:2],
        }
        summaries.append(summary)

    skills_text = _format_skill_inventory(skills)
    modifiable_files = _modifiable_skill_files(skills)
    source_games = sorted({
        str(summary.get("game_id", ""))
        for summary in summaries
        if summary.get("game_id")
    })

    # Build rejected-proposal context
    rejected_text = _format_rejected_buffer(rejected or [])

    return [
        {
            "role": "system",
            "content": (
                "你是狼人杀 Agent 的角色级长期记忆整合器。"
                "你需要分析某角色最近 N 局的中期记忆，发现该角色的跨局趋势，并提出 skill 修改建议。"
                "每条建议必须有证据支撑，且只有 direct 洞察可以生成 actionable 建议。"
                "contextual 洞察仅可作为背景说明。必须输出 JSON，不要输出额外自然语言。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"分析角色: {role}\n\n"
                f"最近 {len(filtered_analyses)} 局中期记忆（已按角色过滤）:\n"
                f"{_compact_json(summaries)}\n\n"
                f"当前角色 skills:\n{skills_text}\n\n"
                "请分析跨局趋势并提出 skill 修改建议，要求:\n"
                "1. trends: 3-5 条跨局趋势\n"
                "2. proposals: 对 skill 的修改建议\n"
                "   - target_file 必须从上方 Skill file 列表中逐字复制，不允许自造文件名\n"
                "   - action_type 是技能修改动作，不是游戏动作；必须从该文件的 evolution.allowed_actions 中选择\n"
                "   - applicable_actions 只是 skill 适用的游戏动作，不能填进 proposal.action_type\n"
                "   - 只有 evolution.enabled=true 的文件可以进入 proposals\n"
                "   - 每个 proposal 必须包含 evidence 引用具体 game_id 和 decision/action\n"
                "   - risk 只能是 low|medium|high；high risk 建议只写入 trends，不要进入 proposals\n"
                "   - expected_direction 只能是 improve|maintain|reduce\n"
                "   - 大胆提案，不要过于保守；对战阶段会验证提案质量\n"
                f"当前 source_games(JSON): {_compact_json(source_games)}\n"
                f"可修改文件清单(JSON): {_compact_json(modifiable_files)}\n"
                f"{rejected_text}\n"
                "输出 JSON schema:\n"
                "{\n"
                '  "trends": ["趋势1", "趋势2"],\n'
                '  "proposals": [\n'
                "    {\n"
                '      "proposal_id": "prop_001",\n'
                '      "target_file": "从Skill file清单逐字复制的文件路径.md",\n'
                '      "action_type": "append_rule|rewrite_section|deprecate_rule",\n'
                '      "section": "目标章节名(rewrite_section时必填)",\n'
                '      "content": "具体修改内容",\n'
                '      "rationale": "修改理由",\n'
                '      "confidence": 0.0,\n'
                '      "risk": "low|medium|high",\n'
                '      "expected_metric": "期望影响的指标",\n'
                '      "expected_direction": "improve|maintain|reduce",\n'
                '      "evidence": [\n'
                "        {\n"
                '          "game_id": "game_001",\n'
                '          "role": "seer",\n'
                '          "player_id": 1,\n'
                '          "decision_id": "",\n'
                '          "action_type": "seer_check",\n'
                '          "quote": "相关原文摘录"\n'
                "        }\n"
                "      ],\n"
                '      "conflicts_with": ["proposal_id_of_conflicting_proposal"]\n'
                "    }\n"
                "  ]\n"
                "}"
            ),
        },
    ]


def _parse_role_consolidation(
    *,
    role: str,
    raw_output: str,
    run_id: str,
    parent_hash: str,
    source_window: int,
    source_games: list[str],
    prompt_version: str,
) -> RoleSkillConsolidation:
    """Parse LLM output into a role-evolution SkillConsolidation."""
    data = load_json_object(raw_output)

    proposals: list[SkillProposal] = []
    for p in data.get("proposals", []):
        if not isinstance(p, dict):
            continue
        evidence = [
            EvidenceRef.from_dict(e) for e in p.get("evidence", []) if isinstance(e, dict)
        ]
        proposals.append(SkillProposal(
            proposal_id=str(p.get("proposal_id", "")),
            target_file=str(p.get("target_file", "")),
            action_type=str(p.get("action_type", "append_rule")),
            content=str(p.get("content", "")),
            rationale=str(p.get("rationale", "")),
            confidence=_as_float(p.get("confidence"), 0.0),
            risk=str(p.get("risk", "")),
            expected_metric=str(p.get("expected_metric", "")),
            expected_direction=str(p.get("expected_direction", "")),
            section=p.get("section"),
            evidence=evidence,
            conflicts_with=[str(c) for c in p.get("conflicts_with", [])],
        ))

    return RoleSkillConsolidation(
        role=role,
        run_id=run_id,
        parent_hash=parent_hash,
        generated_at=_now(),
        source_window=source_window,
        prompt_version=prompt_version,
        proposals=proposals[:8],
        trends=[str(t) for t in data.get("trends", [])][:5],
        source_games=source_games,
    )


def _load_role_skills_for_str(
    role: str, *, skill_root: Path | str | None = None,
) -> list[MarkdownSkill]:
    """Load skills for a role identified by string (not Role enum)."""
    root = skill_root if isinstance(skill_root, Path) else (Path(skill_root) if skill_root else None)
    if root is None:
        return []
    skills = load_markdown_skills(root)
    return [
        s for s in skills
        if s.role is None or (s.role is not None and s.role.value == role)
    ]
