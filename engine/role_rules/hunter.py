from __future__ import annotations

from typing import Any

from engine.models import Role
from engine.role_rules.base import BaseRoleRule


class HunterRule(BaseRoleRule):
    role = Role.HUNTER

    def init_role_state(self) -> dict[str, Any]:
        return {"has_shot": False, "shot_target": None}

    def get_role_state(self, engine, player_id: int) -> dict[str, Any]:
        ps = engine.state.players[player_id]
        return dict(ps.role_state)
