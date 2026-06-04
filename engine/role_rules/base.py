from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from engine.models import Role, Team

if TYPE_CHECKING:
    from engine.engine import GameEngine


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

    def init_role_state(self) -> dict[str, Any]:
        ...

    def get_role_state(self, engine: GameEngine, player_id: int) -> dict[str, Any]:
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

    def init_role_state(self) -> dict[str, Any]:
        """Return the initial role_state dict for this role."""
        return {}

    def get_role_state(self, engine: GameEngine, player_id: int) -> dict[str, Any]:
        """Return the current visible role_state for the given player."""
        return {}
