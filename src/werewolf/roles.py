from __future__ import annotations

from collections import Counter
import random

from werewolf.config import GameConfig, STANDARD_12
from werewolf.models import Role


def standard_roles() -> dict[int, Role]:
    return assign_roles(
        STANDARD_12,
        ordered_roles=(
            Role.WHITE_WOLF_KING,
            Role.WEREWOLF,
            Role.WEREWOLF,
            Role.WEREWOLF,
            Role.SEER,
            Role.WITCH,
            Role.HUNTER,
            Role.GUARD,
            Role.VILLAGER,
            Role.VILLAGER,
            Role.VILLAGER,
            Role.VILLAGER,
        ),
    )


def random_standard_roles(seed: int | None = None, rng: random.Random | None = None) -> dict[int, Role]:
    return assign_roles(STANDARD_12, seed=seed, rng=rng)


def roles_from_config(config: GameConfig) -> list[Role]:
    roles: list[Role] = []
    for role, count in config.role_counts.items():
        roles.extend([role] * count)
    return roles


def assign_roles(
    config: GameConfig,
    *,
    seed: int | None = None,
    rng: random.Random | None = None,
    ordered_roles: tuple[Role, ...] | list[Role] | None = None,
) -> dict[int, Role]:
    roles = list(ordered_roles) if ordered_roles is not None else roles_from_config(config)
    if len(roles) != config.player_count:
        raise ValueError(f"expected {config.player_count} roles for {config.name}, got {len(roles)}")
    actual = Counter(roles)
    if actual != config.role_counter:
        raise ValueError(f"expected roles for {config.name}: {dict(config.role_counter)}, got {dict(actual)}")
    if ordered_roles is None:
        role_rng = rng or random.Random(seed)
        role_rng.shuffle(roles)
    return {
        player_id: role
        for player_id, role in zip(range(1, config.player_count + 1), roles, strict=True)
    }
