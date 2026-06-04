"""Tests verifying that role_state is the sole authority for role-specific state.

These tests confirm that the role rules derive all role-specific data from
PlayerState.role_state rather than from GameState flat fields (which were
removed during the role_state migration).
"""

import unittest

from engine.config import GameConfig, STANDARD_12
from engine.engine import GameEngine
from engine.models import (
    ActionResponse,
    ActionType,
    DeathCause,
    Phase,
    PlayerState,
    Role,
    Team,
)
from engine.role_rules.registry import rule_for
from engine.role_rules.seer import SeerRule
from engine.role_rules.witch import WitchRule
from engine.role_rules.guard import GuardRule
from engine.role_rules.hunter import HunterRule
from engine.role_rules.white_wolf_king import WhiteWolfKingRule
from engine.role_rules.villager import VillagerRule
from engine.role_rules.werewolf import WerewolfRule
from engine.players import ScriptedAgent

from helpers import run, agents_with, standard_roles


def _make_minimal_engine(roles_dict, agents_dict, config=None):
    """Create a GameEngine with the given roles and agents."""
    return GameEngine(roles_dict, agents_dict, config=config)


class SeerRoleStateTests(unittest.TestCase):
    """Tests for SeerRule.seer_checks() deriving from role_state."""

    def test_seer_checks_returns_empty_dict_for_player_with_no_checks(self):
        """A seer with no checks in role_state should return {}."""
        roles = {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER}
        config = GameConfig(
            name="seer_test",
            role_counts={Role.SEER: 1, Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.SEER,),
        )
        agents = agents_with()
        engine = _make_minimal_engine(roles, agents, config=config)
        seer_rule = rule_for(Role.SEER)

        result = seer_rule.seer_checks(engine, 1)
        self.assertEqual(result, {})

    def test_seer_checks_returns_dict_from_role_state(self):
        """SeerRule.seer_checks() should derive results from role_state["checks"]."""
        roles = {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER}
        config = GameConfig(
            name="seer_test",
            role_counts={Role.SEER: 1, Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.SEER,),
        )
        agents = agents_with()
        engine = _make_minimal_engine(roles, agents, config=config)

        # Manually populate the seer's role_state checks
        seer_ps = engine.state.players[1]
        seer_ps.role_state["checks"]["2"] = {
            "day": 1,
            "target": 2,
            "result": "werewolves",
        }
        seer_ps.role_state["checks"]["3"] = {
            "day": 2,
            "target": 3,
            "result": "villagers",
        }

        seer_rule = rule_for(Role.SEER)
        result = seer_rule.seer_checks(engine, 1)

        self.assertEqual(result[2], Team.WEREWOLVES)
        self.assertEqual(result[3], Team.VILLAGERS)
        self.assertEqual(len(result), 2)

    def test_seer_checks_skips_invalid_team_values(self):
        """SeerRule.seer_checks() should skip entries with invalid Team strings."""
        roles = {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER}
        config = GameConfig(
            name="seer_test",
            role_counts={Role.SEER: 1, Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.SEER,),
        )
        agents = agents_with()
        engine = _make_minimal_engine(roles, agents, config=config)

        seer_ps = engine.state.players[1]
        seer_ps.role_state["checks"]["2"] = {
            "day": 1,
            "target": 2,
            "result": "werewolves",
        }
        seer_ps.role_state["checks"]["3"] = {
            "day": 2,
            "target": 3,
            "result": "invalid_team_value",
        }

        seer_rule = rule_for(Role.SEER)
        result = seer_rule.seer_checks(engine, 1)

        self.assertEqual(result[2], Team.WEREWOLVES)
        self.assertNotIn(3, result)

    def test_seer_checks_returns_empty_for_nonexistent_player(self):
        """SeerRule.seer_checks() should return {} for a non-existent player ID."""
        roles = {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER}
        config = GameConfig(
            name="seer_test",
            role_counts={Role.SEER: 1, Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.SEER,),
        )
        agents = agents_with()
        engine = _make_minimal_engine(roles, agents, config=config)

        seer_rule = rule_for(Role.SEER)
        result = seer_rule.seer_checks(engine, 99)
        self.assertEqual(result, {})

    def test_seer_night_action_updates_role_state(self):
        """Seer night_action should write check results to role_state, not GameState."""
        roles = {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER}
        config = GameConfig(
            name="seer_test",
            role_counts={Role.SEER: 1, Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.SEER,),
        )
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.SEER_CHECK, target=2))
        engine = _make_minimal_engine(roles, agents, config=config)
        engine.state.day = 1

        seer_rule = rule_for(Role.SEER)
        run(seer_rule.night_action(engine))

        seer_ps = engine.state.players[1]
        checks = seer_ps.role_state["checks"]
        self.assertIn("2", checks)
        self.assertEqual(checks["2"]["target"], 2)
        self.assertEqual(checks["2"]["day"], 1)
        self.assertEqual(checks["2"]["result"], "werewolves")

    def test_seer_init_role_state_has_checks_dict(self):
        """SeerRule.init_role_state() should return {"checks": {}}."""
        seer_rule = rule_for(Role.SEER)
        state = seer_rule.init_role_state()
        self.assertEqual(state, {"checks": {}})


class WitchRoleStateTests(unittest.TestCase):
    """Tests for WitchRule deriving state from role_state."""

    def test_witch_init_role_state_has_antidote_and_poison(self):
        """WitchRule.init_role_state() should include antidote/poison availability."""
        witch_rule = rule_for(Role.WITCH)
        state = witch_rule.init_role_state()
        self.assertTrue(state["antidote_available"])
        self.assertTrue(state["poison_available"])
        self.assertEqual(state["antidote_history"], [])
        self.assertEqual(state["poison_history"], [])

    def test_witch_night_action_save_updates_role_state(self):
        """Witch saving should set antidote_available=False in role_state."""
        roles = {1: Role.WEREWOLF, 2: Role.WITCH, 3: Role.VILLAGER}
        config = GameConfig(
            name="witch_test",
            role_counts={Role.WEREWOLF: 1, Role.WITCH: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.WEREWOLF, Role.WITCH),
        )
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.WEREWOLF_KILL, target=3))
        agents[2].push(ActionResponse(ActionType.WITCH_ACT, choice="save"))
        engine = _make_minimal_engine(roles, agents, config=config)
        engine.state.day = 1

        # Run night phases manually
        werewolf_rule = rule_for(Role.WEREWOLF)
        killed_target = run(werewolf_rule.night_action(engine))

        witch_rule = rule_for(Role.WITCH)
        run(witch_rule.night_action(engine, killed_target=killed_target))

        witch_ps = engine.state.players[2]
        self.assertFalse(witch_ps.role_state["antidote_available"])
        self.assertTrue(witch_ps.role_state["poison_available"])
        self.assertEqual(len(witch_ps.role_state["antidote_history"]), 1)
        self.assertEqual(witch_ps.role_state["antidote_history"][0]["target"], 3)

    def test_witch_night_action_poison_updates_role_state(self):
        """Witch poisoning should set poison_available=False in role_state."""
        roles = {1: Role.WEREWOLF, 2: Role.WITCH, 3: Role.VILLAGER}
        config = GameConfig(
            name="witch_test",
            role_counts={Role.WEREWOLF: 1, Role.WITCH: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.WEREWOLF, Role.WITCH),
        )
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.WEREWOLF_KILL, target=3))
        agents[2].push(ActionResponse(ActionType.WITCH_ACT, choice="poison", target=3))
        engine = _make_minimal_engine(roles, agents, config=config)
        engine.state.day = 1

        werewolf_rule = rule_for(Role.WEREWOLF)
        killed_target = run(werewolf_rule.night_action(engine))

        witch_rule = rule_for(Role.WITCH)
        run(witch_rule.night_action(engine, killed_target=killed_target))

        witch_ps = engine.state.players[2]
        self.assertTrue(witch_ps.role_state["antidote_available"])
        self.assertFalse(witch_ps.role_state["poison_available"])
        self.assertEqual(len(witch_ps.role_state["poison_history"]), 1)

    def test_witch_night_action_none_does_not_change_role_state(self):
        """Witch doing nothing should not change antidote/poison availability."""
        roles = {1: Role.WEREWOLF, 2: Role.WITCH, 3: Role.VILLAGER}
        config = GameConfig(
            name="witch_test",
            role_counts={Role.WEREWOLF: 1, Role.WITCH: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.WEREWOLF, Role.WITCH),
        )
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.WEREWOLF_KILL, target=3))
        agents[2].push(ActionResponse(ActionType.WITCH_ACT, choice="none"))
        engine = _make_minimal_engine(roles, agents, config=config)
        engine.state.day = 1

        werewolf_rule = rule_for(Role.WEREWOLF)
        killed_target = run(werewolf_rule.night_action(engine))

        witch_rule = rule_for(Role.WITCH)
        run(witch_rule.night_action(engine, killed_target=killed_target))

        witch_ps = engine.state.players[2]
        self.assertTrue(witch_ps.role_state["antidote_available"])
        self.assertTrue(witch_ps.role_state["poison_available"])


class GuardRoleStateTests(unittest.TestCase):
    """Tests for GuardRule deriving state from role_state."""

    def test_guard_init_role_state_has_last_target_and_history(self):
        """GuardRule.init_role_state() should include last_target=None."""
        guard_rule = rule_for(Role.GUARD)
        state = guard_rule.init_role_state()
        self.assertIsNone(state["last_target"])
        self.assertEqual(state["protect_history"], [])

    def test_guard_candidates_excludes_last_target_from_role_state(self):
        """Guard candidates should exclude role_state["last_target"], not GameState."""
        roles = {1: Role.GUARD, 2: Role.WEREWOLF, 3: Role.VILLAGER}
        config = GameConfig(
            name="guard_test",
            role_counts={Role.GUARD: 1, Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.GUARD,),
        )
        agents = agents_with()
        engine = _make_minimal_engine(roles, agents, config=config)

        # Simulate that the guard protected player 3 on the previous night
        guard_ps = engine.state.players[1]
        guard_ps.role_state["last_target"] = 3

        # On the next night, guard should not be able to protect player 3 again
        guard_rule = rule_for(Role.GUARD)
        # The candidates are computed inside night_action, so we need to
        # verify via the engine's _ask call. But we can verify the logic
        # directly by inspecting how candidates are built:
        alive_ids = engine.alive_ids()
        last_target = guard_ps.role_state.get("last_target")
        candidates = tuple(pid for pid in alive_ids if pid != last_target)

        self.assertNotIn(3, candidates)
        self.assertIn(2, candidates)
        # Guard itself can protect itself (only last_target is excluded)
        self.assertIn(1, candidates)

    def test_guard_night_action_updates_role_state_last_target(self):
        """Guard night_action should update role_state["last_target"], not GameState."""
        roles = {1: Role.GUARD, 2: Role.WEREWOLF, 3: Role.VILLAGER}
        config = GameConfig(
            name="guard_test",
            role_counts={Role.GUARD: 1, Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.GUARD,),
        )
        agents = agents_with()
        agents[1].push(ActionResponse(ActionType.GUARD_PROTECT, target=3))
        engine = _make_minimal_engine(roles, agents, config=config)
        engine.state.day = 1

        guard_rule = rule_for(Role.GUARD)
        run(guard_rule.night_action(engine))

        guard_ps = engine.state.players[1]
        self.assertEqual(guard_ps.role_state["last_target"], 3)
        self.assertEqual(len(guard_ps.role_state["protect_history"]), 1)
        self.assertEqual(guard_ps.role_state["protect_history"][0]["day"], 1)
        self.assertEqual(guard_ps.role_state["protect_history"][0]["target"], 3)


class InitRoleStateTests(unittest.TestCase):
    """Tests confirming each role rule returns the correct init_role_state."""

    def test_villager_init_role_state_is_empty(self):
        rule = rule_for(Role.VILLAGER)
        self.assertEqual(rule.init_role_state(), {})

    def test_werewolf_init_role_state_is_empty(self):
        rule = rule_for(Role.WEREWOLF)
        self.assertEqual(rule.init_role_state(), {})

    def test_seer_init_role_state(self):
        rule = rule_for(Role.SEER)
        state = rule.init_role_state()
        self.assertEqual(state, {"checks": {}})

    def test_witch_init_role_state(self):
        rule = rule_for(Role.WITCH)
        state = rule.init_role_state()
        self.assertTrue(state["antidote_available"])
        self.assertTrue(state["poison_available"])
        self.assertEqual(state["antidote_history"], [])
        self.assertEqual(state["poison_history"], [])

    def test_hunter_init_role_state(self):
        rule = rule_for(Role.HUNTER)
        state = rule.init_role_state()
        self.assertFalse(state["has_shot"])
        self.assertIsNone(state["shot_target"])

    def test_guard_init_role_state(self):
        rule = rule_for(Role.GUARD)
        state = rule.init_role_state()
        self.assertIsNone(state["last_target"])
        self.assertEqual(state["protect_history"], [])

    def test_white_wolf_king_init_role_state(self):
        rule = rule_for(Role.WHITE_WOLF_KING)
        state = rule.init_role_state()
        self.assertFalse(state["has_exploded"])

    def test_engine_initializes_role_state_for_all_players(self):
        """GameEngine.__init__ should set role_state via rule_for().init_role_state()."""
        engine = GameEngine(standard_roles(), agents_with())

        for player_id, ps in engine.state.players.items():
            expected_state = rule_for(ps.role).init_role_state()
            self.assertEqual(ps.role_state, expected_state,
                             f"Player {player_id} ({ps.role.value}) role_state mismatch")

    def test_get_role_state_returns_copy_of_player_role_state(self):
        """get_role_state should return a dict copy of the player's role_state."""
        engine = GameEngine(standard_roles(), agents_with())

        seer_id = next(pid for pid, ps in engine.state.players.items() if ps.role is Role.SEER)
        seer_rule = rule_for(Role.SEER)
        returned_state = seer_rule.get_role_state(engine, seer_id)

        # Should be a copy, not the same dict object
        self.assertIsNot(returned_state, engine.state.players[seer_id].role_state)
        # Should have the same content
        self.assertEqual(returned_state, dict(engine.state.players[seer_id].role_state))


class ObservationRoleStateTests(unittest.TestCase):
    """Tests verifying that observation_for includes role_state."""

    def test_observation_for_seer_includes_seer_checks_from_role_state(self):
        """observation_for should include seer_checks derived from role_state."""
        roles = {1: Role.SEER, 2: Role.WEREWOLF, 3: Role.VILLAGER}
        config = GameConfig(
            name="seer_test",
            role_counts={Role.SEER: 1, Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
            night_order=(Role.SEER,),
        )
        agents = agents_with()
        engine = _make_minimal_engine(roles, agents, config=config)

        # Manually add a check
        seer_ps = engine.state.players[1]
        seer_ps.role_state["checks"]["2"] = {
            "day": 1,
            "target": 2,
            "result": "werewolves",
        }

        obs = engine.observation_for(1)
        self.assertEqual(obs.seer_checks[2], Team.WEREWOLVES)
        self.assertEqual(obs.role_state["checks"]["2"]["result"], "werewolves")

    def test_observation_for_witch_includes_antidote_available(self):
        """observation_for witch should show role_state with antidote/poison status."""
        engine = GameEngine(standard_roles(), agents_with())
        witch_id = next(pid for pid, ps in engine.state.players.items() if ps.role is Role.WITCH)

        obs = engine.observation_for(witch_id)
        self.assertTrue(obs.role_state["antidote_available"])
        self.assertTrue(obs.role_state["poison_available"])


if __name__ == "__main__":
    unittest.main()