"""JSON helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def compact_json(value: Any) -> str:
    """JSON-dump value with compact format, sorted keys, non-ASCII preserved.

    Falls back to str(value) on TypeError.
    """
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def write_json(path: Any, data: Any) -> None:
    """Atomically write JSON data to a file using tmp + os.replace."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp")
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(output_path))
