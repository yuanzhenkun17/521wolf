from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import Phase, Team, Winner

if TYPE_CHECKING:
    from engine.engine import GameEngine


def determine_winner(engine: GameEngine) -> Winner | None:
    alive_wolves = [
        player for player in engine.state.players.values() if player.alive and player.role.is_wolf()
    ]
    alive_villagers = [
        player for player in engine.state.players.values() if player.alive and player.team is Team.VILLAGERS
    ]
    alive_gods = [
        player for player in engine.state.players.values() if player.alive and player.team is Team.GODS
    ]
    alive_good = [p for p in engine.state.players.values() if p.alive and p.role.is_good()]
    if not alive_wolves:
        return Winner.VILLAGERS
    if not alive_villagers or not alive_gods or len(alive_wolves) >= len(alive_good):
        return Winner.WEREWOLVES
    return None


def check_winner(engine: GameEngine) -> Winner | None:
    if engine.state.winner is not None:
        return engine.state.winner
    engine.state.winner = determine_winner(engine)
    if engine.state.winner is not None:
        engine.state.phase = Phase.FINISHED
        engine._log(
            "game_end",
            f"游戏结束，胜利方：{engine.state.winner.value}",
            payload={"winner": engine.state.winner.value},
        )
    return engine.state.winner
