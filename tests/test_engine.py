import json
import unittest

from helpers import agents_with, run, standard_roles
from werewolf.config import GameConfig
from werewolf.engine import GameEngine
from werewolf.models import (
    ActionResponse,
    ActionType,
    DeathCause,
    Phase,
    Role,
    Winner,
)


class EngineTests(unittest.TestCase):
    def test_first_sheriff_election_happens_after_first_night_before_death_reveal(self):
        class FlowAgent:
            def __init__(self, player_id):
                self.player_id = player_id
                self.requests = []

            async def act(self, request):
                self.requests.append(request)
                if request.action_type is ActionType.WEREWOLF_KILL:
                    return ActionResponse(ActionType.WEREWOLF_KILL, target=9)
                if request.action_type is ActionType.SHERIFF_RUN:
                    return ActionResponse(ActionType.SHERIFF_RUN, choice="run" if self.player_id == 9 else "pass")
                if request.action_type is ActionType.SHERIFF_SPEAK:
                    return ActionResponse(ActionType.SHERIFF_SPEAK, text="我竞选警长")
                if request.action_type is ActionType.SHERIFF_WITHDRAW:
                    return ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="stay")
                if request.action_type is ActionType.SHERIFF_VOTE:
                    return ActionResponse(ActionType.SHERIFF_VOTE, target=9)
                if request.action_type is ActionType.SHERIFF_BADGE:
                    return ActionResponse(ActionType.SHERIFF_BADGE, choice="destroy")
                if request.action_type is ActionType.WHITE_WOLF_EXPLODE:
                    return ActionResponse(ActionType.WHITE_WOLF_EXPLODE, choice="pass")
                return ActionResponse(request.action_type, text="")

        agents = {player_id: FlowAgent(player_id) for player_id in range(1, 13)}
        engine = GameEngine(standard_roles(), agents)

        with self.assertRaises(RuntimeError):
            run(engine.run_until_finished(max_days=1))

        events = [entry.event_type for entry in engine.logger.entries]
        self.assertLess(events.index("night_end"), events.index("sheriff_election_start"))
        self.assertLess(events.index("sheriff_election_end"), events.index("death"))

        sheriff_run_request = next(
            request for request in agents[9].requests if request.action_type is ActionType.SHERIFF_RUN
        )
        self.assertEqual(sheriff_run_request.observation.day, 1)
        self.assertEqual(engine.state.sheriff_id, None)
        self.assertFalse(engine.state.players[9].alive)

    def test_observation_filters_private_information_by_player_role(self):
        engine = GameEngine(standard_roles(), agents_with())
        wolf_view = engine.observation_for(2)
        villager_view = engine.observation_for(9)

        self.assertEqual(wolf_view.self_role, Role.WEREWOLF)
        self.assertEqual(wolf_view.known_roles[1], Role.WHITE_WOLF_KING)
        self.assertEqual(wolf_view.known_roles[3], Role.WEREWOLF)
        self.assertNotIn(5, wolf_view.known_roles)
        self.assertEqual(villager_view.self_role, Role.VILLAGER)
        self.assertEqual(villager_view.known_roles, {})

    def test_night_resolution_handles_same_guard_and_save_as_death_and_poison_blocks_hunter(self):
        agents = agents_with()
        agents[8].push(ActionResponse(ActionType.GUARD_PROTECT, target=7))
        for wolf_id in [1, 2, 3, 4]:
            agents[wolf_id].push(ActionResponse(ActionType.WEREWOLF_KILL, target=7))
        agents[5].push(ActionResponse(ActionType.SEER_CHECK, target=1))
        agents[6].push(ActionResponse(ActionType.WITCH_ACT, choice="save"))
        engine = GameEngine(standard_roles(), agents)

        run(engine.run_night())

        self.assertFalse(engine.state.players[7].alive)
        self.assertEqual(engine.state.deaths[-1].cause, DeathCause.WEREWOLF)
        self.assertTrue(engine.can_hunter_shoot(7))

        engine = GameEngine(standard_roles(), agents_with())
        engine.kill_player(7, DeathCause.WITCH_POISON)

        self.assertFalse(engine.can_hunter_shoot(7))

    def test_engine_validates_against_config_instead_of_fixed_standard_setup(self):
        config = GameConfig(
            name="tiny_config",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.WEREWOLF,),
        )

        engine = GameEngine({1: Role.WEREWOLF, 2: Role.VILLAGER}, agents_with(), config=config)
        self.assertEqual(engine.config, config)

        with self.assertRaisesRegex(ValueError, "expected 2 players"):
            GameEngine({1: Role.WEREWOLF}, agents_with(), config=config)

        with self.assertRaisesRegex(ValueError, "expected roles"):
            GameEngine({1: Role.WEREWOLF, 2: Role.WEREWOLF}, agents_with(), config=config)

    def test_config_can_disable_sheriff_election_in_main_flow(self):
        config = GameConfig(
            name="no_sheriff",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.WEREWOLF,),
        )
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.WEREWOLF_KILL, target=2))
        engine = GameEngine({1: Role.WEREWOLF, 2: Role.VILLAGER}, agents, config=config)

        winner = run(engine.run_until_finished(max_days=1))

        self.assertEqual(winner, Winner.WEREWOLVES)
        self.assertNotIn(ActionType.SHERIFF_RUN, [request.action_type for request in agents[1].requests])

    def test_night_order_skips_roles_absent_from_config(self):
        config = GameConfig(
            name="no_guard_night",
            role_counts={
                Role.WEREWOLF: 1,
                Role.SEER: 1,
                Role.WITCH: 1,
                Role.VILLAGER: 2,
            },
            enable_sheriff=False,
            night_order=(Role.WEREWOLF, Role.SEER, Role.WITCH),
        )
        roles = {
            1: Role.WEREWOLF,
            2: Role.SEER,
            3: Role.WITCH,
            4: Role.VILLAGER,
            5: Role.VILLAGER,
        }
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.WEREWOLF_KILL, target=4))
        agents[2].push(ActionResponse(ActionType.SEER_CHECK, target=1))
        agents[3].push(ActionResponse(ActionType.WITCH_ACT, choice="none"))
        engine = GameEngine(roles, agents, config=config)

        run(engine.run_night())

        requested_actions = [request.action_type for agent in agents.values() for request in agent.requests]
        self.assertNotIn(ActionType.GUARD_PROTECT, requested_actions)
        self.assertIn(ActionType.WEREWOLF_KILL, requested_actions)
        self.assertIn(ActionType.SEER_CHECK, requested_actions)
        self.assertIn(ActionType.WITCH_ACT, requested_actions)

    def test_sheriff_vote_counts_as_one_and_a_half_and_badge_can_transfer(self):
        engine = GameEngine(standard_roles(), agents_with())
        engine.state.sheriff_id = 5

        exile = engine.resolve_exile_votes({5: 9, 6: 10, 7: 10})
        self.assertEqual(exile, 10)

        engine.kill_player(5, DeathCause.WEREWOLF)
        agents = agents_with()
        agents[5].push(ActionResponse(ActionType.SHERIFF_BADGE, choice="transfer", target=6))
        engine.agents = agents

        run(engine.resolve_sheriff_death(5))

        self.assertEqual(engine.state.sheriff_id, 6)
        self.assertFalse(engine.state.badge_destroyed)

    def test_sheriff_selects_reverse_day_speech_order_and_speaks_last(self):
        class SpeechOrderAgent:
            def __init__(self, player_id):
                self.player_id = player_id
                self.requests = []

            def act(self, request):
                self.requests.append(request)
                if request.action_type is ActionType.SPEECH_ORDER:
                    return ActionResponse(ActionType.SPEECH_ORDER, choice="reverse")
                if request.action_type is ActionType.WHITE_WOLF_EXPLODE:
                    return ActionResponse(ActionType.WHITE_WOLF_EXPLODE, choice="pass")
                return ActionResponse(request.action_type, text=f"{self.player_id}号发言")

        agents = {player_id: SpeechOrderAgent(player_id) for player_id in range(1, 13)}
        engine = GameEngine(standard_roles(), agents)
        engine.state.sheriff_id = 5

        run(engine.run_day_speeches())

        speech_order_requests = [
            request for request in agents[5].requests if request.action_type is ActionType.SPEECH_ORDER
        ]
        speak_order = [
            entry.actor
            for entry in engine.logger.entries
            if entry.event_type == "action_response"
            and entry.payload.get("action_type") == ActionType.SPEAK.value
        ]
        self.assertEqual(len(speech_order_requests), 1)
        self.assertEqual(speak_order, [4, 3, 2, 1, 12, 11, 10, 9, 8, 7, 6, 5])

    def test_public_log_includes_public_speeches_for_agent_memory(self):
        class SpeakingAgent:
            def __init__(self, player_id):
                self.player_id = player_id

            async def act(self, request):
                if request.action_type is ActionType.WHITE_WOLF_EXPLODE:
                    return ActionResponse(ActionType.WHITE_WOLF_EXPLODE, choice="pass")
                return ActionResponse(request.action_type, text=f"{self.player_id}号公开发言")

        agents = {player_id: SpeakingAgent(player_id) for player_id in range(1, 13)}
        engine = GameEngine(standard_roles(), agents)

        run(engine.run_day_speeches())

        public_events = [json.loads(item) for item in engine.state.public_log]
        speech_events = [event for event in public_events if event["type"] == ActionType.SPEAK.value]
        self.assertEqual(speech_events[0]["actor"], 1)
        self.assertEqual(speech_events[0]["content"], "1号公开发言")

    def test_sheriff_withdraw_requests_include_runner_context(self):
        agents = agents_with()
        for player_id in range(1, 13):
            if player_id not in (5, 7):
                agents[player_id].push(ActionResponse(ActionType.SHERIFF_RUN, choice="pass"))
                agents[player_id].push(ActionResponse(ActionType.SHERIFF_VOTE, target=7))
        for player_id in (5, 7):
            agents[player_id].push(ActionResponse(ActionType.SHERIFF_RUN, choice="run"))
        for player_id in (5, 7):
            agents[player_id].push(ActionResponse(ActionType.SHERIFF_SPEAK, text=f"{player_id}号警上发言"))
        agents[5].push(ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="withdraw"))
        agents[7].push(ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="stay"))
        engine = GameEngine(standard_roles(), agents)

        sheriff = run(engine.run_sheriff_election())

        first_withdraw = next(
            request for request in agents[5].requests if request.action_type is ActionType.SHERIFF_WITHDRAW
        )
        last_withdraw = next(
            request for request in agents[7].requests if request.action_type is ActionType.SHERIFF_WITHDRAW
        )
        self.assertEqual(sheriff, 7)
        self.assertEqual(first_withdraw.candidates, (5, 7))
        self.assertEqual(first_withdraw.metadata["runners"], [5, 7])
        self.assertEqual(first_withdraw.metadata["remaining_runners"], [5, 7])
        self.assertEqual(last_withdraw.metadata["runners"], [7])
        self.assertEqual(last_withdraw.metadata["initial_runners"], [5, 7])

    def test_withdrawn_sheriff_runner_cannot_vote_for_sheriff(self):
        agents = agents_with()
        for player_id in (5, 7):
            agents[player_id].push(ActionResponse(ActionType.SHERIFF_RUN, choice="run"))
            agents[player_id].push(ActionResponse(ActionType.SHERIFF_SPEAK, text=f"{player_id}号警上发言"))
        agents[5].push(ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="withdraw"))
        agents[7].push(ActionResponse(ActionType.SHERIFF_WITHDRAW, choice="stay"))
        agents[5].push(ActionResponse(ActionType.SHERIFF_VOTE, target=7))
        engine = GameEngine(standard_roles(), agents)

        sheriff = run(engine.run_sheriff_election())

        withdrawn_runner_votes = [
            request for request in agents[5].requests if request.action_type is ActionType.SHERIFF_VOTE
        ]
        self.assertEqual(sheriff, None)
        self.assertEqual(withdrawn_runner_votes, [])

    def test_tied_exile_vote_enters_pk_and_second_tie_exiles_nobody(self):
        agents = agents_with()
        for voter, target in [(1, 9), (2, 10), (3, 9), (4, 10)]:
            agents[voter].push(ActionResponse(ActionType.EXILE_VOTE, target=target))
        for voter, target in [(1, 9), (2, 10), (3, 9), (4, 10)]:
            agents[voter].push(ActionResponse(ActionType.PK_VOTE, target=target))
        engine = GameEngine(standard_roles(), agents)
        for player_id in range(5, 13):
            engine.kill_player(player_id, DeathCause.WEREWOLF)
        engine.revive_player(9)
        engine.revive_player(10)

        exiled = run(engine.run_exile_vote())

        self.assertIsNone(exiled)
        self.assertTrue(engine.state.players[9].alive)
        self.assertTrue(engine.state.players[10].alive)
        self.assertEqual(engine.state.phase, Phase.DAY_SPEECH)

    def test_exiled_hunter_shoots_and_kills_target(self):
        agents = agents_with()
        for voter in range(1, 13):
            agents[voter].push(ActionResponse(ActionType.EXILE_VOTE, target=7))
        agents[7].push(ActionResponse(ActionType.LAST_WORD, text="猎人遗言"))
        agents[7].push(ActionResponse(ActionType.HUNTER_SHOOT, target=4))
        engine = GameEngine(standard_roles(), agents)

        exiled = run(engine.run_exile_vote())

        self.assertEqual(exiled, 7)
        self.assertFalse(engine.state.players[7].alive)
        self.assertFalse(engine.state.players[4].alive)
        self.assertEqual(engine.last_death_for(4).cause, DeathCause.HUNTER_SHOT)
        self.assertIn("hunter_shot", [event.type for event in engine.state.events])

    def test_exiled_hunter_has_last_word_but_hunter_shot_target_does_not(self):
        agents = agents_with()
        for voter in range(1, 13):
            agents[voter].push(ActionResponse(ActionType.EXILE_VOTE, target=7))
        agents[7].push(ActionResponse(ActionType.LAST_WORD, text="猎人遗言"))
        agents[7].push(ActionResponse(ActionType.HUNTER_SHOOT, target=4))
        agents[4].push(ActionResponse(ActionType.LAST_WORD, text="不应出现"))
        engine = GameEngine(standard_roles(), agents)

        run(engine.run_exile_vote())

        hunter_actions = [request.action_type for request in agents[7].requests]
        shot_target_actions = [request.action_type for request in agents[4].requests]
        self.assertLess(hunter_actions.index(ActionType.LAST_WORD), hunter_actions.index(ActionType.HUNTER_SHOOT))
        self.assertIn(ActionType.LAST_WORD, hunter_actions)
        self.assertNotIn(ActionType.LAST_WORD, shot_target_actions)

    def test_exiled_player_gets_immediate_last_word(self):
        agents = agents_with()
        for voter in range(1, 13):
            agents[voter].push(ActionResponse(ActionType.EXILE_VOTE, target=9))
        agents[9].push(ActionResponse(ActionType.LAST_WORD, text="即时遗言"))
        engine = GameEngine(standard_roles(), agents)

        run(engine.run_exile_vote())

        actions = [request.action_type for request in agents[9].requests]
        last_word_index = next(
            index
            for index, entry in enumerate(engine.logger.entries)
            if entry.event_type == "action_response"
            and entry.actor == 9
            and entry.payload.get("action_type") == ActionType.LAST_WORD.value
        )
        exile_end_index = next(index for index, entry in enumerate(engine.logger.entries) if entry.event_type == "exile_vote_end")

        self.assertIn(ActionType.LAST_WORD, actions)
        self.assertLess(last_word_index, exile_end_index)
        self.assertNotIn(9, engine.state.pending_last_words)

    def test_pk_exiled_player_gets_immediate_last_word(self):
        agents = agents_with()
        for voter, target in [(1, 9), (2, 10), (3, 9), (4, 10)]:
            agents[voter].push(ActionResponse(ActionType.EXILE_VOTE, target=target))
        for voter, target in [(1, 9), (2, 9), (3, 9), (4, 10)]:
            agents[voter].push(ActionResponse(ActionType.PK_VOTE, target=target))
        agents[9].push(ActionResponse(ActionType.LAST_WORD, text="PK遗言"))
        engine = GameEngine(standard_roles(), agents)
        for player_id in range(5, 13):
            engine.kill_player(player_id, DeathCause.WEREWOLF)
        engine.revive_player(9)
        engine.revive_player(10)

        exiled = run(engine.run_exile_vote())

        actions = [request.action_type for request in agents[9].requests]
        self.assertEqual(exiled, 9)
        self.assertIn(ActionType.LAST_WORD, actions)
        self.assertNotIn(9, engine.state.pending_last_words)

    def test_werewolf_killed_villager_has_no_daytime_last_word(self):
        agents = agents_with()
        agents[8].push(ActionResponse(ActionType.GUARD_PROTECT, target=6))
        for wolf_id in [1, 2, 3, 4]:
            agents[wolf_id].push(ActionResponse(ActionType.WEREWOLF_KILL, target=9))
        agents[5].push(ActionResponse(ActionType.SEER_CHECK, target=1))
        agents[6].push(ActionResponse(ActionType.WITCH_ACT, choice="none"))
        agents[9].push(ActionResponse(ActionType.LAST_WORD, text="不应出现"))
        engine = GameEngine(standard_roles(), agents)

        run(engine.run_night())
        run(engine.run_day_speeches())

        villager_actions = [request.action_type for request in agents[9].requests]
        self.assertFalse(engine.state.players[9].alive)
        self.assertNotIn(ActionType.LAST_WORD, villager_actions)
        self.assertNotIn(9, engine.state.pending_last_words)

    def test_werewolf_killed_hunter_shoots_after_daybreak_without_last_word(self):
        agents = agents_with()
        agents[8].push(ActionResponse(ActionType.GUARD_PROTECT, target=6))
        for wolf_id in [1, 2, 3, 4]:
            agents[wolf_id].push(ActionResponse(ActionType.WEREWOLF_KILL, target=7))
        agents[5].push(ActionResponse(ActionType.SEER_CHECK, target=1))
        agents[6].push(ActionResponse(ActionType.WITCH_ACT, choice="none"))
        agents[7].push(ActionResponse(ActionType.HUNTER_SHOOT, target=4))
        agents[4].push(ActionResponse(ActionType.LAST_WORD, text="不应出现"))
        engine = GameEngine(standard_roles(), agents)

        run(engine.run_night())

        self.assertFalse(engine.state.players[7].alive)
        self.assertTrue(engine.state.players[4].alive)
        self.assertNotIn("hunter_shot", [event.type for event in engine.state.events])

        run(engine.run_day_speeches())

        hunter_actions = [request.action_type for request in agents[7].requests]
        shot_target_actions = [request.action_type for request in agents[4].requests]
        event_types = [event.type for event in engine.state.events]
        self.assertNotIn(ActionType.LAST_WORD, hunter_actions)
        self.assertIn(ActionType.HUNTER_SHOOT, hunter_actions)
        self.assertFalse(engine.state.players[4].alive)
        self.assertIn("hunter_shot", event_types)
        self.assertNotIn(ActionType.LAST_WORD, shot_target_actions)

    def test_hunter_shot_can_end_game_before_remaining_day_speeches(self):
        agents = agents_with()
        agents[7].push(ActionResponse(ActionType.HUNTER_SHOOT, target=9))
        engine = GameEngine(standard_roles(), agents)
        for player_id in (1, 3, 4, 5, 6, 8, 10, 11, 12):
            engine.kill_player(player_id, DeathCause.WEREWOLF)
        engine.kill_player(7, DeathCause.WEREWOLF)
        engine.state.pending_hunter_shots.append(7)

        result = run(engine.run_day_speeches())

        self.assertEqual(result, "finished")
        self.assertEqual(engine.state.winner, Winner.WEREWOLVES)
        self.assertFalse(engine.state.players[9].alive)
        self.assertIn("hunter_shot", [event.type for event in engine.state.events])
        self.assertNotIn(ActionType.SPEAK, [request.action_type for request in agents[2].requests])

    def test_poisoned_hunter_does_not_shoot(self):
        agents = agents_with()
        agents[7].push(ActionResponse(ActionType.HUNTER_SHOOT, target=4))
        engine = GameEngine(standard_roles(), agents)

        engine.kill_player(7, DeathCause.WITCH_POISON)
        run(engine.resolve_hunter_death(7))

        self.assertTrue(engine.state.players[4].alive)
        self.assertNotIn("hunter_shot", [event.type for event in engine.state.events])

    def test_white_wolf_can_explode_during_speech_and_only_target_non_wolves(self):
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.WHITE_WOLF_EXPLODE, target=2))
        agents[1].push(ActionResponse(ActionType.WHITE_WOLF_EXPLODE, target=5))
        engine = GameEngine(standard_roles(), agents)

        result = run(engine.run_day_speeches())

        self.assertEqual(result, "white_wolf_exploded")
        self.assertFalse(engine.state.players[1].alive)
        self.assertFalse(engine.state.players[5].alive)
        self.assertTrue(engine.state.players[2].alive)
        self.assertEqual(engine.state.phase, Phase.NIGHT)

    def test_white_wolf_last_word_happens_immediately_after_explosion(self):
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.WHITE_WOLF_EXPLODE, target=5))
        agents[1].push(ActionResponse(ActionType.LAST_WORD, text="白狼王遗言"))
        engine = GameEngine(standard_roles(), agents)

        result = run(engine.run_day_speeches())

        self.assertEqual(result, "white_wolf_exploded")
        action_responses = [
            (entry.actor, entry.payload.get("action_type"))
            for entry in engine.logger.entries
            if entry.event_type == "action_response"
        ]
        explosion_index = next(
            index for index, entry in enumerate(engine.logger.entries) if entry.event_type == "white_wolf_explosion"
        )
        later_day_speech_entries = [
            entry
            for entry in engine.logger.entries[explosion_index + 1 :]
            if entry.day == 1 and entry.phase is Phase.DAY_SPEECH
        ]

        self.assertIn((1, ActionType.LAST_WORD.value), action_responses)
        self.assertNotIn((5, ActionType.LAST_WORD.value), action_responses)
        self.assertEqual(later_day_speech_entries, [])
        self.assertNotIn(1, engine.state.pending_last_words)

    def test_run_until_finished_skips_exile_vote_after_white_wolf_explosion(self):
        class WolfAgent:
            def __init__(self, explode_target: int | None = None):
                self.explode_target = explode_target

            def act(self, request):
                if request.action_type is ActionType.WEREWOLF_KILL:
                    return ActionResponse(ActionType.WEREWOLF_KILL, target=9)
                if request.action_type is ActionType.WHITE_WOLF_EXPLODE:
                    return ActionResponse(ActionType.WHITE_WOLF_EXPLODE, target=self.explode_target)
                return ActionResponse(request.action_type, choice="pass")

        agents = agents_with()
        agents[1] = WolfAgent(explode_target=6)
        for wolf_id in [2, 3, 4]:
            agents[wolf_id] = WolfAgent()
        engine = GameEngine(standard_roles(), agents)

        with self.assertRaises(RuntimeError):
            run(engine.run_until_finished(max_days=1))

        events = [(entry.day, entry.event_type) for entry in engine.logger.entries]
        self.assertIn((1, "white_wolf_explosion"), events)
        self.assertNotIn((1, "exile_vote_start"), events)

    def test_white_wolf_has_last_word_but_white_wolf_target_does_not(self):
        agents = agents_with()
        engine = GameEngine(standard_roles(), agents)
        engine.state.day = 1
        engine.state.phase = Phase.DAY_SPEECH

        engine.kill_player(1, DeathCause.SELF_EXPLODE)
        engine.kill_player(5, DeathCause.WHITE_WOLF)
        run(engine.run_day_speeches())

        player_1_actions = [request.action_type for request in agents[1].requests]
        player_5_actions = [request.action_type for request in agents[5].requests]
        self.assertIn(ActionType.LAST_WORD, player_1_actions)
        self.assertNotIn(ActionType.LAST_WORD, player_5_actions)

    def test_white_wolf_targeted_hunter_does_not_shoot(self):
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.WHITE_WOLF_EXPLODE, target=7))
        agents[7].push(ActionResponse(ActionType.HUNTER_SHOOT, target=4))
        engine = GameEngine(standard_roles(), agents)

        run(engine.run_day_speeches())

        hunter_actions = [request.action_type for request in agents[7].requests]
        self.assertFalse(engine.state.players[7].alive)
        self.assertTrue(engine.state.players[4].alive)
        self.assertNotIn(ActionType.HUNTER_SHOOT, hunter_actions)

    def test_last_words_are_not_repeated_on_later_days(self):
        class EchoAgent:
            def __init__(self):
                self.requests = []

            def act(self, request):
                self.requests.append(request)
                return ActionResponse(request.action_type)

        agents = agents_with()
        agents[2] = EchoAgent()
        engine = GameEngine(standard_roles(), agents)
        engine.state.day = 1
        engine.state.phase = Phase.DAY_SPEECH

        engine.kill_player(2, DeathCause.EXILE)
        run(engine.run_day_speeches())
        run(engine.run_day_speeches())

        last_word_requests = [
            request for request in agents[2].requests if request.action_type is ActionType.LAST_WORD
        ]
        self.assertEqual(len(last_word_requests), 1)

    def test_win_condition_uses_side_slaughter(self):
        engine = GameEngine(standard_roles(), agents_with())
        for wolf_id in [1, 2, 3, 4]:
            engine.kill_player(wolf_id, DeathCause.EXILE)

        self.assertEqual(engine.check_winner(), Winner.VILLAGERS)

        engine = GameEngine(standard_roles(), agents_with())
        for villager_id in [9, 10, 11, 12]:
            engine.kill_player(villager_id, DeathCause.WEREWOLF)

        self.assertEqual(engine.check_winner(), Winner.WEREWOLVES)

        engine = GameEngine(standard_roles(), agents_with())
        for god_id in [5, 6, 7, 8]:
            engine.kill_player(god_id, DeathCause.WEREWOLF)

        self.assertEqual(engine.check_winner(), Winner.WEREWOLVES)

        engine = GameEngine(standard_roles(), agents_with())
        for player_id in (1, 4, 6, 7, 8, 10, 11, 12):
            engine.kill_player(player_id, DeathCause.WEREWOLF)

        self.assertEqual(engine.check_winner(), Winner.WEREWOLVES)


if __name__ == "__main__":
    unittest.main()
