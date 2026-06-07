"""Winner string helpers."""

from __future__ import annotations


def is_werewolf_win(winner: str) -> bool:
    """Check if winner string indicates a werewolf victory."""
    normalized = winner.lower()
    return normalized in ("werewolves", "werewolf") or "werewolf" in normalized
