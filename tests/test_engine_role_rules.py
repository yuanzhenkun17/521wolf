from __future__ import annotations

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

    assert target == 3
    assert engine.agents[1].requests[-1].candidates == (3, 4)
    assert engine.agents[2].requests[-1].candidates == (3, 4)
    assert all(not event.public for event in _events(engine, ActionType.WEREWOLF_KILL.value))
    assert _events(engine, "werewolf_result")[-1].public is False


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
    result_event = _events(engine, "seer_result")[-1]
    assert result_event.public is False
    assert result_event.message == "预言家1号查验2号，结果坏人"
    assert "狼人" not in result_event.message


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
    assert result.deaths == [(4, DeathCause.WEREWOLF)]


async def test_white_wolf_king_explosion_kills_self_and_good_target():
    engine = _engine(
        {1: Role.WHITE_WOLF_KING, 2: Role.WEREWOLF, 3: Role.VILLAGER, 4: Role.SEER},
        responses={
            1: [
                ActionResponse(ActionType.WHITE_WOLF_EXPLODE, target=3),
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
    assert _events(engine, "white_wolf_explosion")[-1].public is True
