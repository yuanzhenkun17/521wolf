from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from werewolf.models import Role, Team

if TYPE_CHECKING:
    from werewolf.engine import GameEngine


class RoleRule(Protocol):
    role: Role

    def visible_roles(self, engine: GameEngine, player_id: int) -> dict[int, Role]:
        ...

    def seer_checks(self, engine: GameEngine, player_id: int) -> dict[int, Team]:
        ...

    async def night_action(self, engine: GameEngine):
        ...

    async def day_interrupt(self, engine: GameEngine, player_id: int) -> str | None:
        ...


class BaseRoleRule:
    role: Role

    def visible_roles(self, engine: GameEngine, player_id: int) -> dict[int, Role]:
        return {}

    def seer_checks(self, engine: GameEngine, player_id: int) -> dict[int, Team]:
        return {}

    async def night_action(self, engine: GameEngine):
        return None

    async def day_interrupt(self, engine: GameEngine, player_id: int) -> str | None:
        return None
