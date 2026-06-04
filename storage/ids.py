"""Stable IDs for storage indexes derived from raw artifact paths."""

from __future__ import annotations

import re
from pathlib import Path


def safe_storage_id(value: str) -> str:
    text = value.strip().replace("\\", "/")
    text = re.sub(r"[^A-Za-z0-9_.:/-]+", "_", text)
    return text.replace("/", "::").strip(":") or "unknown"


def artifact_game_id(
    game_dir: Path,
    *,
    root: Path | None = None,
    raw_game_id: str | None = None,
) -> str:
    if root is not None:
        try:
            relative = game_dir.resolve().relative_to(root.resolve())
            return safe_storage_id(relative.as_posix())
        except ValueError:
            pass
    return safe_storage_id(game_dir.name or raw_game_id or "unknown")


def storage_decision_id(game_id: str, raw_decision_id: str) -> str:
    raw = str(raw_decision_id)
    prefix = f"{game_id}::"
    if raw.startswith(prefix):
        return raw
    return f"{game_id}::{safe_storage_id(raw)}"


def public_decision_id(storage_id: str, game_id: str) -> str:
    prefix = f"{game_id}::"
    if storage_id.startswith(prefix):
        return storage_id[len(prefix):]
    return storage_id
