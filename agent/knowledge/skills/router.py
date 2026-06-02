"""Skill router — selects which Markdown skills to inject into a prompt.

Logic::

    1. Inject role skills matching ctx.role and ctx.request.action_type.
    2. Filter by requires metadata match.
    3. Empty applicable_actions = always inject for that role.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.models import ActionType, Role

from agent.core.context import AgentContext
from agent.knowledge.skills.loader import MarkdownSkill, load_markdown_skills


_log = logging.getLogger(__name__)


@dataclass
class SkillIndex:
    """Indexed skill collection for one skill root."""
    by_role: dict[Role, list[MarkdownSkill]]


_SKILL_CACHE: dict[Path, SkillIndex] = {}
_CURRENT_SKILL_ROOT: Path | None = None


def configure_skill_root(root: Path | str | None = None) -> None:
    """Configure the skill root and clear the cache. For testing."""
    global _CURRENT_SKILL_ROOT
    _CURRENT_SKILL_ROOT = Path(root) if root is not None else None
    _SKILL_CACHE.clear()


def _load_skill_index(root: Path) -> SkillIndex:
    """Load all markdown skills from root and index by role."""
    all_skills = load_markdown_skills(root)
    by_role: dict[Role, list[MarkdownSkill]] = {}
    for skill in all_skills:
        if skill.role is not None:
            by_role.setdefault(skill.role, []).append(skill)
    return SkillIndex(by_role=by_role)


def _get_skill_index(skill_root: Path | None = None) -> SkillIndex:
    """Get or load the skill index for the given root.

    If *skill_root* is None and no root has been configured, returns
    an empty index — the system works without a seed skills directory.
    """
    root = skill_root or _CURRENT_SKILL_ROOT
    if root is None:
        return SkillIndex(by_role={})
    root = root.resolve()
    if root not in _SKILL_CACHE:
        _SKILL_CACHE[root] = _load_skill_index(root)
    return _SKILL_CACHE[root]


def _requirements_match(requires: dict[str, Any], ctx: AgentContext) -> bool:
    """Check whether request metadata satisfies the skill requires."""
    if not ctx.request.metadata:
        return not requires
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
    """Select role skills matching the current context.

    Returns:
        Role skills matching role + action_type, sorted by name.
    """
    idx = _get_skill_index(skill_root)
    selected: list[MarkdownSkill] = []

    # Inject role skills matching role + action_type
    action_type = ctx.request.action_type
    for skill in idx.by_role.get(role, []):
        if not skill.applicable_actions or action_type in skill.applicable_actions:
            if _requirements_match(skill.requires, ctx):
                selected.append(skill)

    return selected


def format_skill_context(selected: list[MarkdownSkill], action_type: ActionType) -> str:
    """Format selected skills into a prompt block.

    Role skills under role header, action-relevant skills listed first.
    """
    parts: list[str] = []

    if selected:
        parts.append("## role strategy Skill")
        parts.append("")
        action_skills = [s for s in selected if action_type in s.applicable_actions]
        other_skills = [s for s in selected if action_type not in s.applicable_actions]
        for skill in action_skills + other_skills:
            parts.append(f"### {skill.name}")
            parts.append("")
            parts.append(skill.body)
            parts.append("")

    return chr(10).join(parts).strip()


