from __future__ import annotations

import asyncio
from collections import Counter

from engine.config import GameConfig
from engine.engine import GameEngine
from engine.models import ActionResponse, ActionType, DeathCause, Phase, Role, Team
from engine.phases import night
from engine.players import ScriptedAgent
from engine.role_rules.registry import rule_for


def _engine(
    roles: dict[int, Role],
    *,
    responses: dict[int, list[ActionResponse]] | None = None,
    night_order: tuple[Role, ...] | None = None,
    runner_max_retries: int = 2,
    runner_retry_delay: float = 0.0,
    runner_action_timeout: float | None = None,
) -> GameEngine:
    agents = {
        player_id: ScriptedAgent((responses or {}).get(player_id, []))
        for player_id in roles
    }
    config = GameConfig(
        name="test_role_rules",
        role_counts=Counter(roles.values()),
        night_order=night_order
        if night_order is not None
        else (Role.GUARD, Role.WEREWOLF, Role.SEER, Role.WITCH),
        runner_max_retries=runner_max_retries,
        runner_retry_delay=runner_retry_delay,
        runner_action_timeout=runner_action_timeout,
    )
    return GameEngine(roles, agents, config=config)


def _events(engine: GameEngine, event_type: str):
    return [event for event in engine.logger.entries if event.type == event_type]


async def test_werewolves_only_see_wolf_team_members_and_target_good_players():
    engine = _engine(
        {
            1: Role.WEREWOLF,
            2: Role.WHITE_WOLF_KING,
            3: Role.VILLAGER,
            4: Role.SEER,
        },
        responses={
            1: [ActionResponse(ActionType.WEREWOLF_KILL, target=3)],
            2: [ActionResponse(ActionType.WEREWOLF_KILL, target=4)],
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    assert engine.observation_for(1).known_roles == {2: Role.WHITE_WOLF_KING}
    assert engine.observation_for(2).known_roles == {1: Role.WEREWOLF}

    target = await rule_for(Role.WEREWOLF).night_action(engine)

    assert target == 4
    assert engine.agents[1].requests[-1].candidates == (3, 4)
    assert engine.agents[2].requests[-1].candidates == (3, 4)
    assert all(not event.public for event in _events(engine, ActionType.WEREWOLF_KILL.value))
    result_event = _events(engine, "werewolf_result")[-1]
    assert result_event.public is False
    assert result_event.visible_to == (1, 2)
    assert result_event.payload["votes"] == {1: 3, 2: 4}
    assert result_event in engine.observation_for(1).visible_events
    assert result_event not in engine.observation_for(3).visible_events


async def test_guard_cannot_protect_same_target_on_consecutive_nights():
    engine = _engine(
        {1: Role.GUARD, 2: Role.WEREWOLF, 3: Role.VILLAGER},
        responses={
            1: [
                ActionResponse(ActionType.GUARD_PROTECT, target=3),
                ActionResponse(ActionType.GUARD_PROTECT, target=3),
                ActionResponse(ActionType.GUARD_PROTECT, target=2),
            ]
        },
    )
    engine.state.phase = Phase.NIGHT

    engine.state.day = 1
    first_target = await rule_for(Role.GUARD).night_action(engine)
    engine.state.day = 2
    second_target = await rule_for(Role.GUARD).night_action(engine)

    assert first_target == 3
    assert second_target == 2
    assert engine.state.players[1].role_state["last_target"] == 2
    assert 3 not in engine.agents[1].requests[-1].candidates
    assert _events(engine, "invalid_response")[-1].public is False
    assert all(event.public is False for event in _events(engine, "guard_result"))


async def test_guard_must_choose_target_when_legal_candidate_exists():
    engine = _engine(
        {1: Role.GUARD, 2: Role.WEREWOLF, 3: Role.VILLAGER},
        responses={
            1: [
                ActionResponse(ActionType.GUARD_PROTECT),
                ActionResponse(ActionType.GUARD_PROTECT, target=3),
            ]
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    target = await rule_for(Role.GUARD).night_action(engine)

    assert target == 3
    assert _events(engine, "invalid_response")[-1].actor == 1


async def test_seer_check_records_private_team_result_for_seer_only():
    engine = _engine(
        {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER},
        responses={1: [ActionResponse(ActionType.SEER_CHECK, target=2)]},
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    await rule_for(Role.SEER).night_action(engine)

    assert engine.state.players[1].role_state["checks"]["2"] == {
        "day": 1,
        "target": 2,
        "result": Team.WEREWOLVES.value,
    }
    assert engine.observation_for(1).seer_checks == {2: Team.WEREWOLVES}
    assert _events(engine, ActionType.SEER_CHECK.value)[-1].public is False
    assert _events(engine, "seer_result")[-1].public is False


async def test_seer_default_uses_legal_target_after_invalid_responses():
    engine = _engine(
        {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER},
        responses={
            1: [
                ActionResponse(ActionType.SEER_CHECK, target=99),
                ActionResponse(ActionType.SEER_CHECK),
            ]
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    await rule_for(Role.SEER).night_action(engine)

    assert engine.state.players[1].role_state["checks"]["2"] == {
        "day": 1,
        "target": 2,
        "result": Team.WEREWOLVES.value,
    }
    assert [event.target for event in _events(engine, "invalid_response")] == [99, None]
    assert _events(engine, "default_action")[0].target == 2


async def test_ask_retries_and_delay_follow_game_config(monkeypatch):
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("engine.actions.asyncio.sleep", fake_sleep)
    engine = _engine(
        {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER},
        responses={
            1: [
                ActionResponse(ActionType.SEER_CHECK, target=99),
                ActionResponse(ActionType.SEER_CHECK),
                ActionResponse(ActionType.SEER_CHECK, target=2),
            ]
        },
        runner_max_retries=3,
        runner_retry_delay=0.25,
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    await rule_for(Role.SEER).night_action(engine)

    assert [request.retry_count for request in engine.agents[1].requests] == [0, 1, 2]
    assert sleep_calls == [0.25, 0.25]
    assert engine.state.players[1].role_state["checks"]["2"]["target"] == 2


async def test_ask_hard_times_out_hung_agent_act_and_uses_default():
    class HungAgent:
        def __init__(self) -> None:
            self.requests = []

        async def act(self, request):
            self.requests.append(request)
            await asyncio.Event().wait()

    engine = _engine(
        {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER},
        runner_max_retries=1,
        runner_retry_delay=0.0,
        runner_action_timeout=0.01,
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT
    engine.agents[1] = HungAgent()

    response = await asyncio.wait_for(
        engine._ask(
            1,
            ActionType.SEER_CHECK,
            candidates=(2, 3),
            default=ActionResponse(ActionType.SEER_CHECK, target=2),
        ),
        timeout=1.0,
    )

    assert response.action_type is ActionType.SEER_CHECK
    assert response.target == 2
    assert engine.agents[1].requests[0].retry_count == 0
    assert _events(engine, "agent_error")[0].payload["error_type"] == "TimeoutError"
    assert _events(engine, "agent_error")[0].payload["retry_count"] == 0
    assert _events(engine, "default_action")[0].target == 2
    assert _events(engine, "action_response") == []


async def test_seer_check_reports_god_roles_as_good():
    engine = _engine(
        {1: Role.GUARD, 2: Role.WEREWOLF, 4: Role.SEER},
        responses={4: [ActionResponse(ActionType.SEER_CHECK, target=1)]},
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    await rule_for(Role.SEER).night_action(engine)

    result_event = _events(engine, "seer_result")[-1]
    assert engine.state.players[4].role_state["checks"]["1"] == {
        "day": 1,
        "target": 1,
        "result": Team.VILLAGERS.value,
    }
    assert engine.observation_for(4).seer_checks == {1: Team.VILLAGERS}
    assert result_event.payload == {"result": Team.VILLAGERS.value}
    assert result_event.message == "预言家4号查验1号，结果好人"
    assert "gods" not in result_event.message


def test_seer_checks_skips_entries_with_bad_history_keys():
    engine = _engine({1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER})
    engine.state.players[1].role_state["checks"] = {
        "2": {"day": 1, "result": Team.WEREWOLVES.value},
        "bad-key": {"day": 1, "result": Team.VILLAGERS.value},
        "also-bad": {"day": 1, "target": "not-an-int", "result": Team.GODS.value},
    }

    assert rule_for(Role.SEER).seer_checks(engine, 1) == {2: Team.WEREWOLVES}


async def test_witch_save_consumes_antidote_and_records_private_history():
    engine = _engine(
        {1: Role.WITCH, 2: Role.WEREWOLF, 3: Role.VILLAGER},
        responses={1: [ActionResponse(ActionType.WITCH_ACT, choice="save")]},
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    saved, poisoned_target = await rule_for(Role.WITCH).night_action(engine, killed_target=3)

    witch_state = engine.state.players[1].role_state
    assert saved is True
    assert poisoned_target is None
    assert witch_state["antidote_available"] is False
    assert witch_state["antidote_history"] == [{"day": 1, "target": 3}]
    assert engine.agents[1].requests[-1].metadata["can_save"] is True
    assert _events(engine, ActionType.WITCH_ACT.value)[-1].public is False
    assert _events(engine, "witch_result")[-1].public is False


async def test_witch_save_records_attacked_target_not_unrelated_response_target():
    accepted_responses: list[ActionResponse] = []

    def capture_accepted(response: ActionResponse) -> None:
        accepted_responses.append(response)

    engine = _engine(
        {1: Role.WITCH, 2: Role.WEREWOLF, 3: Role.VILLAGER, 4: Role.SEER},
        responses={
            1: [
                ActionResponse(
                    ActionType.WITCH_ACT,
                    choice="save",
                    target=4,
                    decision_id="witch-save-noisy-target",
                    on_accepted=capture_accepted,
                )
            ]
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    saved, poisoned_target = await rule_for(Role.WITCH).night_action(engine, killed_target=3)

    witch_action = _events(engine, ActionType.WITCH_ACT.value)[-1]
    action_response = _events(engine, "action_response")[-1]
    assert saved is True
    assert poisoned_target is None
    assert accepted_responses[0].target == 3
    assert witch_action.target == 3
    assert action_response.target == 3
    assert engine.state.players[1].role_state["antidote_history"] == [{"day": 1, "target": 3}]


async def test_witch_poison_rejects_self_target_and_retries():
    engine = _engine(
        {1: Role.WITCH, 2: Role.WEREWOLF, 3: Role.VILLAGER},
        responses={
            1: [
                ActionResponse(ActionType.WITCH_ACT, choice="poison", target=1),
                ActionResponse(ActionType.WITCH_ACT, choice="poison", target=3),
            ]
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.NIGHT

    saved, poisoned_target = await rule_for(Role.WITCH).night_action(engine, killed_target=None)

    witch_state = engine.state.players[1].role_state
    assert saved is False
    assert poisoned_target == 3
    assert witch_state["poison_available"] is False
    assert witch_state["poison_history"] == [{"day": 1, "target": 3}]
    assert 1 not in engine.agents[1].requests[-1].candidates
    assert _events(engine, "invalid_response")[-1].public is False


async def test_guard_and_witch_save_same_target_results_in_death():
    engine = _engine(
        {1: Role.GUARD, 2: Role.WEREWOLF, 3: Role.WITCH, 4: Role.VILLAGER},
        responses={
            1: [ActionResponse(ActionType.GUARD_PROTECT, target=4)],
            2: [ActionResponse(ActionType.WEREWOLF_KILL, target=4)],
            3: [ActionResponse(ActionType.WITCH_ACT, choice="save")],
        },
    )

    result = await night.resolve_night_actions(engine)

    assert result.protected_target == 4
    assert result.killed_target == 4
    assert result.saved is True
    assert result.deaths == [(4, (DeathCause.WEREWOLF,))]


async def test_wolf_kill_and_poison_same_target_keeps_both_causes():
    engine = _engine(
        {1: Role.WEREWOLF, 2: Role.HUNTER, 3: Role.WITCH},
        responses={
            1: [ActionResponse(ActionType.WEREWOLF_KILL, target=2)],
            3: [ActionResponse(ActionType.WITCH_ACT, choice="poison", target=2)],
        },
    )

    result = await night.resolve_night_actions(engine)

    assert result.deaths == [(2, (DeathCause.WEREWOLF, DeathCause.WITCH_POISON))]


async def test_white_wolf_king_explosion_kills_self_and_good_target():
    engine = _engine(
        {1: Role.WHITE_WOLF_KING, 2: Role.WEREWOLF, 3: Role.VILLAGER, 4: Role.SEER},
        responses={
            1: [
                ActionResponse(ActionType.WHITE_WOLF_EXPLODE, choice="explode", target=3),
                ActionResponse(ActionType.LAST_WORD, text="last word"),
            ],
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.DAY_SPEECH

    result = await rule_for(Role.WHITE_WOLF_KING).day_interrupt(engine, 1)

    assert result == "white_wolf_exploded"
    assert engine.state.players[1].role_state["has_exploded"] is True
    assert not engine.state.players[1].alive
    assert not engine.state.players[3].alive
    assert engine.state.deaths[-2].cause is DeathCause.SELF_EXPLODE
    assert engine.state.deaths[-1].cause is DeathCause.WHITE_WOLF
    assert engine.state.phase is Phase.NIGHT
    explosion = _events(engine, "white_wolf_explosion")[-1]
    assert explosion.public is True
    assert explosion.index < _events(engine, "death")[0].index


async def test_white_wolf_king_pass_with_target_does_not_explode():
    engine = _engine(
        {1: Role.WHITE_WOLF_KING, 2: Role.WEREWOLF, 3: Role.VILLAGER, 4: Role.SEER},
        responses={
            1: [
                ActionResponse(ActionType.WHITE_WOLF_EXPLODE, choice="pass", target=3),
                ActionResponse(ActionType.WHITE_WOLF_EXPLODE, choice="pass"),
            ],
        },
    )
    engine.state.day = 1
    engine.state.phase = Phase.DAY_SPEECH

    result = await rule_for(Role.WHITE_WOLF_KING).day_interrupt(engine, 1)

    assert result is None
    assert engine.state.players[1].role_state["has_exploded"] is False
    assert engine.state.players[1].alive
    assert engine.state.players[3].alive
    assert _events(engine, "invalid_response")[-1].actor == 1
    assert all(not event.public for event in _events(engine, ActionType.WHITE_WOLF_EXPLODE.value))
    assert _events(engine, "white_wolf_explosion") == []
