from __future__ import annotations

from typing import TYPE_CHECKING

from engine.models import ActionResponse, ActionType, Phase
from engine.role_rules.registry import rule_for

if TYPE_CHECKING:
    from engine.engine import GameEngine


async def run_exile_vote(engine: GameEngine) -> int | str | None:
    engine.state.phase = Phase.EXILE_VOTE
    engine._record("exile_vote_start", message=f"第 {engine.state.day} 天放逐投票开始")
    alive = engine.alive_ids()
    votes, abstentions = await collect_votes(engine, ActionType.EXILE_VOTE, alive, alive, exclude_self=True)
    result = engine.resolve_exile_votes(votes, return_ties=True)
    if isinstance(result, int):
        engine._record(
            "exile_vote_end",
            message=f"放逐投票结束，{result} 号出局",
            target=result,
            payload={"votes": votes, "abstentions": abstentions},
        )
        await engine.resolve_exiled_player(result)
        return result
    if len(result) <= 1:
        engine._record("exile_vote_end", message="放逐投票结束，无人出局", payload={"votes": votes, "abstentions": abstentions})
        engine.state.phase = Phase.DAY_SPEECH
        return None
    engine._record(
        "exile_vote_tie",
        message=f"放逐投票平票，进入 PK：{list(result)}",
        payload={"votes": votes, "abstentions": abstentions, "tied": result},
    )
    for candidate in result:
        player = engine.state.players[candidate]
        interrupt = await rule_for(player.role).day_interrupt(engine, candidate)
        if interrupt is not None:
            return interrupt
        await engine._ask(candidate, ActionType.PK_SPEAK, default=ActionResponse(ActionType.PK_SPEAK, text=""))
    pk_voters = tuple(player_id for player_id in alive if player_id not in result and engine.state.players[player_id].alive)
    engine.state.phase = Phase.PK_VOTE
    engine._record("pk_vote_start", message=f"第 {engine.state.day} 天 PK 投票开始", payload={"candidates": result})
    pk_votes, pk_abstentions = await collect_votes(engine, ActionType.PK_VOTE, pk_voters, tuple(result))
    pk_result = engine.resolve_exile_votes(pk_votes, candidates=tuple(result), return_ties=True)
    if isinstance(pk_result, int):
        engine._record(
            "pk_vote_end",
            message=f"PK 投票结束，{pk_result} 号出局",
            target=pk_result,
            payload={"votes": pk_votes, "abstentions": pk_abstentions},
        )
        await engine.resolve_exiled_player(pk_result)
        return pk_result
    engine._record(
        "pk_vote_end",
        message="PK 再次平票，无人出局",
        payload={"votes": pk_votes, "abstentions": pk_abstentions, "tied": pk_result},
    )
    engine.state.phase = Phase.DAY_SPEECH
    return None


async def collect_votes(
    engine: GameEngine,
    action_type: ActionType,
    voters: tuple[int, ...],
    candidates: tuple[int, ...],
    *,
    exclude_self: bool = False,
) -> tuple[dict[int, int], list[int]]:
    votes: dict[int, int] = {}
    abstentions: list[int] = []
    for voter in voters:
        voter_candidates = tuple(candidate for candidate in candidates if not exclude_self or candidate != voter)
        candidate_set = set(voter_candidates)
        response = await engine._ask(
            voter,
            action_type,
            candidates=voter_candidates,
            validator=lambda res, candidate_set=candidate_set: res.target in candidate_set or res.target is None,
            default=ActionResponse(action_type),
        )
        if response.target is None:
            abstentions.append(voter)
        else:
            votes[voter] = response.target
    return votes, abstentions
