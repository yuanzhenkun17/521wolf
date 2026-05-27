from __future__ import annotations

from engine.models import ActionResponse, ActionType, Role
from engine.role_rules.base import BaseRoleRule


class GuardRule(BaseRoleRule):
    role = Role.GUARD

    async def night_action(self, engine) -> int | None:
        guards = engine.role_ids(Role.GUARD, alive_only=True)
        if not guards:
            return None
        candidates = tuple(player_id for player_id in engine.alive_ids() if player_id != engine.state.guard_last_target)
        response = await engine._ask(
            guards[0],
            ActionType.GUARD_PROTECT,
            candidates=candidates,
            validator=lambda res: res.target is None or res.target in candidates,
            default=ActionResponse(ActionType.GUARD_PROTECT),
        )
        engine.state.guard_last_target = response.target
        engine._log(
            "guard_result",
            f"守卫 {guards[0]} 号守护 {response.target} 号" if response.target else f"守卫 {guards[0]} 号未守护",
            actor=guards[0],
            target=response.target,
        )
        return response.target
