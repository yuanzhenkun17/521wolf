"""JSON helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable


def compact_json(value: Any) -> str:
    """JSON-dump value with compact format, sorted keys, non-ASCII preserved.

    Falls back to str(value) on TypeError.
    """
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses, paths, and mapping keys to JSON-safe values."""
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


class DictMixin:
    """Small serialization helper for dataclass-style models."""

    def to_dict(self) -> dict[str, Any]:
        return to_jsonable(self)


def read_json(path: Any) -> dict[str, Any]:
    """Read a UTF-8 JSON object from a file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path: Any) -> list[dict[str, Any]]:
    """Read a UTF-8 JSONL file. Missing files return an empty list."""
    input_path = Path(path)
    if not input_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_json(path: Any, data: Any) -> None:
    """Atomically write JSON data to a file using tmp + os.replace."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp")
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(output_path))


def write_jsonl(path: Any, rows: Iterable[Any]) -> None:
    """Write rows to a UTF-8 JSONL file."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in rows:
        data = row.to_dict() if hasattr(row, "to_dict") else row
        lines.append(json.dumps(data, ensure_ascii=False, default=str))
    output_path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def write_text(path: Any, content: str) -> None:
    """Write UTF-8 text, creating parent directories."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
