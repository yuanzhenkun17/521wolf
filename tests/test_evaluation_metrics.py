"""Tests for agent.evaluation.metrics — scoring formula and aggregation."""
from __future__ import annotations

import unittest

from agent.evaluation.metrics import (
    PlayerScore,
    aggregate_batch_scores,
    compute_role_score,
)


class TestComputeRoleScore(unittest.TestCase):
    def test_basic_formula(self):
        score = compute_role_score(
            speech_score=0.8, vote_score=0.7, skill_score=0.6,
            logic_score=0.9, team_score=0.5, risk_penalty=0.0
        )
        expected = 0.25 * 0.8 + 0.25 * 0.7 + 0.20 * 0.6 + 0.20 * 0.9 + 0.10 * 0.5
        self.assertAlmostEqual(score, expected, places=3)

    def test_risk_penalty_deducted(self):
        score = compute_role_score(
            speech_score=0.8, vote_score=0.7, skill_score=0.6,
            logic_score=0.9, team_score=0.5, risk_penalty=0.1
        )
        base = 0.25 * 0.8 + 0.25 * 0.7 + 0.20 * 0.6 + 0.20 * 0.9 + 0.10 * 0.5
        self.assertAlmostEqual(score, base - 0.1, places=3)

    def test_skill_not_applicable_renormalizes(self):
        score = compute_role_score(
            speech_score=0.8, vote_score=0.7, skill_score=0.0,
            logic_score=0.9, team_score=0.5, risk_penalty=0.0,
            skill_applicable=False
        )
        # Without skill: speech=0.25/0.80, vote=0.25/0.80, logic=0.20/0.80, team=0.10/0.80
        expected = (0.25 / 0.80) * 0.8 + (0.25 / 0.80) * 0.7 + (0.20 / 0.80) * 0.9 + (0.10 / 0.80) * 0.5
        self.assertAlmostEqual(score, expected, places=3)

    def test_zero_scores(self):
        score = compute_role_score(
            speech_score=0, vote_score=0, skill_score=0,
            logic_score=0, team_score=0, risk_penalty=0
        )
        self.assertEqual(score, 0.0)

    def test_negative_result_clamped_to_zero(self):
        score = compute_role_score(
            speech_score=0.1, vote_score=0.1, skill_score=0.1,
            logic_score=0.1, team_score=0.1, risk_penalty=0.9
        )
        self.assertEqual(score, 0.0)


class TestAggregateBatchScores(unittest.TestCase):
    def test_empty_scores(self):
        result = aggregate_batch_scores([], batch_id="b1")
        self.assertEqual(result.game_count, 0)
        self.assertEqual(result.strength_score, 0.0)

    def test_single_player(self):
        ps = PlayerScore(player_id=1, role="seer", speech_score=0.8, role_score=0.75)
        result = aggregate_batch_scores([ps], batch_id="b1")
        self.assertEqual(result.game_count, 1)
        self.assertAlmostEqual(result.avg_role_score, 0.75, places=3)

    def test_role_category_aggregation(self):
        scores = [
            PlayerScore(player_id=1, role="werewolf", role_score=0.7),
            PlayerScore(player_id=2, role="villager", role_score=0.6),
            PlayerScore(player_id=3, role="seer", role_score=0.8),
        ]
        result = aggregate_batch_scores(scores, batch_id="b1")
        # wolf=0.7, villager=0.6, god=0.8 -> strength = (0.7+0.6+0.8)/3
        self.assertAlmostEqual(result.strength_score, 0.7, places=2)
        self.assertIn("wolf", result.by_role_category)
        self.assertIn("villager", result.by_role_category)
        self.assertIn("god", result.by_role_category)
