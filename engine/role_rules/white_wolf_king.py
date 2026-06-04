from __future__ import annotations

from typing import Any

from engine.models import ActionResponse, ActionType, DeathCause, Phase, Role, Team
from engine.role_rules.werewolf import WerewolfRule


class WhiteWolfKingRule(WerewolfRule):
    role = Role.WHITE_WOLF_KING

    def init_role_state(self) -> dict[str, Any]:
        return {"has_exploded": False}

    def get_role_state(self, engine, player_id: int) -> dict[str, Any]:
        ps = engine.state.players[player_id]
        return dict(ps.role_state)

    async def day_interrupt(self, engine, player_id: int) -> str | None:
        candidates = tuple(
            candidate_id
            for candidate_id in engine.alive_ids()
            if engine.state.players[candidate_id].team is not Team.WEREWOLVES
        )
        response = await engine._ask(
            player_id,
            ActionType.WHITE_WOLF_EXPLODE,
            candidates=candidates,
            validator=lambda res: res.target in candidates
            or (res.target is None and res.choice in {"pass", None}),
            default=ActionResponse(ActionType.WHITE_WOLF_EXPLODE, choice="pass"),
        )
        if response.target not in candidates:
            return None
        ww_ps = engine.state.players[player_id]
        ww_ps.role_state["has_exploded"] = True
        engine.kill_player(player_id, DeathCause.SELF_EXPLODE)
        engine.kill_player(response.target, DeathCause.WHITE_WOLF)
        await engine.resolve_death_triggers([player_id, response.target])
        engine._log(
            "white_wolf_explosion",
            f"白狼王 {player_id} 号自爆并带走 {response.target} 号",
            actor=player_id,
            target=response.target,
        )
        await engine.resolve_last_word(player_id)
        engine.state.phase = Phase.NIGHT
        return "white_wolf_exploded"
