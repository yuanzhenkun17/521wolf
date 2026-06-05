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

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.models import ActionType, Role

_log = logging.getLogger(__name__)


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
    # Phase 3 fields
    status: str = "active"  # "active" | "deprecated"
    runtime_body: str = ""  # only runtime-relevant sections


# Sections considered "runtime" — their content enters the prompt at decision time.
_RUNTIME_SECTIONS = {"Strategy", "Heuristics", "Decision Rules", "Risk Boundaries"}
# Sections considered "system" — useful for audit/tracking but never in prompt.
_SYSTEM_SECTIONS = {"Examples", "Deprecated Rules", "Changelog", "Provenance", "Evaluation Notes"}

# ---------------------------------------------------------------------------
# Forbidden-content scanner
# ---------------------------------------------------------------------------
# Patterns that must NOT appear in runtime_body.  Each pattern is a compiled
# regex; the human-readable label is stored alongside for violation messages.

_FORBIDDEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Player numbers: P1, P2, P10, 1号, 7号, etc.
    (re.compile(r"\bP\d+\b", re.IGNORECASE), "player number (P1/P2/…)"),
    (re.compile(r"\d+号"), "player number (N号)"),
    # Game/run identifiers
    (re.compile(r"\bgame_id\b", re.IGNORECASE), "game_id"),
    (re.compile(r"\brun_id\b", re.IGNORECASE), "run_id"),
    (re.compile(r"\bseed\b", re.IGNORECASE), "seed"),
    (re.compile(r"\bsource_game_id\b", re.IGNORECASE), "source_game_id"),
    # Model/provider identifiers
    (re.compile(r"\bmodel_id\b", re.IGNORECASE), "model_id"),
    (re.compile(r"\bprovider\b", re.IGNORECASE), "provider"),
    (re.compile(r"\bgpt[-\s]?[34o]", re.IGNORECASE), "model name (GPT)"),
    (re.compile(r"\bclaude[-\s]?(3|sonnet|opus|haiku)", re.IGNORECASE), "model name (Claude)"),
    (re.compile(r"\bgemini\b", re.IGNORECASE), "model name (Gemini)"),
    (re.compile(r"\bllama\b", re.IGNORECASE), "model name (Llama)"),
    # A/B result details
    (re.compile(r"\bwin[-_]?rate\b", re.IGNORECASE), "A/B result (win_rate)"),
    (re.compile(r"\bvictory[-_]?count\b", re.IGNORECASE), "A/B result (victory_count)"),
    (re.compile(r"\bloss[-_]?count\b", re.IGNORECASE), "A/B result (loss_count)"),
    (re.compile(r"\bresult[=:]\s*\w+", re.IGNORECASE), "A/B result detail"),
]

# ---------------------------------------------------------------------------
# Length limits
# ---------------------------------------------------------------------------
_RUNTIME_BODY_SOFT_LIMIT = 1800   # chars – warn
_RUNTIME_BODY_HARD_LIMIT = 2400   # chars – error
_SKILL_FILE_TOTAL_SOFT_LIMIT = 6000  # chars – warn (front-matter + body)


def validate_runtime_body(body: str) -> list[str]:
    """Return a list of forbidden-content violations found in *body*.

    An empty list means the body is clean.
    """
    violations: list[str] = []
    for pattern, label in _FORBIDDEN_PATTERNS:
        if pattern.search(body):
            violations.append(label)
    return violations


def check_skill_limits(skill: MarkdownSkill) -> list[str]:
    """Return a list of limit warnings/errors for *skill*.

    Items prefixed with ``"[soft]"`` are warnings; ``"[hard]"`` are errors.
    An empty list means all limits are respected.
    """
    issues: list[str] = []
    rb_len = len(skill.runtime_body)
    if rb_len > _RUNTIME_BODY_HARD_LIMIT:
        issues.append(
            f"[hard] runtime_body length {rb_len} exceeds hard limit "
            f"{_RUNTIME_BODY_HARD_LIMIT}"
        )
    elif rb_len > _RUNTIME_BODY_SOFT_LIMIT:
        issues.append(
            f"[soft] runtime_body length {rb_len} exceeds soft limit "
            f"{_RUNTIME_BODY_SOFT_LIMIT}"
        )

    total_len = len(skill.body)
    if total_len > _SKILL_FILE_TOTAL_SOFT_LIMIT:
        issues.append(
            f"[soft] skill body length {total_len} exceeds soft limit "
            f"{_SKILL_FILE_TOTAL_SOFT_LIMIT}"
        )
    return issues


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
    status = str(front.get("status", "active")).strip().lower()
    if status not in ("active", "deprecated"):
        status = "active"

    # Extract runtime_body from markdown sections
    full_body = body.strip()
    runtime_body = _extract_runtime_sections(full_body)

    skill = MarkdownSkill(
        name=name,
        relative_path=_relative_skill_path(path, root),
        description=description,
        role=role,
        applicable_actions=actions,
        requires=requires,
        body=full_body,
        evolution=evolution,
        status=status,
        runtime_body=runtime_body,
    )

    # --- runtime validation (warn only, never reject) ---
    violations = validate_runtime_body(runtime_body)
    if violations:
        _log.warning(
            "Skill %s has forbidden runtime content: %s", name, violations
        )
    limit_issues = check_skill_limits(skill)
    for issue in limit_issues:
        _log.warning("Skill %s limit issue: %s", name, issue)

    return skill


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


def _extract_runtime_sections(body: str) -> str:
    """Extract content under runtime section headings.

    Runtime sections (Strategy, Heuristics, Decision Rules, Risk Boundaries)
    are included in the prompt. System sections (Examples, Deprecated Rules,
    Changelog, Provenance, Evaluation Notes) are excluded from the prompt.

    If no explicit sections are found, the entire body is treated as runtime.
    """
    # Check if body has any section headings
    heading_pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    headings = heading_pattern.findall(body)

    if not headings:
        # No sections — treat entire body as runtime
        return body

    # Check if any runtime sections exist
    has_runtime = any(h.strip() in _RUNTIME_SECTIONS for h in headings)
    if not has_runtime:
        # No recognized runtime sections — treat entire body as runtime
        return body

    # Extract content under runtime section headings
    sections = _split_into_sections(body)
    runtime_parts = []
    for heading, content in sections:
        heading_clean = heading.strip()
        if heading_clean in _RUNTIME_SECTIONS:
            runtime_parts.append(f"## {heading}\n{content}")

    return "\n\n".join(runtime_parts).strip()


def _split_into_sections(body: str) -> list[tuple[str, str]]:
    """Split markdown body into (heading, content) pairs."""
    heading_pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(heading_pattern.finditer(body))

    if not matches:
        return [("", body)]

    sections = []
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        sections.append((heading, content))

    # Content before first heading
    if matches[0].start() > 0:
        pre = body[: matches[0].start()].strip()
        if pre:
            sections.insert(0, ("", pre))

    return sections
