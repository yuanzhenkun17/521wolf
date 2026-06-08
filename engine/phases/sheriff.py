from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import ActionResponse, ActionType, Phase

if TYPE_CHECKING:
    from engine.engine import GameEngine


async def run_sheriff_election(engine: GameEngine) -> int | None:
    engine.state.phase = Phase.SHERIFF_ELECTION
    engine._record("sheriff_election_start", message="警长竞选开始")
    alive = engine.alive_ids()
    runners: set[int] = set()
    for player_id in alive:
        response = await engine._ask(
            player_id,
            ActionType.SHERIFF_RUN,
            candidates=alive,
            validator=lambda res: res.choice in {"run", "pass", None},
            default=ActionResponse(ActionType.SHERIFF_RUN, choice="pass"),
        )
        if response.choice == "run":
            runners.add(player_id)
    for player_id in sorted(runners):
        await engine._ask(player_id, ActionType.SHERIFF_SPEAK, default=ActionResponse(ActionType.SHERIFF_SPEAK, text=""))
    initial_runners = tuple(sorted(runners))
    for player_id in initial_runners:
        current_runners = tuple(sorted(runners))
        response = await engine._ask(
            player_id,
            ActionType.SHERIFF_WITHDRAW,
            candidates=current_runners,
            metadata={
                "initial_runners": list(initial_runners),
                "runners": list(current_runners),
                "remaining_runners": list(current_runners),
            },
            validator=lambda res: res.choice in {"withdraw", "stay", None},
            default=ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="stay"),
        )
        if response.choice == "withdraw":
            runners.remove(player_id)
    if not runners:
        engine._record("sheriff_election_end", message="无人竞选警长", payload={"runners": []})
        return None
    votes: dict[int, int] = {}
    voters = tuple(player_id for player_id in alive if player_id not in initial_runners)
    for player_id in voters:
        response = await engine._ask(
            player_id,
            ActionType.SHERIFF_VOTE,
            candidates=tuple(sorted(runners)),
            validator=lambda res: res.target in runners or res.target is None,
            default=ActionResponse(ActionType.SHERIFF_VOTE),
        )
        if response.target is not None:
            votes[player_id] = response.target
    winner = engine.resolve_exile_votes(votes)
    engine.state.sheriff_id = winner
    engine._record(
        "sheriff_election_end",
        message=f"警长竞选结束，警长为 {winner} 号" if winner is not None else "警长竞选结束，无人当选",
        payload={"runners": sorted(runners), "votes": votes, "winner": winner},
    )
    return winner


