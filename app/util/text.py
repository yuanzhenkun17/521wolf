"""Text parsing utilities — JSON extraction, YAML front matter, Markdown sections.

Moved from app/services/chain.py (_parse_json) and app/services/prompt.py
(YAML + Markdown helpers).
"""

from __future__ import annotations

from typing import Any


# ===========================================================================
# JSON extraction from LLM output
# ===========================================================================

def extract_json(content: str) -> dict:
    """Parse JSON from raw LLM output, handling code fences and partial text.

    Tries exact parse first, then extracts the first balanced {…} block.
    Raises ValueError if no valid JSON object is found.
    """
    import json

    try:
        return json.loads(content.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    start = content.find("{")
    if start == -1:
        raise ValueError("no JSON object found in output")

    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(content[start : i + 1])

    raise ValueError("unbalanced JSON braces in output")


def try_extract_json(content: str) -> dict | None:
    """Like extract_json, but returns None instead of raising."""
    try:
        return extract_json(content)
    except ValueError:
        return None


# ===========================================================================
# YAML-like front matter parsing (no PyYAML dependency)
# ===========================================================================

def parse_yaml_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like front matter from a Markdown string.

    Returns ``(front_matter_dict, body_string)``.
    If no front matter is found, returns ``({}, text)``.

    Supports simple types: str, int, float, bool, list[str],
    and one-level nested dict of str -> simple.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break

    if end is None:
        return {}, text

    raw = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    data = _parse_yaml_like(raw)
    return data, body


def _parse_yaml_like(raw: str) -> dict[str, Any]:
    """Parse raw front-matter lines into a dict (YAML-like subset)."""
    result: dict[str, Any] = {}
    current_key: str | None = None
    nested_lines: list[str] | None = None

    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[0] in (" ", "\t") and current_key is not None:
            if nested_lines is not None:
                nested_lines.append(stripped)
            continue
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
        result[key] = coerce_value(raw_val)

    if nested_lines is not None and current_key is not None:
        result[current_key] = _parse_nested_value(nested_lines)

    return result


def _parse_nested_value(lines: list[str]) -> Any:
    """Parse indented lines as either a list (if ``-``) or a dict."""
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
            items.append(coerce_value(stripped[2:].strip()))
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
            d[k] = coerce_value(v)

    if list_lines is not None and current_key is not None:
        d[current_key] = _parse_simple_list(list_lines)

    return d


def coerce_value(raw: str) -> Any:
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


# ===========================================================================
# Markdown section splitting
# ===========================================================================

import re

_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def split_markdown_sections(body: str) -> list[tuple[str, str]]:
    """Split Markdown body into ``(heading, content)`` pairs at ``##`` boundaries."""
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return [("", body)]

    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((heading, body[start:end].strip()))

    # Content before first heading
    if matches[0].start() > 0:
        pre = body[: matches[0].start()].strip()
        if pre:
            sections.insert(0, ("", pre))

    return sections
