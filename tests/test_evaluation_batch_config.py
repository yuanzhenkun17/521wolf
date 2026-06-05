"""Tests for agent.evaluation.config — EvaluationBatchConfig."""
from __future__ import annotations

import unittest

from agent.evaluation.config import EvaluationBatchConfig


class TestEvaluationBatchConfig(unittest.TestCase):
    def test_default_config(self):
        cfg = EvaluationBatchConfig()
        self.assertEqual(cfg.comparison_type, "model_id")
        self.assertEqual(cfg.mode, "dev")
        self.assertEqual(cfg.game_count, 20)
        self.assertEqual(cfg.temperature, 1.0)
        self.assertEqual(cfg.ruleset_version, "werewolf_12p_v1")

    def test_to_dict_round_trip(self):
        cfg = EvaluationBatchConfig(
            batch_id="b1",
            comparison_type="role_version",
            mode="formal",
            model_id="qwen",
            game_count=10,
            target_role="witch",
            target_version_id="witch_v2",
        )
        d = cfg.to_dict()
        self.assertEqual(d["batch_id"], "b1")
        self.assertEqual(d["comparison_type"], "role_version")
        self.assertEqual(d["mode"], "formal")
        self.assertEqual(d["model_id"], "qwen")
        self.assertEqual(d["game_count"], 10)
        self.assertEqual(d["target_role"], "witch")
        self.assertEqual(d["target_version_id"], "witch_v2")

    def test_role_version_config_default_empty(self):
        cfg = EvaluationBatchConfig()
        self.assertEqual(cfg.role_version_config, {})
