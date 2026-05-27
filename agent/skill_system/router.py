"""Skill router — selects which Markdown skills to inject into a prompt.

Logic::

    1. Always inject common skills (scope="common").
    2. Inject role skills matching ctx.role and ctx.request.action_type.
    3. Filter by requires metadata match.
"""

from __future__ import annotations

from pathlib import Path

from engine.models import ActionType, Role

from agent.runtime.context import AgentContext
from agent.skill_system.loader import MarkdownSkill, load_markdown_skills


# Module-level caches — loaded once at import time
_COMMON_SKILLS: list[MarkdownSkill] = []
_ROLE_SKILLS: dict[Role, list[MarkdownSkill]] = {}
_SKILL_ROOT: Path = Path(__file__).parent.parent / "skills"


def configure_skill_root(root: Path | str | None = None) -> None:
    """Configure the Markdown skill root and clear the cached index."""
    global _SKILL_ROOT
    _SKILL_ROOT = Path(root) if root is not None else Path(__file__).parent.parent / "skills"
    _COMMON_SKILLS.clear()
    _ROLE_SKILLS.clear()


def _init_skills() -> None:
    """Load all markdown skills and index by scope + role."""
    all_skills = load_markdown_skills(_SKILL_ROOT)

    _COMMON_SKILLS.clear()
    _ROLE_SKILLS.clear()

    for skill in all_skills:
        if skill.scope == "common":
            _COMMON_SKILLS.append(skill)
        elif skill.role is not None:
            _ROLE_SKILLS.setdefault(skill.role, []).append(skill)


def _requirements_match(requires: dict, ctx: AgentContext) -> bool:
    """Check whether request metadata satisfies the skill's ``requires``."""
    for key, expected in requires.items():
        if ctx.request.metadata.get(key) != expected:
            return False
    return True


def select_skills(ctx: AgentContext, role: Role) -> list[MarkdownSkill]:
    """Select common + role skills matching the current context.

    Returns:
        A list of :class:`MarkdownSkill` instances.  Common skills first,
        then role skills, sorted by name within each group.
    """
    if not _COMMON_SKILLS and not _ROLE_SKILLS:
        _init_skills()

    selected: list[MarkdownSkill] = []

    # 1. Always inject common skills
    selected.extend(_COMMON_SKILLS)

    # 2. Inject role skills matching role + action_type
    action_type = ctx.request.action_type
    for skill in _ROLE_SKILLS.get(role, []):
        if action_type in skill.applicable_actions:
            if _requirements_match(skill.requires, ctx):
                selected.append(skill)

    return selected


def format_skill_context(selected: list[MarkdownSkill], action_type: ActionType) -> str:
    """Format a list of skills into a prompt block.

    Common skills are grouped under "通用规则 Skill", role skills under
    "角色策略 Skill".  Skills matching the current action type are listed
    first within the role section.
    """
    parts: list[str] = []

    common = [s for s in selected if s.scope == "common"]
    role_skills = [s for s in selected if s.scope == "role"]

    if common:
        parts.append("## 通用规则 Skill")
        parts.append("")
        for skill in common:
            parts.append(f"### {skill.name}")
            parts.append("")
            parts.append(skill.body)
            parts.append("")

    if role_skills:
        parts.append("## 角色策略 Skill")
        parts.append("")
        # Action-relevant skills first, then others
        action_skills = [s for s in role_skills if action_type in s.applicable_actions]
        other_skills = [s for s in role_skills if action_type not in s.applicable_actions]
        for skill in action_skills + other_skills:
            parts.append(f"### {skill.name}")
            parts.append("")
            parts.append(skill.body)
            parts.append("")

    return "\n".join(parts).strip()
