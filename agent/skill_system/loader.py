"""Lightweight Markdown skill loader.

Loads skill definitions from Markdown files with YAML front matter
and returns :class:`MarkdownSkill` instances.

Directory structure::

    skills/
      common/
        game_rules.md
        output_schema.md
      werewolf/
        fake_seer.md
      seer/
        claim.md
      …
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.models import ActionType, Role


@dataclass(slots=True)
class MarkdownSkill:
    """A skill defined in a Markdown file (YAML front matter + body)."""

    name: str
    relative_path: str = ""
    description: str = ""
    role: Role | None = None
    applicable_actions: set[ActionType] = field(default_factory=set)
    requires: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    evolution: dict[str, Any] = field(default_factory=lambda: {"enabled": False, "allowed_actions": []})


_FRONT_MATTER_SEP = "---"


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like front matter from a Markdown string.

    Supports only simple types: str, int, float, bool, list[str],
    and one-level nested dict of str -> simple.  This avoids a PyYAML
    dependency.

    Returns ``(front_matter_dict, body_string)``.  If no front matter
    is found, returns ``({}, text)``.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != _FRONT_MATTER_SEP:
        return {}, text

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FRONT_MATTER_SEP:
            end = i
            break

    if end is None:
        return {}, text

    raw = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    data = _parse_yaml_like(raw)
    return data, body


def _parse_yaml_like(raw: str) -> dict[str, Any]:
    """Parse the raw front-matter lines into a dict (YAML-like subset)."""
    result: dict[str, Any] = {}
    current_key: str | None = None
    nested_lines: list[str] | None = None

    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Detect nested block (indented)
        if line[0] in (" ", "\t") and current_key is not None:
            if nested_lines is not None:
                nested_lines.append(stripped)
            continue

        # Flush nested dict if we were building one
        if nested_lines is not None:
            result[current_key] = _parse_nested_value(nested_lines)
            nested_lines = None

        if ":" not in stripped:
            continue

        key, _, raw_val = stripped.partition(":")
        key = key.strip()
        raw_val = raw_val.strip()

        if not raw_val:
            current_key = key
            nested_lines = []
            continue

        result[key] = _coerce_value(raw_val)

    if nested_lines is not None and current_key is not None:
        result[current_key] = _parse_nested_value(nested_lines)

    return result


def _parse_nested_value(lines: list[str]) -> Any:
    """Parse indented lines as either a list (if lines start with ``-``) or a dict."""
    if not lines:
        return {}
    first = next((line for line in lines if line.strip()), "")
    if first.startswith("-"):
        return _parse_simple_list(lines)
    return _parse_nested_dict_with_lists(lines)


def _parse_simple_list(lines: list[str]) -> list[str]:
    """Parse indented ``- item`` lines into a list of strings."""
    items = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(_coerce_value(stripped[2:].strip()))
    return items


def _parse_nested_dict_with_lists(lines: list[str]) -> dict[str, Any]:
    """Parse indented ``key: value`` lines into a dict, handling nested lists."""
    d: dict[str, Any] = {}
    current_key: str | None = None
    list_lines: list[str] | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Flush pending list
        if list_lines is not None and not stripped.startswith("-"):
            d[current_key] = _parse_simple_list(list_lines)
            list_lines = None
            current_key = None

        if stripped.startswith("-") and current_key is not None:
            if list_lines is None:
                list_lines = []
            list_lines.append(stripped)
            continue

        if ":" in stripped:
            k, _, v = stripped.partition(":")
            k = k.strip()
            v = v.strip()
            if not v:
                current_key = k
                list_lines = []
                continue
            d[k] = _coerce_value(v)

    # Flush remaining list
    if list_lines is not None and current_key is not None:
        d[current_key] = _parse_simple_list(list_lines)

    return d


def _coerce_value(raw: str) -> Any:
    """Coerce a YAML value string to its Python type."""
    if not raw:
        return None
    if raw.lower() in ("true", "yes"):
        return True
    if raw.lower() in ("false", "no"):
        return False
    if raw.startswith("[") and raw.endswith("]"):
        items = [item.strip().strip('"').strip("'") for item in raw[1:-1].split(",")]
        return [item for item in items if item]
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw.strip('"').strip("'")


_skill_cache: tuple[float, Path, list[MarkdownSkill]] | None = None


def load_markdown_skills(root: Path) -> list[MarkdownSkill]:
    """Recursively load markdown skills from *root*.

    Results are cached based on the directory's mtime so repeated calls
    within the same game tick avoid redundant disk I/O.
    """
    global _skill_cache
    if not root.is_dir():
        return []
    try:
        mtime = os.path.getmtime(root)
    except OSError:
        mtime = 0.0
    if _skill_cache is not None and _skill_cache[1] == root and _skill_cache[0] == mtime:
        return _skill_cache[2]
    skills: list[MarkdownSkill] = []
    for md_path in sorted(root.rglob("*.md")):
        skill = _load_skill_file(md_path, root=root)
        if skill is not None:
            skills.append(skill)
    _skill_cache = (mtime, root, skills)
    return skills


def _load_skill_file(path: Path, *, root: Path | None = None) -> MarkdownSkill | None:
    """Load a single markdown skill file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    front, body = parse_front_matter(text)
    if not front:
        return None

    name = front.get("name", path.stem)
    description = front.get("description", "")

    role: Role | None = None
    role_name = front.get("role")
    if role_name:
        try:
            role = Role(role_name)
        except (ValueError, KeyError):
            pass

    raw_actions = front.get("applicable_actions", [])
    if isinstance(raw_actions, str):
        raw_actions = [raw_actions]
    actions: set[ActionType] = set()
    for a in raw_actions:
        try:
            actions.add(ActionType(a))
        except (ValueError, KeyError):
            pass

    requires = front.get("requires", {})
    if not isinstance(requires, dict):
        requires = {}

    evolution = _normalize_evolution(front.get("evolution", {}))

    return MarkdownSkill(
        name=name,
        relative_path=_relative_skill_path(path, root),
        description=description,
        role=role,
        applicable_actions=actions,
        requires=requires,
        body=body.strip(),
        evolution=evolution,
    )


def _relative_skill_path(path: Path, root: Path | None) -> str:
    """Return a stable POSIX-style skill path for prompt and proposal use."""
    try:
        if root is not None:
            return path.relative_to(root).as_posix()
    except ValueError:
        pass
    return path.name


def _normalize_evolution(value: Any) -> dict[str, Any]:
    """Normalize optional evolution metadata to the keys validators expect."""
    evolution = dict(value) if isinstance(value, dict) else {}
    raw_allowed = evolution.get("allowed_actions", [])
    if isinstance(raw_allowed, str):
        allowed_actions = [raw_allowed]
    elif isinstance(raw_allowed, list):
        allowed_actions = [str(action) for action in raw_allowed]
    else:
        allowed_actions = []
    evolution["enabled"] = bool(evolution.get("enabled", False))
    evolution["allowed_actions"] = allowed_actions
    return evolution
