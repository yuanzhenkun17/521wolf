from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import ActionResponse, ActionType

if TYPE_CHECKING:
    from engine.engine import GameEngine


async def resolve_sheriff_death(engine: GameEngine, sheriff_id: int) -> None:
    if engine.state.sheriff_id != sheriff_id:
        return
    alive = engine.alive_ids()
    response = await engine._ask(
        sheriff_id,
        ActionType.SHERIFF_BADGE,
        candidates=alive,
        validator=lambda res: (res.choice == "destroy" and res.target is None)
        or (res.choice == "transfer" and res.target in alive),
        default=ActionResponse(ActionType.SHERIFF_BADGE, choice="destroy"),
    )
    if response.choice == "transfer" and response.target in alive:
        engine.state.sheriff_id = response.target
        engine.state.badge_destroyed = False
        engine._record(
            "sheriff_badge_transfer",
            message=f"警长 {sheriff_id} 号将警徽移交给 {response.target} 号",
            actor=sheriff_id,
            target=response.target,
            payload={"from": sheriff_id, "to": response.target},
        )
    else:
        engine.state.sheriff_id = None
        engine.state.badge_destroyed = True
        engine._record(
            "sheriff_badge_destroy",
            message=f"警长 {sheriff_id} 号撕毁警徽",
            actor=sheriff_id,
            payload={"from": sheriff_id},
        )
