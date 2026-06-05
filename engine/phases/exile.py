from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import ActionResponse, ActionType, Phase
from engine.public_log import append_public_event

if TYPE_CHECKING:
    from engine.engine import GameEngine


async def run_exile_vote(engine: GameEngine) -> int | None:
    engine.state.phase = Phase.EXILE_VOTE
    engine._record("exile_vote_start", message=f"第 {engine.state.day} 天放逐投票开始")
    alive = engine.alive_ids()
    votes = await collect_votes(engine, ActionType.EXILE_VOTE, alive, alive)
    append_vote_public_events(engine, ActionType.EXILE_VOTE, alive, votes)
    result = engine.resolve_exile_votes(votes, return_ties=True)
    if isinstance(result, int):
        await engine.resolve_exiled_player(result)
        engine._record("exile_vote_end", message=f"放逐投票结束，{result} 号出局", target=result, payload={"votes": votes})
        return result
    if len(result) <= 1:
        engine.state.phase = Phase.DAY_SPEECH
        engine._record("exile_vote_end", message="放逐投票结束，无人出局", payload={"votes": votes})
        return None
    engine._record("exile_vote_tie", message=f"放逐投票平票，进入 PK：{list(result)}", payload={"votes": votes, "tied": result})
    for candidate in result:
        await engine._ask(candidate, ActionType.PK_SPEAK, default=ActionResponse(ActionType.PK_SPEAK, text=""))
    pk_voters = tuple(player_id for player_id in alive if player_id not in result and engine.state.players[player_id].alive)
    pk_votes = await collect_votes(engine, ActionType.PK_VOTE, pk_voters, tuple(result))
    append_vote_public_events(engine, ActionType.PK_VOTE, pk_voters, pk_votes)
    pk_result = engine.resolve_exile_votes(pk_votes, candidates=tuple(result), return_ties=True)
    if isinstance(pk_result, int):
        await engine.resolve_exiled_player(pk_result)
        engine._record(
            "pk_vote_end",
            message=f"PK 投票结束，{pk_result} 号出局",
            target=pk_result,
            payload={"votes": pk_votes},
        )
        return pk_result
    engine.state.phase = Phase.DAY_SPEECH
    engine._record("pk_vote_end", message="PK 再次平票，无人出局", payload={"votes": pk_votes, "tied": pk_result})
    return None


def append_vote_public_events(
    engine: GameEngine,
    action_type: ActionType,
    voters: tuple[int, ...],
    votes: dict[int, int],
    prefix: str = "",
) -> None:
    for voter in voters:
        target = votes.get(voter)
        if target is not None:
            content = f"{voter}号{prefix}投给{target}号"
        else:
            content = f"{voter}号{prefix}弃票"
        append_public_event(engine, action_type.value, actor=voter, target=target, content=content)


async def collect_votes(
    engine: GameEngine, action_type: ActionType, voters: tuple[int, ...], candidates: tuple[int, ...]
) -> dict[int, int]:
    votes: dict[int, int] = {}
    for voter in voters:
        response = await engine._ask(
            voter,
            action_type,
            candidates=candidates,
            validator=lambda res: res.target in candidates or res.target is None,
            default=ActionResponse(action_type),
        )
        if response.target is not None:
            votes[voter] = response.target
    return votes
