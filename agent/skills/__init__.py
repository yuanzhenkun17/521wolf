"""Skill system.

Skills are Markdown files in ``skills/`` loaded by :mod:`skill_loader` and
selected by :mod:`skill_router`.  No Python skill classes — pure Markdown.
"""

from agent.skill_system.loader import MarkdownSkill, load_markdown_skills, parse_front_matter
from agent.skill_system.router import select_skills, format_skill_context

__all__ = [
    "MarkdownSkill",
    "load_markdown_skills",
    "parse_front_matter",
    "select_skills",
    "format_skill_context",
]
