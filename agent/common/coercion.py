"""Type coercion helpers."""

from __future__ import annotations

from typing import Any


def as_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int_list(value: Any) -> list[int]:
    """Safely convert a list of values to ``list[int]``."""
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result
