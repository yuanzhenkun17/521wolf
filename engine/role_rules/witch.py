from __future__ import annotations

from engine.models import ActionResponse, ActionType, Role
from engine.role_rules.base import BaseRoleRule


class WitchRule(BaseRoleRule):
    role = Role.WITCH

    async def night_action(self, engine, killed_target: int | None = None) -> tuple[bool, int | None]:
        witches = engine.role_ids(Role.WITCH, alive_only=True)
        if not witches:
            return False, None
        witch_id = witches[0]
        candidates = tuple(player_id for player_id in engine.alive_ids() if player_id != witch_id)
        metadata = {
            "attacked_player": killed_target,
            "can_save": engine.state.witch_antidote_available and killed_target is not None,
            "can_poison": engine.state.witch_poison_available,
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
            engine.state.witch_antidote_available = False
            engine._log("witch_result", f"女巫 {witch_id} 号使用解药救 {killed_target} 号", actor=witch_id, target=killed_target)
            return True, None
        if response.choice == "poison" and metadata["can_poison"] and response.target in candidates:
            engine.state.witch_poison_available = False
            engine._log("witch_result", f"女巫 {witch_id} 号使用毒药毒 {response.target} 号", actor=witch_id, target=response.target)
            return False, response.target
        engine._log("witch_result", f"女巫 {witch_id} 号未使用药", actor=witch_id)
        return False, None

    def valid_response(self, response: ActionResponse, candidates: tuple[int, ...], metadata: dict) -> bool:
        if response.choice in {None, "none"}:
            return True
        if response.choice == "save":
            return metadata["can_save"]
        if response.choice == "poison":
            return metadata["can_poison"] and response.target in candidates
        return False
