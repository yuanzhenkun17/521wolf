from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from engine.models import Role


@dataclass(frozen=True, slots=True)
class GameConfig:
    name: str
    role_counts: Mapping[Role, int]
    enable_sheriff: bool = True
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
