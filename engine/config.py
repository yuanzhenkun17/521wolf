from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from engine.models import Role


@dataclass(frozen=True, slots=True)
class GameConfig:
    """Game rules and runtime configuration.

    Centralises all tuneable parameters so they aren't scattered as
    hardcoded literals across engine, voting, and runner code.
    """

    name: str
    role_counts: Mapping[Role, int]
    enable_sheriff: bool = True
    sheriff_vote_weight: float = 1.5
    max_days: int = 20
    runner_max_retries: int = 2
    runner_retry_delay: float = 0.0
    runner_action_timeout: float | None = None
    night_order: tuple[Role, ...] = (
        Role.GUARD,
        Role.WEREWOLF,
        Role.SEER,
        Role.WITCH,
    )

    @property
    def player_count(self) -> int:
        return sum(self.role_counts.values())

    @property
    def role_counter(self) -> Counter[Role]:
        return Counter(self.role_counts)


STANDARD_12 = GameConfig(
    name="standard_12",
    runner_max_retries=1,
    role_counts={
        Role.WEREWOLF: 3,
        Role.WHITE_WOLF_KING: 1,
        Role.VILLAGER: 4,
        Role.SEER: 1,
        Role.WITCH: 1,
        Role.HUNTER: 1,
        Role.GUARD: 1,
    },
)
