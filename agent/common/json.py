"""JSON helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def compact_json(value: Any) -> str:
    """JSON-dump value with readable indentation and non-ASCII preserved."""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def write_json(path: Any, data: Any) -> None:
    """Write formatted JSON to path, creating parent directories."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
