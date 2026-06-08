from __future__ import annotations

from collections import Counter

from engine.models import ActionResponse, ActionType, Role, Team
from engine.role_rules.base import BaseRoleRule


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
        votes: dict[int, int] = {}
        abstentions: list[int] = []
        for wolf_id in wolves:
            response = await engine._ask(
                wolf_id,
                ActionType.WEREWOLF_KILL,
                candidates=candidates,
                validator=lambda res: res.target in candidates,
                default=ActionResponse(ActionType.WEREWOLF_KILL),
            )
            if response.target is None:
                abstentions.append(wolf_id)
            else:
                votes[wolf_id] = response.target
        target = _resolve_wolf_kill(votes, wolves, candidates, engine.state.day)
        engine._record(
            "werewolf_result",
            message=f"狼人最终击杀目标 {target} 号" if target else "狼人未产生击杀目标",
            public=False,
            target=target,
            visible_to=wolves,
            payload={"votes": votes, "abstentions": abstentions},
        )
        return target


def _resolve_wolf_kill(
    votes: dict[int, int],
    wolves: tuple[int, ...],
    candidates: tuple[int, ...],
    day: int,
) -> int | None:
    if not candidates:
        return None
    if not votes:
        return candidates[(day + sum(wolves)) % len(candidates)]
    counts = Counter(votes.values())
    highest = max(counts.values())
    tied = {target for target, count in counts.items() if count == highest}
    if len(tied) == 1:
        return next(iter(tied))
    for wolf_id in reversed(wolves):
        target = votes.get(wolf_id)
        if target in tied:
            return target
    return None
