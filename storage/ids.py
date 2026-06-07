"""Stable IDs for storage indexes derived from raw artifact paths."""

from __future__ import annotations

import re
from pathlib import Path


_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:(?:/|$)")


def safe_storage_id(value: str) -> str:
    text = str(value).strip().replace("\\", "/")
    _reject_unsafe_path_id(text)

    segments = [segment for segment in text.split("/") if segment]
    safe_segments = [
        re.sub(r"[^A-Za-z0-9_.-]+", "_", segment)
        for segment in segments
    ]
    return "::".join(segment for segment in safe_segments if segment) or "unknown"


def _reject_unsafe_path_id(text: str) -> None:
    if not text:
        return
    if "\0" in text:
        raise ValueError("Unsafe storage id: contains NUL byte")
    if text.startswith("//"):
        raise ValueError(f"Unsafe storage id: absolute UNC path {text!r}")
    if text.startswith("/"):
        raise ValueError(f"Unsafe storage id: absolute path {text!r}")
    if _WINDOWS_DRIVE_RE.match(text) or ":" in text:
        raise ValueError(f"Unsafe storage id: drive or colon character {text!r}")
    if any(segment in {".", ".."} for segment in text.split("/")):
        raise ValueError(f"Unsafe storage id: relative path segment {text!r}")


def artifact_game_id(
    game_dir: Path,
    *,
    root: Path | None = None,
    raw_game_id: str | None = None,
) -> str:
    if root is not None:
        try:
            relative = game_dir.resolve().relative_to(root.resolve())
        except ValueError:
            raise ValueError(f"Artifact path {str(game_dir)!r} is not under root {str(root)!r}") from None
        return safe_storage_id(relative.as_posix())
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
