from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import ActionResponse, ActionType, Phase, Role
from engine.role_rules.registry import rule_for

if TYPE_CHECKING:
    from engine.engine import GameEngine


async def run_sheriff_election(
    engine: GameEngine,
    *,
    first_night_deaths: tuple[int, ...] = (),
) -> int | str | None:
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
        interrupt = await _maybe_white_wolf_interrupt(engine, player_id, first_night_deaths)
        if interrupt is not None:
            engine.state.sheriff_id = None
            engine._record(
                "sheriff_election_end",
                message="警长竞选因白狼王自爆终止，无人当选",
                payload={"runners": sorted(runners), "winner": None, "interrupted_by": player_id},
            )
            return interrupt
        await engine._ask(player_id, ActionType.SHERIFF_SPEAK, default=ActionResponse(ActionType.SHERIFF_SPEAK, text=""))
    initial_runners = tuple(sorted(runners))
    for player_id in initial_runners:
        current_runners = tuple(sorted(runners))
        can_withdraw = len(current_runners) > 1
        response = await engine._ask(
            player_id,
            ActionType.SHERIFF_WITHDRAW,
            candidates=current_runners,
            metadata={
                "initial_runners": list(initial_runners),
                "runners": list(current_runners),
                "remaining_runners": list(current_runners),
            },
            validator=lambda res: res.choice in {"stay", None} or (res.choice == "withdraw" and can_withdraw),
            default=ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="stay"),
        )
        if response.choice == "withdraw" and len(runners) > 1:
            runners.remove(player_id)
    if not runners:
        engine._record("sheriff_election_end", message="无人竞选警长", payload={"runners": []})
        return None
    if len(runners) == 1:
        winner = next(iter(runners))
        engine.state.sheriff_id = winner
        engine._record(
            "sheriff_election_end",
            message=f"警长竞选结束，唯一候选人 {winner} 号自动当选",
            payload={"runners": sorted(runners), "votes": {}, "abstentions": [], "winner": winner, "auto_elected": True},
        )
        return winner

    voters = tuple(player_id for player_id in alive if player_id not in initial_runners)
    if not voters:
        engine.state.sheriff_id = None
        engine._record(
            "sheriff_election_end",
            message="警长竞选结束，无警下投票人，无人当选",
            payload={"runners": sorted(runners), "votes": {}, "abstentions": [], "winner": None},
        )
        return None

    votes, abstentions = await _collect_sheriff_votes(engine, voters, tuple(sorted(runners)))
    result = engine.resolve_exile_votes(votes, candidates=tuple(sorted(runners)), return_ties=True)
    if isinstance(result, tuple) and len(result) > 1:
        engine._record(
            "sheriff_vote_tie",
            message=f"警长投票平票，进入 PK：{list(result)}",
            payload={"votes": votes, "abstentions": abstentions, "tied": result},
        )
        for candidate in result:
            interrupt = await _maybe_white_wolf_interrupt(engine, candidate, first_night_deaths)
            if interrupt is not None:
                engine.state.sheriff_id = None
                engine._record(
                    "sheriff_election_end",
                    message="警长 PK 因白狼王自爆终止，无人当选",
                    payload={
                        "runners": sorted(runners),
                        "votes": votes,
                        "abstentions": abstentions,
                        "tied": result,
                        "winner": None,
                        "interrupted_by": candidate,
                    },
                )
                return interrupt
            await engine._ask(candidate, ActionType.SHERIFF_SPEAK, default=ActionResponse(ActionType.SHERIFF_SPEAK, text=""))
        pk_votes, pk_abstentions = await _collect_sheriff_votes(engine, voters, tuple(result))
        pk_result = engine.resolve_exile_votes(pk_votes, candidates=tuple(result), return_ties=True)
        winner = pk_result if isinstance(pk_result, int) else None
        engine.state.sheriff_id = winner
        engine._record(
            "sheriff_election_end",
            message=f"警长竞选结束，警长为 {winner} 号" if winner is not None else "警长 PK 再次平票，无人当选",
            payload={
                "runners": sorted(runners),
                "votes": votes,
                "abstentions": abstentions,
                "tied": result,
                "pk_votes": pk_votes,
                "pk_abstentions": pk_abstentions,
                "winner": winner,
            },
        )
        return winner

    winner = result if isinstance(result, int) else None
    engine.state.sheriff_id = winner
    engine._record(
        "sheriff_election_end",
        message=f"警长竞选结束，警长为 {winner} 号" if winner is not None else "警长竞选结束，无人当选",
        payload={"runners": sorted(runners), "votes": votes, "abstentions": abstentions, "winner": winner},
    )
    return winner


async def _collect_sheriff_votes(
    engine: GameEngine,
    voters: tuple[int, ...],
    candidates: tuple[int, ...],
) -> tuple[dict[int, int], list[int]]:
    votes: dict[int, int] = {}
    abstentions: list[int] = []
    candidate_set = set(candidates)
    for player_id in voters:
        response = await engine._ask(
            player_id,
            ActionType.SHERIFF_VOTE,
            candidates=candidates,
            validator=lambda res: res.target in candidate_set or res.target is None,
            default=ActionResponse(ActionType.SHERIFF_VOTE),
        )
        if response.target is None:
            abstentions.append(player_id)
        else:
            votes[player_id] = response.target
    return votes, abstentions


async def _maybe_white_wolf_interrupt(
    engine: GameEngine,
    player_id: int,
    first_night_deaths: tuple[int, ...],
) -> str | None:
    player = engine.state.players[player_id]
    if player.role is not Role.WHITE_WOLF_KING or player_id in first_night_deaths or not player.alive:
        return None
    return await rule_for(player.role).day_interrupt(engine, player_id)
