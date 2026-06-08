from __future__ import annotations

from typing import Any

from engine.models import ActionResponse, ActionType, Role, Team
from engine.role_rules.base import BaseRoleRule


class SeerRule(BaseRoleRule):
    role = Role.SEER

    def init_role_state(self) -> dict[str, Any]:
        return {"checks": {}}

    def get_role_state(self, engine, player_id: int) -> dict[str, Any]:
        ps = engine.state.players[player_id]
        return dict(ps.role_state)

    def seer_checks(self, engine, player_id: int) -> dict[int, Team]:
        ps = engine.state.players.get(player_id)
        if ps is None:
            return {}
        checks = ps.role_state.get("checks", {})
        result: dict[int, Team] = {}
        for target_str, entry in checks.items():
            if isinstance(entry, dict):
                target_value = entry.get("target")
                if target_value is None:
                    target_value = target_str
                try:
                    target_id = int(target_value)
                except (TypeError, ValueError):
                    continue
                result_str = entry.get("result", "")
                # Convert Team string value back to Team enum
                try:
                    result[target_id] = Team(result_str)
                except ValueError:
                    pass
        return result

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
            result = seer_check_result(engine.state.players[response.target].role)
            seer_ps = engine.state.players[seer_id]
            seer_ps.role_state["checks"][str(response.target)] = {
                "day": engine.state.day,
                "target": response.target,
                "result": result.value,
            }
            engine._record(
                "seer_result",
                message=f"预言家{seer_id}号查验{response.target}号，结果{seer_result_label(result)}",
                public=False,
                actor=seer_id,
                target=response.target,
                payload={"result": result.value},
            )


def seer_check_result(role: Role) -> Team:
    return Team.WEREWOLVES if role.team is Team.WEREWOLVES else Team.VILLAGERS


def seer_result_label(result: Team) -> str:
    if result is Team.WEREWOLVES:
        return "坏人"
    if result is Team.VILLAGERS:
        return "好人"
    return result.value
