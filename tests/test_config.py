"""Tests for engine.config — GameConfig defaults and presets."""

import unittest

from engine.config import GameConfig, STANDARD_12
from engine.models import Role


class GameConfigDefaultTests(unittest.TestCase):
    """Tests for GameConfig default field values."""

    def test_max_days_default_is_20(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
        )
        self.assertEqual(config.max_days, 20)

    def test_sheriff_vote_weight_default_is_1_5(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
        )
        self.assertEqual(config.sheriff_vote_weight, 1.5)

    def test_runner_max_retries_default_is_5(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
        )
        self.assertEqual(config.runner_max_retries, 5)

    def test_enable_sheriff_default_is_true(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
        )
        self.assertTrue(config.enable_sheriff)

    def test_runner_retry_delay_default_is_1_0(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
        )
        self.assertEqual(config.runner_retry_delay, 1.0)

    def test_night_order_default_includes_guard_werewolf_seer_witch(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
        )
        self.assertEqual(config.night_order, (Role.GUARD, Role.WEREWOLF, Role.SEER, Role.WITCH))


class GameConfigCustomTests(unittest.TestCase):
    """Tests for GameConfig with custom field values."""

    def test_custom_max_days(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
            max_days=10,
        )
        self.assertEqual(config.max_days, 10)

    def test_custom_sheriff_vote_weight(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
            sheriff_vote_weight=2.0,
        )
        self.assertEqual(config.sheriff_vote_weight, 2.0)

    def test_custom_runner_max_retries(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
            runner_max_retries=10,
        )
        self.assertEqual(config.runner_max_retries, 10)

    def test_custom_enable_sheriff_false(self):
        config = GameConfig(
            name="no_sheriff",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
            enable_sheriff=False,
        )
        self.assertFalse(config.enable_sheriff)


class GameConfigPropertyTests(unittest.TestCase):
    """Tests for GameConfig computed properties."""

    def test_player_count_from_role_counts(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 3, Role.VILLAGER: 5},
        )
        self.assertEqual(config.player_count, 8)

    def test_role_counter_matches_role_counts(self):
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 3, Role.VILLAGER: 5},
        )
        counter = config.role_counter
        self.assertEqual(counter[Role.WEREWOLF], 3)
        self.assertEqual(counter[Role.VILLAGER], 5)

    def test_player_count_with_standard_12(self):
        self.assertEqual(STANDARD_12.player_count, 12)


class STANDARD12Tests(unittest.TestCase):
    """Tests for the STANDARD_12 preset configuration."""

    def test_standard_12_name(self):
        self.assertEqual(STANDARD_12.name, "standard_12")

    def test_standard_12_max_days_is_20(self):
        self.assertEqual(STANDARD_12.max_days, 20)

    def test_standard_12_sheriff_vote_weight_is_1_5(self):
        self.assertEqual(STANDARD_12.sheriff_vote_weight, 1.5)

    def test_standard_12_runner_max_retries_is_5(self):
        self.assertEqual(STANDARD_12.runner_max_retries, 5)

    def test_standard_12_enable_sheriff_is_true(self):
        self.assertTrue(STANDARD_12.enable_sheriff)

    def test_standard_12_player_count_is_12(self):
        self.assertEqual(STANDARD_12.player_count, 12)

    def test_standard_12_role_counts_sum_to_12(self):
        total = sum(STANDARD_12.role_counts.values())
        self.assertEqual(total, 12)

    def test_standard_12_includes_all_expected_roles(self):
        expected_roles = {
            Role.WEREWOLF,
            Role.WHITE_WOLF_KING,
            Role.VILLAGER,
            Role.SEER,
            Role.WITCH,
            Role.HUNTER,
            Role.GUARD,
        }
        self.assertEqual(set(STANDARD_12.role_counts.keys()), expected_roles)

    def test_standard_12_night_order(self):
        self.assertEqual(
            STANDARD_12.night_order,
            (Role.GUARD, Role.WEREWOLF, Role.SEER, Role.WITCH),
        )

    def test_standard_12_is_frozen_dataclass(self):
        """STANDARD_12 should be immutable (frozen dataclass)."""
        with self.assertRaises(AttributeError):
            STANDARD_12.max_days = 99

    def test_game_config_is_frozen(self):
        """Any GameConfig instance should be immutable."""
        config = GameConfig(
            name="test",
            role_counts={Role.WEREWOLF: 1, Role.VILLAGER: 1},
        )
        with self.assertRaises(AttributeError):
            config.max_days = 99


if __name__ == "__main__":
    unittest.main()