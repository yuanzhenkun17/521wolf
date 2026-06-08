"""Winner string helpers."""

from __future__ import annotations


VALID_WINNERS = frozenset({"villagers", "werewolves"})


def normalize_winner(winner: object) -> str | None:
    """Return a canonical rankable winner string, or None for non-results."""
    if winner is None:
        return None
    value = str(winner.value if hasattr(winner, "value") else winner).strip().lower()
    if value == "villager":
        value = "villagers"
    elif value == "werewolf":
        value = "werewolves"
    return value if value in VALID_WINNERS else None


def has_valid_winner(game: dict) -> bool:
    """A game is rankable only when it completed with a real winning side."""
    return not game.get("error") and normalize_winner(game.get("winner")) is not None


def is_werewolf_win(winner: str) -> bool:
    """Check if winner string indicates a werewolf victory."""
    normalized = winner.lower()
    return normalized in ("werewolves", "werewolf") or "werewolf" in normalized
