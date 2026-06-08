from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import ActionResponse, ActionType, DeathCause, DeathRecord, Phase, Role

if TYPE_CHECKING:
    from engine.engine import GameEngine


def kill_player(engine: GameEngine, player_id: int, cause: DeathCause) -> None:
    player = engine.state.players[player_id]
    if not player.alive:
        return
    player.alive = False
    engine.state.deaths.append(DeathRecord(player_id, cause, engine.state.day, engine.state.phase))
    if has_last_word(cause):
        engine.state.pending_last_words.append(player_id)
    engine._record(
        "death",
        message=f"{player_id} 号死亡，原因：{cause.value}",
        target=player_id,
        payload={"cause": cause.value},
    )


def revive_player(engine: GameEngine, player_id: int) -> None:
    engine.state.players[player_id].alive = True
    engine.state.deaths = [death for death in engine.state.deaths if death.player_id != player_id]
    engine.state.pending_last_words = [
        pending_id for pending_id in engine.state.pending_last_words if pending_id != player_id
    ]
    engine.state.pending_hunter_shots = [
        pending_id for pending_id in engine.state.pending_hunter_shots if pending_id != player_id
    ]


def has_last_word(cause: DeathCause) -> bool:
    return cause in {DeathCause.EXILE, DeathCause.SELF_EXPLODE}


def last_death_for(engine: GameEngine, player_id: int) -> DeathRecord | None:
    for death in reversed(engine.state.deaths):
        if death.player_id == player_id:
            return death
    return None


def is_hunter(engine: GameEngine, player_id: int) -> bool:
    return engine.state.players[player_id].role is Role.HUNTER


def can_hunter_shoot(engine: GameEngine, player_id: int) -> bool:
    player = engine.state.players[player_id]
    death = last_death_for(engine, player_id)
    return (
        player.role is Role.HUNTER
        and not player.alive
        and death is not None
        and death.cause in {DeathCause.WEREWOLF, DeathCause.EXILE}
    )


async def resolve_hunter_death(engine: GameEngine, hunter_id: int) -> int | None:
    if not can_hunter_shoot(engine, hunter_id):
        engine._record("hunter_no_shot", message=f"猎人 {hunter_id} 号不能开枪", actor=hunter_id)
        return None
    candidates = tuple(player_id for player_id in engine.alive_ids() if player_id != hunter_id)
    if not candidates:
        engine._record("hunter_no_shot", message=f"猎人 {hunter_id} 号无可射击目标", actor=hunter_id)
        return None
    response = await engine._ask(
        hunter_id,
        ActionType.HUNTER_SHOOT,
        candidates=candidates,
        validator=lambda res: res.target in candidates or res.target is None,
        default=ActionResponse(ActionType.HUNTER_SHOOT),
    )
    if response.target is None:
        engine._record("hunter_no_shot", message=f"猎人 {hunter_id} 号选择不开枪", actor=hunter_id)
        return None
    hunter_ps = engine.state.players[hunter_id]
    hunter_ps.role_state["has_shot"] = True
    hunter_ps.role_state["shot_target"] = response.target
    kill_player(engine, response.target, DeathCause.HUNTER_SHOT)
    engine._record(
        "hunter_shot",
        message=f"猎人 {hunter_id} 号开枪带走 {response.target} 号",
        actor=hunter_id,
        target=response.target,
        payload={"target": response.target},
    )
    await engine.resolve_sheriff_death(response.target)
    return response.target


async def resolve_death_triggers(engine: GameEngine, player_ids: list[int] | tuple[int, ...]) -> None:
    for player_id in player_ids:
        await engine.resolve_sheriff_death(player_id)
        if not is_hunter(engine, player_id):
            continue
        if should_delay_hunter_shot(engine, player_id):
            queue_pending_hunter_shot(engine, player_id)
            continue
        await resolve_hunter_death(engine, player_id)


def should_delay_hunter_shot(engine: GameEngine, player_id: int) -> bool:
    death = last_death_for(engine, player_id)
    return (
        death is not None
        and death.cause is DeathCause.WEREWOLF
        and death.phase is Phase.NIGHT
        and can_hunter_shoot(engine, player_id)
    )


def queue_pending_hunter_shot(engine: GameEngine, player_id: int) -> None:
    if player_id not in engine.state.pending_hunter_shots:
        engine.state.pending_hunter_shots.append(player_id)


async def resolve_pending_daybreak_actions(engine: GameEngine) -> None:
    while engine.state.pending_last_words:
        player_id = engine.state.pending_last_words.pop(0)
        await resolve_last_word(engine, player_id)
    while engine.state.pending_hunter_shots:
        if engine.check_winner() is not None:
            break
        player_id = engine.state.pending_hunter_shots.pop(0)
        await resolve_hunter_death(engine, player_id)


async def resolve_last_word(engine: GameEngine, player_id: int) -> None:
    if player_id in engine.state.pending_last_words:
        engine.state.pending_last_words.remove(player_id)
    if not engine.state.players[player_id].alive:
        await engine._ask(player_id, ActionType.LAST_WORD, default=ActionResponse(ActionType.LAST_WORD, text=""))


async def resolve_exiled_player(engine: GameEngine, player_id: int) -> None:
    kill_player(engine, player_id, DeathCause.EXILE)
    await engine.resolve_sheriff_death(player_id)
    await resolve_last_word(engine, player_id)
    if is_hunter(engine, player_id):
        await resolve_hunter_death(engine, player_id)
