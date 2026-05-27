"""Skill router — selects which Markdown skills to inject into a prompt.

Logic::

    1. Always inject common skills (scope="common").
    2. Inject role skills matching ctx.role and ctx.request.action_type.
    3. Filter by requires metadata match.
    4. Empty applicable_actions = always inject for that role.

Two-stage flow (when LLM is available):
    Stage 1: ``select_skills_by_llm()`` sends descriptions, LLM picks relevant skills.
    Stage 2: ``filter_by_selection()`` keeps only LLM-selected skills for full injection.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from engine.models import ActionType, Role

from agent.runtime.context import AgentContext
from agent.skill_system.loader import MarkdownSkill, load_markdown_skills


class _ModelLike(Protocol):
    async def complete(self, messages: list[dict[str, str]], *, name: str = "") -> str: ...


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SKILL_ROOT: Path = _PROJECT_ROOT / "skills"


@dataclass
class SkillIndex:
    """Indexed skill collection for one skill root."""
    common: list[MarkdownSkill]
    by_role: dict[Role, list[MarkdownSkill]]


_SKILL_CACHE: dict[Path, SkillIndex] = {}


def configure_skill_root(root: Path | str | None = None) -> None:
    """Configure the default skill root and clear the cache. For testing."""
    global DEFAULT_SKILL_ROOT
    DEFAULT_SKILL_ROOT = Path(root) if root is not None else _PROJECT_ROOT / "skills"
    _SKILL_CACHE.clear()


def _load_skill_index(root: Path) -> SkillIndex:
    """Load all markdown skills from root and index by scope + role."""
    all_skills = load_markdown_skills(root)
    common: list[MarkdownSkill] = []
    by_role: dict[Role, list[MarkdownSkill]] = {}
    for skill in all_skills:
        if skill.scope == "common":
            common.append(skill)
        elif skill.role is not None:
            by_role.setdefault(skill.role, []).append(skill)
    return SkillIndex(common=common, by_role=by_role)


def _get_skill_index(skill_root: Path | None = None) -> SkillIndex:
    """Get or load the skill index for the given root."""
    root = (skill_root or DEFAULT_SKILL_ROOT).resolve()
    if root not in _SKILL_CACHE:
        _SKILL_CACHE[root] = _load_skill_index(root)
    return _SKILL_CACHE[root]


def _requirements_match(requires: dict, ctx: AgentContext) -> bool:
    """Check whether request metadata satisfies the skill requires."""
    for key, expected in requires.items():
        if ctx.request.metadata.get(key) != expected:
            return False
    return True


def select_skills(
    ctx: AgentContext,
    role: Role,
    *,
    skill_root: Path | None = None,
) -> list[MarkdownSkill]:
    """Select common + role skills matching the current context.

    Returns:
        Common skills first, then role skills, sorted by name within each group.
    """
    idx = _get_skill_index(skill_root)
    selected: list[MarkdownSkill] = []

    # 1. Always inject common skills
    selected.extend(idx.common)

    # 2. Inject role skills matching role + action_type
    action_type = ctx.request.action_type
    for skill in idx.by_role.get(role, []):
        if not skill.applicable_actions or action_type in skill.applicable_actions:
            if _requirements_match(skill.requires, ctx):
                selected.append(skill)

    return selected


def format_skill_context(selected: list[MarkdownSkill], action_type: ActionType) -> str:
    """Format selected skills into a prompt block.

    Common skills under generic header, role skills under role header.
    Action-relevant skills listed first within the role section.
    """
    parts: list[str] = []

    common = [s for s in selected if s.scope == "common"]
    role_skills = [s for s in selected if s.scope == "role"]

    if common:
        parts.append("## common rules Skill")
        parts.append("")
        for skill in common:
            parts.append(f"### {skill.name}")
            parts.append("")
            parts.append(skill.body)
            parts.append("")

    if role_skills:
        parts.append("## role strategy Skill")
        parts.append("")
        action_skills = [s for s in role_skills if action_type in s.applicable_actions]
        other_skills = [s for s in role_skills if action_type not in s.applicable_actions]
        for skill in action_skills + other_skills:
            parts.append(f"### {skill.name}")
            parts.append("")
            parts.append(skill.body)
            parts.append("")

    return chr(10).join(parts).strip()


# ── Two-stage skill selection ────────────────────────────────────────────────


_SELECTION_PROMPT = (
    "你是狼人杀 AI，需要选择当前场景最相关的策略技能。\n\n"
    "当前角色: {role}\n"
    "当前动作: {action_type}\n"
    "已有身份声明: {claims}\n\n"
    "可用技能:\n{skill_list}\n\n"
    "请选择最相关的技能，输出 JSON 数组（技能名称列表），如 [\"skill_a\", \"skill_b\"]。\n"
    "只输出 JSON 数组，不要输出其他内容。"
)


def _build_skill_list(skills: list[MarkdownSkill]) -> str:
    lines = []
    for s in skills:
        desc = s.description or "(无描述)"
        lines.append(f"- {s.name}: {desc}")
    return "\n".join(lines)


def _parse_skill_names(raw: str) -> list[str]:
    """Extract a JSON array of skill names from LLM output."""
    # Try direct parse first
    try:
        parsed = json.loads(raw.strip())
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    # Try extracting JSON array from text
    match = re.search(r'\[.*?\]', raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


async def select_skills_by_llm(
    ctx: AgentContext,
    role: Role,
    model: _ModelLike,
    *,
    skill_root: Path | None = None,
) -> list[MarkdownSkill] | None:
    """Stage 1: Ask LLM to select relevant skills from descriptions.

    Returns the selected skills, or None if the LLM call fails (caller
    should fall back to ``select_skills()``).
    """
    idx = _get_skill_index(skill_root)
    candidates: list[MarkdownSkill] = list(idx.common)
    for skill in idx.by_role.get(role, []):
        if not skill.applicable_actions or ctx.request.action_type in skill.applicable_actions:
            if _requirements_match(skill.requires, ctx):
                candidates.append(skill)

    if not candidates:
        return []

    claims = {k: v for k, v in ctx.request.metadata.items() if "claim" in k.lower()}
    claims_str = str(claims) if claims else "{}"

    prompt = _SELECTION_PROMPT.format(
        role=role.value,
        action_type=ctx.request.action_type.value,
        claims=claims_str,
        skill_list=_build_skill_list(candidates),
    )
    messages = [{"role": "user", "content": prompt}]

    try:
        raw = await model.complete(messages, name=f"skill_select/{ctx.player_id}")
    except Exception:
        return None

    selected_names = set(_parse_skill_names(raw))
    if not selected_names:
        return None

    # Always include common skills
    selected = [s for s in idx.common]
    # Add LLM-selected role skills
    for skill in candidates:
        if skill.name in selected_names and skill.scope != "common":
            selected.append(skill)
    return selected


def filter_by_selection(
    skills: list[MarkdownSkill],
    selected_names: set[str],
) -> list[MarkdownSkill]:
    """Keep only skills whose names are in ``selected_names``."""
    return [s for s in skills if s.name in selected_names or s.scope == "common"]
