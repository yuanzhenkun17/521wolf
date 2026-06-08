from __future__ import annotations

from typing import Any

from engine.models import ActionResponse, ActionType, Role
from engine.role_rules.base import BaseRoleRule


class WitchRule(BaseRoleRule):
    role = Role.WITCH

    def init_role_state(self) -> dict[str, Any]:
        return {
            "antidote_available": True,
            "poison_available": True,
            "antidote_history": [],
            "poison_history": [],
        }

    def get_role_state(self, engine, player_id: int) -> dict[str, Any]:
        ps = engine.state.players[player_id]
        return dict(ps.role_state)

    async def night_action(self, engine, killed_target: int | None = None) -> tuple[bool, int | None]:
        witches = engine.role_ids(Role.WITCH, alive_only=True)
        if not witches:
            return False, None
        witch_id = witches[0]
        witch_ps = engine.state.players[witch_id]
        candidates = tuple(player_id for player_id in engine.alive_ids() if player_id != witch_id)
        metadata = {
            "attacked_player": killed_target,
            "can_save": witch_ps.role_state["antidote_available"] and killed_target is not None,
            "can_poison": witch_ps.role_state["poison_available"],
        }
        response = await engine._ask(
            witch_id,
            ActionType.WITCH_ACT,
            candidates=candidates,
            metadata=metadata,
            validator=lambda res: self.valid_response(res, candidates, metadata),
            default=ActionResponse(ActionType.WITCH_ACT, choice="none"),
        )
        if response.choice == "save" and metadata["can_save"]:
            witch_ps.role_state["antidote_available"] = False
            witch_ps.role_state["antidote_history"].append(
                {"day": engine.state.day, "target": killed_target}
            )
            engine._record("witch_result", message=f"女巫 {witch_id} 号使用解药救 {killed_target} 号", public=False, actor=witch_id, target=killed_target)
            return True, None
        if response.choice == "poison" and metadata["can_poison"] and response.target in candidates:
            witch_ps.role_state["poison_available"] = False
            witch_ps.role_state["poison_history"].append(
                {"day": engine.state.day, "target": response.target}
            )
            engine._record("witch_result", message=f"女巫 {witch_id} 号使用毒药毒 {response.target} 号", public=False, actor=witch_id, target=response.target)
            return False, response.target
        engine._record("witch_result", message=f"女巫 {witch_id} 号未使用药", public=False, actor=witch_id)
        return False, None

    def valid_response(self, response: ActionResponse, candidates: tuple[int, ...], metadata: dict) -> bool:
        if response.choice in {None, "none"}:
            return True
        if response.choice == "save":
            return metadata["can_save"]
        if response.choice == "poison":
            return metadata["can_poison"] and response.target in candidates
        return False
