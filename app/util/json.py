"""JSON helpers."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
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


def read_json_object(path: Any, default: Any = None) -> dict[str, Any] | Any:
    """Read a UTF-8 JSON object, returning default for missing or invalid files."""
    try:
        value = read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return default
    if not isinstance(value, dict):
        return default
    return value


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
    tmp = output_path.parent / (
        f".{output_path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    try:
        tmp.write_text(content, encoding="utf-8")
        _replace_with_retry(tmp, output_path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def write_jsonl(path: Any, rows: Iterable[Any]) -> None:
    """Atomically write rows to a UTF-8 JSONL file using tmp + os.replace."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in rows:
        data = row.to_dict() if hasattr(row, "to_dict") else row
        lines.append(json.dumps(data, ensure_ascii=False, default=str))
    content = ("\n".join(lines) + "\n") if lines else ""
    tmp = output_path.parent / (
        f".{output_path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        tmp.write_text(content, encoding="utf-8")
        _replace_with_retry(tmp, output_path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _replace_with_retry(src: Path, dst: Path) -> None:
    for attempt in range(6):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.01 * (attempt + 1))


def write_text(path: Any, content: str) -> None:
    """Write UTF-8 text, creating parent directories."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
