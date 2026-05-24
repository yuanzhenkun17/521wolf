from __future__ import annotations

from werewolf.models import ActionResponse, ActionType, Role, Team
from werewolf.role_rules.base import BaseRoleRule


class SeerRule(BaseRoleRule):
    role = Role.SEER

    def seer_checks(self, engine, player_id: int) -> dict[int, Team]:
        return dict(engine.state.seer_checks.get(player_id, {}))

    async def night_action(self, engine) -> None:
        seers = engine.role_ids(Role.SEER, alive_only=True)
        if not seers:
            return
        seer_id = seers[0]
        candidates = tuple(player_id for player_id in engine.alive_ids() if player_id != seer_id)
        response = await engine._ask(
            seer_id,
            ActionType.SEER_CHECK,
            candidates=candidates,
            validator=lambda res: res.target in candidates,
            default=ActionResponse(ActionType.SEER_CHECK),
        )
        if response.target is not None:
            result = engine.state.players[response.target].team
            engine.state.seer_checks.setdefault(seer_id, {})[response.target] = result
            engine._log(
                "seer_result",
                f"预言家 {seer_id} 号查验 {response.target} 号，结果 {result.value}",
                actor=seer_id,
                target=response.target,
                payload={"result": result.value},
            )
