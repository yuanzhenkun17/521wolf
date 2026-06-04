from __future__ import annotations

from typing import Any

from engine.models import ActionResponse, ActionType, Role
from engine.role_rules.base import BaseRoleRule


class GuardRule(BaseRoleRule):
    role = Role.GUARD

    def init_role_state(self) -> dict[str, Any]:
        return {"last_target": None, "protect_history": []}

    def get_role_state(self, engine, player_id: int) -> dict[str, Any]:
        ps = engine.state.players[player_id]
        return dict(ps.role_state)

    async def night_action(self, engine) -> int | None:
        guards = engine.role_ids(Role.GUARD, alive_only=True)
        if not guards:
            return None
        guard_id = guards[0]
        guard_ps = engine.state.players[guard_id]
        candidates = tuple(player_id for player_id in engine.alive_ids() if player_id != guard_ps.role_state.get("last_target"))
        response = await engine._ask(
            guard_id,
            ActionType.GUARD_PROTECT,
            candidates=candidates,
            validator=lambda res: res.target is None or res.target in candidates,
            default=ActionResponse(ActionType.GUARD_PROTECT),
        )
        guard_ps.role_state["last_target"] = response.target
        guard_ps.role_state["protect_history"].append(
            {"day": engine.state.day, "target": response.target}
        )
        engine._log(
            "guard_result",
            f"守卫 {guard_id} 号守护 {response.target} 号" if response.target else f"守卫 {guard_id} 号未守护",
            actor=guard_id,
            target=response.target,
        )
        return response.target
