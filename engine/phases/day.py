from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import ActionResponse, ActionType, Phase
from engine.role_rules.registry import rule_for

if TYPE_CHECKING:
    from engine.engine import GameEngine


async def run_day_speeches(engine: GameEngine) -> str:
    engine.state.phase = Phase.DAY_SPEECH
    await engine.resolve_pending_daybreak_actions()
    if engine.check_winner() is not None:
        return "finished"
    engine._record("day_speech_start", message=f"第 {engine.state.day} 天白天发言开始", payload={"alive": engine.alive_ids()})
    speech_order = await determine_speech_order(engine)
    for player_id in speech_order:
        player = engine.state.players[player_id]
        interrupt = await rule_for(player.role).day_interrupt(engine, player_id)
        if interrupt is not None:
            return interrupt
        await engine._ask(player_id, ActionType.SPEAK, default=ActionResponse(ActionType.SPEAK, text=""))
    engine._record("day_speech_end", message=f"第 {engine.state.day} 天白天发言结束")
    return "completed"


async def determine_speech_order(engine: GameEngine) -> list[int]:
    alive = engine.alive_ids()
    sheriff_id = engine.state.sheriff_id
    if sheriff_id is None or sheriff_id not in alive:
        return list(alive)

    response = await engine._ask(
        sheriff_id,
        ActionType.SPEECH_ORDER,
        metadata={"choices": ["forward", "reverse"]},
        validator=lambda response: response.choice in {"forward", "reverse"},
        default=ActionResponse(ActionType.SPEECH_ORDER, choice="forward"),
    )
    ordered = speech_order_from_sheriff(alive, sheriff_id, response.choice or "forward")
    direction_name = "顺序" if response.choice != "reverse" else "逆序"
    engine._record(
        "day_speech_order",
        message=f"警长 {sheriff_id} 号选择{direction_name}发言，发言顺序为 {'、'.join(map(str, ordered))}",
        actor=sheriff_id,
        payload={"sheriff_id": sheriff_id, "choice": response.choice or "forward", "order": ordered},
    )
    return ordered


def speech_order_from_sheriff(alive: tuple[int, ...], sheriff_id: int, choice: str) -> list[int]:
    seats = list(alive)
    sheriff_index = seats.index(sheriff_id)
    if choice == "reverse":
        before_sheriff = seats[:sheriff_index]
        after_sheriff = seats[sheriff_index + 1 :]
        return list(reversed(before_sheriff)) + list(reversed(after_sheriff)) + [sheriff_id]
    return seats[sheriff_index + 1 :] + seats[:sheriff_index] + [sheriff_id]
