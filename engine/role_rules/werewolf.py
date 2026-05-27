from __future__ import annotations

from engine.models import ActionResponse, ActionType, Role, Team
from engine.role_rules.base import BaseRoleRule
from engine.rules.voting import plurality


class WerewolfRule(BaseRoleRule):
    role = Role.WEREWOLF

    def visible_roles(self, engine, player_id: int) -> dict[int, Role]:
        return {
            other_id: other.role
            for other_id, other in engine.state.players.items()
            if other_id != player_id and other.role.team is Team.WEREWOLVES
        }

    async def night_action(self, engine) -> int | None:
        wolves = engine.team_ids(Team.WEREWOLVES, alive_only=True)
        candidates = tuple(
            player_id
            for player_id in engine.alive_ids()
            if engine.state.players[player_id].team is not Team.WEREWOLVES
        )
        if not wolves or not candidates:
            return None
        votes = []
        for wolf_id in wolves:
            response = await engine._ask(
                wolf_id,
                ActionType.WEREWOLF_KILL,
                candidates=candidates,
                validator=lambda res: res.target in candidates,
                default=ActionResponse(ActionType.WEREWOLF_KILL, target=candidates[0]),
            )
            votes.append(response.target)
        target = plurality(votes)
        engine._log(
            "werewolf_result",
            f"狼人最终击杀目标 {target} 号" if target else "狼人未产生击杀目标",
            target=target,
            payload={"votes": votes},
        )
        return target
