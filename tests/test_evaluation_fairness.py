"""Tests for agent.evaluation.fairness — fairness validation and rankable."""
from __future__ import annotations

import unittest

from agent.evaluation.fairness import (
    compute_rankable,
    validate_model_comparison,
    validate_role_version_comparison,
)


def _make_batch(**overrides):
    base = {
        "batch_id": "b1",
        "evaluation_set_id": "eval_v1",
        "seed_set_id": "seed_v1",
        "game_count": 20,
        "max_days": 20,
        "player_count": 12,
        "ruleset_version": "werewolf_12p_v1",
        "role_version_config": {"seer": "baseline", "witch": "baseline"},
        "model_id": "qwen",
        "model_config_hash": "hash1",
    }
    base.update(overrides)
    return base


class TestValidateModelComparison(unittest.TestCase):
    def test_same_model_not_fair(self):
        a = _make_batch(model_id="qwen", model_config_hash="h1")
        b = _make_batch(model_id="qwen", model_config_hash="h1")
        result = validate_model_comparison([a, b])
        self.assertFalse(result.is_fair)
        self.assertIn("model_id", result.reason)

    def test_different_model_same_config_fair(self):
        a = _make_batch(model_id="qwen", model_config_hash="h1")
        b = _make_batch(model_id="gpt", model_config_hash="h2")
        result = validate_model_comparison([a, b])
        self.assertTrue(result.is_fair)

    def test_different_seed_set_not_fair(self):
        a = _make_batch(model_id="qwen", model_config_hash="h1", seed_set_id="s1")
        b = _make_batch(model_id="gpt", model_config_hash="h2", seed_set_id="s2")
        result = validate_model_comparison([a, b])
        self.assertFalse(result.is_fair)
        self.assertIn("seed_set_id", result.reason)

    def test_different_game_count_not_fair(self):
        a = _make_batch(model_id="qwen", model_config_hash="h1", game_count=20)
        b = _make_batch(model_id="gpt", model_config_hash="h2", game_count=10)
        result = validate_model_comparison([a, b])
        self.assertFalse(result.is_fair)

    def test_single_batch_not_fair(self):
        result = validate_model_comparison([_make_batch()])
        self.assertFalse(result.is_fair)


class TestValidateRoleVersionComparison(unittest.TestCase):
    def test_same_version_not_fair(self):
        a = _make_batch(role_version_config={"witch": "v1", "seer": "baseline"})
        b = _make_batch(role_version_config={"witch": "v1", "seer": "baseline"})
        result = validate_role_version_comparison([a, b], target_role="witch")
        self.assertFalse(result.is_fair)
        self.assertIn("witch", result.reason)

    def test_different_target_version_fair(self):
        a = _make_batch(role_version_config={"witch": "baseline", "seer": "baseline"})
        b = _make_batch(role_version_config={"witch": "v2", "seer": "baseline"})
        result = validate_role_version_comparison([a, b], target_role="witch")
        self.assertTrue(result.is_fair)

    def test_different_other_version_not_fair(self):
        a = _make_batch(role_version_config={"witch": "baseline", "seer": "baseline"})
        b = _make_batch(role_version_config={"witch": "v2", "seer": "v2"})
        result = validate_role_version_comparison([a, b], target_role="witch")
        self.assertFalse(result.is_fair)


class TestComputeRankable(unittest.TestCase):
    def test_formal_paired_enough_games_is_rankable(self):
        rankable, reason = compute_rankable(
            mode="formal", paired_seed=True, game_count=20, valid_game_rate=0.9, is_fair=True
        )
        self.assertTrue(rankable)
        self.assertEqual(reason, "rankable")

    def test_dev_mode_not_rankable(self):
        rankable, reason = compute_rankable(
            mode="dev", paired_seed=True, game_count=20, valid_game_rate=0.9, is_fair=True
        )
        self.assertFalse(rankable)
        self.assertIn("formal", reason)

    def test_not_paired_not_rankable(self):
        rankable, reason = compute_rankable(
            mode="formal", paired_seed=False, game_count=20, valid_game_rate=0.9, is_fair=True
        )
        self.assertFalse(rankable)
        self.assertIn("paired", reason)

    def test_too_few_games_not_rankable(self):
        rankable, reason = compute_rankable(
            mode="formal", paired_seed=True, game_count=10, valid_game_rate=0.9, is_fair=True
        )
        self.assertFalse(rankable)
        self.assertIn("10", reason)

    def test_low_valid_rate_not_rankable(self):
        rankable, reason = compute_rankable(
            mode="formal", paired_seed=True, game_count=20, valid_game_rate=0.5, is_fair=True
        )
        self.assertFalse(rankable)
        self.assertIn("0.50", reason)

    def test_not_fair_not_rankable(self):
        rankable, reason = compute_rankable(
            mode="formal", paired_seed=True, game_count=20, valid_game_rate=0.9, is_fair=False
        )
        self.assertFalse(rankable)
        self.assertIn("fairness", reason)
