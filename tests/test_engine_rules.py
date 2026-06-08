from __future__ import annotations

from collections import Counter

import pytest

from engine.config import GameConfig
from engine.engine import GameEngine
from engine.models import ActionResponse, ActionType, DeathCause, Phase, Role, Winner
from engine.players import ScriptedAgent
from engine.rules import voting


def _engine(
    roles: dict[int, Role],
    *,
    responses: dict[int, list[ActionResponse]] | None = None,
    sheriff_vote_weight: float = 1.5,
    max_days: int = 20,
    enable_sheriff: bool = True,
) -> GameEngine:
    agents = {
        player_id: ScriptedAgent((responses or {}).get(player_id, []))
        for player_id in roles
    }
    config = GameConfig(
        name="test_rules",
        role_counts=Counter(roles.values()),
        sheriff_vote_weight=sheriff_vote_weight,
        max_days=max_days,
        enable_sheriff=enable_sheriff,
    )
    return GameEngine(roles, agents, config=config)


def _events(engine: GameEngine, event_type: str):
    return [event for event in engine.logger.entries if event.type == event_type]


def test_resolve_votes_applies_sheriff_weight():
    assert voting.resolve_votes({1: 3, 2: 4}, sheriff_id=1) == 3


def test_resolve_votes_returns_sorted_ties_when_requested():
    votes = {1: 4, 2: 3}

    assert voting.resolve_votes(votes, sheriff_id=None) is None
    assert voting.resolve_votes(votes, sheriff_id=None, return_ties=True) == (3, 4)


def test_resolve_votes_filters_targets_outside_candidates():
    assert voting.resolve_votes(
        {1: 99, 2: 3},
        sheriff_id=None,
        candidates=(3, 4),
        return_ties=True,
    ) == 3


def test_plurality_ignores_abstentions_and_breaks_ties_by_lowest_seat():
    assert voting.plurality([None, 4, 3]) == 3
    assert voting.plurality([None, None]) is None


def test_villagers_win_when_all_wolves_are_dead():
    engine = _engine({1: Role.WEREWOLF, 2: Role.VILLAGER, 3: Role.SEER})
    engine.state.players[1].alive = False

    assert engine.check_winner() is Winner.VILLAGERS
    assert engine.state.phase is Phase.FINISHED
    assert _events(engine, "game_end")[-1].payload == {"winner": Winner.VILLAGERS.value}


def test_werewolves_win_when_villagers_are_eliminated():
    engine = _engine({1: Role.WEREWOLF, 2: Role.VILLAGER, 3: Role.SEER})
    engine.state.players[2].alive = False

    assert engine.check_winner() is Winner.WEREWOLVES
    assert engine.state.phase is Phase.FINISHED


def test_werewolves_win_at_parity():
    engine = _engine(
        {
            1: Role.WEREWOLF,
            2: Role.WHITE_WOLF_KING,
            3: Role.VILLAGER,
            4: Role.SEER,
        }
    )

    assert engine.check_winner() is Winner.WEREWOLVES


async def test_run_until_finished_records_no_winner_when_max_days_reached():
    engine = _engine(
        {
            1: Role.WEREWOLF,
            2: Role.VILLAGER,
            3: Role.SEER,
            4: Role.GUARD,
        },
        responses={
            1: [ActionResponse(ActionType.WEREWOLF_KILL, target=2)],
            4: [ActionResponse(ActionType.GUARD_PROTECT, target=2)],
        },
        max_days=1,
        enable_sheriff=False,
    )

    winner = await engine.run_until_finished()

    assert winner is None
    assert engine.state.winner is None
    assert engine.state.phase is Phase.FINISHED
    event = _events(engine, "game_end")[-1]
    assert event.payload == {
        "winner": None,
        "outcome": "no_winner",
        "terminal_reason": "max_days_reached",
        "max_days": 1,
    }


def test_kill_and_revive_update_death_state_and_last_words():
    engine = _engine({1: Role.WEREWOLF, 2: Role.HUNTER, 3: Role.VILLAGER})
    engine.state.day = 1
    engine.state.phase = Phase.EXILE_VOTE

    engine.kill_player(2, DeathCause.EXILE)

    assert not engine.state.players[2].alive
    assert engine.state.deaths[-1].player_id == 2
    assert engine.state.pending_last_words == [2]
    death_events = _events(engine, "death")
    assert len(death_events) == 1
    assert death_events[0].target == 2
    assert death_events[0].message == "2 号死亡"
    assert death_events[0].payload == {}
    detail_events = _events(engine, "death_detail")
    assert detail_events[0].public is False
    assert detail_events[0].payload == {"causes": [DeathCause.EXILE.value]}

    engine.revive_player(2)

    assert engine.state.players[2].alive
    assert engine.state.deaths == []
    assert engine.state.pending_last_words == []


async def test_night_werewolf_death_delays_hunter_shot_until_daybreak():
    engine = _engine(
        {
            1: Role.WEREWOLF,
            2: Role.HUNTER,
            3: Role.VILLAGER,
            4: Role.SEER,
        }
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    engine.kill_player(2, DeathCause.WEREWOLF)
    await engine.resolve_death_triggers([2])

    assert engine.state.pending_hunter_shots == [2]
    assert engine.agents[2].requests == []


async def test_pending_hunter_shot_resolves_at_daybreak():
    engine = _engine(
        {
            1: Role.WEREWOLF,
            2: Role.HUNTER,
            3: Role.VILLAGER,
            4: Role.SEER,
        },
        responses={
            2: [ActionResponse(ActionType.HUNTER_SHOOT, target=1)],
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    engine.kill_player(2, DeathCause.WEREWOLF)
    await engine.resolve_death_triggers([2])
    await engine.resolve_pending_daybreak_actions()

    assert not engine.state.players[1].alive
    assert engine.state.players[2].role_state["has_shot"] is True
    assert engine.state.players[2].role_state["shot_target"] == 1
    assert engine.state.pending_hunter_shots == []


async def test_pending_hunter_shot_resolves_before_daybreak_victory_check():
    engine = _engine(
        {
            1: Role.WEREWOLF,
            2: Role.HUNTER,
            3: Role.VILLAGER,
        },
        responses={
            2: [ActionResponse(ActionType.HUNTER_SHOOT, target=1)],
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    engine.kill_player(2, DeathCause.WEREWOLF)
    await engine.resolve_death_triggers([2])
    result = await engine.run_day_speeches()

    assert result == "finished"
    assert not engine.state.players[1].alive
    assert engine.state.players[2].role_state["has_shot"] is True
    assert engine.state.pending_hunter_shots == []
    assert engine.state.winner is Winner.VILLAGERS


async def test_hunter_shot_records_single_descriptive_event():
    engine = _engine(
        {
            1: Role.WEREWOLF,
            2: Role.HUNTER,
            3: Role.VILLAGER,
            4: Role.SEER,
        },
        responses={2: [ActionResponse(ActionType.HUNTER_SHOOT, target=1)]},
    )
    engine.state.day = 1
    engine.state.phase = Phase.DAY_SPEECH
    engine.kill_player(2, DeathCause.EXILE)

    await engine.resolve_hunter_death(2)

    hunter_shots = _events(engine, "hunter_shot")
    assert len(hunter_shots) == 1
    assert hunter_shots[0].message == "猎人 2 号开枪带走 1 号"
    assert hunter_shots[0].actor == 2
    assert hunter_shots[0].target == 1
    assert hunter_shots[0].payload == {"target": 1}


async def test_hunter_cannot_shoot_twice():
    engine = _engine(
        {
            1: Role.WEREWOLF,
            2: Role.HUNTER,
            3: Role.VILLAGER,
            4: Role.SEER,
        },
        responses={
            2: [
                ActionResponse(ActionType.HUNTER_SHOOT, target=1),
                ActionResponse(ActionType.HUNTER_SHOOT, target=3),
            ],
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.DAY_SPEECH
    engine.kill_player(2, DeathCause.EXILE)

    first_target = await engine.resolve_hunter_death(2)
    second_target = await engine.resolve_hunter_death(2)

    assert first_target == 1
    assert second_target is None
    assert engine.can_hunter_shoot(2) is False
    assert engine.state.players[3].alive
    assert engine.state.players[2].role_state["shot_target"] == 1
    assert len(_events(engine, "hunter_shot")) == 1
    assert len(engine.agents[2].requests) == 1


@pytest.mark.parametrize(
    "cause",
    [DeathCause.WITCH_POISON, DeathCause.HUNTER_SHOT, DeathCause.WHITE_WOLF],
)
def test_hunter_cannot_shoot_for_non_shootable_death_causes(cause: DeathCause):
    engine = _engine({1: Role.WEREWOLF, 2: Role.HUNTER, 3: Role.VILLAGER})
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    engine.kill_player(2, cause)

    assert engine.can_hunter_shoot(2) is False


def test_hunter_cannot_shoot_when_death_causes_include_poison():
    engine = _engine({1: Role.WEREWOLF, 2: Role.HUNTER, 3: Role.WITCH})
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    engine.kill_player(2, DeathCause.WEREWOLF, causes=(DeathCause.WEREWOLF, DeathCause.WITCH_POISON))

    assert engine.state.deaths[-1].causes == (DeathCause.WEREWOLF, DeathCause.WITCH_POISON)
    assert engine.can_hunter_shoot(2) is False


async def test_last_sheriff_runner_cannot_withdraw():
    engine = _engine(
        {
            1: Role.VILLAGER,
            2: Role.WEREWOLF,
            3: Role.SEER,
        },
        responses={
            1: [
                ActionResponse(ActionType.SHERIFF_RUN, choice="run"),
                ActionResponse(ActionType.SHERIFF_SPEAK, text="running"),
                ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="withdraw"),
            ],
            2: [
                ActionResponse(ActionType.SHERIFF_RUN, choice="pass"),
                ActionResponse(ActionType.SHERIFF_VOTE, target=1),
            ],
            3: [
                ActionResponse(ActionType.SHERIFF_RUN, choice="pass"),
                ActionResponse(ActionType.SHERIFF_VOTE, target=1),
            ],
        },
    )

    winner = await engine.run_sheriff_election()

    assert winner == 1
    assert engine.state.sheriff_id == 1
    assert _events(engine, "invalid_response")[-1].actor == 1
    assert _events(engine, "sheriff_election_end")[-1].payload["runners"] == [1]
    assert _events(engine, "sheriff_election_end")[-1].payload["auto_elected"] is True


async def test_sheriff_vote_tie_enters_pk_and_revote():
    engine = _engine(
        {
            1: Role.VILLAGER,
            2: Role.WEREWOLF,
            3: Role.SEER,
            4: Role.HUNTER,
        },
        responses={
            1: [
                ActionResponse(ActionType.SHERIFF_RUN, choice="run"),
                ActionResponse(ActionType.SHERIFF_SPEAK, text="run 1"),
                ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="stay"),
                ActionResponse(ActionType.SHERIFF_SPEAK, text="pk 1"),
            ],
            2: [
                ActionResponse(ActionType.SHERIFF_RUN, choice="run"),
                ActionResponse(ActionType.SHERIFF_SPEAK, text="run 2"),
                ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="stay"),
                ActionResponse(ActionType.SHERIFF_SPEAK, text="pk 2"),
            ],
            3: [
                ActionResponse(ActionType.SHERIFF_RUN, choice="pass"),
                ActionResponse(ActionType.SHERIFF_VOTE, target=1),
                ActionResponse(ActionType.SHERIFF_VOTE, target=1),
            ],
            4: [
                ActionResponse(ActionType.SHERIFF_RUN, choice="pass"),
                ActionResponse(ActionType.SHERIFF_VOTE, target=2),
                ActionResponse(ActionType.SHERIFF_VOTE, target=1),
            ],
        },
    )

    winner = await engine.run_sheriff_election()

    assert winner == 1
    assert engine.state.sheriff_id == 1
    assert _events(engine, "sheriff_vote_tie")[-1].payload["tied"] == (1, 2)
    assert _events(engine, "sheriff_election_end")[-1].payload["pk_votes"] == {3: 1, 4: 1}


async def test_exile_vote_excludes_self_and_reveals_full_tally_only_at_end():
    engine = _engine(
        {
            1: Role.VILLAGER,
            2: Role.WEREWOLF,
            3: Role.SEER,
        },
        responses={
            1: [
                ActionResponse(ActionType.EXILE_VOTE, target=1),
                ActionResponse(ActionType.EXILE_VOTE, target=2),
            ],
            2: [ActionResponse(ActionType.EXILE_VOTE, target=1)],
            3: [ActionResponse(ActionType.EXILE_VOTE, target=1)],
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.DAY_SPEECH

    exiled = await engine.run_exile_vote()

    assert exiled == 1
    assert 1 not in engine.agents[1].requests[0].candidates
    assert _events(engine, "invalid_response")[-1].actor == 1
    assert all(not event.public for event in _events(engine, ActionType.EXILE_VOTE.value))
    assert _events(engine, "exile_vote_end")[-1].payload["votes"] == {1: 2, 2: 1, 3: 1}


async def test_exile_tie_records_pk_votes_in_pk_phase():
    engine = _engine(
        {
            1: Role.VILLAGER,
            2: Role.WEREWOLF,
            3: Role.SEER,
            4: Role.GUARD,
        },
        responses={
            1: [
                ActionResponse(ActionType.EXILE_VOTE, target=2),
                ActionResponse(ActionType.PK_SPEAK, text="pk 1"),
            ],
            2: [
                ActionResponse(ActionType.EXILE_VOTE, target=1),
                ActionResponse(ActionType.PK_SPEAK, text="pk 2"),
            ],
            3: [
                ActionResponse(ActionType.EXILE_VOTE, target=1),
                ActionResponse(ActionType.PK_VOTE, target=1),
            ],
            4: [
                ActionResponse(ActionType.EXILE_VOTE, target=2),
                ActionResponse(ActionType.PK_VOTE, target=2),
            ],
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.DAY_SPEECH

    exiled = await engine.run_exile_vote()

    assert exiled is None
    assert _events(engine, "exile_vote_tie")[-1].phase is Phase.EXILE_VOTE
    assert _events(engine, "pk_vote_start")[-1].phase is Phase.PK_VOTE
    assert _events(engine, "pk_vote_end")[-1].phase is Phase.PK_VOTE
    pk_requests = [
        request
        for agent in engine.agents.values()
        for request in agent.requests
        if request.action_type is ActionType.PK_VOTE
    ]
    assert [request.phase for request in pk_requests] == [Phase.PK_VOTE, Phase.PK_VOTE]
    assert all(event.phase is Phase.PK_VOTE for event in _events(engine, ActionType.PK_VOTE.value))
